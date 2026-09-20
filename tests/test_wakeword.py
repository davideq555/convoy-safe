"""Tests del detector de wake word con Vosk, sin cargar el modelo real."""

from __future__ import annotations

import io
import json
import sys
import types
from pathlib import Path

import pytest
from comboy import wakeword
from comboy.logging_setup import Logger


def _logger(buffer: io.StringIO | None = None) -> Logger:
    return Logger(node_id=1, role="leader", stream=buffer if buffer is not None else io.StringIO())


def _instalar_vosk_falso(monkeypatch: pytest.MonkeyPatch, texto: str) -> dict[str, object]:
    """Instala un ``vosk`` de mentira que registra la gramática recibida.

    Evita cargar el modelo de 58 MB: los tests tienen que seguir siendo rápidos.
    """

    registros: dict[str, object] = {"texto": texto}

    class _Modelo:
        def __init__(self, path: str) -> None:
            registros["model_path"] = path

    class _Recognizer:
        def __init__(self, model: object, rate: int, grammar: str) -> None:
            registros["grammar"] = grammar
            registros["rate"] = rate

        def AcceptWaveform(self, data: bytes) -> bool:
            return True

        def Result(self) -> str:
            return json.dumps({"text": registros["texto"]})

        def FinalResult(self) -> str:
            return json.dumps({"text": registros["texto"]})

    modulo = types.ModuleType("vosk")
    modulo.Model = _Modelo
    modulo.KaldiRecognizer = _Recognizer
    modulo.SetLogLevel = lambda level: registros.setdefault("log_level", level)
    monkeypatch.setitem(sys.modules, "vosk", modulo)
    return registros


def test_to_grammar_sustituye_solo_la_palabra_conocida() -> None:
    assert wakeword.to_grammar("atencion comboy") == "atencion convoy"
    assert wakeword.to_grammar("otra frase cualquiera") == "otra frase cualquiera"


def test_la_gramatica_usa_la_palabra_del_vocabulario(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Guarda contra el truco comboy/convoy: Vosk recibe "convoy", no "comboy"."""

    registros = _instalar_vosk_falso(monkeypatch, "atencion convoy")
    wakeword.VoskWakeWord(str(tmp_path), logger=_logger())

    grammar = str(registros["grammar"])
    assert "convoy" in grammar
    assert "comboy" not in grammar
    assert wakeword.UNKNOWN_TOKEN in grammar


def test_detecta_la_frase_completa(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _instalar_vosk_falso(monkeypatch, "atencion convoy")
    detector = wakeword.VoskWakeWord(str(tmp_path), logger=_logger())

    assert detector.available is True
    assert detector.accept(b"\x00\x00") is True
    assert detector.last_text == "atencion convoy"


def test_una_palabra_suelta_de_la_gramatica_no_alcanza(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _instalar_vosk_falso(monkeypatch, "convoy")
    detector = wakeword.VoskWakeWord(str(tmp_path), logger=_logger())

    assert detector.accept(b"\x00\x00") is False


def test_texto_vacio_no_detecta(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _instalar_vosk_falso(monkeypatch, "")
    detector = wakeword.VoskWakeWord(str(tmp_path), logger=_logger())

    assert detector.accept(b"\x00\x00") is False


def test_flush_detecta_la_cola(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _instalar_vosk_falso(monkeypatch, "atencion convoy")
    detector = wakeword.VoskWakeWord(str(tmp_path), logger=_logger())

    assert detector.flush() is True


def test_queda_no_disponible_si_falta_el_modelo(tmp_path: Path) -> None:
    buffer = io.StringIO()
    detector = wakeword.VoskWakeWord(str(tmp_path / "no-existe"), logger=_logger(buffer))

    assert detector.available is False
    assert detector.accept(b"\x00\x00") is False
    assert detector.flush() is False
    assert detector.last_text == ""
    assert "wakeword.unavailable" in buffer.getvalue()
