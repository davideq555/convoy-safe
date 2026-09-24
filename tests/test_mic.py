"""Tests del micrófono (``arecord``) y del lector de WAV.

No tocan audio real: el subproceso se reemplaza por un doble y el WAV se
construye con la librería estándar.
"""

from __future__ import annotations

import io
import wave
from pathlib import Path

import pytest
from convoy import mic
from convoy.logging_setup import Logger


class _ProcesoFalso:
    """Sustituto mínimo de ``subprocess.Popen`` para no abrir el micrófono."""

    def __init__(self, data: bytes) -> None:
        self.stdout = io.BytesIO(data)
        self.terminated = False
        self.killed = False
        self.wait_llamado = False

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> int:
        self.wait_llamado = True
        return 0


def _logger(buffer: io.StringIO) -> Logger:
    return Logger(node_id=1, role="leader", stream=buffer)


def test_sin_arecord_queda_no_disponible(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mic.shutil, "which", lambda _name: None)
    buffer = io.StringIO()
    micro = mic.Microphone(logger=_logger(buffer))

    assert micro.available is False
    assert list(micro.chunks()) == []
    micro.close()  # no debe lanzar
    assert "mic.unavailable" in buffer.getvalue()


def test_cerrar_dos_veces_no_falla(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mic.shutil, "which", lambda _name: "/usr/bin/arecord")
    micro = mic.Microphone()
    micro.close()
    micro.close()


def test_chunks_entrega_el_pcm_y_cierra_el_proceso(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proceso = _ProcesoFalso(b"abcdefgh")
    monkeypatch.setattr(mic.shutil, "which", lambda _name: "/usr/bin/arecord")
    monkeypatch.setattr(mic, "DEFAULT_CHUNK_BYTES", 4)
    monkeypatch.setattr(mic.subprocess, "Popen", lambda *args, **kwargs: proceso)

    micro = mic.Microphone()

    assert list(micro.chunks()) == [b"abcd", b"efgh"]
    assert proceso.terminated is True
    assert proceso.wait_llamado is True
    micro.close()  # segunda vez: seguro


def test_wav_16k_mono_s16_entrega_los_bytes(tmp_path: Path) -> None:
    path = tmp_path / "voz.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x01\x02" * 1000)

    assert len(b"".join(mic.wav_chunks(path))) == 2000


def test_wav_con_formato_incorrecto_falla_claro(tmp_path: Path) -> None:
    path = tmp_path / "voz.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 100)

    with pytest.raises(ValueError, match="16 kHz, mono, s16"):
        mic.wav_chunks(path)
