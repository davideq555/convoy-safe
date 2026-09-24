"""Tests del parser de ``.env`` y de su integración con la configuración."""

from __future__ import annotations

from pathlib import Path

import pytest
from convoy.config import load_config
from convoy.envfile import ENV_FILE_VAR, load_env_file


def _write(tmp_path: Path, text: str) -> Path:
    target = tmp_path / ".env"
    target.write_text(text, encoding="utf-8")
    return target


def test_lee_pares_clave_valor(tmp_path: Path) -> None:
    path = _write(tmp_path, "CONVOY_UDP_PEERS=eevee.local:45550\n")
    assert load_env_file(path) == {"CONVOY_UDP_PEERS": "eevee.local:45550"}


def test_ignora_comentarios_y_lineas_vacias(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "# un comentario\n\n   \nCONVOY_LOG_LEVEL=debug\n# otro comentario\n",
    )
    assert load_env_file(path) == {"CONVOY_LOG_LEVEL": "debug"}


def test_ignora_claves_ajenas_al_prefijo(tmp_path: Path) -> None:
    """Un .env no puede inyectar variables arbitrarias en el entorno."""

    path = _write(
        tmp_path,
        "PATH=/usr/bin:/bin\nHOME=/root\nCONVOY_LOG_LEVEL=warn\n",
    )
    assert load_env_file(path) == {"CONVOY_LOG_LEVEL": "warn"}


def test_saca_las_comillas_del_valor(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "CONVOY_UDP_PEERS=\"eevee.local:45550\"\nCONVOY_UDP_BIND='0.0.0.0:45550'\n",
    )
    assert load_env_file(path) == {
        "CONVOY_UDP_PEERS": "eevee.local:45550",
        "CONVOY_UDP_BIND": "0.0.0.0:45550",
    }


def test_conserva_los_iguales_dentro_del_valor(tmp_path: Path) -> None:
    path = _write(tmp_path, "CONVOY_LOG_LEVEL=debug=verbose\n")
    assert load_env_file(path)["CONVOY_LOG_LEVEL"] == "debug=verbose"


def test_la_ultima_definicion_gana(tmp_path: Path) -> None:
    path = _write(tmp_path, "CONVOY_LOG_LEVEL=info\nCONVOY_LOG_LEVEL=debug\n")
    assert load_env_file(path) == {"CONVOY_LOG_LEVEL": "debug"}


def test_un_archivo_ausente_no_es_un_error(tmp_path: Path) -> None:
    assert load_env_file(tmp_path / "no-existe") == {}


def test_un_directorio_no_es_un_error(tmp_path: Path) -> None:
    assert load_env_file(tmp_path) == {}


def test_el_env_llega_a_la_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(ENV_FILE_VAR, str(_write(tmp_path, "CONVOY_UDP_PEERS=10.1.1.1:45550\n")))
    assert load_config(None).transport.udp.peers == ["10.1.1.1:45550"]


def test_el_entorno_real_gana_sobre_el_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(ENV_FILE_VAR, str(_write(tmp_path, "CONVOY_UDP_PEERS=10.1.1.1:45550\n")))
    monkeypatch.setenv("CONVOY_UDP_PEERS", "9.9.9.9:45550")
    assert load_config(None).transport.udp.peers == ["9.9.9.9:45550"]


def test_el_env_gana_sobre_el_yaml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    yaml_path = tmp_path / "nodo.yaml"
    yaml_path.write_text("log:\n  level: info\n", encoding="utf-8")
    monkeypatch.setenv(ENV_FILE_VAR, str(_write(tmp_path, "CONVOY_LOG_LEVEL=debug\n")))
    assert load_config(yaml_path).log.level == "debug"
