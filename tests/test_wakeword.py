"""Tests del detector de wake word con Vosk, sin cargar el modelo real."""

from __future__ import annotations

import io
import json
import sys
import types
from pathlib import Path

import pytest
from convoy import wakeword
from convoy.logging_setup import Logger


def _logger(buffer: io.StringIO | None = None) -> Logger:
    return Logger(node_id=1, role="leader", stream=buffer if buffer is not None else io.StringIO())


def _instalar_vosk_falso(
    monkeypatch: pytest.MonkeyPatch,
    texto: str,
    *,
    parcial: str = "",
    resultados: list[bool] | None = None,
    wake_end: float | None = None,
    wake_ends: list[float] | None = None,
    result_vacio: bool = False,
) -> dict[str, object]:
    """Instala un ``vosk`` de mentira que registra la gramática recibida.

    Evita cargar el modelo de 58 MB: los tests tienen que seguir siendo rápidos.

    ``resultados`` controla qué devuelve ``AcceptWaveform`` llamada por llamada
    (el último valor se repite): con ``False`` se simula un parcial y con
    ``True`` un final. Por defecto siempre final, que es lo que esperan los
    tests que no ejercitan ``early``. ``parcial`` es el texto de
    ``PartialResult``. Con ``wake_end`` el resultado final incluye un array
    ``result`` con el tiempo (en segundos) en que terminó la última palabra, tal
    como lo devuelve Vosk con ``SetWords(True)``; sin él no hay array y el
    replay debe caer al fallback. ``wake_ends`` es la variante para varias
    detecciones: cada ``Result()`` consume el siguiente valor (el último se
    repite) y, a diferencia de ``wake_end``, sus valores son **absolutos** desde
    el inicio del stream, como los de Vosk cuando no se reinicia su contador de
    frames. El fake implementa ``SetWords``, ``PartialResult`` y ``Reset``
    porque el detector los usa: sin ellos, el ``except Exception`` se comería el
    ``AttributeError`` en silencio.
    """

    registros: dict[str, object] = {"texto": texto, "parcial": parcial, "llamadas": 0}

    def _payload() -> str:
        data: dict[str, object] = {"text": registros["texto"]}
        if result_vacio:
            data["result"] = []
        elif wake_ends is not None:
            finales = int(registros.get("finales", 0))
            registros["finales"] = finales + 1
            end = wake_ends[min(finales, len(wake_ends) - 1)]
            data["result"] = [{"word": "convoy", "start": 0.0, "end": end, "conf": 0.9}]
        elif wake_end is not None:
            data["result"] = [{"word": "convoy", "start": 0.0, "end": wake_end, "conf": 0.9}]
        return json.dumps(data)

    class _Modelo:
        def __init__(self, path: str) -> None:
            registros["model_path"] = path

    class _Recognizer:
        def __init__(self, model: object, rate: int, grammar: str) -> None:
            registros["grammar"] = grammar
            registros["rate"] = rate

        def SetWords(self, enabled: bool) -> None:
            registros["set_words"] = enabled

        def AcceptWaveform(self, data: bytes) -> bool:
            indice = int(registros["llamadas"])
            registros["llamadas"] = indice + 1
            if resultados is None:
                return True
            if indice < len(resultados):
                return resultados[indice]
            return resultados[-1]

        def Result(self) -> str:
            return _payload()

        def PartialResult(self) -> str:
            return json.dumps({"text": registros["parcial"]})

        def FinalResult(self) -> str:
            return _payload()

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


# ── Replay del audio posterior a la wake word ────────────────────────────────

#: 1000 Hz hace que cada sample valga 1 ms y las cuentas del test sean triviales.
#: El detector real corre a 16 kHz, pero el fake ignora el audio.
_RATE = 1000


def test_activa_los_timestamps_por_palabra(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Sin ``SetWords(True)`` Vosk no devuelve el array ``result`` con tiempos."""

    registros = _instalar_vosk_falso(monkeypatch, "atencion convoy")
    wakeword.VoskWakeWord(str(tmp_path), logger=_logger())

    assert registros["set_words"] is True


def test_audio_since_wake_devuelve_desde_el_fin_de_la_wake_word(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """El test central: no se pierde ninguna muestra posterior a la wake word.

    A 1000 Hz cada sample es 1 ms. La wake word termina en 0.25 s = sample 250;
    con el margen de 50 ms el corte arranca en el sample 200. Se alimentan cuatro
    chunks de 200 bytes (100 samples) con bytes distinguibles para poder afirmar
    exactamente qué tramo se recupera: desde el sample 200 en adelante, o sea los
    chunks C y D completos.
    """

    _instalar_vosk_falso(
        monkeypatch, "atencion convoy", resultados=[False, False, False, True], wake_end=0.25
    )
    detector = wakeword.VoskWakeWord(str(tmp_path), rate=_RATE, logger=_logger())

    assert detector.accept(b"\xaa" * 200) is False
    assert detector.accept(b"\xbb" * 200) is False
    assert detector.accept(b"\xcc" * 200) is False
    assert detector.accept(b"\xdd" * 200) is True  # final: acá dispara

    recorte = detector.audio_since_wake()
    assert recorte == b"\xcc" * 200 + b"\xdd" * 200
    assert recorte is not None and len(recorte) % 2 == 0


def test_el_margen_de_seguridad_se_resta_al_punto_de_corte(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Un margen mayor devuelve audio desde más atrás del fin de la wake word."""

    _instalar_vosk_falso(
        monkeypatch, "atencion convoy", resultados=[False, False, False, True], wake_end=0.25
    )
    detector = wakeword.VoskWakeWord(str(tmp_path), rate=_RATE, logger=_logger())

    for byte in (b"\xaa", b"\xbb", b"\xcc", b"\xdd"):
        detector.accept(byte * 200)

    # 100 ms de margen => sample 150, dentro del chunk B.
    assert detector.audio_since_wake(margin_ms=100) == (
        b"\xbb" * 100 + b"\xcc" * 200 + b"\xdd" * 200
    )


def test_el_offset_se_redondea_a_byte_par() -> None:
    """Un offset impar partiría una muestra s16 al medio."""

    assert wakeword._even_byte_offset(401) == 400
    assert wakeword._even_byte_offset(400) == 400
    assert wakeword._even_byte_offset(0) == 0


def test_audio_since_wake_sin_timestamp_es_none_y_loguea(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Sin array ``result`` no hay ``wake_end``: fallback, nunca excepción."""

    buffer = io.StringIO()
    _instalar_vosk_falso(monkeypatch, "atencion convoy", wake_end=None)
    detector = wakeword.VoskWakeWord(str(tmp_path), rate=_RATE, logger=_logger(buffer))

    assert detector.accept(b"\x00\x00") is True
    assert detector.audio_since_wake() is None
    assert "wakeword.replay_fallback" in buffer.getvalue()
    assert "sin_timestamp" in buffer.getvalue()


def test_audio_since_wake_con_result_vacio_es_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Un array ``result`` vacío tampoco alcanza: fallback sin excepción."""

    buffer = io.StringIO()
    _instalar_vosk_falso(monkeypatch, "atencion convoy", result_vacio=True)
    detector = wakeword.VoskWakeWord(str(tmp_path), rate=_RATE, logger=_logger(buffer))

    assert detector.accept(b"\x00\x00") is True
    assert detector.audio_since_wake() is None
    assert "sin_timestamp" in buffer.getvalue()


def test_el_buffer_esta_acotado(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """El buffer descarta lo más viejo al pasarse de 30 s; no crece sin límite."""

    _instalar_vosk_falso(monkeypatch, "otra cosa", resultados=[False])
    detector = wakeword.VoskWakeWord(str(tmp_path), rate=_RATE, logger=_logger())

    for _ in range(31):  # 31 s de audio en chunks de 1 s
        detector.accept(b"\x00" * 2000)

    assert detector.buffered_samples == 30 * _RATE
    assert detector.total_samples_fed == 31 * _RATE


def test_wake_word_mas_vieja_que_el_buffer_es_none_y_loguea(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Si el ``wake_end`` quedó fuera de lo que el buffer conserva, fallback."""

    buffer = io.StringIO()
    _instalar_vosk_falso(
        monkeypatch,
        "atencion convoy",
        resultados=[False] * 30 + [True],
        wake_end=0.01,  # sample 10, muy anterior a los últimos 30 s
    )
    detector = wakeword.VoskWakeWord(str(tmp_path), rate=_RATE, logger=_logger(buffer))

    for _ in range(31):
        detector.accept(b"\x00" * 2000)

    assert detector.audio_since_wake() is None
    assert "wakeword.replay_fallback" in buffer.getvalue()
    assert "fuera_del_buffer" in buffer.getvalue()


def test_reset_no_limpia_buffer_ni_contador_y_limpia_el_latch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """El buffer y el contador SOBREVIVEN a ``reset()``; el disparo sí se limpia.

    Es el invariante central del replay: ``Reset()`` de Vosk no reinicia su
    contador de frames, así que el contador y el buffer del detector tienen que
    ser monotónicos durante toda su vida para no desincronizarse. Limpiarlos en
    ``reset()`` era el bug que consagraba el test viejo.
    """

    _instalar_vosk_falso(
        monkeypatch,
        "atencion convoy",
        parcial="atencion convoy",
        resultados=[False, False],
        wake_end=0.25,
    )
    detector = wakeword.VoskWakeWord(str(tmp_path), rate=_RATE, early=True, logger=_logger())

    assert detector.accept(b"\x00" * 200) is True  # parcial: dispara y arma el latch
    assert detector.total_samples_fed == 100
    assert detector.buffered_samples == 100
    # Un ``wake_end`` vigente (lo dejaría el último final) que reset debe limpiar.
    detector._wake_end_sample = 250

    detector.reset()

    # El disparo se limpia: no queda timestamp ni latch.
    assert detector._wake_end_sample is None
    assert detector.audio_since_wake() is None
    # Pero el buffer y el contador sobreviven: son monotónicos, igual que Vosk.
    assert detector.total_samples_fed == 100
    assert detector.buffered_samples == 100
    # Latch limpio: el mismo parcial vuelve a disparar y el contador sigue subiendo.
    assert detector.accept(b"\x00" * 200) is True
    assert detector.total_samples_fed == 200
    assert detector.buffered_samples == 200


def test_segunda_deteccion_tras_reset_tambien_recupera_audio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regresión: el replay debe funcionar en la SEGUNDA detección, no solo en la primera.

    Reproduce el camino de ``_talk``: detectar, ``reset()``, seguir escuchando y
    detectar de nuevo. ``wake_ends`` da un ``end`` absoluto por detección, como
    los timestamps de Vosk (que no se reinician con ``Reset()``).

    Con el código viejo este test **falla**: ``reset()`` volvía
    ``_total_samples_fed`` a 0 y vaciaba el buffer, pero Vosk seguía reportando
    ``wake_end`` absoluto, así que en la segunda detección
    ``wake_end_sample`` (250) superaba a ``total_samples_fed`` (200), el recorte
    caía fuera del buffer y ``audio_since_wake()`` devolvía ``None``. A 1000 Hz
    cada sample es 1 ms.
    """

    _instalar_vosk_falso(
        monkeypatch,
        "atencion convoy",
        resultados=[True, False, True],
        wake_ends=[0.05, 0.25],
    )
    detector = wakeword.VoskWakeWord(str(tmp_path), rate=_RATE, logger=_logger())

    # 1ª detección: wake_end en el sample 50; con el margen de 50 ms el corte
    # arranca en 0, así que se recupera el chunk A entero.
    assert detector.accept(b"\xaa" * 200) is True
    assert detector.audio_since_wake() == b"\xaa" * 200

    detector.reset()

    # 2ª detección: wake_end en el sample 250 (absoluto desde el inicio del
    # stream). El buffer NO se vació, así que el tramo recuperado es el chunk C.
    assert detector.accept(b"\xbb" * 200) is False
    assert detector.accept(b"\xcc" * 200) is True
    assert detector.audio_since_wake() == b"\xcc" * 200
    assert detector.total_samples_fed == 300
    assert detector.buffered_samples == 300


def test_guard_invariante_roto_loguea_evento_propio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Si ``wake_end_sample > total_samples_fed`` se registra el invariante roto.

    Es un bug de sincronía, no un fallback normal: el evento tiene que ser
    distinto de ``wakeword.replay_fallback`` y traer los dos valores como
    evidencia.
    """

    buffer = io.StringIO()
    # ``wake_end`` absurdo (100 s) contra 100 samples alimentados: el corte
    # apunta más allá de todo lo que hay, que es exactamente el desfase.
    _instalar_vosk_falso(monkeypatch, "atencion convoy", wake_end=100.0)
    detector = wakeword.VoskWakeWord(str(tmp_path), rate=_RATE, logger=_logger(buffer))

    assert detector.accept(b"\x00" * 200) is True
    assert detector.audio_since_wake() is None

    salida = buffer.getvalue()
    assert "wakeword.invariant_broken" in salida
    assert "wake_end_sample=100000" in salida
    assert "total_samples_fed=100" in salida
    assert "wakeword.replay_fallback" not in salida
