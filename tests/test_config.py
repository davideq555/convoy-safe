"""Tests de carga de configuración y de los overrides por variables de entorno."""

from __future__ import annotations

from pathlib import Path

import pytest
from comboy.config import (
    apply_env_overrides,
    config_from_mapping,
    load_config,
)


def test_lee_los_valores_del_yaml() -> None:
    config = config_from_mapping(
        {
            "node": {"id": 2, "role": "follower"},
            "transport": {"kind": "udp", "udp": {"bind": "0.0.0.0:45550", "peers": ["a:1"]}},
        }
    )
    assert config.node.id == 2
    assert config.node.role == "follower"
    assert config.transport.kind == "udp"
    assert config.transport.udp.peers == ["a:1"]


def test_el_entorno_define_los_peers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMBOY_UDP_PEERS", "192.168.25.155:45550")
    config = config_from_mapping({})
    assert config.transport.udp.peers == ["192.168.25.155:45550"]


def test_los_peers_admiten_una_lista_separada_por_comas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMBOY_UDP_PEERS", " 10.0.0.2:45550 , 10.0.0.3:45550 ,")
    config = config_from_mapping({})
    assert config.transport.udp.peers == ["10.0.0.2:45550", "10.0.0.3:45550"]


def test_el_entorno_gana_sobre_el_archivo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMBOY_UDP_PEERS", "9.9.9.9:45550")
    config = config_from_mapping(
        {"transport": {"kind": "udp", "udp": {"peers": ["1.1.1.1:45550"]}}}
    )
    assert config.transport.udp.peers == ["9.9.9.9:45550"]


def test_una_variable_vacia_se_ignora(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMBOY_UDP_PEERS", "")
    config = config_from_mapping(
        {"transport": {"kind": "udp", "udp": {"peers": ["1.1.1.1:45550"]}}}
    )
    assert config.transport.udp.peers == ["1.1.1.1:45550"]


def test_el_entorno_aplica_sin_archivo_de_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("COMBOY_NODE_ID", "7")
    monkeypatch.setenv("COMBOY_NODE_ROLE", "leader")
    assert (load_config(None).node.id, load_config(None).node.role) == (7, "leader")
    faltante = load_config(tmp_path / "no-existe.yaml")
    assert (faltante.node.id, faltante.node.role) == (7, "leader")


def test_node_id_invalido_falla_con_mensaje_claro(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMBOY_NODE_ID", "siete")
    with pytest.raises(ValueError, match="COMBOY_NODE_ID"):
        config_from_mapping({})


def test_el_override_no_muta_la_entrada(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMBOY_UDP_BIND", "0.0.0.0:50000")
    original = {"transport": {"udp": {"bind": "0.0.0.0:45550"}}}
    apply_env_overrides(original)
    assert original["transport"]["udp"]["bind"] == "0.0.0.0:45550"


def test_el_entorno_crea_secciones_ausentes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMBOY_UDP_BIND", "0.0.0.0:50000")
    config = config_from_mapping(None)
    assert config.transport.udp.bind == "0.0.0.0:50000"


def test_embedding_usa_los_valores_por_defecto() -> None:
    config = config_from_mapping({})
    assert config.embedding.kind == "ollama"
    assert config.embedding.url == "http://localhost:11434"
    assert config.embedding.model == "qwen3-embedding:0.6b"
    assert config.embedding.min_similarity == 0.68
    assert config.embedding.min_margin == 0.02
    assert config.embedding.timeout_s == 60.0
    assert config.embedding.batch_size == 16
    assert config.embedding.cache_path == ".comboy-embeddings.json"


def test_embedding_cache_se_puede_cambiar_por_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMBOY_EMBEDDING_CACHE", "/tmp/mi-cache.json")
    config = config_from_mapping({})
    assert config.embedding.cache_path == "/tmp/mi-cache.json"


def test_embedding_cache_vacio_deshabilita_el_disco(monkeypatch: pytest.MonkeyPatch) -> None:
    # A diferencia del resto de las variables, acá el vacío es significativo:
    # es la forma de apagar el caché en disco sin borrar la clave del YAML.
    monkeypatch.setenv("COMBOY_EMBEDDING_CACHE", "")
    config = config_from_mapping({"embedding": {"cache_path": "/tmp/otro.json"}})
    assert config.embedding.cache_path == ""


def test_embedding_cache_null_en_yaml_deshabilita() -> None:
    config = config_from_mapping({"embedding": {"cache_path": None}})
    assert config.embedding.cache_path == ""


def test_embedding_kind_null_de_yaml_es_el_cliente_sin_red() -> None:
    # En YAML, ``null`` sin comillas es el valor nulo: el cargador lo interpreta
    # como el kind "null".
    config = config_from_mapping({"embedding": {"kind": None}})
    assert config.embedding.kind == "null"


def test_embedding_admite_overrides_por_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMBOY_EMBEDDING_KIND", "null")
    monkeypatch.setenv("COMBOY_EMBEDDING_URL", "http://otro:1234")
    monkeypatch.setenv("COMBOY_EMBEDDING_MODEL", "otro-modelo")
    config = config_from_mapping({})
    assert config.embedding.kind == "null"
    assert config.embedding.url == "http://otro:1234"
    assert config.embedding.model == "otro-modelo"


def test_embedding_kind_invalido_falla() -> None:
    with pytest.raises(ValueError, match=r"embedding\.kind"):
        config_from_mapping({"embedding": {"kind": "otro"}})


def test_embedding_umbrales_fuera_de_rango_fallan() -> None:
    with pytest.raises(ValueError, match="min_similarity"):
        config_from_mapping({"embedding": {"min_similarity": 1.5}})
    with pytest.raises(ValueError, match="min_margin"):
        config_from_mapping({"embedding": {"min_margin": -0.1}})


def test_embedding_timeout_desde_el_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMBOY_EMBEDDING_TIMEOUT", "12.5")
    config = config_from_mapping({})
    assert config.embedding.timeout_s == 12.5


def test_embedding_timeout_no_numerico_falla(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMBOY_EMBEDDING_TIMEOUT", "cero")
    with pytest.raises(ValueError, match="COMBOY_EMBEDDING_TIMEOUT"):
        config_from_mapping({})


def test_embedding_timeout_y_batch_invalidos_fallan() -> None:
    with pytest.raises(ValueError, match="timeout_s"):
        config_from_mapping({"embedding": {"timeout_s": 0}})
    with pytest.raises(ValueError, match="batch_size"):
        config_from_mapping({"embedding": {"batch_size": 0}})
