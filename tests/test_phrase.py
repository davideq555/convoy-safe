"""Tests de la construcción de la frase de TTS."""

from __future__ import annotations

from convoy.codes import Confidence, Hazard, Lane, Urgency
from convoy.frame import AlertFrame
from convoy.phrase import build_phrase


def _frame(
    *,
    hazard: int = Hazard.PIEDRAS,
    lane: int = Lane.SIN_ESPECIFICAR,
    dist_km: int = 255,
    urgency: int = Urgency.PRECAUCION,
    confidence: int = Confidence.ALTA,
) -> AlertFrame:
    return AlertFrame(
        alert_id=0,
        origin_id=1,
        hazard=hazard,
        lane=lane,
        dist_km=dist_km,
        urgency=urgency,
        confidence=confidence,
    )


def test_doc_06_verified_example() -> None:
    frame = _frame(
        hazard=Hazard.PIEDRAS,
        lane=Lane.DERECHO,
        dist_km=2,
        urgency=Urgency.PRECAUCION,
        confidence=Confidence.ALTA,
    )
    assert build_phrase(frame) == (
        "Piedras en la calzada, carril derecho, a 2 kilómetros. Precaución."
    )


def test_low_confidence_adds_posible_prefix() -> None:
    frame = _frame(hazard=Hazard.ANIMAL, dist_km=3, confidence=Confidence.BAJA)
    assert build_phrase(frame) == ("Posible animal sobre la calzada, a 3 kilómetros. Precaución.")


def test_unspecified_lane_is_omitted() -> None:
    text = build_phrase(_frame(hazard=Hazard.BACHE, dist_km=2))
    assert text == "Bache en la calzada, a 2 kilómetros. Precaución."


def test_distance_here() -> None:
    text = build_phrase(_frame(hazard=Hazard.CONTROL, dist_km=0))
    assert text == "Control en la ruta, aquí mismo. Precaución."


def test_distance_singular_kilometre() -> None:
    text = build_phrase(_frame(hazard=Hazard.CURVA, dist_km=1))
    assert text == "Curva peligrosa, a 1 kilómetro. Precaución."


def test_distance_unknown_is_omitted() -> None:
    text = build_phrase(_frame(hazard=Hazard.HIELO, dist_km=255))
    assert text == "Hielo sobre la calzada. Precaución."


def test_urgency_detener_text() -> None:
    text = build_phrase(
        _frame(
            hazard=Hazard.ACCIDENTE,
            lane=Lane.TODA_LA_RUTA,
            dist_km=1,
            urgency=Urgency.DETENERSE,
        )
    )
    assert text == ("Accidente en la calzada, toda la ruta, a 1 kilómetro. Deténgase.")


def test_urgency_info_text() -> None:
    text = build_phrase(
        _frame(
            hazard=Hazard.DERRUMBE,
            lane=Lane.TODA_LA_RUTA,
            dist_km=0,
            urgency=Urgency.INFO,
        )
    )
    assert text == ("Derrumbe sobre la ruta, toda la ruta, aquí mismo. Solo informativo.")


def test_unknown_hazard_uses_generic_text() -> None:
    text = build_phrase(_frame(hazard=0xFE, dist_km=255))
    assert text == "Peligro no identificado. Precaución."


def test_unknown_lane_is_omitted() -> None:
    text = build_phrase(_frame(hazard=Hazard.PIEDRAS, lane=0xFE, dist_km=2))
    assert text == "Piedras en la calzada, a 2 kilómetros. Precaución."


def test_first_letter_is_capitalized() -> None:
    text = build_phrase(_frame(hazard=Hazard.PIEDRAS, dist_km=255))
    assert text[0].isupper()
