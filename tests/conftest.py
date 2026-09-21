"""Fixtures compartidas por la suite."""

from __future__ import annotations

from pathlib import Path

import pytest
from comboy import datos
from comboy.config import ENV_FILE_VAR, ENV_VARS

#: Variables de datos que no son overrides de config, pero que un ``export`` del
#: desarrollador tampoco debe poder filtrar a la suite.
ENV_VARS_DATOS = (datos.CORPUS_PATH_VAR, datos.MEDICION_PATH_VAR)


@pytest.fixture(autouse=True)
def _clean_comboy_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Aísla los tests del entorno del desarrollador.

    Borra las variables ``COMBOY_*`` (incluidas las rutas de datos), apunta el
    ``.env`` a un archivo inexistente y limpia las cachés del cargador. Sin esto,
    un ``.env`` local, una variable exportada para una prueba manual o un corpus
    cacheado de un test anterior cambiarían el resultado de la suite en silencio.
    """

    for name in (*ENV_VARS, *ENV_VARS_DATOS):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(ENV_FILE_VAR, str(tmp_path / "no-existe.env"))
    datos.limpiar_cache()
    yield
    datos.limpiar_cache()
