"""Transporte nulo: descarta todo lo enviado y nunca recibe."""

from __future__ import annotations

import threading
from collections.abc import Iterator


class NullTransport:
    """Transporte de un solo nodo / offline.

    Se usa para ejercitar el pipeline sin red (docs/02, doc 09).
    """

    def __init__(self) -> None:
        self._closed = threading.Event()

    def send_frame(self, frame: bytes) -> None:
        """Acepta y descarta una trama."""

    def recv_frames(self) -> Iterator[tuple[bytes, str]]:
        """Bloquea hasta que se llame a :meth:`close`; nunca emite una trama."""

        self._closed.wait()
        return
        yield  # pragma: no cover - convierte esto en una función generadora

    def close(self) -> None:
        self._closed.set()


__all__ = ["NullTransport"]
