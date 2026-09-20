"""Test de integración del subcomando ``listen`` con dobles.

No usa micrófono, ni red, ni modelo: reemplaza el detector, la fuente de audio y
el transporte para verificar que una detección dispara exactamente una alerta.

También cubre el subcomando ``text`` con ``embedding.kind: null``, que corre sin
red.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

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


def _config_sin_red(tmp_path: Path) -> str:
    """Escribe un YAML con ``embedding.kind: null`` y devuelve su ruta.

    El ``null`` va sin comillas a propósito: es la forma natural de escribirlo y
    el cargador la acepta como el cliente sin red.
    """

    ruta = tmp_path / "sin-red.yaml"
    ruta.write_text("embedding:\n  kind: null\n", encoding="utf-8")
    return str(ruta)


def test_text_clasifica_sin_red(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    codigo = cli.main(["text", "se vino la montaña abajo", "--config", _config_sin_red(tmp_path)])

    assert codigo == 0
    salida = capsys.readouterr().out
    assert "DERRUMBE" in salida
    assert "ALTA" in salida


def test_text_emite_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    codigo = cli.main(
        [
            "text",
            "hubo un accidente en la ruta",
            "--config",
            _config_sin_red(tmp_path),
            "--json",
        ]
    )

    assert codigo == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["hazard"] == "ACCIDENTE"
    assert payload["confidence"] == "ALTA"
    assert set(payload) == {
        "hazard",
        "lane",
        "dist_km",
        "urgency",
        "confidence",
        "similarity",
        "margin",
    }


def test_text_json_desconocido(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    codigo = cli.main(["text", "zzz qqq wwww", "--config", _config_sin_red(tmp_path), "--json"])

    assert codigo == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["hazard"] == "DESCONOCIDO"
    assert payload["confidence"] == "BAJA"
