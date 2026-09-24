"""Tests del cargador de datos: corpus y medición desde archivos JSON.

Todos corren sin red. Los tests de base y fusión apuntan
``DEFAULT_CORPUS_PATH``/``DEFAULT_MEDICION_PATH`` a archivos temporales; los
tests de integridad usan los archivos versionados reales.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
from convoy import datos
from convoy.codes import Hazard
from convoy.datos import (
    DatosInvalidos,
    Medicion,
    cargar_corpus,
    cargar_medicion,
    limpiar_cache,
    ruta_corpus,
    ruta_medicion,
)
from convoy.logging_setup import Logger
from convoy.normalize import normalize


def _escribir(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _logger(buffer: io.StringIO) -> Logger:
    return Logger(node_id=1, role="leader", stream=buffer)


def _apuntar_corpus(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(datos, "DEFAULT_CORPUS_PATH", path)
    limpiar_cache()


def _apuntar_medicion(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(datos, "DEFAULT_MEDICION_PATH", path)
    limpiar_cache()


# ── Carga de la base y metadatos ─────────────────────────────────────────────


def test_carga_la_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = _escribir(
        tmp_path / "corpus.json",
        {"version": 1, "peligros": {"PIEDRAS": ["hay una piedra en la ruta"]}},
    )
    _apuntar_corpus(monkeypatch, base)

    assert cargar_corpus() == {Hazard.PIEDRAS: ["hay una piedra en la ruta"]}


def test_la_nota_se_ignora(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = _escribir(
        tmp_path / "corpus.json",
        {"_nota": "documentación del formato", "peligros": {"BACHE": ["hay un pozo"]}},
    )
    _apuntar_corpus(monkeypatch, base)

    assert cargar_corpus() == {Hazard.BACHE: ["hay un pozo"]}


def test_quitar_saca_una_frase_de_la_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """La fusión solo suma: ``_quitar`` es la única forma de sacar algo de la base."""

    base = _escribir(
        tmp_path / "corpus.json",
        {"peligros": {"PIEDRAS": ["hay piedras en la ruta", "hay rocas sueltas"]}},
    )
    extra = _escribir(
        tmp_path / "extra.json",
        {"peligros": {"PIEDRAS": ["cuidado con el pedregullo"]}, "_quitar": ["hay rocas sueltas"]},
    )
    _apuntar_corpus(monkeypatch, base)
    monkeypatch.setenv(datos.CORPUS_PATH_VAR, str(extra))
    limpiar_cache()

    assert cargar_corpus() == {
        Hazard.PIEDRAS: ["hay piedras en la ruta", "cuidado con el pedregullo"]
    }


def test_quitar_compara_normalizado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = _escribir(tmp_path / "corpus.json", {"peligros": {"PIEDRAS": ["¡Hay Piedras!"]}})
    extra = _escribir(tmp_path / "extra.json", {"_quitar": ["hay piedras"]})
    _apuntar_corpus(monkeypatch, base)
    monkeypatch.setenv(datos.CORPUS_PATH_VAR, str(extra))
    limpiar_cache()

    assert cargar_corpus() == {Hazard.PIEDRAS: []}


def test_quitar_tambien_saca_ruido(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = _escribir(
        tmp_path / "medicion.json", {"ruido": ["che falta mucho", "me gusta el asado"]}
    )
    extra = _escribir(tmp_path / "extra.json", {"_quitar": ["me gusta el asado"]})
    _apuntar_medicion(monkeypatch, base)
    monkeypatch.setenv(datos.MEDICION_PATH_VAR, str(extra))
    limpiar_cache()

    assert cargar_medicion().ruido == ["che falta mucho"]


def test_quitar_invalido_lanza(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = _escribir(tmp_path / "corpus.json", {"peligros": {"PIEDRAS": ["hay piedras"]}})
    extra = _escribir(tmp_path / "extra.json", {"_quitar": "no soy una lista"})
    _apuntar_corpus(monkeypatch, base)
    monkeypatch.setenv(datos.CORPUS_PATH_VAR, str(extra))
    limpiar_cache()

    with pytest.raises(DatosInvalidos):
        cargar_corpus()


# ── Fusión con el archivo extra ──────────────────────────────────────────────


def test_fusiona_el_extra(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = _escribir(
        tmp_path / "corpus.json", {"peligros": {"PIEDRAS": ["hay piedras en la ruta"]}}
    )
    extra = _escribir(
        tmp_path / "extra.json",
        {"peligros": {"PIEDRAS": ["cuidado con las rocas"], "BACHE": ["hay un pozo"]}},
    )
    _apuntar_corpus(monkeypatch, base)
    monkeypatch.setenv(datos.CORPUS_PATH_VAR, str(extra))
    limpiar_cache()

    assert cargar_corpus() == {
        Hazard.PIEDRAS: ["hay piedras en la ruta", "cuidado con las rocas"],
        Hazard.BACHE: ["hay un pozo"],
    }


def test_fusiona_deduplicando_por_frase_normalizada(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _escribir(tmp_path / "corpus.json", {"peligros": {"PIEDRAS": ["¡Hay Piedras!"]}})
    extra = _escribir(
        tmp_path / "extra.json",
        {"peligros": {"PIEDRAS": ["hay piedras", "hay rocas sueltas"]}},
    )
    _apuntar_corpus(monkeypatch, base)
    monkeypatch.setenv(datos.CORPUS_PATH_VAR, str(extra))
    limpiar_cache()

    # "hay piedras" normaliza igual que "¡Hay Piedras!" y se descarta; la otra se agrega.
    assert cargar_corpus() == {Hazard.PIEDRAS: ["¡Hay Piedras!", "hay rocas sueltas"]}


# ── Errores duros ────────────────────────────────────────────────────────────


def test_codigo_invalido_lanza_con_el_nombre(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _escribir(tmp_path / "corpus.json", {"peligros": {"PIDRAS": ["x"]}})
    _apuntar_corpus(monkeypatch, base)

    with pytest.raises(DatosInvalidos, match="PIDRAS"):
        cargar_corpus()


def test_json_malformado_lanza(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = tmp_path / "corpus.json"
    base.write_text("{esto no es json", encoding="utf-8")
    _apuntar_corpus(monkeypatch, base)

    with pytest.raises(DatosInvalidos, match="JSON malformado"):
        cargar_corpus()


def test_peligros_que_no_es_objeto_lanza(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = _escribir(tmp_path / "corpus.json", {"peligros": []})
    _apuntar_corpus(monkeypatch, base)

    with pytest.raises(DatosInvalidos, match="peligros"):
        cargar_corpus()


def test_frases_que_no_son_textos_lanza(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = _escribir(tmp_path / "corpus.json", {"peligros": {"PIEDRAS": [1, 2]}})
    _apuntar_corpus(monkeypatch, base)

    with pytest.raises(DatosInvalidos):
        cargar_corpus()


# ── Base y extra ausentes ────────────────────────────────────────────────────


def test_base_ausente_da_vacio_sin_lanzar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(datos, "DEFAULT_CORPUS_PATH", tmp_path / "no-existe.json")
    monkeypatch.setattr(datos, "DEFAULT_MEDICION_PATH", tmp_path / "no-existe.json")
    limpiar_cache()

    assert cargar_corpus() == {}
    assert cargar_medicion() == Medicion(peligros={}, ruido=[])


def test_base_ausente_registra_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = tmp_path / "no-existe.json"
    _apuntar_corpus(monkeypatch, base)
    buffer = io.StringIO()

    cargar_corpus(_logger(buffer))

    salida = buffer.getvalue()
    assert "datos.corpus" in salida
    assert "base_ausente" in salida


def test_extra_ausente_se_ignora_y_se_registra(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _escribir(tmp_path / "corpus.json", {"peligros": {"BACHE": ["hay un pozo"]}})
    _apuntar_corpus(monkeypatch, base)
    monkeypatch.setenv(datos.CORPUS_PATH_VAR, str(tmp_path / "no-existe.json"))
    buffer = io.StringIO()

    corpus = cargar_corpus(_logger(buffer))

    assert corpus == {Hazard.BACHE: ["hay un pozo"]}
    assert "extra_ausente" in buffer.getvalue()


# ── Rutas desde el entorno ───────────────────────────────────────────────────


def test_ruta_corpus_sale_del_entorno(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert ruta_corpus() is None

    monkeypatch.setenv(datos.CORPUS_PATH_VAR, str(tmp_path / "extra.json"))
    assert ruta_corpus() == tmp_path / "extra.json"


def test_ruta_medicion_vacia_es_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(datos.MEDICION_PATH_VAR, "   ")
    assert ruta_medicion() is None


# ── Medición ─────────────────────────────────────────────────────────────────


def test_carga_medicion_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = _escribir(
        tmp_path / "medicion.json",
        {
            "peligros": {"POLVO": ["hay tierra en el aire"]},
            "ruido": ["che cuánto falta"],
        },
    )
    _apuntar_medicion(monkeypatch, base)

    medicion = cargar_medicion()

    assert medicion.peligros == {Hazard.POLVO: ["hay tierra en el aire"]}
    assert medicion.ruido == ["che cuánto falta"]


def test_medicion_fusiona_el_extra(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = _escribir(
        tmp_path / "medicion.json",
        {"peligros": {"POLVO": ["hay tierra en el aire"]}, "ruido": ["tengo sed"]},
    )
    extra = _escribir(
        tmp_path / "extra.json",
        {"peligros": {"POLVO": ["no se ve por el polvo"]}, "ruido": ["me pasás el agua"]},
    )
    _apuntar_medicion(monkeypatch, base)
    monkeypatch.setenv(datos.MEDICION_PATH_VAR, str(extra))
    limpiar_cache()

    medicion = cargar_medicion()

    assert medicion.peligros == {Hazard.POLVO: ["hay tierra en el aire", "no se ve por el polvo"]}
    assert medicion.ruido == ["tengo sed", "me pasás el agua"]


def test_medicion_json_malformado_lanza(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = tmp_path / "medicion.json"
    base.write_text("[1, 2, 3]", encoding="utf-8")
    _apuntar_medicion(monkeypatch, base)

    with pytest.raises(DatosInvalidos, match="raíz"):
        cargar_medicion()


# ── Integridad de los datos versionados ──────────────────────────────────────


def test_el_corpus_versionado_cubre_los_16_peligros() -> None:
    corpus = cargar_corpus()
    esperados = {hazard for hazard in Hazard if hazard is not Hazard.DESCONOCIDO}

    assert set(corpus) == esperados
    assert all(corpus[hazard] for hazard in esperados)


def test_ninguna_frase_de_medicion_esta_en_el_corpus() -> None:
    corpus = cargar_corpus()
    medicion = cargar_medicion()

    en_corpus = {normalize(frase) for frases in corpus.values() for frase in frases}
    reservadas = [frase for frases in medicion.peligros.values() for frase in frases]
    reservadas += medicion.ruido

    repetidas = [frase for frase in reservadas if normalize(frase) in en_corpus]
    assert repetidas == []


def test_el_ruido_versionado_tiene_las_28_frases() -> None:
    assert len(cargar_medicion().ruido) == 28
