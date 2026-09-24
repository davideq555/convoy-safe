"""Transporte con pérdidas: envuelve otro transporte e inyecta condiciones de radio.

Refleja el decorador esbozado en docs/09-banco-de-pruebas.md: descarta una
fracción de las tramas salientes y agrega una demora aproximada de tiempo en
el aire.
"""

from __future__ import annotations

import random
import time
from collections.abc import Iterator

from .base import Transport


class LossyTransport:
    """Envuelve ``inner`` agregando latencia y pérdida de paquetes configurables."""

    def __init__(self, inner: Transport, delay_ms: float = 340.0, loss: float = 0.10) -> None:
        if not 0.0 <= loss <= 1.0:
            raise ValueError(f"loss debe estar en 0..1, se obtuvo {loss}")
        self._inner = inner
        self._delay = max(delay_ms, 0.0) / 1000.0
        self._loss = loss

    def send_frame(self, frame: bytes) -> None:
        if self._loss > 0.0 and random.random() < self._loss:
            return  # pérdida de paquetes simulada
        if self._delay > 0.0:
            time.sleep(self._delay)  # tiempo en el aire aproximado
        self._inner.send_frame(frame)

    def recv_frames(self) -> Iterator[tuple[bytes, str]]:
        yield from self._inner.recv_frames()

    def close(self) -> None:
        close = getattr(self._inner, "close", None)
        if callable(close):
            close()


__all__ = ["LossyTransport"]
