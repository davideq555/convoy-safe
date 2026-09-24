"""Paquete de transportes: interfaz, implementaciones y la fábrica."""

from __future__ import annotations

from ..config import Config
from ..logging_setup import Logger
from .base import Transport
from .lossy import LossyTransport
from .null import NullTransport
from .udp import UdpTransport

# ``LoraTransport`` (SX1262 sobre SPI) va aquí cuando exista el hardware.
# Deliberadamente no está implementado en la Fase 0. Ver docs/09-banco-de-pruebas.md.

__all__ = [
    "LossyTransport",
    "NullTransport",
    "Transport",
    "UdpTransport",
    "create_transport",
]


def create_transport(config: Config, logger: Logger | None = None) -> Transport:
    """Construye el transporte descrito por ``config``.

    Cuando ``simulation.enabled`` es verdadero, el transporte real se envuelve
    en un :class:`LossyTransport` (latencia + pérdida), según docs/09.
    """

    kind = config.transport.kind
    transport: Transport
    if kind == "null":
        transport = NullTransport()
    elif kind == "udp":
        transport = UdpTransport(
            bind=config.transport.udp.bind,
            peers=config.transport.udp.peers,
            logger=logger,
        )
    elif kind == "lora":
        raise NotImplementedError(
            "LoraTransport está previsto para la Fase 5; usar transport.kind 'udp' o 'null'"
        )
    else:  # pragma: no cover - load_config ya valida el valor
        raise ValueError(f"tipo de transporte no soportado: {kind!r}")

    if config.simulation.enabled:
        transport = LossyTransport(
            transport,
            delay_ms=config.simulation.delay_ms,
            loss=config.simulation.loss,
        )
    return transport
