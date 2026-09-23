"""Tests del subcomando ``talk`` y del modelo compartido entre wake word y STT.

No usan red, ni micrófono, ni vosk: la detección, la transcripción y el audio se
reemplazan por dobles, y el modelo de Vosk nunca se carga. El único fake de vosk
que aparece acá acepta gramática opcional, porque ``talk`` ejercita los dos
recognizers (el de wake word con gramática y el de frase libre sin ella).
"""

from __future__ import annotations

import io
import json
import sys
import types
import wave
from pathlib import Path

import pytest
from comboy import cli, voice, wakeword
from comboy.classify import Classification
from comboy.codes import Confidence, Hazard, Lane, Urgency
from comboy.frame import decode
from comboy.logging_setup import Logger

# ── Dobles y ayudas ──────────────────────────────────────────────────────────


def _logger(buffer: io.StringIO | None = None) -> Logger:
    return Logger(node_id=1, role="leader", stream=buffer if buffer is not None else io.StringIO())


class _DetectorFalso:
    """Detector determinista: despierta exactamente en la llamada ``dispara_en``.

    Con ``dispara_en=0`` nunca despierta, que es lo que hace falta para probar un
    WAV sin wake word. Expone ``model`` porque ``_talk`` lo comparte con el
    transcriber.
    """

    def __init__(self, *, disponible: bool = True, dispara_en: int = 1) -> None:
        self._disponible = disponible
        self._dispara_en = dispara_en
        self.llamadas = 0
        self.last_text = "atencion convoy"
        self.model = object()

    @property
    def available(self) -> bool:
        return self._disponible

    def accept(self, pcm: bytes) -> bool:
        self.llamadas += 1
        return self._disponible and self.llamadas == self._dispara_en

    def flush(self) -> bool:
        return False


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
    """Instala un ``vosk`` de mentira que acepta gramática **opcional**.

    El wake word construye ``KaldiRecognizer(model, rate, grammar)`` y el
    transcriber ``KaldiRecognizer(model, rate)``; el tercer argumento por defecto
    ``None`` permite ejercitar los dos caminos con el mismo fake. Registra cada
    modelo recibido para poder verificar que se comparte el mismo objeto.
    """

    registros: dict[str, object] = {"texto": texto, "modelos": [], "instancias_modelo": 0}

    class _Modelo:
        def __init__(self, path: str) -> None:
            registros["instancias_modelo"] = int(registros["instancias_modelo"]) + 1
            registros["model_path"] = path

    class _Recognizer:
        def __init__(self, model: object, rate: int, grammar: str | None = None) -> None:
            modelos = registros["modelos"]
            assert isinstance(modelos, list)
            modelos.append(model)
            registros["rate"] = rate
            registros["grammar"] = grammar

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


def _clasificacion() -> Classification:
    return Classification(
        hazard=Hazard.PIEDRAS,
        lane=Lane.DERECHO,
        dist_km=2,
        urgency=Urgency.PRECAUCION,
        confidence=Confidence.ALTA,
        similarity=0.91,
        margin=0.10,
    )


def _correr_talk(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    detector: _DetectorFalso | None = None,
    transcriber: _TranscriberFalso | None = None,
    chunks: list[bytes] | None = None,
    extra: list[str] | None = None,
) -> tuple[int, _TransporteFalso]:
    """Corre ``talk`` sobre chunks controlados y devuelve ``(código, transporte)``."""

    transporte = _TransporteFalso()
    detector = detector or _DetectorFalso()
    transcriber = transcriber or _TranscriberFalso()
    muestra = chunks or [b"A", b"B", b"C"]
    monkeypatch.setattr(cli, "wav_chunks", lambda *args, **kwargs: iter(muestra))
    monkeypatch.setattr(cli, "VoskWakeWord", lambda *args, **kwargs: detector)
    monkeypatch.setattr(cli, "create_transcriber", lambda *args, **kwargs: transcriber)
    monkeypatch.setattr(cli, "create_transport", lambda *args, **kwargs: transporte)
    monkeypatch.setattr(cli, "classify", lambda *args, **kwargs: _clasificacion())

    argumentos = ["talk", "--wav", "dummy.wav", "--config", _config_sin_red(tmp_path)]
    argumentos += extra or []
    codigo = cli.main(argumentos)
    return codigo, transporte


# ── CLI: contrato del subcomando ─────────────────────────────────────────────


def test_talk_help_lista_los_flags_y_no_tiene_hazard(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as salida:
        cli.main(["talk", "--help"])

    assert salida.value.code == 0
    ayuda = capsys.readouterr().out
    esperados = (
        "--config",
        "--wav",
        "--seconds",
        "--json",
        "--no-send",
        "--origin-id",
        "--alert-id",
    )
    for flag in esperados:
        assert flag in ayuda
    assert "--hazard" not in ayuda
    assert "--lane" not in ayuda


def test_talk_con_wav_inexistente_devuelve_2_sin_cargar_modelos(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """El WAV se valida antes de cargar el modelo: un archivo malo falla rápido."""

    cargas: list[str] = []
    monkeypatch.setattr(cli, "VoskWakeWord", lambda *args, **kwargs: cargas.append("detector"))
    monkeypatch.setattr(cli, "create_transcriber", lambda *args, **kwargs: cargas.append("stt"))

    codigo = cli.main(["talk", "--wav", str(tmp_path / "no-existe.wav")])

    assert codigo == 2
    assert "error" in capsys.readouterr().err
    assert cargas == []


# ── CLI: el contrato de envío ────────────────────────────────────────────────


def test_talk_wake_word_mas_frase_clasifica_y_envia(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    codigo, transporte = _correr_talk(monkeypatch, tmp_path)

    assert codigo == 0
    assert len(transporte.enviadas) == 1
    frame = decode(transporte.enviadas[0])
    assert frame is not None
    assert frame.hazard == int(Hazard.PIEDRAS)
    assert frame.lane == int(Lane.DERECHO)
    assert frame.dist_km == 2
    assert frame.urgency == int(Urgency.PRECAUCION)
    assert frame.confidence == int(Confidence.ALTA)


def test_talk_con_wav_real_envia(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Un WAV válido de verdad recorre la validación real de ``wav_chunks``."""

    transporte = _TransporteFalso()
    monkeypatch.setattr(cli, "VoskWakeWord", lambda *args, **kwargs: _DetectorFalso())
    monkeypatch.setattr(cli, "create_transcriber", lambda *args, **kwargs: _TranscriberFalso())
    monkeypatch.setattr(cli, "create_transport", lambda *args, **kwargs: transporte)
    monkeypatch.setattr(cli, "classify", lambda *args, **kwargs: _clasificacion())

    codigo = cli.main(
        ["talk", "--wav", _wav_valido(tmp_path), "--config", _config_sin_red(tmp_path)]
    )

    assert codigo == 0
    assert len(transporte.enviadas) == 1


def test_talk_no_send_no_transmite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    codigo, transporte = _correr_talk(monkeypatch, tmp_path, extra=["--no-send"])

    assert codigo == 0
    assert transporte.enviadas == []
    assert "no se transmitió" in capsys.readouterr().out


def test_talk_frase_vacia_no_envia_ni_falla(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Wake word sola: se registra ``talk.empty``, no se envía y no hay error."""

    codigo, transporte = _correr_talk(
        monkeypatch,
        tmp_path,
        detector=_DetectorFalso(dispara_en=1),
        transcriber=_TranscriberFalso(""),
    )

    assert codigo == 0
    assert transporte.enviadas == []
    assert "talk.empty" in capsys.readouterr().err


def test_talk_wav_sin_wake_word_no_envia(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    codigo, transporte = _correr_talk(monkeypatch, tmp_path, detector=_DetectorFalso(dispara_en=0))

    assert codigo == 0
    assert transporte.enviadas == []


def test_talk_pasa_el_modelo_del_detector_al_transcriber(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``_talk`` comparte el modelo: la factory recibe ``model=detector.model``."""

    detector = _DetectorFalso(dispara_en=0)
    capturado: dict[str, object] = {}

    def _factory(*args: object, **kwargs: object) -> _TranscriberFalso:
        capturado.update(kwargs)
        return _TranscriberFalso("")

    monkeypatch.setattr(cli, "wav_chunks", lambda *args, **kwargs: iter([b"A"]))
    monkeypatch.setattr(cli, "VoskWakeWord", lambda *args, **kwargs: detector)
    monkeypatch.setattr(cli, "create_transcriber", _factory)
    monkeypatch.setattr(cli, "create_transport", lambda *args, **kwargs: _TransporteFalso())

    codigo = cli.main(["talk", "--wav", "dummy.wav", "--config", _config_sin_red(tmp_path)])

    assert codigo == 0
    assert capturado["model"] is detector.model


def test_talk_sin_detector_ni_transcriber_disponibles_devuelve_2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "wav_chunks", lambda *args, **kwargs: iter([b"A"]))
    monkeypatch.setattr(
        cli, "VoskWakeWord", lambda *args, **kwargs: _DetectorFalso(disponible=False)
    )
    monkeypatch.setattr(
        cli, "create_transcriber", lambda *args, **kwargs: _TranscriberFalso(disponible=False)
    )
    monkeypatch.setattr(cli, "create_transport", lambda *args, **kwargs: _TransporteFalso())

    codigo = cli.main(["talk", "--wav", "dummy.wav", "--config", _config_sin_red(tmp_path)])

    assert codigo == 2
    assert "vosk" in capsys.readouterr().err


# ── Modelo compartido: el test que protege la decisión de diseño ─────────────


def test_vosktranscriber_reutiliza_el_mismo_modelo_sin_cargar_otro(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Un solo ``Model`` cargado y el mismo objeto en ambos recognizers."""

    registros = _instalar_vosk_falso(monkeypatch, "atencion convoy")

    detector = wakeword.VoskWakeWord(str(tmp_path), logger=_logger())
    assert detector.model is not None

    transcriber = voice.VoskTranscriber(str(tmp_path), logger=_logger(), model=detector.model)

    assert transcriber.available is True
    modelos = registros["modelos"]
    assert isinstance(modelos, list)
    # detector y transcriber: dos recognizers, un único modelo.
    assert len(modelos) == 2
    assert modelos[0] is modelos[1]
    assert modelos[1] is detector.model
    assert registros["instancias_modelo"] == 1
    # El transcriber no pasó gramática (vocabulario libre).
    assert registros["grammar"] is None


def test_create_transcriber_usa_el_modelo_compartido(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    registros = _instalar_vosk_falso(monkeypatch, "texto")

    detector = wakeword.VoskWakeWord(str(tmp_path), logger=_logger())
    # La ruta no existe, pero el modelo compartido manda: no se mira el disco.
    transcriber = voice.create_transcriber(
        str(tmp_path / "no-existe"), logger=_logger(), model=detector.model
    )

    assert isinstance(transcriber, voice.VoskTranscriber)
    assert transcriber.available is True
    assert registros["instancias_modelo"] == 1
