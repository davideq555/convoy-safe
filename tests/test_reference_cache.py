"""Tests de la persistencia del índice de referencias en disco.

Todos corren sin red con ``NullEmbedding`` y ``tmp_path``. El criterio central
es que una segunda resolución con el mismo corpus, proveedor y modelo **no vuelva
a embeber**: el índice se reutiliza desde el archivo. Un caché escrito por un
proveedor nunca debe leerse con otro, aunque el nombre del modelo coincida.
"""

from __future__ import annotations

import io
import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from comboy import classify as classify_module
from comboy import datos
from comboy.classify import (
    _corpus_fingerprint,
    _resolve_reference_index,
    classify,
)
from comboy.codes import Hazard
from comboy.config import EmbeddingConfig
from comboy.embedding import NullEmbedding
from comboy.logging_setup import Logger

MODELO = "modelo-de-prueba"
URL = "http://localhost:11434"


def _config(
    cache: str,
    *,
    kind: str = "null",
    model: str = MODELO,
    url: str = URL,
) -> EmbeddingConfig:
    """Config de embeddings para tests: sin red y con la ruta de caché dada."""

    return EmbeddingConfig(kind=kind, model=model, url=url, cache_path=cache)


class _ClienteQueCuenta:
    """Envuelve un cliente real y cuenta cuántos textos se embebieron."""

    def __init__(self) -> None:
        self._inner = NullEmbedding()
        self.textos = 0

    @property
    def available(self) -> bool:
        return True

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.textos += len(texts)
        return self._inner.embed(texts)

    def reset(self) -> None:
        self.textos = 0


def _logger(buffer: io.StringIO | None = None) -> Logger:
    return Logger(node_id=1, role="leader", stream=buffer if buffer is not None else io.StringIO())


# ── Hit y visibilidad ────────────────────────────────────────────────────────


def test_un_hit_no_vuelve_a_embeber(tmp_path: Path) -> None:
    cache = tmp_path / "cache.json"
    config = _config(str(cache))
    cliente = _ClienteQueCuenta()

    primera = _resolve_reference_index(cliente, config, _logger())
    assert cliente.textos > 0

    cliente.reset()
    segunda = _resolve_reference_index(cliente, config, _logger())

    assert cliente.textos == 0
    consulta = NullEmbedding().embed(["hubo un accidente en la ruta"])[0]
    ref_primera, sim_primera, _ = primera.score(consulta)
    ref_segunda, sim_segunda, _ = segunda.score(consulta)
    assert ref_segunda.hazard == ref_primera.hazard
    assert ref_segunda.phrase == ref_primera.phrase
    assert sim_segunda == pytest.approx(sim_primera)


def test_emite_embedding_cache_hit(tmp_path: Path) -> None:
    cache = tmp_path / "cache.json"
    config = _config(str(cache))
    _resolve_reference_index(_ClienteQueCuenta(), config, _logger())

    buffer = io.StringIO()
    _resolve_reference_index(_ClienteQueCuenta(), config, _logger(buffer))

    salida = buffer.getvalue()
    assert "embedding.cache" in salida
    assert "result=hit" in salida
    assert f"path={cache}" in salida


def test_emite_embedding_cache_miss_si_no_hay_archivo(tmp_path: Path) -> None:
    buffer = io.StringIO()
    _resolve_reference_index(
        _ClienteQueCuenta(), _config(str(tmp_path / "nuevo.json")), _logger(buffer)
    )

    salida = buffer.getvalue()
    assert "embedding.cache" in salida
    assert "result=miss" in salida
    assert "reason=ausente" in salida


# ── Invalidación: corpus, modelo, proveedor y url ────────────────────────────


def test_corpus_distinto_reconstruye(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = tmp_path / "cache.json"
    config = _config(str(cache))
    cliente = _ClienteQueCuenta()
    _resolve_reference_index(cliente, config, _logger())
    huella_original = _corpus_fingerprint(config)

    cliente.reset()
    corpus_alterado = dict(classify_module.cargar_corpus())
    corpus_alterado[Hazard.ACCIDENTE] = ["chocaron de frente en la ruta"]
    monkeypatch.setattr(classify_module, "cargar_corpus", lambda *args, **kwargs: corpus_alterado)

    _resolve_reference_index(cliente, config, _logger())

    assert cliente.textos > 0
    assert _corpus_fingerprint(config) != huella_original


def test_modelo_distinto_reconstruye(tmp_path: Path) -> None:
    cache = tmp_path / "cache.json"
    _resolve_reference_index(_ClienteQueCuenta(), _config(str(cache), model="modelo-a"), _logger())

    cliente = _ClienteQueCuenta()
    _resolve_reference_index(cliente, _config(str(cache), model="modelo-b"), _logger())

    assert cliente.textos > 0


def test_el_fingerprint_cambia_con_el_modelo() -> None:
    modelo_a = _config("", model="modelo-a")
    modelo_b = _config("", model="modelo-b")

    assert _corpus_fingerprint(modelo_a) != _corpus_fingerprint(modelo_b)


def test_el_fingerprint_cambia_con_el_corpus(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config("")
    original = _corpus_fingerprint(config)
    corpus_alterado = dict(classify_module.cargar_corpus())
    corpus_alterado[Hazard.PIEDRAS] = ["hay escombros en la calzada"]
    monkeypatch.setattr(classify_module, "cargar_corpus", lambda *args, **kwargs: corpus_alterado)

    assert _corpus_fingerprint(config) != original


def test_editar_el_json_cambia_la_huella(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Criterio de aceptación: el JSON manda, no una constante de Python.

    La huella cubre el contenido cargado, así que editar ``datos/corpus.json`` y
    recargar invalida el índice en disco.
    """

    base = tmp_path / "corpus.json"
    base.write_text(
        json.dumps({"peligros": {"PIEDRAS": ["hay piedras en la ruta"]}}), encoding="utf-8"
    )
    monkeypatch.setattr(datos, "DEFAULT_CORPUS_PATH", base)
    datos.limpiar_cache()
    config = _config("")

    antes = _corpus_fingerprint(config)

    base.write_text(
        json.dumps({"peligros": {"PIEDRAS": ["hay muchas piedras en la ruta"]}}),
        encoding="utf-8",
    )
    datos.limpiar_cache()

    assert _corpus_fingerprint(config) != antes


def test_el_fingerprint_cambia_con_el_proveedor() -> None:
    # Mismo modelo, distinto proveedor: la huella debe ser distinta.
    con_ollama = _config("", kind="ollama")
    con_null = _config("", kind="null")

    assert _corpus_fingerprint(con_ollama) != _corpus_fingerprint(con_null)


def test_el_fingerprint_cambia_con_la_url() -> None:
    # Mismo proveedor y modelo, distinto servidor: la huella debe ser distinta.
    un_servidor = _config("", kind="ollama", url="http://localhost:11434")
    otro_servidor = _config("", kind="ollama", url="http://otro-servidor:11434")

    assert _corpus_fingerprint(un_servidor) != _corpus_fingerprint(otro_servidor)


# ── Nunca romper ─────────────────────────────────────────────────────────────


def test_archivo_corrupto_se_ignora_y_reconstruye(tmp_path: Path) -> None:
    cache = tmp_path / "cache.json"
    config = _config(str(cache))
    cache.write_text("{esto no es json", encoding="utf-8")
    cliente = _ClienteQueCuenta()

    _resolve_reference_index(cliente, config, _logger())

    assert cliente.textos > 0
    payload = json.loads(cache.read_text(encoding="utf-8"))
    assert payload["fingerprint"] == _corpus_fingerprint(config)


def test_referencia_con_formato_inesperado_se_ignora(tmp_path: Path) -> None:
    cache = tmp_path / "cache.json"
    config = _config(str(cache))
    cache.write_text(
        json.dumps(
            {
                "version": 1,
                "fingerprint": _corpus_fingerprint(config),
                "model": MODELO,
                "references": [{"hazard": "NO_EXISTE", "phrase": "x", "vector": []}],
            }
        ),
        encoding="utf-8",
    )
    cliente = _ClienteQueCuenta()

    _resolve_reference_index(cliente, config, _logger())

    assert cliente.textos > 0


def test_fingerprint_que_no_coincide_se_ignora(tmp_path: Path) -> None:
    cache = tmp_path / "cache.json"
    config = _config(str(cache))
    _resolve_reference_index(_ClienteQueCuenta(), config, _logger())
    payload = json.loads(cache.read_text(encoding="utf-8"))
    payload["fingerprint"] = "0" * 64
    cache.write_text(json.dumps(payload), encoding="utf-8")

    cliente = _ClienteQueCuenta()
    _resolve_reference_index(cliente, config, _logger())

    assert cliente.textos > 0
    assert json.loads(cache.read_text(encoding="utf-8"))["fingerprint"] == _corpus_fingerprint(
        config
    )


# ── Deshabilitar y escritura atómica ─────────────────────────────────────────


def test_cache_path_vacio_no_escribe_ningun_archivo(tmp_path: Path) -> None:
    cliente = _ClienteQueCuenta()

    _resolve_reference_index(cliente, _config(""), _logger())

    assert cliente.textos > 0
    assert list(tmp_path.iterdir()) == []


def test_no_quedan_archivos_temporales(tmp_path: Path) -> None:
    cache = tmp_path / "cache.json"

    _resolve_reference_index(_ClienteQueCuenta(), _config(str(cache)), _logger())

    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["cache.json"]


# ── Criterio central: la segunda corrida no reconstruye el índice ────────────


def test_la_segunda_clasificacion_no_reconstruye_el_indice(tmp_path: Path) -> None:
    cache = tmp_path / "cache.json"
    cliente = _ClienteQueCuenta()
    config = _config(str(cache))
    logger = _logger()

    # Primera corrida: construye el índice (todo el corpus) y lo persiste.
    classify_module._reference_index.cache_clear()
    classify("hubo un accidente en la ruta", cliente, config, logger)
    assert cliente.textos > 1  # las 70 frases del corpus más la consulta

    # Segunda corrida en un proceso nuevo: la caché en memoria arranca vacía.
    classify_module._reference_index.cache_clear()
    cliente.reset()
    result = classify("hubo un accidente en la ruta", cliente, config, logger)

    assert cliente.textos == 1  # solo la consulta: el índice vino del disco
    assert result.hazard is Hazard.ACCIDENTE


def test_un_proveedor_no_reutiliza_el_cache_de_otro(tmp_path: Path) -> None:
    """Caso de regresión: mismo modelo, distinto proveedor, caché ajeno.

    Antes la huella dependía solo del modelo, así que un caché escrito sin red
    (``kind: null``, vectores de 128 dimensiones) se reutilizaba al volver a
    ``kind: ollama`` con el mismo nombre de modelo. Los vectores de 1024
    dimensiones se comparaban contra los de 128 y todo clasificaba
    ``DESCONOCIDO`` en silencio. Con el proveedor dentro de la huella, el segundo
    cliente reconstruye el índice en vez de confiar en el archivo ajeno.
    """

    cache = tmp_path / "cache.json"
    config_null = _config(str(cache), kind="null")
    config_ollama = _config(str(cache), kind="ollama")

    cliente_construye = _ClienteQueCuenta()
    _resolve_reference_index(cliente_construye, config_null, _logger())
    assert cliente_construye.textos > 0
    assert json.loads(cache.read_text(encoding="utf-8"))["fingerprint"] == _corpus_fingerprint(
        config_null
    )

    # Otro proveedor, el mismo modelo: no debe reutilizar el caché ajeno.
    cliente_reconstruye = _ClienteQueCuenta()
    _resolve_reference_index(cliente_reconstruye, config_ollama, _logger())

    assert cliente_reconstruye.textos > 0
    assert json.loads(cache.read_text(encoding="utf-8"))["fingerprint"] == _corpus_fingerprint(
        config_ollama
    )
