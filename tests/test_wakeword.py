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


def _instalar_vosk_falso(
    monkeypatch: pytest.MonkeyPatch,
    texto: str,
    *,
    parcial: str = "",
    resultados: list[bool] | None = None,
) -> dict[str, object]:
    """Instala un ``vosk`` de mentira que registra la gramática recibida.

    Evita cargar el modelo de 58 MB: los tests tienen que seguir siendo rápidos.

    ``resultados`` controla qué devuelve ``AcceptWaveform`` llamada por llamada
    (el último valor se repite): con ``False`` se simula un parcial y con
    ``True`` un final. Por defecto siempre final, que es lo que esperan los
    tests que no ejercitan ``early``. ``parcial`` es el texto de
    ``PartialResult``. El fake implementa ``PartialResult`` y ``Reset`` porque
    el detector los usa: sin ellos, el ``except Exception`` se comería el
    ``AttributeError`` en silencio.
    """

    registros: dict[str, object] = {"texto": texto, "parcial": parcial, "llamadas": 0}

    class _Modelo:
        def __init__(self, path: str) -> None:
            registros["model_path"] = path

    class _Recognizer:
        def __init__(self, model: object, rate: int, grammar: str) -> None:
            registros["grammar"] = grammar
            registros["rate"] = rate

        def AcceptWaveform(self, data: bytes) -> bool:
            indice = int(registros["llamadas"])
            registros["llamadas"] = indice + 1
            if resultados is None:
                return True
            if indice < len(resultados):
                return resultados[indice]
            return resultados[-1]

        def Result(self) -> str:
            return json.dumps({"text": registros["texto"]})

        def PartialResult(self) -> str:
            return json.dumps({"text": registros["parcial"]})

        def FinalResult(self) -> str:
            return json.dumps({"text": registros["texto"]})

        def Reset(self) -> None:
            registros["resets"] = int(registros.get("resets", 0)) + 1

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
    # reset() no debe lanzar aunque no haya recognizer.
    detector.reset()
    assert "wakeword.unavailable" in buffer.getvalue()


# ── Detección temprana por resultados parciales ──────────────────────────────


def test_early_dispara_con_un_parcial_sin_final(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Con ``early=True`` alcanza un resultado parcial para despertar."""

    _instalar_vosk_falso(
        monkeypatch,
        "",
        parcial="atencion convoy",
        resultados=[False],
    )
    detector = wakeword.VoskWakeWord(str(tmp_path), early=True, logger=_logger())

    assert detector.accept(b"\x00\x00") is True
    assert detector.last_text == "atencion convoy"


def test_sin_early_un_parcial_no_dispara(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Con el default ``early=False`` el parcial se ignora: ``listen`` no cambia."""

    _instalar_vosk_falso(
        monkeypatch,
        "",
        parcial="atencion convoy",
        resultados=[False],
    )
    detector = wakeword.VoskWakeWord(str(tmp_path), logger=_logger())

    assert detector.accept(b"\x00\x00") is False
    assert detector.last_text == ""


def test_el_latch_evita_disparos_repetidos_por_parcial(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Un parcial dispara una vez; el siguiente parcial se ignora hasta el final."""

    _instalar_vosk_falso(
        monkeypatch,
        "atencion convoy",
        parcial="atencion convoy",
        resultados=[False, False, True, False],
    )
    detector = wakeword.VoskWakeWord(str(tmp_path), early=True, logger=_logger())

    assert detector.accept(b"\x00\x00") is True  # parcial: dispara y arma el latch
    assert detector.accept(b"\x00\x00") is False  # parcial repetido: latch lo calla
    assert detector.accept(b"\x00\x00") is True  # final: cierra la utterance y limpia
    assert detector.accept(b"\x00\x00") is True  # parcial nuevo: vuelve a poder disparar


def test_reset_limpia_el_latch_y_llama_al_recognizer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    registros = _instalar_vosk_falso(
        monkeypatch,
        "atencion convoy",
        parcial="atencion convoy",
        resultados=[False, False],
    )
    detector = wakeword.VoskWakeWord(str(tmp_path), early=True, logger=_logger())

    assert detector.accept(b"\x00\x00") is True
    assert detector.accept(b"\x00\x00") is False  # latch armado

    detector.reset()

    assert registros["resets"] == 1
    assert detector.last_text == ""
    # Con el latch limpio, el mismo parcial vuelve a disparar.
    assert detector.accept(b"\x00\x00") is True
