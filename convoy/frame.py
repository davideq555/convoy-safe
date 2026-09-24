"""Codec de trama de 17 bytes (ver docs/03-protocolo-de-radio.md).

Disposición en el cable (todos los campos multibyte little-endian)::

    offset  campo         tipo
    0       version       u8
    1       msg_type      u8
    2-5     alert_id      u32
    6       origin_id     u8
    7       origin_role   u8
    8       hop           u8
    9       ttl           u8
    10      hazard        u8
    11      lane          u8
    12      dist_km       u8
    13      urgency       u8
    14      confidence    u8
    15-16   crc16         u16   sobre los bytes 0..14

Elección de CRC
---------------
El documento de diseño solo dice "CRC-16/CCITT", que es ambiguo. Este módulo
usa deliberadamente **CRC-16/CCITT-FALSE**: poly ``0x1021``, init ``0xFFFF``,
sin reflexión de entrada/salida, xorout ``0x0000``. Vector de verificación
obligatorio: ``b"123456789"`` -> ``0x29B1``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .codes import Confidence, Hazard, Lane, MsgType, Role, Urgency

PROTOCOL_VERSION = 1
FRAME_SIZE = 17

#: Cantidad de bytes iniciales cubiertos por el CRC (version .. confidence).
_CRC_COVERED_BYTES = 15

#: version, msg_type, alert_id, origin_id, origin_role, hop, ttl,
#: hazard, lane, dist_km, urgency, confidence  (15 bytes, sin CRC).
_HEADER_STRUCT = struct.Struct("<BBIBBBBBBBBB")
_FRAME_STRUCT = struct.Struct("<BBIBBBBBBBBBH")

# Parámetros de CRC-16/CCITT-FALSE, nombrados explícitamente a propósito (ver docstring del módulo).
CRC16_CCITT_FALSE_POLY = 0x1021
CRC16_CCITT_FALSE_INIT = 0xFFFF
CRC16_CCITT_FALSE_XOROUT = 0x0000


def _build_crc_table() -> tuple[int, ...]:
    table: list[int] = []
    for byte in range(256):
        crc = byte << 8
        for _ in range(8):
            if crc & 0x8000:  # noqa: SIM108 - explicit table build reads better
                crc = ((crc << 1) ^ CRC16_CCITT_FALSE_POLY) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
        table.append(crc)
    return tuple(table)


_CRC_TABLE = _build_crc_table()


def crc16_ccitt_false(data: bytes) -> int:
    """Devuelve el checksum CRC-16/CCITT-FALSE de ``data``."""

    crc = CRC16_CCITT_FALSE_INIT
    for byte in data:
        crc = ((crc << 8) & 0xFFFF) ^ _CRC_TABLE[((crc >> 8) ^ byte) & 0xFF]
    return crc ^ CRC16_CCITT_FALSE_XOROUT


@dataclass(frozen=True, slots=True)
class AlertFrame:
    """Una trama de protocolo decodificada de 17 bytes.

    Los campos se guardan como enteros crudos para que los valores desconocidos
    que lleguen de un par más nuevo nunca rompan la decodificación. Los helpers
    de :mod:`convoy.codes` mapean esos valores a los enums de dominio.
    """

    version: int = PROTOCOL_VERSION
    msg_type: int = MsgType.ALERTA
    alert_id: int = 0
    origin_id: int = 0
    origin_role: int = Role.LIDER
    hop: int = 0
    ttl: int = 0
    hazard: int = Hazard.DESCONOCIDO
    lane: int = Lane.SIN_ESPECIFICAR
    dist_km: int = 255
    urgency: int = Urgency.PRECAUCION
    confidence: int = Confidence.ALTA

    def encode(self) -> bytes:
        """Serializa la trama a su representación de cable de 17 bytes."""

        header = _HEADER_STRUCT.pack(
            self.version,
            self.msg_type,
            self.alert_id,
            self.origin_id,
            self.origin_role,
            self.hop,
            self.ttl,
            self.hazard,
            self.lane,
            self.dist_km,
            self.urgency,
            self.confidence,
        )
        crc = crc16_ccitt_false(header)
        return header + struct.pack("<H", crc)

    @classmethod
    def decode(cls, data: bytes) -> AlertFrame | None:
        """Decodifica una trama, o devuelve ``None`` ante cualquier entrada inválida.

        Inválida significa: no bytes-like, longitud incorrecta, versión de
        protocolo desconocida o CRC incorrecto. Este método nunca lanza
        excepciones ante datos basura.
        """

        try:
            raw = bytes(data)
        except (TypeError, ValueError):
            return None

        if len(raw) != FRAME_SIZE:
            return None

        try:
            (
                version,
                msg_type,
                alert_id,
                origin_id,
                origin_role,
                hop,
                ttl,
                hazard,
                lane,
                dist_km,
                urgency,
                confidence,
                crc,
            ) = _FRAME_STRUCT.unpack(raw)
        except struct.error:
            return None

        if version != PROTOCOL_VERSION:
            return None
        if crc16_ccitt_false(raw[:_CRC_COVERED_BYTES]) != crc:
            return None

        return cls(
            version=version,
            msg_type=msg_type,
            alert_id=alert_id,
            origin_id=origin_id,
            origin_role=origin_role,
            hop=hop,
            ttl=ttl,
            hazard=hazard,
            lane=lane,
            dist_km=dist_km,
            urgency=urgency,
            confidence=confidence,
        )


__all__ = [
    "CRC16_CCITT_FALSE_INIT",
    "CRC16_CCITT_FALSE_POLY",
    "CRC16_CCITT_FALSE_XOROUT",
    "FRAME_SIZE",
    "PROTOCOL_VERSION",
    "AlertFrame",
    "crc16_ccitt_false",
    "decode",
    "encode",
]


def encode(frame: AlertFrame) -> bytes:
    """Atajo a nivel de módulo para :meth:`AlertFrame.encode`."""

    return frame.encode()


def decode(data: bytes) -> AlertFrame | None:
    """Atajo a nivel de módulo para :meth:`AlertFrame.decode`.

    Devuelve ``None`` ante cualquier entrada inválida y nunca lanza excepciones
    ante datos basura.
    """

    return AlertFrame.decode(data)
