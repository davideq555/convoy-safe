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

Detección temprana por resultados parciales
-------------------------------------------

Vosk no reporta nada hasta que detecta silencio. Mientras el conductor sigue
hablando después de "atencion comboy", el detector no dice nada y los chunks de
la frase de peligro se descartan. Con ``early=True`` el detector mira también
:meth:`~KaldiRecognizer.PartialResult`, que trae el texto provisorio **sin**
esperar silencio: la wake word dispara apenas se pronuncia y la frase no pierde
su arranque. :meth:`VoskWakeWord.accept` documenta el latch que evita disparos
repetidos mientras el parcial siga conteniendo la frase.

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
        logger: Logger | None = None,
    ) -> None:
        """Construye el detector.

        ``early`` habilita la detección por resultados parciales. Existe porque
        Vosk no reporta hasta el silencio: si el conductor encadena "atencion
        comboy" con la frase de peligro, el final no llega hasta que termina y
        los chunks intermedios se descartan. Con ``early=True`` la wake word
        dispara apenas se pronuncia. El costo es que puede disparar un poco
        antes, dejando un resto de "convoy" al principio de la frase capturada.
        Por defecto queda apagado: ``listen`` no cambia de comportamiento.
        """

        self._logger = logger
        self._grammar_phrase = to_grammar(phrase)
        self._rate = rate
        self._early = early
        self._model: Any = None
        self._recognizer: Any = None
        self._last_text = ""
        # Latch de disparo por parcial. Ver :meth:`accept`: evita que el texto
        # parcial, que sigue conteniendo la frase mientras el conductor habla,
        # dispare en cada chunk.
        self._latched = False

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

    def _warn_unavailable(self, **extra: object) -> None:
        if self._logger is not None:
            self._logger.warn("wakeword.unavailable", **extra)

    def accept(self, pcm: bytes) -> bool:
        """Procesa un fragmento de PCM y reporta si la wake word está presente.

        Vosk emite un resultado **final** cuando detecta el fin de la frase
        (silencio); recién ahí se compara el texto, como siempre. Con
        ``early=True`` también se interpretan los resultados **parciales** de
        :meth:`~KaldiRecognizer.PartialResult`, que Vosk emite en streaming sin
        esperar silencio: la wake word dispara apenas se pronuncia y no se
        pierden los chunks donde el conductor ya arrancó la frase de peligro.

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
        """Reinicia el recognizer y el estado interno del detector.

        Se usa al volver a la fase de wake word después de procesar una frase:
        el texto parcial de la wake word anterior puede seguir vivo y
        re-disparar de inmediato. Limpia el latch y :attr:`last_text`, y delega
        en ``Reset()`` del recognizer. No lanza si el recognizer no está
        disponible.
        """

        self._latched = False
        self._last_text = ""
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
        """Extrae el texto de un JSON de Vosk y comprueba la frase completa."""

        try:
            text = str(json.loads(raw).get("text", ""))
        except (TypeError, ValueError, AttributeError):
            return False
        text = " ".join(text.split())
        self._last_text = text
        return bool(text) and self._grammar_phrase in text


__all__ = [
    "DEFAULT_MODEL_PATH",
    "UNKNOWN_TOKEN",
    "VOCABULARY_SUBSTITUTIONS",
    "WAKE_PHRASE",
    "VoskWakeWord",
    "WakeWordDetector",
    "to_grammar",
]
