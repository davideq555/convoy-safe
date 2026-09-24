"""Tests del catálogo de códigos del protocolo."""

from __future__ import annotations

import pytest
from convoy.codes import (
    HAZARD_TTS,
    LANE_TTS,
    ROLE_BY_NAME,
    ROLE_NAMES,
    URGENCY_TTS,
    Confidence,
    Hazard,
    Lane,
    MsgType,
    Role,
    Urgency,
    as_confidence,
    as_hazard,
    as_lane,
    as_urgency,
    role_from_name,
)


def test_msg_type_values() -> None:
    assert (MsgType.ALERTA, MsgType.HEARTBEAT, MsgType.JOIN, MsgType.LEAVE) == (1, 2, 3, 4)


def test_hazard_values_match_doc() -> None:
    assert Hazard.DESCONOCIDO == 0x00
    assert Hazard.ACCIDENTE == 0x01
    assert Hazard.PIEDRAS == 0x02
    assert Hazard.ANIMAL == 0x03
    assert Hazard.PEATON == 0x04
    assert Hazard.VEHICULO_DETENIDO == 0x05
    assert Hazard.BACHE == 0x06
    assert Hazard.OBRA == 0x07
    assert Hazard.CONTROL == 0x08
    assert Hazard.NIEBLA == 0x09
    assert Hazard.LLUVIA == 0x0A
    assert Hazard.HIELO == 0x0B
    assert Hazard.DERRUMBE == 0x0C
    assert Hazard.CURVA == 0x0D
    assert Hazard.CONTRAMANO == 0x0E
    assert Hazard.CRECIDA == 0x0F
    assert Hazard.POLVO == 0x10


def test_lane_values_match_doc() -> None:
    assert Lane.SIN_ESPECIFICAR == 0x00
    assert Lane.IZQUIERDO == 0x01
    assert Lane.DERECHO == 0x02
    assert Lane.TODA_LA_RUTA == 0x03
    assert Lane.BANQUINA == 0x04
    assert Lane.CALZADA == 0x05


def test_urgency_and_confidence_values() -> None:
    assert (Urgency.INFO, Urgency.PRECAUCION, Urgency.DETENERSE) == (0, 1, 2)
    assert (Confidence.BAJA, Confidence.ALTA) == (0, 1)


def test_every_hazard_has_non_empty_tts_text() -> None:
    assert set(HAZARD_TTS) == set(Hazard)
    assert all(HAZARD_TTS[hazard] for hazard in Hazard)


def test_every_lane_has_tts_text() -> None:
    assert set(LANE_TTS) == set(Lane)
    assert LANE_TTS[Lane.SIN_ESPECIFICAR] == ""
    assert all(LANE_TTS[lane] for lane in Lane if lane is not Lane.SIN_ESPECIFICAR)


def test_urgency_tts_texts_are_exact() -> None:
    assert URGENCY_TTS[Urgency.INFO] == "Solo informativo."
    assert URGENCY_TTS[Urgency.PRECAUCION] == "Precaución."
    assert URGENCY_TTS[Urgency.DETENERSE] == "Deténgase."


def test_unknown_values_fall_back_without_raising() -> None:
    assert as_hazard(0xFE) is Hazard.DESCONOCIDO
    assert as_lane(0xFE) is Lane.SIN_ESPECIFICAR
    assert as_urgency(0xFE) is Urgency.PRECAUCION
    assert as_confidence(0xFE) is Confidence.BAJA


def test_known_values_map_to_enum() -> None:
    assert as_hazard(0x02) is Hazard.PIEDRAS
    assert as_lane(0x02) is Lane.DERECHO
    assert as_urgency(0x02) is Urgency.DETENERSE
    assert as_confidence(0x01) is Confidence.ALTA


def test_role_names_round_trip() -> None:
    assert role_from_name("leader") is Role.LIDER
    assert role_from_name("Follower") is Role.SEGUIDOR
    assert ROLE_NAMES[Role.LIDER] == "leader"
    assert ROLE_BY_NAME["follower"] is Role.SEGUIDOR


def test_role_from_name_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        role_from_name("capitan")
