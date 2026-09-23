"""Detección de wake word con Vosk (modelo chico en español).

El nodo escucha de forma continua y solo reacciona cuando aparece la frase de
activación. Vosk hace el reconocimiento con una **gramática restringida**: la
salida solo puede contener las palabras de la gramática (o ``[unk]``), lo que
reduce falsos positivos y costo.

El motor vive detrás del :class:`WakeWordDetector`, igual que el resto del
sistema habla con ``Transport`` en vez de con un socket.

El truco de "comboy" vs "convoy"
--------------------------------

La frase que dice el conductor es ``atencion comboy``, pero la palabra que se
carga en la gramática de Vosk es **``convoy``**. No es un error de tipeo:

* ``comboy`` **no existe** en el vocabulario del modelo. Vosk descarta en
  silencio las palabras que no conoce —solo deja un aviso por *stderr*—, así que
  una gramática con ``comboy`` nunca haría match.
* ``convoy`` sí existe en el vocabulario.
* En español, ``b`` y ``v`` se pronuncian igual (betacismo). Decir "atención
  comboy" suena exactamente como "atención convoy", de modo que el modelo
  transcribe ``convoy`` y la detección funciona.

Por eso existe :data:`VOCABULARY_SUBSTITUTIONS`: la equivalencia es explícita y
se aplica token por token en :func:`to_grammar`. Un test la protege para que
nadie la "arregle" pensando que es un bug.

Alcance de este módulo
----------------------

Responde sí/no a la wake word y nada más: la transcripción de la frase de
peligro y el clasificador viven en :mod:`comboy.voice` y :mod:`comboy.classify`,
y el comando ``talk`` los une. El VAD y el half-duplex siguen pendientes.

Recuperación del audio posterior a la wake word
-----------------------------------------------

Vosk no reporta nada hasta que detecta silencio. Mientras el conductor sigue
hablando después de "atencion comboy", el detector no dice nada y los chunks de
la frase de peligro se descartan. El primer intento de arreglo fue **detección
temprana por resultados parciales** (``early=True``): mirar
:meth:`~KaldiRecognizer.PartialResult` para disparar apenas se pronuncia la
frase, sin esperar la pausa. No alcanzó: Vosk emite el parcial con retraso, una
vez que ya procesó audio que incluye el arranque de la frase, así que el disparo
sigue llegando tarde y ese arranque se pierde igual.

La solución es no depender de *cuándo* dispara la detección. En vez de evitar
perder audio, se lo **guarda y se lo recupera**: el detector mantiene un **buffer
rodante de PCM** y, cuando Vosk emite el resultado final, con ``SetWords(True)``
la respuesta trae los tiempos por palabra. El ``end`` de la última palabra es
dónde terminó la wake word; el audio posterior a ese punto se reinyecta al
transcriber de la frase. Así ninguna muestra hablada después de la activación se
pierde, sin importar cuántos chunks haya tardado la detección.

El invariante crítico es que los **timestamps de Vosk y el contador de samples
del buffer tengan el mismo origen**: ambos arrancan cuando se crea el recognizer
y **nunca se reinician**. La razón es que ``Reset()`` de Vosk limpia el estado de
decodificación pero **no** reinicia su contador de frames: sus ``end`` siguen
siendo absolutos desde el inicio del stream. Por eso
:meth:`VoskWakeWord.reset` no debe tocar el buffer ni el contador —si lo
hiciera, los dos orígenes se separarían a partir de la segunda detección y el
replay dejaría de recuperar audio—. El buffer vive acá adentro justamente para
que ese invariante no se pueda violar desde afuera. Ver
:meth:`VoskWakeWord.audio_since_wake`.

El flag ``early`` sigue existiendo (con default ``False``) por compatibilidad y
porque ``_listen`` lo deja apagado, pero ``talk`` ya no lo usa: con el replay la
detección temprana dejó de ser necesaria y se elimina el riesgo de falsos
positivos por parciales.

Si el modelo falta, el módulo registra un único WARN ``wakeword.unavailable`` y
queda permanentemente no disponible: :meth:`VoskWakeWord.accept` siempre devuelve
``False``. Nunca lanza excepciones.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .logging_setup import Logger

#: Ruta por defecto del modelo. ``models/`` está gitignoreado: no se versiona
#: ni se descarga automáticamente.
DEFAULT_MODEL_PATH = "models/vosk-model-small-es-0.42"

#: Frase que el conductor pronuncia para despertar al nodo.
WAKE_PHRASE = "atencion comboy"

#: Equivalencias que exige el vocabulario del modelo. Ver el docstring del
#: módulo: ``comboy`` no está en el vocabulario y ``convoy`` sí.
VOCABULARY_SUBSTITUTIONS: dict[str, str] = {"comboy": "convoy"}

#: Palabra de relleno que absorbe cualquier cosa fuera de la gramática.
UNKNOWN_TOKEN = "[unk]"

#: Cuántos segundos de PCM retiene el buffer rodante. A 16 kHz mono s16 son
#: ~960 KB: trivial en RAM, y cubre de sobra el tramo entre la wake word y la
#: detección, que se mide en décimas de segundo.
DEFAULT_BUFFER_SECONDS = 30.0

#: Margen de seguridad por defecto, en milisegundos, que se recorta **antes**
#: del ``end`` de la wake word al recuperar el audio. Los tiempos de Vosk vienen
#: del alineamiento acústico y pueden errar unas decenas de milisegundos: incluir
#: un pelín de audio previo (silencio o la cola de "convoy") es inofensivo,
#: mientras que cortar una sílaba de la frase sí la daña. Ver
#: :meth:`VoskWakeWord.audio_since_wake`.
DEFAULT_REPLAY_MARGIN_MS = 50.0


def _even_byte_offset(offset: int) -> int:
    """Redondea un offset en bytes hacia abajo al byte par más cercano.

    El audio es s16 mono: cada muestra ocupa 2 bytes. Un corte en un offset
    impar partiría una muestra al medio y corrompería todo el tramo. Hoy el
    offset siempre sale par porque se calcula desde índices de muestra, pero el
    redondeo queda como red de seguridad para cualquier cálculo futuro basado en
    bytes.
    """

    return offset - (offset % 2)


def to_grammar(phrase: str) -> str:
    """Convierte la frase hablada en la frase que entiende la gramática.

    Aplica :data:`VOCABULARY_SUBSTITUTIONS` token por token. La sustitución es
    explícita y visible: los tokens sin equivalencia pasan tal cual.
    """

    tokens = [VOCABULARY_SUBSTITUTIONS.get(token.lower(), token) for token in phrase.split()]
    return " ".join(tokens)


@runtime_checkable
class WakeWordDetector(Protocol):
    """El resto del sistema no conoce a Vosk; habla con esto."""

    @property
    def available(self) -> bool:
        """``True`` si el detector puede procesar audio."""

        ...

    def accept(self, pcm: bytes) -> bool:
        """Recibe PCM y devuelve ``True`` justo cuando detectó la wake word."""

        ...

    def audio_since_wake(self, margin_ms: float = DEFAULT_REPLAY_MARGIN_MS) -> bytes | None:
        """Devuelve el PCM posterior a la wake word, o ``None`` si no se puede.

        Es el audio que la detección tardía habría descartado. Ver
        :meth:`VoskWakeWord.audio_since_wake`.
        """

        ...


class VoskWakeWord:
    """Detector de wake word sobre Vosk, con gramática restringida.

    Cargar el modelo tarda segundos, así que se hace **una sola vez** en el
    constructor. Si el modelo no está, el detector queda no disponible.
    """

    def __init__(
        self,
        model_path: str = DEFAULT_MODEL_PATH,
        *,
        phrase: str = WAKE_PHRASE,
        rate: int = 16000,
        early: bool = False,
        buffer_seconds: float = DEFAULT_BUFFER_SECONDS,
        logger: Logger | None = None,
    ) -> None:
        """Construye el detector.

        ``early`` habilita la detección por resultados parciales. Existe porque
        Vosk no reporta hasta el silencio: si el conductor encadena "atencion
        comboy" con la frase de peligro, el final no llega hasta que termina y
        los chunks intermedios se descartan. Con ``early=True`` la wake word
        dispara apenas se pronuncia. El costo es que puede disparar un poco
        antes, dejando un resto de "convoy" al principio de la frase capturada.
        Por defecto queda apagado: ``listen`` no cambia de comportamiento, y
        ``talk`` usa el replay del buffer en vez de este modo.

        ``buffer_seconds`` acota el buffer rodante de PCM. El buffer y el
        contador de samples **no** se reinician en :meth:`reset`: son
        monotónicos durante toda la vida del detector, igual que el origen de
        timestamps de Vosk (``Reset()`` no reinicia su contador de frames). Ver
        :meth:`reset`.
        """

        self._logger = logger
        self._grammar_phrase = to_grammar(phrase)
        self._rate = rate
        self._early = early
        self._buffer_seconds = buffer_seconds
        self._model: Any = None
        self._recognizer: Any = None
        self._last_text = ""
        # Latch de disparo por parcial. Ver :meth:`accept`: evita que el texto
        # parcial, que sigue conteniendo la frase mientras el conductor habla,
        # dispare en cada chunk.
        self._latched = False
        # Buffer rodante de PCM ya alimentado. Se llena **antes** de procesar
        # cada chunk con Vosk (ver :meth:`accept`), así el audio en vuelo ya está
        # disponible cuando la detección dispara.
        self._pcm_buffer = bytearray()
        # Samples absolutos alimentados durante toda la vida del detector. Es el
        # mismo origen temporal que usan los timestamps de Vosk: el sample del
        # buffer que corresponde a ``end`` segundos es ``int(end * rate)``. No se
        # reinicia en reset(): ver el invariante allí. Ver el docstring del
        # módulo.
        self._total_samples_fed = 0
        # Sample absoluto donde terminó la wake word, según los timestamps por
        # palabra del último resultado interpretado. ``None`` si ese resultado no
        # traía array ``result`` (o si todavía no hubo detección).
        self._wake_end_sample: int | None = None

        path = Path(model_path)
        if not path.is_dir():
            self._warn_unavailable(model=model_path, motivo="modelo ausente")
            return

        # Import perezoso: el módulo debe poder importarse (y el resto de los
        # comandos funcionar) aunque vosk no esté instalado.
        try:
            from vosk import KaldiRecognizer, Model, SetLogLevel
        except Exception as exc:
            self._warn_unavailable(model=model_path, error=str(exc))
            return

        try:
            SetLogLevel(-1)  # silencia el logging interno de kaldi
            model = Model(str(path))
            grammar = json.dumps([self._grammar_phrase, UNKNOWN_TOKEN], ensure_ascii=False)
            self._recognizer = KaldiRecognizer(model, rate, grammar)
            # Sin esto, ``Result()`` no trae el array ``result`` con los tiempos
            # por palabra, y el replay no tendría de dónde sacar ``wake_end``.
            self._recognizer.SetWords(True)
            self._model = model  # mantiene vivo el modelo mientras exista el recognizer
        except Exception as exc:
            self._warn_unavailable(model=model_path, error=str(exc))

    @property
    def available(self) -> bool:
        return self._recognizer is not None

    @property
    def last_text(self) -> str:
        """Último texto reconocido que se interpretó, final o parcial.

        Vacío si todavía no hubo ninguno. Con ``early=True`` puede ser un texto
        **parcial**: es el que efectivamente disparó la detección, útil para el
        log. Ver :meth:`accept`.
        """

        return self._last_text

    @property
    def model(self) -> Any:
        """Modelo de Vosk ya cargado, o ``None`` si el detector no está disponible.

        Se expone para poder **compartirlo**: :class:`comboy.voice.VoskTranscriber`
        construye su recognizer sobre el mismo modelo en vez de cargar un segundo,
        que costaría segundos de latencia y RAM. Mientras exista el detector, el
        modelo sigue vivo y el transcriber puede apoyarse en él.
        """

        return self._model

    @property
    def buffered_samples(self) -> int:
        """Samples de PCM retenidos hoy en el buffer rodante.

        Es observabilidad baratita: permite verificar que el buffer no crece sin
        límite (se descarta lo más viejo al pasar de :data:`DEFAULT_BUFFER_SECONDS`).
        **No** se vacía en :meth:`reset`: el buffer es monotónico durante toda la
        vida del detector, igual que el origen de timestamps de Vosk. Ver el
        invariante en :meth:`reset`.
        """

        return len(self._pcm_buffer) // 2

    @property
    def total_samples_fed(self) -> int:
        """Samples absolutos alimentados durante toda la vida del detector.

        Es el origen temporal que comparten el buffer y los timestamps de Vosk.
        **No** vuelve a cero en :meth:`reset`: ver el invariante allí. Ver
        también el docstring del módulo.
        """

        return self._total_samples_fed

    def _warn_unavailable(self, **extra: object) -> None:
        if self._logger is not None:
            self._logger.warn("wakeword.unavailable", **extra)

    def _append(self, pcm: bytes) -> None:
        """Agrega el chunk al buffer rodante y avanza el contador de samples.

        Se llama **antes** de procesar el chunk con Vosk: así el audio en vuelo
        ya está en el buffer cuando la detección dispara, y el replay no depende
        de cuándo Vosk decidió emitir el resultado. Solo se guardan muestras
        completas (bytes pares); un byte suelto no es una muestra s16.

        El buffer está acotado a :data:`DEFAULT_BUFFER_SECONDS` segundos: al
        pasarse se descarta lo más viejo. El contador de samples absolutos no se
        toca al descartar, así el origen temporal sigue siendo el del recognizer.
        """

        usable = len(pcm) - (len(pcm) % 2)
        if usable <= 0:
            return
        self._pcm_buffer.extend(pcm[:usable])
        self._total_samples_fed += usable // 2

        max_bytes = int(self._buffer_seconds * self._rate) * 2
        excess = len(self._pcm_buffer) - max_bytes
        if excess > 0:
            # Descartar una cantidad impar de bytes desalinearía el buffer
            # respecto de los samples: se redondea hacia arriba a byte par.
            excess += excess % 2
            del self._pcm_buffer[:excess]

    def audio_since_wake(self, margin_ms: float = DEFAULT_REPLAY_MARGIN_MS) -> bytes | None:
        """Devuelve el PCM posterior a la wake word, listo para el transcriber.

        Es el corazón del arreglo: cuando Vosk detecta la wake word —tarde, tras
        varios chunks— el buffer ya tiene todo el audio que vino después, y este
        método lo entrega para reinyectarlo. El tramo devuelto termina
        exactamente donde termina el buffer, así que los chunks que siguen se
        procesan en vivo sin solaparse ni duplicarse.

        Origen temporal
        ---------------

        ``wake_end_sample`` y el buffer se miden en el mismo contador de samples
        absolutos: ambos arrancan cuando se crea el recognizer y **nunca se
        reinician**, porque ``Reset()`` de Vosk limpia el estado de decodificación
        pero no su contador de frames. Por eso el ``end`` en segundos del array
        ``result`` de Vosk se traduce a un índice de sample con ``end * rate`` y
        apunta al lugar correcto del buffer incluso después de varios
        :meth:`reset`. Si los dos orígenes se separaran, el recorte empezaría en
        cualquier lado; ese caso lo detecta el guard de abajo.

        Margen de seguridad
        -------------------

        ``margin_ms`` se resta al punto de corte: se devuelve audio desde un
        poco **antes** de que terminara la wake word. Los timestamps de Vosk
        vienen del alineamiento acústico y pueden errar unas decenas de
        milisegundos; incluir la cola de "convoy" o un poco de silencio no
        molesta al clasificador, pero cortar el arranque de una sílaba de la
        frase sí. El default es :data:`DEFAULT_REPLAY_MARGIN_MS`.

        Fallback y guard
        ----------------

        Devuelve ``None`` —nunca lanza— cuando no puede recuperar el audio:

        * el resultado que disparó no traía array ``result`` (sin timestamp), o
        * la wake word quedó más atrás que el buffer (audio ya descartado).

        En ambos casos se registra ``wakeword.replay_fallback`` con el motivo y
        el llamador cae al comportamiento de siempre: empezar en el chunk
        siguiente. No es un error: es la degradación segura cuando el dato no
        está.

        Aparte está el caso en que ``wake_end_sample`` **supera** a
        :attr:`total_samples_fed`: eso es imposible si ambos comparten el mismo
        origen, así que no es un fallback sino un **invariante roto**. Se registra
        ``wakeword.invariant_broken`` con los dos valores como evidencia y se
        devuelve ``None``. Si aparece en un log, hay un bug de sincronía en el
        detector —no un dato faltante— y hay que arreglarlo, no confiar en el
        replay.
        """

        if self._recognizer is None:
            return None
        if self._wake_end_sample is None:
            self._log_replay_fallback("sin_timestamp")
            return None
        if self._wake_end_sample > self._total_samples_fed:
            # El corte apunta más allá de todo lo alimentado: los dos orígenes
            # se separaron. Es un bug, no un fallback.
            self._log_invariant_broken()
            return None

        margin_samples = int(margin_ms / 1000.0 * self._rate)
        start_sample = self._wake_end_sample - margin_samples
        if start_sample < 0:
            start_sample = 0

        buffer_start_sample = self._total_samples_fed - len(self._pcm_buffer) // 2
        if start_sample < buffer_start_sample:
            # La wake word terminó antes de lo que el buffer conserva: el audio
            # ya se descartó y no hay forma de recuperarlo.
            self._log_replay_fallback("fuera_del_buffer")
            return None

        offset = _even_byte_offset((start_sample - buffer_start_sample) * 2)
        recorte = bytes(self._pcm_buffer[offset:])
        return recorte or None

    def _log_replay_fallback(self, reason: str) -> None:
        if self._logger is not None:
            self._logger.warn("wakeword.replay_fallback", reason=reason)

    def _log_invariant_broken(self) -> None:
        """Registra que los orígenes temporales de Vosk y del buffer se separaron.

        Es un evento **ERROR** y distinto de ``wakeword.replay_fallback`` a
        propósito: un fallback es degradación esperada (falta el dato); esto es
        un **bug** de sincronía del detector. Se registran los dos valores como
        evidencia: si ``wake_end_sample > total_samples_fed``, el corte apunta
        más allá de todo lo alimentado y no hay audio válido que recuperar.
        """

        if self._logger is not None:
            self._logger.error(
                "wakeword.invariant_broken",
                wake_end_sample=self._wake_end_sample,
                total_samples_fed=self._total_samples_fed,
            )

    def accept(self, pcm: bytes) -> bool:
        """Procesa un fragmento de PCM y reporta si la wake word está presente.

        Vosk emite un resultado **final** cuando detecta el fin de la frase
        (silencio); recién ahí se compara el texto, como siempre. Con
        ``early=True`` también se interpretan los resultados **parciales** de
        :meth:`~KaldiRecognizer.PartialResult`, que Vosk emite en streaming sin
        esperar silencio.

        El chunk se agrega al buffer rodante **antes** de pasarlo a Vosk. El
        orden importa: si se procesara primero y se buffeara después, el audio
        que disparó la detección podría no estar todavía en el buffer y el
        replay perdería justo el tramo en vuelo.

        Latch de parciales
        ------------------

        El texto parcial sigue conteniendo "atencion convoy" en **todos** los
        chunks mientras el conductor habla. Sin protección, ``accept`` devolvería
        ``True`` en cada uno y se mandarían alertas duplicadas. Por eso, cuando
        el disparo viene de un parcial se activa un latch que ignora los
        parciales siguientes hasta que llegue un resultado final, que lo limpia.
        El resultado neto es **una detección por utterance**. El final sí puede
        volver a disparar: es el que cierra la frase y re-arma el latch.

        Devuelve ``False`` ante cualquier error.
        """

        if self._recognizer is None:
            return False
        try:
            self._append(pcm)
            if self._recognizer.AcceptWaveform(pcm):
                # Un final cierra la utterance: limpia el latch de parciales.
                self._latched = False
                return self._interpret(self._recognizer.Result())
            if not self._early:
                return False
            if self._latched:
                # Ya disparó un parcial de esta utterance; el parcial sigue
                # conteniendo la frase, así que se ignora hasta el final.
                return False
            if self._interpret(self._recognizer.PartialResult()):
                self._latched = True
                return True
            return False
        except Exception:
            return False

    def reset(self) -> None:
        """Reinicia el recognizer y el estado de disparo del detector.

        Se usa al volver a la fase de wake word después de procesar una frase:
        el texto parcial de la wake word anterior puede seguir vivo y
        re-disparar de inmediato. Limpia el latch, :attr:`last_text` y
        ``_wake_end_sample``, y delega en ``Reset()`` del recognizer. No lanza si
        el recognizer no está disponible.

        Invariante: el buffer y el contador **NO** se limpian
        ----------------------------------------------------

        A primera vista "reset debería limpiar todo" parece lo correcto, pero
        acá sería un bug. El origen temporal del replay es el del stream del
        recognizer de Vosk, y ``Reset()`` limpia el estado de decodificación
        **pero no reinicia su contador de frames**: los ``end`` de los resultados
        siguientes siguen siendo absolutos desde el inicio del stream. Para que
        ``wake_end_sample`` (absoluto, en samples de Vosk) siga apuntando al
        sample correcto de :attr:`_pcm_buffer`, el buffer y
        :attr:`total_samples_fed` tienen que ser **monotónicos durante toda la
        vida del detector**, igual que el contador de Vosk.

        Si ``reset`` volviera :attr:`total_samples_fed` a cero y vaciara el
        buffer, a partir de la **segunda** detección los dos orígenes quedarían
        desfasados: ``wake_end_sample`` (grande) superaría a
        ``total_samples_fed`` (chico), el recorte caería fuera del buffer y
        :meth:`audio_since_wake` devolvería ``None`` para siempre. El guard
        ``wakeword.invariant_broken`` detecta justo ese caso.

        El buffer no crece sin control por no vaciarse: está acotado a
        :data:`DEFAULT_BUFFER_SECONDS` y :meth:`_append` descarta lo más viejo al
        pasarse.

        Riesgo residual: ``flush()``/``FinalResult()``
        ----------------------------------------------

        Este método no llama ``flush()``. Queda anotado como riesgo conocido que
        si en el futuro algo invocara ``flush()``/``FinalResult()`` sobre este
        detector, habría que verificar si **eso** sí reinicia el contador de
        frames de Vosk: no está medido. Si lo hiciera, el mismo desfase que
        arregla este cambio reaparecería por otra puerta.
        """

        self._latched = False
        self._last_text = ""
        self._wake_end_sample = None
        # El buffer y _total_samples_fed quedan intactos a propósito: ver el
        # invariante en este docstring. Limpiarlos separaría los orígenes.
        if self._recognizer is None:
            return
        with contextlib.suppress(Exception):
            self._recognizer.Reset()

    def flush(self) -> bool:
        """Cierra la frase en curso y reporta si la wake word estaba en la cola.

        Necesario para fuentes finitas (por ejemplo un WAV) que terminan sin
        silencio de cierre: sin esto, el último tramo nunca se emitiría. Como un
        final, limpia el latch de parciales.
        """

        if self._recognizer is None:
            return False
        try:
            self._latched = False
            return self._interpret(self._recognizer.FinalResult())
        except Exception:
            return False

    def _interpret(self, raw: str) -> bool:
        """Extrae el texto de un JSON de Vosk y comprueba la frase completa.

        De paso refresca :attr:`_wake_end_sample` desde el array ``result`` del
        resultado. Se limpia antes de parsear para que un resultado sin
        timestamps no deje colgado el ``wake_end`` de una utterance anterior: si
        no hay dato, el replay debe caer al fallback, no usar un sample viejo.
        """

        self._wake_end_sample = None
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError, AttributeError):
            return False
        if not isinstance(payload, dict):
            return False
        text = " ".join(str(payload.get("text", "")).split())
        self._last_text = text
        self._remember_wake_end(payload)
        return bool(text) and self._grammar_phrase in text

    def _remember_wake_end(self, payload: dict[str, Any]) -> None:
        """Guarda el sample absoluto donde terminó la última palabra reconocida.

        Con ``SetWords(True)``, ``Result()`` incluye ``result``: una lista de
        palabras con ``start``/``end`` **en segundos** desde el inicio del stream
        del recognizer. El ``end`` de la última palabra es el fin de la wake
        word, y como el contador de samples del buffer usa el mismo origen, el
        sample absoluto sale de ``end * rate``.

        Si el array falta, está vacío o no tiene un ``end`` numérico, no se toca
        nada: :meth:`audio_since_wake` hará fallback.
        """

        words = payload.get("result")
        if not isinstance(words, list) or not words:
            return
        last = words[-1]
        if not isinstance(last, dict):
            return
        end = last.get("end")
        # ``bool`` es subclase de ``int``: hay que descartarlo explícitamente.
        if isinstance(end, bool) or not isinstance(end, (int, float)):
            return
        self._wake_end_sample = int(float(end) * self._rate)


__all__ = [
    "DEFAULT_BUFFER_SECONDS",
    "DEFAULT_MODEL_PATH",
    "DEFAULT_REPLAY_MARGIN_MS",
    "UNKNOWN_TOKEN",
    "VOCABULARY_SUBSTITUTIONS",
    "WAKE_PHRASE",
    "VoskWakeWord",
    "WakeWordDetector",
    "to_grammar",
]
