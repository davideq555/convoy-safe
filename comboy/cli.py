"""Interfaz de línea de comandos: ``python -m comboy``.

Subcomandos:
    run       Corre el loop de recepción del nodo.
    send      Construye y transmite una trama de alerta.
    listen    Escucha el micrófono, detecta la wake word y envía la alerta.
    text      Clasifica una frase escrita y muestra el código resultante (L1).
    selftest  Autoprueba offline (CRC, round-trip del codec, rechazo de
              tramas corruptas, frase).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Sequence

from . import __version__
from .classify import classify
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
from .wakeword import DEFAULT_MODEL_PATH, VoskWakeWord


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m comboy",
        description="Alerta temprana de peligros para comboys de montaña (Fase 0 / L0).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    run_parser = subparsers.add_parser("run", help="corre el loop de recepción del nodo")
    run_parser.add_argument(
        "--config",
        default=None,
        help="ruta al archivo de config YAML (valores por defecto si se omite)",
    )

    send_parser = subparsers.add_parser("send", help="construye y envía una trama de alerta")
    send_parser.add_argument(
        "--config",
        default=None,
        help="ruta al archivo de config YAML (valores por defecto si se omite)",
    )
    _add_alert_arguments(send_parser)

    listen_parser = subparsers.add_parser(
        "listen", help="escucha el micrófono y envía una alerta al detectar la wake word"
    )
    listen_parser.add_argument(
        "--config",
        default=None,
        help="ruta al archivo de config YAML (valores por defecto si se omite)",
    )
    listen_parser.add_argument(
        "--wav",
        default=None,
        help="lee un WAV 16 kHz mono s16 en vez del micrófono (para probar sin micrófono)",
    )
    _add_alert_arguments(listen_parser)

    text_parser = subparsers.add_parser(
        "text", help="clasifica una frase escrita y muestra el código resultante"
    )
    text_parser.add_argument(
        "phrase", help='frase del conductor, p. ej. "hay piedras en la calzada"'
    )
    text_parser.add_argument(
        "--config",
        default=None,
        help="ruta al archivo de config YAML (valores por defecto si se omite)",
    )
    text_parser.add_argument(
        "--json", action="store_true", help="imprime la clasificación como objeto JSON"
    )

    subparsers.add_parser("selftest", help="corre las autopruebas offline (sin red)")

    return parser


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
    parser.add_argument(
        "--origin-id", type=int, default=None, help="sobrescribe el id de nodo configurado"
    )
    parser.add_argument(
        "--alert-id", type=lambda value: int(value, 0), default=None, help="id de alerta explícito"
    )


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
    if args.command == "text":
        return _text(args)
    if args.command == "selftest":
        return _selftest(args)

    parser.print_help()
    return 2


__all__ = ["build_parser", "main"]
