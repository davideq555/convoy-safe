"""Test de integración del subcomando ``listen`` con dobles.

No usa micrófono, ni red, ni modelo: reemplaza el detector, la fuente de audio y
el transporte para verificar que una detección dispara exactamente una alerta.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from comboy import cli


class _DetectorFalso:
    def __init__(self) -> None:
        self.llamadas = 0
        self.last_text = "atencion convoy"

    @property
    def available(self) -> bool:
        return True

    def accept(self, pcm: bytes) -> bool:
        self.llamadas += 1
        return self.llamadas == 1

    def flush(self) -> bool:
        return False


class _TransporteFalso:
    def __init__(self) -> None:
        self.enviadas: list[bytes] = []

    def send_frame(self, frame: bytes) -> None:
        self.enviadas.append(frame)

    def recv_frames(self) -> Iterator[tuple[bytes, str]]:
        return iter(())

    def close(self) -> None:
        pass


def test_listen_envia_una_alerta_al_detectar(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    detector = _DetectorFalso()
    transporte = _TransporteFalso()
    monkeypatch.setattr(cli, "VoskWakeWord", lambda *args, **kwargs: detector)
    monkeypatch.setattr(cli, "wav_chunks", lambda *args, **kwargs: iter([b"PCM", b"PCM"]))
    monkeypatch.setattr(cli, "create_transport", lambda *args, **kwargs: transporte)

    codigo = cli.main(["listen", "--wav", "dummy.wav", "--hazard", "PIEDRAS", "--dist-km", "2"])

    assert codigo == 0
    assert len(transporte.enviadas) == 1
    salida = capsys.readouterr().err
    assert "wake_word" in salida
    assert "alert.tx" in salida
    assert "shutdown" in salida
