"""Fixtures compartidas por la suite."""

from __future__ import annotations

from pathlib import Path

import pytest
from comboy.config import ENV_FILE_VAR, ENV_VARS


@pytest.fixture(autouse=True)
def _clean_comboy_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Aísla los tests del entorno del desarrollador.

    Borra las variables ``COMBOY_*`` y apunta el ``.env`` a un archivo
    inexistente. Sin esto, un ``.env`` local o una variable exportada para una
    prueba manual cambiarían el resultado de la suite en silencio.
    """

    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(ENV_FILE_VAR, str(tmp_path / "no-existe.env"))
