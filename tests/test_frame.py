"""Tests del codec de tramas y del CRC."""

from __future__ import annotations

import os

import pytest
from comboy.codes import Confidence, Hazard, Lane, MsgType, Role, Urgency
from comboy.frame import (
    CRC16_CCITT_FALSE_INIT,
    FRAME_SIZE,
    PROTOCOL_VERSION,
    AlertFrame,
    crc16_ccitt_false,
    decode,
)


def _example_frame(**overrides: int) -> AlertFrame:
    values = {
        "version": PROTOCOL_VERSION,
        "msg_type": MsgType.ALERTA,
        "alert_id": 0x11223344,
        "origin_id": 1,
        "origin_role": Role.LIDER,
        "hop": 0,
        "ttl": 3,
        "hazard": Hazard.PIEDRAS,
        "lane": Lane.DERECHO,
        "dist_km": 2,
        "urgency": Urgency.PRECAUCION,
        "confidence": Confidence.ALTA,
    }
    values.update(overrides)
    return AlertFrame(**values)  # type: ignore[arg-type]


def test_crc_check_vector() -> None:
    assert crc16_ccitt_false(b"123456789") == 0x29B1


def test_crc_init_constant_is_ccitt_false() -> None:
    assert CRC16_CCITT_FALSE_INIT == 0xFFFF


def test_crc_empty_is_init() -> None:
    assert crc16_ccitt_false(b"") == 0xFFFF


def test_encode_is_exactly_17_bytes() -> None:
    assert len(_example_frame().encode()) == FRAME_SIZE == 17


def test_encode_little_endian_alert_id() -> None:
    frame = _example_frame(alert_id=0x11223344)
    assert frame.encode()[2:6] == b"\x44\x33\x22\x11"


def test_encode_little_endian_crc() -> None:
    frame = _example_frame()
    data = frame.encode()
    expected = crc16_ccitt_false(data[:15])
    assert data[15:17] == expected.to_bytes(2, "little")


def test_crc_covers_bytes_0_to_14() -> None:
    data = _example_frame().encode()
    assert crc16_ccitt_false(data[:15]) == int.from_bytes(data[15:17], "little")


def test_round_trip() -> None:
    frame = _example_frame()
    assert decode(frame.encode()) == frame


def test_round_trip_unknown_catalog_values() -> None:
    frame = _example_frame(hazard=0xFE, lane=0xFD, urgency=0xFC, confidence=0xFB)
    assert decode(frame.encode()) == frame


@pytest.mark.parametrize("length", [0, 1, 15, 16, 18, 32])
def test_decode_rejects_wrong_length(length: int) -> None:
    assert decode(b"\x00" * length) is None


def test_decode_rejects_unknown_version() -> None:
    data = bytearray(_example_frame().encode())
    data[0] = PROTOCOL_VERSION + 1
    assert decode(bytes(data)) is None


def test_decode_rejects_bad_crc() -> None:
    data = bytearray(_example_frame().encode())
    data[15] ^= 0xFF
    assert decode(bytes(data)) is None


def test_decode_rejects_corrupted_payload() -> None:
    data = bytearray(_example_frame().encode())
    data[10] ^= 0x01  # invierte un bit del payload sin corregir el CRC
    assert decode(bytes(data)) is None


def test_decode_returns_none_on_none() -> None:
    assert decode(None) is None  # type: ignore[arg-type]


def test_decode_never_raises_on_garbage() -> None:
    for _ in range(200):
        blob = os.urandom(17)
        try:
            decode(blob)
        except Exception as exc:  # pragma: no cover - camino de fallo
            raise AssertionError(f"decode lanzó una excepción con datos basura: {exc!r}") from exc
