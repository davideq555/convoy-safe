"""Captura de audio en vivo usando ``arecord`` vía subprocess.

Este módulo sigue el mismo patrón que :mod:`convoy.tts`: se apoya en un binario
del sistema en lugar de agregar una dependencia. ``arecord`` (alsa-utils) entrega
PCM crudo por *stdout* y no arrastra PortAudio ni ``sounddevice``, que el diseño
del proyecto evita a propósito.

Formato esperado del PCM: **16 kHz, mono, entero con signo de 16 bits
little-endian** (``S16_LE``). Es el mismo formato que consume el motor de wake
word (:mod:`convoy.wakeword`), así que los bytes viajan sin conversión.

El audio **nunca se persiste** (D8): los fragmentos existen solo en memoria
mientras se procesan.

Si el binario no está disponible, el módulo registra un único WARN
``mic.unavailable`` y la captura pasa a ser un no-op que no entrega fragmentos.
Correr sin micrófono nunca debe tumbar el nodo: la degradación es silenciosa y
el resto del sistema sigue funcionando.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import wave
from collections.abc import Iterator

from .logging_setup import Logger

#: Binario buscado en el PATH.
ARECORD_BINARY = "arecord"

#: Frecuencia de muestreo en Hz. La del pipeline de audio completo.
DEFAULT_RATE = 16000

#: Tamaño de fragmento en bytes. 4000 bytes a 16 kHz mono s16 son ~125 ms, que
#: es un buen compromiso entre latencia y cantidad de llamadas al motor.
DEFAULT_CHUNK_BYTES = 4000

#: Segundos que se espera a que el proceso termine antes de matarlo.
_TERM_TIMEOUT = 2.0


class Microphone:
    """Fuente de PCM crudo sobre ``arecord``.

    Es best-effort: si ``arecord`` falta o falla al arrancar, :attr:`available`
    queda en ``False`` y :meth:`chunks` no entrega nada.
    """

    def __init__(
        self,
        device: str | None = None,
        rate: int = DEFAULT_RATE,
        binary: str = ARECORD_BINARY,
        logger: Logger | None = None,
    ) -> None:
        self._device = device
        self._rate = rate
        self._logger = logger
        self._requested_binary = binary
        self._binary = shutil.which(binary)
        self._process: subprocess.Popen[bytes] | None = None
        self._closed = False
        self._unavailable_warned = False
        if self._binary is None:
            self._warn_unavailable()

    @property
    def available(self) -> bool:
        """``True`` si el binario existe; no garantiza que el dispositivo abra."""

        return self._binary is not None

    def _warn_unavailable(self, **extra: object) -> None:
        if self._logger is not None and not self._unavailable_warned:
            self._logger.warn("mic.unavailable", binary=self._requested_binary, **extra)
            self._unavailable_warned = True

    def _start(self) -> subprocess.Popen[bytes] | None:
        """Lanza ``arecord`` en modo ``S16_LE`` mono crudo hacia un pipe."""

        if self._binary is None or self._closed:
            return None
        args = [
            self._binary,
            "-q",
            "-f",
            "S16_LE",
            "-r",
            str(self._rate),
            "-c",
            "1",
            "-t",
            "raw",
        ]
        if self._device:
            args += ["-D", self._device]
        # ``-`` como archivo de salida manda el PCM a stdout.
        args.append("-")
        try:
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            self._warn_unavailable(error=str(exc))
            return None
        self._process = process
        return process

    def chunks(self) -> Iterator[bytes]:
        """Genera fragmentos de PCM crudo hasta que el proceso termina o se cierra.

        Bloquea en cada lectura, así que pensado para correr en el hilo del
        llamador (o en uno propio). Al agotarse cierra el proceso.
        """

        if self._binary is None or self._closed:
            return
        process = self._start()
        if process is None:
            return
        try:
            stdout = process.stdout
            if stdout is None:
                return
            try:
                while True:
                    data = stdout.read(DEFAULT_CHUNK_BYTES)
                    if not data:
                        break
                    yield data
            except (OSError, ValueError):
                # El proceso murió o el pipe se cerró: la captura degrada a vacío.
                return
        finally:
            self.close()

    def close(self) -> None:
        """Termina el proceso de captura y espera a que salga. Nunca lanza.

        Es idempotente: llamarlo dos veces (o sin haber capturado nunca) es
        seguro. Evita dejar procesos huérfanos, que en este proyecto ya fueron un
        problema.
        """

        self._closed = True
        process, self._process = self._process, None
        if process is None:
            return
        with contextlib.suppress(OSError):
            process.terminate()
        try:
            process.wait(timeout=_TERM_TIMEOUT)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(OSError):
                process.kill()
            with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                process.wait(timeout=_TERM_TIMEOUT)
        except OSError:
            # El proceso ya no existe: no hay nada más que esperar.
            pass
        stdout = process.stdout
        if stdout is not None:
            with contextlib.suppress(OSError, ValueError):
                stdout.close()


def wav_chunks(
    path: str,
    *,
    rate: int = DEFAULT_RATE,
    chunk_bytes: int = DEFAULT_CHUNK_BYTES,
) -> Iterator[bytes]:
    """Lee un WAV y genera su PCM crudo, validando el formato.

    Existe para poder probar la cadena wake word -> alerta sin micrófono. El
    archivo debe ser 16 kHz, mono y s16; si no, lanza ``ValueError`` con un
    mensaje claro en español. La validación es inmediata (no espera a iterar).
    """

    try:
        # El handle es dueño del iterador que se devuelve más abajo, así que un
        # context manager no aplica: se cierra en el ``finally`` de _iter_wav.
        handle = wave.open(str(path), "rb")  # noqa: SIM115
    except (OSError, wave.Error) as exc:
        raise ValueError(f"no se pudo abrir el WAV {str(path)!r}: {exc}") from exc
    if handle.getframerate() != rate or handle.getnchannels() != 1 or handle.getsampwidth() != 2:
        detalle = (
            f"{handle.getframerate()} Hz, "
            f"{handle.getnchannels()} canal(es), "
            f"{handle.getsampwidth() * 8} bits"
        )
        handle.close()
        raise ValueError(f"el WAV debe ser 16 kHz, mono, s16; {str(path)!r} tiene {detalle}")
    return _iter_wav(handle, chunk_bytes)


def _iter_wav(handle: wave.Wave_read, chunk_bytes: int) -> Iterator[bytes]:
    """Genera fragmentos de un WAV ya validado y cierra el archivo al terminar."""

    frames = max(1, chunk_bytes // 2)  # sampwidth = 2 bytes por muestra
    try:
        while True:
            data = handle.readframes(frames)
            if not data:
                break
            yield data
    finally:
        handle.close()


__all__ = [
    "ARECORD_BINARY",
    "DEFAULT_CHUNK_BYTES",
    "DEFAULT_RATE",
    "Microphone",
    "wav_chunks",
]
