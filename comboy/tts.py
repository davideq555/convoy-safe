"""Texto a voz en la Raspberry Pi usando ``espeak-ng`` vía subprocess.

La Fase 0 usa ``espeak-ng`` porque es instantáneo y no necesita descargar
modelos (ver docs/09-banco-de-pruebas.md). Piper es el motor de producción
previsto y reemplazará a este módulo más adelante.

Si el binario no está, el speaker registra un único WARN ``tts.unavailable`` y
pasa a ser un no-op. Correr sin audio nunca debe tumbar el nodo.
"""

from __future__ import annotations

import shutil
import subprocess

from .logging_setup import Logger

#: Binario buscado en el PATH. ``piper`` deliberadamente no se maneja todavía.
ESPEAK_BINARY = "espeak-ng"

#: Voz por defecto. ``es-AR`` no siempre está instalada; la ``es`` simple es segura.
DEFAULT_VOICE = "es"


class Speaker:
    """Speaker de TTS síncrono sobre ``espeak-ng``."""

    def __init__(
        self,
        *,
        voice: str = DEFAULT_VOICE,
        logger: Logger | None = None,
        binary: str = ESPEAK_BINARY,
    ) -> None:
        self._voice = voice
        self._logger = logger
        self._binary = shutil.which(binary)
        self._unavailable_warned = False
        self._failure_warned = False
        if self._binary is None:
            self._warn_unavailable()

    @property
    def available(self) -> bool:
        return self._binary is not None

    def _warn_unavailable(self) -> None:
        if self._logger is not None and not self._unavailable_warned:
            self._logger.warn("tts.unavailable", binary=ESPEAK_BINARY)
            self._unavailable_warned = True

    def speak(self, text: str) -> None:
        """Sintetiza ``text`` hacia los parlantes. Best-effort y nunca lanza excepciones."""

        if not text or self._binary is None:
            return
        try:
            subprocess.run(
                [self._binary, "-v", self._voice, text],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            if self._logger is not None and not self._failure_warned:
                self._logger.warn("tts.unavailable", binary=ESPEAK_BINARY, error=str(exc))
                self._failure_warned = True


__all__ = ["DEFAULT_VOICE", "ESPEAK_BINARY", "Speaker"]
