"""Logger de texto plano con el formato de línea de docs/06-codigos-y-logs.md.

Formato de línea::

    <wall_clock> <uptime_ms> <boot_id> <node> <role> <level> <event> <key=value>...

* wall clock: ISO-8601 con milisegundos, p. ej. ``2026-09-18T14:32:11.123``.
  No es confiable (no hay RTC), y por eso el uptime monotónico viaja junto a él.
* uptime_ms: milisegundos monotónicos desde el arranque del proceso, con signo
  y rellenados a 10 dígitos con ceros, p. ej. ``+0001234567``.
* boot_id: 4 caracteres hex aleatorios por corrida, p. ej. ``boot=7f3a``.
* level: ancho fijo 6, alineado a la izquierda (``INFO  ``, ``WARN  ``, ``DEBUG ``, ``ERROR ``).
* event: ancho fijo 14, alineado a la izquierda.
* pares key=value: separados por espacios; los valores con espacios se
  entrecomillan con comillas dobles.

Esto deliberadamente no es un log de auditoría: sin hashes, sin firmas.
"""

from __future__ import annotations

import contextlib
import secrets
import sys
import threading
import time
from datetime import datetime
from typing import IO, Any

_LEVEL_DEBUG = 10
_LEVEL_INFO = 20
_LEVEL_WARN = 30
_LEVEL_ERROR = 40

_LEVEL_BY_NAME: dict[str, int] = {
    "debug": _LEVEL_DEBUG,
    "info": _LEVEL_INFO,
    "warn": _LEVEL_WARN,
    "warning": _LEVEL_WARN,
    "error": _LEVEL_ERROR,
}

_LEVEL_LABELS: dict[int, str] = {
    _LEVEL_DEBUG: "DEBUG",
    _LEVEL_INFO: "INFO",
    _LEVEL_WARN: "WARN",
    _LEVEL_ERROR: "ERROR",
}

_EVENT_WIDTH = 14
_LEVEL_WIDTH = 6


def _format_value(value: Any) -> str:
    """Formatea un valor de key=value, entrecomillándolo cuando contiene espacios."""

    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if text == "" or any(char.isspace() for char in text):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


class Logger:
    """Logger estructurado pequeño que escribe líneas doc-06 a un stream o archivo."""

    def __init__(
        self,
        *,
        node_id: int,
        role: str,
        level: str = "info",
        path: str | None = None,
        stream: IO[str] | None = None,
        boot_id: str | None = None,
    ) -> None:
        self._node_id = node_id
        self._role = role
        self._threshold = _LEVEL_BY_NAME.get(str(level).strip().lower(), _LEVEL_INFO)
        self._boot_id = boot_id or secrets.token_hex(2)
        self._lock = threading.Lock()
        self._start = time.monotonic()
        self._owns_stream = False

        if stream is not None:
            self._stream: IO[str] = stream
        elif path:
            # El logger es dueño de este handle durante toda su vida, así que un
            # context manager no aplica aquí.
            self._stream = open(path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
            self._owns_stream = True
        else:
            self._stream = sys.stderr

    @property
    def boot_id(self) -> str:
        return self._boot_id

    @property
    def level(self) -> int:
        return self._threshold

    def debug(self, event: str, **fields: Any) -> None:
        self._emit(_LEVEL_DEBUG, event, fields)

    def info(self, event: str, **fields: Any) -> None:
        self._emit(_LEVEL_INFO, event, fields)

    def warn(self, event: str, **fields: Any) -> None:
        self._emit(_LEVEL_WARN, event, fields)

    def error(self, event: str, **fields: Any) -> None:
        self._emit(_LEVEL_ERROR, event, fields)

    def _emit(self, level: int, event: str, fields: dict[str, Any]) -> None:
        if level < self._threshold:
            return
        line = self._format(level, event, fields)
        with self._lock, contextlib.suppress(ValueError, OSError):
            # Un destino de log cerrado o roto nunca debe tumbar el nodo.
            print(line, file=self._stream, flush=True)

    def _format(self, level: int, event: str, fields: dict[str, Any]) -> str:
        wall = datetime.now().isoformat(timespec="milliseconds")
        uptime_ms = int((time.monotonic() - self._start) * 1000)
        prefix = (
            f"{wall} +{uptime_ms:010d} boot={self._boot_id} "
            f"node={self._node_id} role={self._role}"
        )
        head = f"{_LEVEL_LABELS[level]:<{_LEVEL_WIDTH}}{event:<{_EVENT_WIDTH}}"
        line = f"{prefix} {head}"
        pairs = " ".join(f"{key}={_format_value(value)}" for key, value in fields.items())
        if pairs:
            # El campo event se rellena al ancho 14, así que su relleno final
            # ya lo separa del primer par key=value. Solo los eventos largos
            # (>= 14 chars) necesitan un espacio explícito.
            if len(event) >= _EVENT_WIDTH:
                line += " "
            line += pairs
        return line

    def close(self) -> None:
        """Cierra el archivo de log si este logger abrió uno."""

        if not self._owns_stream:
            return
        with self._lock, contextlib.suppress(ValueError, OSError):
            self._stream.close()


__all__ = ["Logger"]
