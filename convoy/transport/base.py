"""Interfaz de transporte (copiada de docs/09-banco-de-pruebas.md)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable


@runtime_checkable
class Transport(Protocol):
    """El resto del sistema nunca toca un socket; habla con esto."""

    def send_frame(self, frame: bytes) -> None:
        """Envía una trama. Puede fallar en silencio: es best-effort."""

        ...

    def recv_frames(self) -> Iterator[tuple[bytes, str]]:
        """Devuelve (frame, origin). Bloqueante; corre en su propio hilo."""

        ...


__all__ = ["Transport"]
