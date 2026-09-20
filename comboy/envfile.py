"""Lectura del archivo ``.env`` local de cada nodo.

Existe para no tener que exportar variables a mano en cada terminal: el archivo
se lee solo, al cargar la configuración.

Reglas deliberadamente conservadoras:

* **Solo se aceptan claves ``COMBOY_*``.** Un ``.env`` no puede inyectar ``PATH``
  ni ninguna otra variable del entorno, ni siquiera por error.
* **El entorno real gana.** Una variable ya presente en el proceso no se pisa,
  así que exportar algo en la terminal siempre tiene la última palabra.
* **Si el archivo no existe, no pasa nada.** Es un archivo opcional.
* Los **valores** no se validan acá: los valida quien los consume, que puede dar
  un mensaje de error específico. Acá solo se separa ``clave=valor``.
"""

from __future__ import annotations

from pathlib import Path

#: Prefijo obligatorio de las claves aceptadas.
PREFIX = "COMBOY_"

#: Variable que permite apuntar a otro archivo (útil para probar varios perfiles).
ENV_FILE_VAR = "COMBOY_ENV_FILE"

#: Nombre por defecto, buscado en el directorio de trabajo.
DEFAULT_ENV_FILE = ".env"


def _parse_line(line: str) -> tuple[str, str] | None:
    """Devuelve ``(clave, valor)`` si la línea define una variable aceptada."""

    text = line.strip()
    if not text or text.startswith("#"):
        return None

    key, separator, raw = text.partition("=")
    key = key.strip()
    if not separator or not key.startswith(PREFIX):
        return None

    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return key, value


def load_env_file(path: str | Path) -> dict[str, str]:
    """Parsea ``path`` y devuelve las claves ``COMBOY_*`` que define.

    Un archivo ausente o ilegible devuelve un diccionario vacío: un ``.env``
    roto nunca debe impedir que el nodo arranque.
    """

    candidate = Path(path)
    if not candidate.is_file():
        return {}

    values: dict[str, str] = {}
    try:
        with candidate.open("r", encoding="utf-8") as handle:
            for line in handle:
                parsed = _parse_line(line)
                if parsed is not None:
                    values[parsed[0]] = parsed[1]
    except OSError:
        return {}
    return values


__all__ = ["DEFAULT_ENV_FILE", "ENV_FILE_VAR", "PREFIX", "load_env_file"]
