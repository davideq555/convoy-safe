"""Transcripción de voz libre con Vosk (modelo chico en español).

Este módulo convierte el audio del conductor en **texto libre**, que después el
clasificador (:mod:`comboy.classify`) transforma en un código de peligro. Es la
pieza que faltaba entre el wake word y el clasificador.

Vocabulario libre vs. gramática restringida
-------------------------------------------

``wakeword.py`` usa Vosk con una **gramática restringida** de tres tokens
(``"atencion convoy"``, ``"[unk]"``): el recognizer solo puede devolver esas
palabras, lo que reduce falsos positivos y costo. Eso sirve para responder sí o
no a la frase de activación, pero **no** para transcribir una frase de peligro:
cualquier palabra fuera de la gramática se descarta.

Acá, en cambio, se construye ``KaldiRecognizer(model, rate)`` **sin** el tercer
argumento de gramática. Sin gramática, el recognizer usa el vocabulario completo
del modelo y devuelve lo que el conductor dijo, palabra por palabra.

La sustitución ``comboy`` -> ``convoy`` de :data:`comboy.wakeword.VOCABULARY_SUBSTITUTIONS`
**no se aplica** en este camino: se quiere el texto tal cual se dijo, y ni
``convoy`` ni ``comboy`` son nombres de peligro. Ese mecanismo pertenece solo al
wake word.

El motor vive detrás de :class:`Transcriber`, igual que el resto del sistema
habla con ``Transport`` en vez de con un socket y con ``EmbeddingClient`` en vez
de con Ollama.

Degradación sin Vosk
--------------------

El import de ``vosk`` es perezoso: el módulo se puede importar (y el resto de los
comandos funcionar) aunque ``vosk`` no esté instalado. Si el modelo falta o algo
falla, se registra un único WARN ``voice.unavailable`` y el transcriber queda
permanentemente no disponible: :meth:`VoskTranscriber.accept` devuelve ``None`` y
:meth:`VoskTranscriber.flush` devuelve ``""``. **Nunca lanza.**
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .logging_setup import Logger
from .wakeword import DEFAULT_MODEL_PATH

__all__ = [
    "DEFAULT_MODEL_PATH",
    "NullTranscriber",
    "Transcriber",
    "VoskTranscriber",
    "create_transcriber",
]


@runtime_checkable
class Transcriber(Protocol):
    """El resto del sistema no conoce a Vosk; habla con esto."""

    @property
    def available(self) -> bool:
        """``True`` si el transcriber puede procesar audio."""

        ...

    @property
    def last_text(self) -> str:
        """Último texto final reconocido, vacío si todavía no hubo ninguno."""

        ...

    def accept(self, pcm: bytes) -> str | None:
        """Recibe PCM y devuelve el texto final cuando Vosk cierra una frase.

        Devuelve ``None`` mientras la frase siga en curso o no haya nada.
        """

        ...

    def flush(self) -> str:
        """Cierra la frase en curso y devuelve el texto final.

        Necesario para fuentes finitas (por ejemplo un WAV) que terminan sin
        silencio de cierre: sin esto, el último tramo nunca se emitiría.
        """

        ...


class VoskTranscriber:
    """Transcriber de vocabulario libre sobre Vosk.

    Cargar el modelo tarda segundos, así que se hace **una sola vez** en el
    constructor. Si el modelo no está —o ``vosk`` no está instalado— el
    transcriber queda no disponible y nunca lanza.

    Con el parámetro ``model`` se puede reutilizar un modelo ya cargado (por
    ejemplo el del wake word) en vez de cargar otro: así el nodo que une wake
    word y transcripción no paga dos veces la carga del modelo ni mantiene dos
    copias en RAM. Cuando ``model`` es ``None`` el comportamiento es el de
    siempre: se valida ``model_path`` y se carga desde disco.
    """

    def __init__(
        self,
        model_path: str = DEFAULT_MODEL_PATH,
        *,
        rate: int = 16000,
        logger: Logger | None = None,
        model: Any = None,
    ) -> None:
        self._logger = logger
        self._rate = rate
        self._model: Any = None
        self._recognizer: Any = None
        self._last_text = ""

        # Un modelo ya cargado se reutiliza tal cual: no se valida ni se carga
        # nada de disco. Solo sin modelo compartido se comprueba el directorio.
        if model is None:
            path = Path(model_path)
            if not path.is_dir():
                self._warn_unavailable(model=model_path, motivo="modelo ausente")
                return

        # Import perezoso: el módulo debe poder importarse (y el resto de los
        # comandos funcionar) aunque vosk no esté instalado. Aun con un modelo
        # compartido hace falta ``KaldiRecognizer`` para construir el recognizer.
        try:
            from vosk import KaldiRecognizer, Model, SetLogLevel
        except Exception as exc:
            self._warn_unavailable(model=model_path, error=str(exc))
            return

        try:
            SetLogLevel(-1)  # silencia el logging interno de kaldi
            if model is None:
                model = Model(str(path))
            # Sin el tercer argumento de gramática: vocabulario libre. Ver el
            # docstring del módulo.
            self._recognizer = KaldiRecognizer(model, rate)
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

    def _warn_unavailable(self, **extra: object) -> None:
        if self._logger is not None:
            self._logger.warn("voice.unavailable", **extra)

    def accept(self, pcm: bytes) -> str | None:
        """Procesa un fragmento de PCM y devuelve el texto final si cerró la frase.

        Vosk emite un resultado final cuando detecta el fin de la frase; recién
        ahí hay texto. Devuelve ``None`` ante cualquier error.
        """

        if self._recognizer is None:
            return None
        try:
            if not self._recognizer.AcceptWaveform(pcm):
                return None
            return self._interpret(self._recognizer.Result())
        except Exception:
            return None

    def flush(self) -> str:
        """Cierra la frase en curso y devuelve el texto final (``""`` si no hay)."""

        if self._recognizer is None:
            return ""
        try:
            return self._interpret(self._recognizer.FinalResult()) or ""
        except Exception:
            return ""

    def _interpret(self, raw: str) -> str | None:
        """Extrae el texto de un JSON de Vosk, normalizado.

        Tolera JSON inválido devolviendo ``None``. Un resultado sin texto deja
        :attr:`last_text` vacío y también devuelve ``None``.
        """

        try:
            text = str(json.loads(raw).get("text", ""))
        except (TypeError, ValueError, AttributeError):
            return None
        text = " ".join(text.split())
        self._last_text = text
        return text or None


class NullTranscriber:
    """Transcriber no-op determinista para tests y para correr sin vosk.

    ``available`` siempre es ``False``: el sistema sabe que no hay transcripción
    y no inventa texto.
    """

    @property
    def available(self) -> bool:
        return False

    @property
    def last_text(self) -> str:
        return ""

    def accept(self, pcm: bytes) -> str | None:
        return None

    def flush(self) -> str:
        return ""


def create_transcriber(
    model_path: str = DEFAULT_MODEL_PATH,
    *,
    rate: int = 16000,
    logger: Logger | None = None,
    model: Any = None,
) -> Transcriber:
    """Construye el transcriber adecuado para ``model_path``.

    Si el directorio del modelo existe, devuelve :class:`VoskTranscriber` (que
    puede quedar no disponible igual si ``vosk`` falta o el modelo no carga). Si
    no existe, devuelve :class:`NullTranscriber`: el sistema degrada sin vosk en
    vez de fallar al importar.

    Con ``model`` ya cargado se devuelve :class:`VoskTranscriber` sin importar
    ``model_path``: el modelo compartido manda y no hay que volver a tocar el
    disco. Un ``model`` en ``None`` cae en el comportamiento de siempre.
    """

    if model is not None or Path(model_path).is_dir():
        return VoskTranscriber(model_path, rate=rate, logger=logger, model=model)
    return NullTranscriber()
