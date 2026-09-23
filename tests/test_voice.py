"""Tests del transcriber de voz libre y del subcomando ``voice``.

No usan red, ni micrófono, ni vosk: la transcripción real se reemplaza por dobles
y el audio por un WAV generado con la librería estándar. El modelo de Vosk nunca
se carga.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import types
import wave
from pathlib import Path

import pytest
from comboy import cli, voice
from comboy.classify import Classification
from comboy.codes import Confidence, Hazard, Lane, Urgency
from comboy.config import default_config
from comboy.frame import decode
from comboy.logging_setup import Logger

# ── Dobles y ayudas ──────────────────────────────────────────────────────────


def _logger(buffer: io.StringIO | None = None) -> Logger:
    return Logger(node_id=1, role="leader", stream=buffer if buffer is not None else io.StringIO())


class _TranscriberFalso:
    """Transcriber determinista: devuelve el texto la primera vez que se le pide."""

    def __init__(self, texto: str = "hay piedras en la calzada", disponible: bool = True) -> None:
        self._texto = texto
        self._disponible = disponible
        self.last_text = ""

    @property
    def available(self) -> bool:
        return self._disponible

    def accept(self, pcm: bytes) -> str | None:
        if not self._disponible:
            return None
        self.last_text = self._texto
        return self._texto or None

    def flush(self) -> str:
        if not self._disponible:
            return ""
        self.last_text = self._texto
        return self._texto


class _TransporteFalso:
    def __init__(self) -> None:
        self.enviadas: list[bytes] = []

    def send_frame(self, frame: bytes) -> None:
        self.enviadas.append(frame)

    def close(self) -> None:
        pass


class _MicrofonoFalso:
    """Micrófono doble: no arranca ``arecord`` y no deja procesos huérfanos."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.cerrado = False

    def chunks(self) -> object:
        return iter([b"\x00\x00" * 800])

    def close(self) -> None:
        self.cerrado = True


def _wav_valido(tmp_path: Path) -> str:
    path = tmp_path / "voz.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 800)
    return str(path)


def _config_sin_red(tmp_path: Path) -> str:
    ruta = tmp_path / "sin-red.yaml"
    ruta.write_text('embedding:\n  kind: null\n  cache_path: ""\n', encoding="utf-8")
    return str(ruta)


def _instalar_vosk_falso(monkeypatch: pytest.MonkeyPatch, texto: str) -> dict[str, object]:
    """Instala un ``vosk`` de mentira cuyos recognizers **no aceptan gramática**.

    Si el código pasara el tercer argumento, el constructor fallaría y el
    transcriber quedaría no disponible. Así el test protege el vocabulario libre.
    """

    registros: dict[str, object] = {"texto": texto}

    class _Modelo:
        def __init__(self, path: str) -> None:
            registros["model_path"] = path

    class _Recognizer:
        def __init__(self, model: object, rate: int) -> None:
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


# ── NullTranscriber ──────────────────────────────────────────────────────────


def test_null_transcriber_no_hace_nada_y_nunca_lanza() -> None:
    transcriber = voice.NullTranscriber()

    assert transcriber.available is False
    assert transcriber.last_text == ""
    assert transcriber.accept(b"") is None
    assert transcriber.accept(b"\x01\x02") is None
    assert transcriber.flush() == ""
    assert transcriber.flush() == ""


# ── VoskTranscriber ──────────────────────────────────────────────────────────


def test_vosk_sin_modelo_queda_no_disponible_y_avisa_una_vez(tmp_path: Path) -> None:
    buffer = io.StringIO()
    transcriber = voice.VoskTranscriber(str(tmp_path / "no-existe"), logger=_logger(buffer))

    assert transcriber.available is False
    assert transcriber.last_text == ""
    assert transcriber.accept(b"\x00\x00") is None
    assert transcriber.flush() == ""
    assert buffer.getvalue().count("voice.unavailable") == 1


def test_vosk_usa_vocabulario_libre_sin_gramatica(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """El recognizer recibe solo ``(model, rate)``: no hay gramática restringida."""

    registros = _instalar_vosk_falso(monkeypatch, "hay piedras en la calzada")
    transcriber = voice.VoskTranscriber(str(tmp_path), logger=_logger())

    assert transcriber.available is True
    assert registros["rate"] == 16000
    assert transcriber.accept(b"\x00\x00") == "hay piedras en la calzada"
    assert transcriber.last_text == "hay piedras en la calzada"
    assert transcriber.flush() == "hay piedras en la calzada"


def test_vosk_normaliza_espacios_y_tolera_json_invalido(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _instalar_vosk_falso(monkeypatch, "  hay   piedras  ")
    transcriber = voice.VoskTranscriber(str(tmp_path), logger=_logger())

    assert transcriber.accept(b"\x00\x00") == "hay piedras"

    class _RecognizerRoto:
        def __init__(self, model: object, rate: int) -> None:
            pass

        def AcceptWaveform(self, data: bytes) -> bool:
            return True

        def Result(self) -> str:
            return "no es json"

        def FinalResult(self) -> str:
            return "no es json"

    monkeypatch.setattr(sys.modules["vosk"], "KaldiRecognizer", _RecognizerRoto, raising=False)
    roto = voice.VoskTranscriber(str(tmp_path), logger=_logger())
    assert roto.accept(b"\x00\x00") is None
    assert roto.flush() == ""


# ── Factory ──────────────────────────────────────────────────────────────────


def test_create_transcriber_elige_la_clase_segun_el_modelo(tmp_path: Path) -> None:
    assert isinstance(voice.create_transcriber(str(tmp_path)), voice.VoskTranscriber)
    assert isinstance(voice.create_transcriber(str(tmp_path / "no-existe")), voice.NullTranscriber)


# ── CLI: validaciones de entrada ─────────────────────────────────────────────


def test_voice_con_wav_inexistente_devuelve_2_sin_traza(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    codigo = cli.main(["voice", "--wav", str(tmp_path / "mal.wav")])

    assert codigo == 2
    assert "error" in capsys.readouterr().err


def test_voice_sin_transcriber_disponible_devuelve_2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        cli, "create_transcriber", lambda *args, **kwargs: _TranscriberFalso(disponible=False)
    )

    codigo = cli.main(["voice", "--wav", _wav_valido(tmp_path), "--no-send"])

    assert codigo == 2
    assert "error" in capsys.readouterr().err


def test_voice_con_texto_vacio_no_manda_nada(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    transporte = _TransporteFalso()
    monkeypatch.setattr(cli, "create_transport", lambda *args, **kwargs: transporte)
    monkeypatch.setattr(cli, "create_transcriber", lambda *args, **kwargs: _TranscriberFalso("   "))

    codigo = cli.main(["voice", "--wav", _wav_valido(tmp_path)])

    assert codigo == 2
    assert transporte.enviadas == []
    assert "no se reconoció nada" in capsys.readouterr().err


# ── CLI: el contrato de envío ────────────────────────────────────────────────


def _ejecutar_voice(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    extra: list[str] | None = None,
) -> _TransporteFalso:
    transporte = _TransporteFalso()
    monkeypatch.setattr(cli, "create_transport", lambda *args, **kwargs: transporte)
    monkeypatch.setattr(
        cli,
        "create_transcriber",
        lambda *args, **kwargs: _TranscriberFalso("hay piedras en la calzada"),
    )
    argumentos = ["voice", "--wav", _wav_valido(tmp_path), "--config", _config_sin_red(tmp_path)]
    argumentos += extra or []
    cli.main(argumentos)
    return transporte


def test_voice_envia_la_trama_clasificada(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    transporte = _TransporteFalso()
    clasificacion = Classification(
        hazard=Hazard.PIEDRAS,
        lane=Lane.DERECHO,
        dist_km=2,
        urgency=Urgency.PRECAUCION,
        confidence=Confidence.ALTA,
        similarity=0.91,
        margin=0.10,
    )
    monkeypatch.setattr(cli, "create_transport", lambda *args, **kwargs: transporte)
    monkeypatch.setattr(
        cli,
        "create_transcriber",
        lambda *args, **kwargs: _TranscriberFalso("hay piedras en la calzada"),
    )
    monkeypatch.setattr(cli, "classify", lambda *args, **kwargs: clasificacion)

    codigo = cli.main(
        ["voice", "--wav", _wav_valido(tmp_path), "--config", _config_sin_red(tmp_path)]
    )

    assert codigo == 0
    assert len(transporte.enviadas) == 1
    frame = decode(transporte.enviadas[0])
    assert frame is not None
    assert frame.hazard == int(Hazard.PIEDRAS)
    assert frame.lane == int(Lane.DERECHO)
    assert frame.dist_km == 2
    assert frame.urgency == int(Urgency.PRECAUCION)
    assert frame.confidence == int(Confidence.ALTA)


def test_voice_no_send_no_transmite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    transporte = _ejecutar_voice(monkeypatch, tmp_path, extra=["--no-send"])

    assert transporte.enviadas == []
    assert "no se transmitió" in capsys.readouterr().out


def test_voice_imprime_el_texto_reconocido(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _ejecutar_voice(monkeypatch, tmp_path, extra=["--no-send"])

    salida = capsys.readouterr().out
    assert "texto" in salida
    assert "hay piedras en la calzada" in salida


def test_voice_emite_json_con_texto(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _ejecutar_voice(monkeypatch, tmp_path, extra=["--json", "--no-send"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["texto"] == "hay piedras en la calzada"
    assert set(payload) == {
        "texto",
        "hazard",
        "lane",
        "dist_km",
        "urgency",
        "confidence",
        "similarity",
        "margin",
    }


def test_voice_usa_microfono_y_lo_cierra(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    creados: list[_MicrofonoFalso] = []

    def _factory(*args: object, **kwargs: object) -> _MicrofonoFalso:
        micro = _MicrofonoFalso()
        creados.append(micro)
        return micro

    monkeypatch.setattr(cli, "Microphone", _factory)
    monkeypatch.setattr(cli, "create_transport", lambda *args, **kwargs: _TransporteFalso())
    monkeypatch.setattr(cli, "create_transcriber", lambda *args, **kwargs: _TranscriberFalso())

    codigo = cli.main(["voice", "--config", _config_sin_red(tmp_path), "--no-send"])

    assert codigo == 0
    assert len(creados) == 1
    assert creados[0].cerrado is True


# ── Construcción de la trama ─────────────────────────────────────────────────


def test_build_classified_frame_lleva_la_clasificacion() -> None:
    clasificacion = Classification(
        hazard=Hazard.ANIMAL,
        lane=Lane.IZQUIERDO,
        dist_km=5,
        urgency=Urgency.DETENERSE,
        confidence=Confidence.ALTA,
        similarity=0.95,
        margin=0.2,
    )
    args = argparse.Namespace(alert_id=0x11223344)

    frame = cli._build_classified_frame(clasificacion, args, default_config(), origin_id=7)
    vuelta = decode(frame.encode())

    assert vuelta is not None
    assert vuelta.hazard == int(Hazard.ANIMAL)
    assert vuelta.lane == int(Lane.IZQUIERDO)
    assert vuelta.dist_km == 5
    assert vuelta.urgency == int(Urgency.DETENERSE)
    assert vuelta.confidence == int(Confidence.ALTA)
    assert vuelta.origin_id == 7
    assert vuelta.alert_id == 0x11223344
