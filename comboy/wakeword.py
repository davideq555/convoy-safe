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

Solo responde sí/no a la wake word. El VAD, la transcripción de la frase de
peligro, el clasificador y el half-duplex son parte de la Fase 2 pero **no** de
este slice.

Si el modelo falta, el módulo registra un único WARN ``wakeword.unavailable`` y
queda permanentemente no disponible: :meth:`VoskWakeWord.accept` siempre devuelve
``False``. Nunca lanza excepciones.
"""

from __future__ import annotations

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
        logger: Logger | None = None,
    ) -> None:
        self._logger = logger
        self._grammar_phrase = to_grammar(phrase)
        self._rate = rate
        self._model: Any = None
        self._recognizer: Any = None
        self._last_text = ""

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
        """Último texto final reconocido (vacío si todavía no hubo ninguno)."""

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
        """Procesa un fragmento de PCM y reporta si terminó una frase con la wake word.

        Vosk emite un resultado final cuando detecta el fin de la frase; recién
        ahí se compara el texto. Devuelve ``False`` ante cualquier error.
        """

        if self._recognizer is None:
            return False
        try:
            if not self._recognizer.AcceptWaveform(pcm):
                return False
            return self._interpret(self._recognizer.Result())
        except Exception:
            return False

    def flush(self) -> bool:
        """Cierra la frase en curso y reporta si la wake word estaba en la cola.

        Necesario para fuentes finitas (por ejemplo un WAV) que terminan sin
        silencio de cierre: sin esto, el último tramo nunca se emitiría.
        """

        if self._recognizer is None:
            return False
        try:
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
