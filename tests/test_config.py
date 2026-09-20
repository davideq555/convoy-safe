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
