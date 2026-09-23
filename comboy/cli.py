"""Interfaz de línea de comandos: ``python -m comboy``.

Subcomandos:
    run       Corre el loop de recepción del nodo.
    send      Construye y transmite una trama de alerta.
    listen    Escucha el micrófono, detecta la wake word y envía la alerta.
    voice     Escucha el micrófono, transcribe la frase libre, la clasifica y
              envía la alerta.
    talk      Detecta la wake word, transcribe la frase libre, la clasifica y
              envía la alerta (une ``listen`` y ``voice``).
    text      Clasifica una frase escrita y muestra el código resultante (L1).
    selftest  Autoprueba offline (CRC, round-trip del codec, rechazo de
              tramas corruptas, frase).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections.abc import Sequence

from . import __version__
from .classify import Classification, classify
from .codes import (
    DIST_UNKNOWN,
    Confidence,
    Hazard,
    Lane,
    MsgType,
    Urgency,
    role_from_name,
)
from .config import Config, load_config
from .embedding import create_embedding_client
from .frame import AlertFrame
from .logging_setup import Logger
from .mic import Microphone, wav_chunks
from .node import Node
from .phrase import build_phrase
from .transport import create_transport
from .tts import Speaker
from .voice import create_transcriber
from .wakeword import DEFAULT_MODEL_PATH, VoskWakeWord


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m comboy",
        description="Alerta temprana de peligros para comboys de montaña (Fase 0 / L0).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    run_parser = subparsers.add_parser("run", help="corre el loop de recepción del nodo")
    _add_config_argument(run_parser)

    send_parser = subparsers.add_parser("send", help="construye y envía una trama de alerta")
    _add_config_argument(send_parser)
    _add_alert_arguments(send_parser)

    listen_parser = subparsers.add_parser(
        "listen", help="escucha el micrófono y envía una alerta al detectar la wake word"
    )
    _add_config_argument(listen_parser)
    _add_wav_argument(listen_parser)
    _add_alert_arguments(listen_parser)

    voice_parser = subparsers.add_parser(
        "voice",
        help="escucha el micrófono, transcribe la frase y la clasifica antes de enviarla",
    )
    _add_config_argument(voice_parser)
    _add_wav_argument(voice_parser)
    _add_capture_arguments(voice_parser)
    _add_json_argument(voice_parser)
    _add_origin_arguments(voice_parser)

    talk_parser = subparsers.add_parser(
        "talk",
        help="detecta la wake word, transcribe la frase libre y la clasifica antes de enviarla",
    )
    _add_config_argument(talk_parser)
    _add_wav_argument(talk_parser)
    _add_capture_arguments(talk_parser)
    _add_json_argument(talk_parser)
    _add_origin_arguments(talk_parser)

    text_parser = subparsers.add_parser(
        "text", help="clasifica una frase escrita y muestra el código resultante"
    )
    text_parser.add_argument(
        "phrase", help='frase del conductor, p. ej. "hay piedras en la calzada"'
    )
    _add_config_argument(text_parser)
    _add_json_argument(text_parser)

    subparsers.add_parser("selftest", help="corre las autopruebas offline (sin red)")

    return parser


def _add_config_argument(parser: argparse.ArgumentParser) -> None:
    """Agrega ``--config``, compartido por todos los subcomandos.

    Existe para no repetir seis veces la misma definición: una sola fuente de
    verdad para el default y el help del flag.
    """

    parser.add_argument(
        "--config",
        default=None,
        help="ruta al archivo de config YAML (valores por defecto si se omite)",
    )


def _add_wav_argument(parser: argparse.ArgumentParser) -> None:
    """Agrega ``--wav``, compartido por ``listen``, ``voice`` y ``talk``.

    Centraliza el modo de prueba sin micrófono para que su help no diverja entre
    subcomandos.
    """

    parser.add_argument(
        "--wav",
        default=None,
        help="lee un WAV 16 kHz mono s16 en vez del micrófono (para probar sin micrófono)",
    )


def _add_json_argument(parser: argparse.ArgumentParser) -> None:
    """Agrega ``--json``, compartido por ``voice``, ``talk`` y ``text``.

    Una sola definición evita que el texto de ayuda del flag de salida JSON se
    desincronice entre los subcomandos.
    """

    parser.add_argument("--json", action="store_true", help="imprime el resultado como objeto JSON")


def _add_origin_arguments(parser: argparse.ArgumentParser) -> None:
    """Agrega ``--origin-id`` y ``--alert-id`` para los subcomandos de alerta.

    Este helper elimina la doble fuente de verdad: antes estos dos flags se
    definían a mano dentro de ``_add_alert_arguments`` y otra vez en ``voice`` y
    ``talk``, con riesgo de que los help divergieran.
    """

    parser.add_argument(
        "--origin-id", type=int, default=None, help="sobrescribe el id de nodo configurado"
    )
    parser.add_argument(
        "--alert-id", type=lambda value: int(value, 0), default=None, help="id de alerta explícito"
    )


def _add_capture_arguments(parser: argparse.ArgumentParser) -> None:
    """Agrega ``--seconds`` y ``--no-send``, compartidos por ``voice`` y ``talk``.

    Agrupa el tope de captura de la frase y el corte de transmisión para no
    repetirlos en cada subcomando de voz.
    """

    parser.add_argument(
        "--seconds",
        type=float,
        default=8.0,
        help="tope de captura de la frase en segundos (por defecto 8)",
    )
    parser.add_argument(
        "--no-send",
        dest="no_send",
        action="store_true",
        help="clasifica y muestra el resultado pero no transmite la alerta",
    )


def _add_alert_arguments(parser: argparse.ArgumentParser) -> None:
    """Agrega los argumentos de alerta compartidos por ``send`` y ``listen``."""

    parser.add_argument(
        "--hazard",
        required=True,
        help="nombre del código de peligro, p. ej. PIEDRAS",
    )
    parser.add_argument(
        "--lane", default="SIN_ESPECIFICAR", help="nombre del código de carril, p. ej. DERECHO"
    )
    parser.add_argument(
        "--dist-km", type=int, default=255, help="distancia declarada 0..15, o 255 desconocida"
    )
    parser.add_argument(
        "--urgency", default="PRECAUCION", help="nombre del código de urgencia, p. ej. PRECAUCION"
    )
    parser.add_argument(
        "--confidence", default="ALTA", help="nombre del código de confianza, p. ej. ALTA"
    )
    _add_origin_arguments(parser)


def _make_logger(config: Config) -> Logger:
    return Logger(
        node_id=config.node.id,
        role=config.node.role,
        level=config.log.level,
        path=config.log.path,
    )


def _parse_hazard(value: str) -> Hazard:
    try:
        return Hazard[value.strip().upper()]
    except KeyError as exc:
        raise ValueError(f"peligro desconocido: {value!r}") from exc


def _parse_lane(value: str) -> Lane:
    try:
        return Lane[value.strip().upper()]
    except KeyError as exc:
        raise ValueError(f"carril desconocido: {value!r}") from exc


def _parse_urgency(value: str) -> Urgency:
    try:
        return Urgency[value.strip().upper()]
    except KeyError as exc:
        raise ValueError(f"urgencia desconocida: {value!r}") from exc


def _parse_confidence(value: str) -> Confidence:
    try:
        return Confidence[value.strip().upper()]
    except KeyError as exc:
        raise ValueError(f"confianza desconocida: {value!r}") from exc


def _resolve_alert_codes(args: argparse.Namespace) -> tuple[Hazard, Lane, Urgency, Confidence]:
    """Traduce los nombres de la CLI a enums y valida ``--dist-km``.

    Lanza ``ValueError`` con el motivo; el llamador decide cómo reportarlo.
    """

    hazard = _parse_hazard(args.hazard)
    lane = _parse_lane(args.lane)
    urgency = _parse_urgency(args.urgency)
    confidence = _parse_confidence(args.confidence)
    if not 0 <= args.dist_km <= 255:
        raise ValueError("--dist-km debe estar en 0..255")
    return hazard, lane, urgency, confidence


def _resolve_origin_id(args: argparse.Namespace, config: Config) -> int:
    """Id de origen efectivo, validado en 1..255. Lanza ``ValueError`` si no sirve."""

    origin_id = args.origin_id if args.origin_id is not None else config.node.id
    if not 1 <= origin_id <= 255:
        raise ValueError("--origin-id debe estar en 1..255")
    return origin_id


def _build_alert_frame(
    codes: tuple[Hazard, Lane, Urgency, Confidence],
    args: argparse.Namespace,
    config: Config,
    origin_id: int,
) -> AlertFrame:
    """Construye la trama de alerta con los argumentos de la CLI."""

    hazard, lane, urgency, confidence = codes
    alert_id = args.alert_id if args.alert_id is not None else random.getrandbits(32)
    return AlertFrame(
        msg_type=MsgType.ALERTA,
        alert_id=alert_id & 0xFFFFFFFF,
        origin_id=origin_id,
        origin_role=int(role_from_name(config.node.role)),
        hop=0,
        ttl=3,  # docs/03: el ttl se inicializa en 3
        hazard=int(hazard),
        lane=int(lane),
        dist_km=args.dist_km,
        urgency=int(urgency),
        confidence=int(confidence),
    )


def _build_classified_frame(
    result: Classification,
    args: argparse.Namespace,
    config: Config,
    origin_id: int,
) -> AlertFrame:
    """Construye la trama de alerta con los campos de una :class:`Classification`.

    ``Classification`` ya trae ``hazard``, ``lane``, ``dist_km``, ``urgency`` y
    ``confidence``, que son exactamente los campos de la trama. Este helper evita
    forzar el resultado a un ``argparse.Namespace`` como hacen ``send``/``listen``.
    """

    alert_id = args.alert_id if args.alert_id is not None else random.getrandbits(32)
    return AlertFrame(
        msg_type=MsgType.ALERTA,
        alert_id=alert_id & 0xFFFFFFFF,
        origin_id=origin_id,
        origin_role=int(role_from_name(config.node.role)),
        hop=0,
        ttl=3,  # docs/03: el ttl se inicializa en 3
        hazard=int(result.hazard),
        lane=int(result.lane),
        dist_km=result.dist_km,
        urgency=int(result.urgency),
        confidence=int(result.confidence),
    )


def _run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    logger = _make_logger(config)
    transport = create_transport(config, logger)
    speaker = Speaker(voice=config.audio.tts_voice, logger=logger)
    node = Node(config, transport, logger, speaker)
    try:
        node.run()
    finally:
        logger.close()
    return 0


def _send(args: argparse.Namespace) -> int:
    try:
        codes = _resolve_alert_codes(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    config = load_config(args.config)
    logger = _make_logger(config)
    transport = create_transport(config, logger)
    speaker = Speaker(voice=config.audio.tts_voice, logger=logger)
    node = Node(config, transport, logger, speaker)

    try:
        origin_id = _resolve_origin_id(args, config)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        node.close()
        logger.close()
        return 2

    frame = _build_alert_frame(codes, args, config, origin_id)
    try:
        node.send_alert(frame)
    finally:
        node.close()
        logger.close()
    return 0


def _listen(args: argparse.Namespace) -> int:
    """Corre el primer slice de la Fase 2: wake word -> alerta enviada.

    Captura audio de forma continua, detecta la wake word y, en cada detección,
    envía la alerta configurada por la misma ruta que ``send``.

    Fuera de alcance a propósito: VAD, transcripción de la frase de peligro,
    clasificador por reglas y half-duplex. Este slice solo prueba que la wake
    word dispare el envío.

    Con ``--wav FILE`` se lee un WAV 16 kHz mono s16 en vez del micrófono, para
    poder validar la cadena sin micrófono real.
    """

    try:
        codes = _resolve_alert_codes(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    config = load_config(args.config)

    try:
        origin_id = _resolve_origin_id(args, config)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # Se valida la fuente antes de cargar el modelo (que tarda segundos): un
    # WAV mal formado debe fallar rápido y con un mensaje claro.
    microphone: Microphone | None = None
    if args.wav:
        try:
            chunks = wav_chunks(args.wav)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        source = "wav"
    else:
        source = "mic"

    logger = _make_logger(config)
    transport = create_transport(config, logger)
    speaker = Speaker(voice=config.audio.tts_voice, logger=logger)
    node = Node(config, transport, logger, speaker)
    if source == "mic":
        microphone = Microphone(logger=logger)
        chunks = microphone.chunks()

    detector = VoskWakeWord(DEFAULT_MODEL_PATH, phrase=config.audio.wake_word, logger=logger)

    def anunciar_wake_word() -> None:
        logger.info(
            "wake_word",
            phrase=config.audio.wake_word,
            text=detector.last_text,
            source=source,
        )
        node.send_alert(_build_alert_frame(codes, args, config, origin_id))

    try:
        for chunk in chunks:
            if detector.accept(chunk):
                anunciar_wake_word()
        # Una fuente finita (WAV) puede terminar sin silencio de cierre.
        if source == "wav" and detector.flush():
            anunciar_wake_word()
    except KeyboardInterrupt:
        pass
    finally:
        if microphone is not None:
            microphone.close()
        node.close()
        logger.info("shutdown")
        logger.close()
    return 0


def _print_voice_result(
    texto: str,
    result: Classification,
    *,
    no_send: bool,
    as_json: bool,
) -> None:
    """Imprime el texto reconocido y la clasificación, al estilo de ``_text``."""

    if as_json:
        print(
            json.dumps(
                {
                    "texto": texto,
                    "hazard": result.hazard.name,
                    "lane": result.lane.name,
                    "dist_km": result.dist_km,
                    "urgency": result.urgency.name,
                    "confidence": result.confidence.name,
                    "similarity": round(result.similarity, 4),
                    "margin": round(result.margin, 4),
                },
                ensure_ascii=False,
            )
        )
        # El objeto JSON debe quedar solo en stdout: la aclaración va a stderr.
        if no_send:
            print("(no se transmitió: --no-send)", file=sys.stderr)
        return

    distancia = "desconocida" if result.dist_km == DIST_UNKNOWN else f"{result.dist_km} km"
    print(f"{'texto':<9} : {texto}")
    print(f"{'peligro':<9} : {result.hazard.name}")
    print(f"{'carril':<9} : {result.lane.name}")
    print(f"{'distancia':<9} : {distancia}")
    print(f"{'urgencia':<9} : {result.urgency.name}")
    print(f"{'confianza':<9} : {result.confidence.name}")
    print(f"{'similitud':<9} : {result.similarity:.4f}")
    print(f"{'margen':<9} : {result.margin:.4f}")
    if no_send:
        print("(no se transmitió: --no-send)")


def _voice(args: argparse.Namespace) -> int:
    """Transcribe una frase hablada, la clasifica y envía la alerta.

    El conductor habla por el micrófono, Vosk transcribe con **vocabulario
    libre** (ver :mod:`comboy.voice`), el clasificador elige un código y la
    trama de 17 bytes sale por el canal. No hay gate de confianza ni confirmación:
    si la clasificación se equivoca, se manda igual (decisión del dueño).

    Con ``--wav FILE`` se lee un WAV 16 kHz mono s16 en vez del micrófono, y con
    ``--no-send`` se clasifica y muestra sin transmitir. Ambas opciones permiten
    probar la cadena sin micrófono ni red.
    """

    config = load_config(args.config)

    try:
        origin_id = _resolve_origin_id(args, config)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # Se valida la fuente antes de cargar el modelo (que tarda segundos): un
    # WAV mal formado debe fallar rápido y con un mensaje claro.
    microphone: Microphone | None = None
    if args.wav:
        try:
            chunks = wav_chunks(args.wav)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        source = "wav"
    else:
        source = "mic"

    logger = _make_logger(config)
    transport = create_transport(config, logger)
    speaker = Speaker(voice=config.audio.tts_voice, logger=logger)
    node = Node(config, transport, logger, speaker)

    try:
        if source == "mic":
            microphone = Microphone(logger=logger)
            chunks = microphone.chunks()

        transcriber = create_transcriber(DEFAULT_MODEL_PATH, logger=logger)
        if not transcriber.available:
            print(
                "error: no hay transcripción disponible: revisá que la dependencia "
                f"'vosk' esté instalada y que el modelo esté en {DEFAULT_MODEL_PATH!r} "
                "(descargalo y descomprimilo en models/)",
                file=sys.stderr,
            )
            return 2

        texto = ""
        samples = 0
        deadline = time.monotonic() + args.seconds
        try:
            for chunk in chunks:
                samples += len(chunk)
                reconocido = transcriber.accept(chunk)
                if reconocido:
                    texto = reconocido
                    break
                if time.monotonic() >= deadline:
                    break
        except KeyboardInterrupt:
            pass
        # Una fuente finita (WAV) o un corte pueden terminar sin silencio de
        # cierre: se cierra la frase en curso para no perder el último tramo.
        if not texto:
            texto = transcriber.flush()

        if not texto.strip():
            print("error: no se reconoció nada, probá de nuevo", file=sys.stderr)
            return 2

        client = create_embedding_client(config.embedding, logger)
        result = classify(texto, client, config.embedding, logger)

        logger.info("voice.transcript", texto=texto, source=source, samples=samples)

        frame = _build_classified_frame(result, args, config, origin_id)
        if not args.no_send:
            node.send_alert(frame)

        _print_voice_result(texto, result, no_send=args.no_send, as_json=args.json)
        return 0
    finally:
        if microphone is not None:
            microphone.close()
        node.close()
        logger.info("shutdown")
        logger.close()


def _talk(args: argparse.Namespace) -> int:
    """Detecta la wake word, transcribe la frase libre y envía la alerta clasificada.

    Une las dos mitades de la Fase 2: ``listen`` (wake word) y ``voice``
    (transcripción libre + clasificación). El nodo escucha de forma continua:
    cada wake word abre una ventana de captura, la frase se clasifica y se
    transmite, y después vuelve a escuchar.

    Dos decisiones no obvias:

    * El fragmento que despierta al detector **no** se le pasa al transcriber:
      contiene la wake word y re-decodificarlo ensuciaría la frase. La frase
      empieza en el fragmento siguiente.
    * Una frase vacía **no** es un error, a diferencia de ``voice``: significa
      que la wake word se disparó sola (un falso positivo). Se registra y se
      vuelve a escuchar en vez de abortar, porque este nodo corre siempre.

    No hay gate de confianza: si la clasificación da ``DESCONOCIDO`` se envía
    igual, por decisión del dueño.

    Con ``--wav FILE`` se lee un WAV 16 kHz mono s16 en vez del micrófono, y con
    ``--no-send`` se clasifica y muestra sin transmitir.
    """

    config = load_config(args.config)

    try:
        origin_id = _resolve_origin_id(args, config)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # Se valida la fuente antes de cargar el modelo (que tarda segundos): un
    # WAV mal formado debe fallar rápido y con un mensaje claro.
    microphone: Microphone | None = None
    if args.wav:
        try:
            chunks = wav_chunks(args.wav)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        source = "wav"
    else:
        source = "mic"

    logger = _make_logger(config)
    transport = create_transport(config, logger)
    speaker = Speaker(voice=config.audio.tts_voice, logger=logger)
    node = Node(config, transport, logger, speaker)

    try:
        if source == "mic":
            microphone = Microphone(logger=logger)
            chunks = microphone.chunks()

        # El detector carga el modelo una sola vez y el transcriber lo reutiliza:
        # un segundo modelo costaría segundos de latencia al despertar y el doble
        # de RAM. Por eso el detector se construye primero.
        detector = VoskWakeWord(DEFAULT_MODEL_PATH, phrase=config.audio.wake_word, logger=logger)
        transcriber = create_transcriber(DEFAULT_MODEL_PATH, logger=logger, model=detector.model)
        if not detector.available or not transcriber.available:
            print(
                "error: no hay wake word ni transcripción disponibles: revisá que la "
                f"dependencia 'vosk' esté instalada y que el modelo esté en "
                f"{DEFAULT_MODEL_PATH!r} (descargalo y descomprimilo en models/)",
                file=sys.stderr,
            )
            return 2

        client = create_embedding_client(config.embedding, logger)
        iterador = iter(chunks)

        try:
            # Bucle externo: re-arma la fase de wake word después de cada alerta.
            while True:
                # Fase wake word: se avanza hasta que el detector despierte.
                despertado = False
                for chunk in iterador:
                    if detector.accept(chunk):
                        despertado = True
                        break
                if not despertado:
                    # La fuente se agotó (WAV) sin wake word: salida limpia.
                    break

                logger.info(
                    "wake_word",
                    phrase=config.audio.wake_word,
                    text=detector.last_text,
                    source=source,
                )

                # Fase frase: el fragmento que despertó no se re-decoda. El
                # tope ``--seconds`` es de seguridad; la frase normalmente cierra
                # por silencio, cuando Vosk emite un resultado final.
                texto = ""
                samples = 0
                deadline = time.monotonic() + args.seconds
                for chunk in iterador:
                    samples += len(chunk)
                    reconocido = transcriber.accept(chunk)
                    if reconocido:
                        texto = reconocido
                        break
                    if time.monotonic() >= deadline:
                        break
                # Una fuente finita (WAV) o un corte pueden terminar sin silencio
                # de cierre: se cierra la frase en curso para no perder el tramo.
                if not texto:
                    texto = transcriber.flush()

                if not texto.strip():
                    # Wake word sola: no es un error, se vuelve a escuchar.
                    logger.info("talk.empty", source=source)
                    continue

                result = classify(texto, client, config.embedding, logger)
                logger.info("voice.transcript", texto=texto, source=source, samples=samples)

                frame = _build_classified_frame(result, args, config, origin_id)
                if not args.no_send:
                    node.send_alert(frame)

                _print_voice_result(texto, result, no_send=args.no_send, as_json=args.json)
                # Vuelve a la fase de wake word: el nodo sigue escuchando.
        except KeyboardInterrupt:
            pass
    finally:
        if microphone is not None:
            microphone.close()
        node.close()
        logger.info("shutdown")
        logger.close()
    return 0


def _text(args: argparse.Namespace) -> int:
    """Clasifica una frase escrita (nivel L1) y muestra el resultado.

    Es la puerta de entrada para depurar el clasificador sin micrófono. Con
    ``embedding.kind: null`` corre sin red; con Ollama usa el modelo configurado.
    """

    config = load_config(args.config)
    logger = _make_logger(config)
    client = create_embedding_client(config.embedding, logger)
    try:
        result = classify(args.phrase, client, config.embedding, logger)
    finally:
        logger.close()

    if args.json:
        print(
            json.dumps(
                {
                    "hazard": result.hazard.name,
                    "lane": result.lane.name,
                    "dist_km": result.dist_km,
                    "urgency": result.urgency.name,
                    "confidence": result.confidence.name,
                    "similarity": round(result.similarity, 4),
                    "margin": round(result.margin, 4),
                },
                ensure_ascii=False,
            )
        )
        return 0

    distancia = "desconocida" if result.dist_km == DIST_UNKNOWN else f"{result.dist_km} km"
    print(f"peligro   : {result.hazard.name}")
    print(f"carril    : {result.lane.name}")
    print(f"distancia : {distancia}")
    print(f"urgencia  : {result.urgency.name}")
    print(f"confianza : {result.confidence.name}")
    print(f"similitud : {result.similarity:.4f}")
    print(f"margen    : {result.margin:.4f}")
    return 0


def _selftest_checks() -> list[tuple[str, bool, str]]:
    from .frame import CRC16_CCITT_FALSE_INIT, FRAME_SIZE, crc16_ccitt_false, decode

    checks: list[tuple[str, bool, str]] = []

    crc_vector = crc16_ccitt_false(b"123456789")
    checks.append(
        (
            "vector de verificación de crc16 b'123456789' -> 0x29B1",
            crc_vector == 0x29B1,
            f"se obtuvo 0x{crc_vector:04X}",
        )
    )
    checks.append(
        (
            "la constante init de crc16 es 0xFFFF",
            CRC16_CCITT_FALSE_INIT == 0xFFFF,
            f"se obtuvo 0x{CRC16_CCITT_FALSE_INIT:04X}",
        )
    )

    example = AlertFrame(
        alert_id=0x11223344,
        origin_id=1,
        origin_role=0,
        hop=0,
        ttl=3,
        hazard=Hazard.PIEDRAS,
        lane=Lane.DERECHO,
        dist_km=2,
        urgency=Urgency.PRECAUCION,
        confidence=Confidence.ALTA,
    )
    encoded = example.encode()
    checks.append(
        (
            "la trama codificada tiene 17 bytes",
            len(encoded) == FRAME_SIZE,
            f"se obtuvo {len(encoded)}",
        )
    )
    checks.append(("ida y vuelta encode/decode", decode(encoded) == example, ""))

    corrupt = bytearray(encoded)
    corrupt[16] ^= 0xFF
    checks.append(("la trama corrupta se rechaza", decode(bytes(corrupt)) is None, ""))
    short = b"\x00" * 16
    checks.append(("la trama corta se rechaza", decode(short) is None, ""))
    unknown_version = bytearray(encoded)
    unknown_version[0] = 2
    checks.append(("la versión desconocida se rechaza", decode(bytes(unknown_version)) is None, ""))

    expected_phrase = "Piedras en la calzada, carril derecho, a 2 kilómetros. Precaución."
    phrase = build_phrase(example)
    checks.append(("frase de ejemplo de docs/06", phrase == expected_phrase, phrase))

    return checks


def _selftest(_args: argparse.Namespace) -> int:
    print(f"comboy-safe {__version__} autoprueba")
    failures = 0
    for name, ok, detail in _selftest_checks():
        status = "OK" if ok else "FALLA"
        suffix = f" ({detail})" if detail and not ok else ""
        print(f"  [{status}] {name}{suffix}")
        if not ok:
            failures += 1
    if failures:
        print(f"autoprueba FALLÓ ({failures} verificaciones)")
        return 1
    print("autoprueba OK")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        return _run(args)
    if args.command == "send":
        return _send(args)
    if args.command == "listen":
        return _listen(args)
    if args.command == "voice":
        return _voice(args)
    if args.command == "talk":
        return _talk(args)
    if args.command == "text":
        return _text(args)
    if args.command == "selftest":
        return _selftest(args)

    parser.print_help()
    return 2


__all__ = ["build_parser", "main"]
