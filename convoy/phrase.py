"""Construye la frase hablada de TTS a partir de una trama decodificada.

La frase empieza directamente con el peligro: el receptor ya no anuncia un
prefijo de TTS "Atención comboy". Esa frase sigue siendo la wake word, que el
conductor dice al micrófono, no algo que el parlante pronuncie.

Formato (docs/06-codigos-y-logs.md)::

    ["Posible " si confidence == BAJA] + texto del peligro
    + [", " + texto del carril, salvo si lane es SIN_ESPECIFICAR]
    + cláusula de distancia
    + ". " + texto de urgencia

Los textos del catálogo van en minúscula; el primer carácter de la frase
ensamblada se capitaliza aquí.

Cláusula de distancia:

* ``dist_km == 0``   -> ``", aquí mismo"``
* ``dist_km == 1``   -> ``", a 1 kilómetro"``
* ``2..15``          -> ``", a N kilómetros"``
* ``255`` (desconocida)  -> se omite por completo

Ejemplo verificado de docs/06: con PIEDRAS / DERECHO / 2 km / PRECAUCION /
ALTA la frase es exactamente
``"Piedras en la calzada, carril derecho, a 2 kilómetros. Precaución."``
"""

from __future__ import annotations

from .codes import (
    DIST_HERE,
    DIST_UNKNOWN,
    HAZARD_TTS,
    LANE_TTS,
    URGENCY_TTS,
    Confidence,
    Lane,
    as_confidence,
    as_hazard,
    as_lane,
    as_urgency,
)
from .frame import AlertFrame

LOW_CONFIDENCE_PREFIX = "Posible "


def _distance_clause(dist_km: int) -> str:
    if dist_km == DIST_UNKNOWN:
        return ""
    if dist_km == DIST_HERE:
        return ", aquí mismo"
    if dist_km == 1:
        return ", a 1 kilómetro"
    return f", a {dist_km} kilómetros"


def build_phrase(frame: AlertFrame) -> str:
    """Renderiza la frase de advertencia completa en español para ``frame``."""

    hazard = as_hazard(frame.hazard)
    lane = as_lane(frame.lane)
    confidence = as_confidence(frame.confidence)
    urgency = as_urgency(frame.urgency)

    parts: list[str] = []
    if confidence is Confidence.BAJA:
        parts.append(LOW_CONFIDENCE_PREFIX)
    parts.append(HAZARD_TTS[hazard])

    if lane is not Lane.SIN_ESPECIFICAR:
        parts.append(", ")
        parts.append(LANE_TTS[lane])

    parts.append(_distance_clause(frame.dist_km))
    parts.append(". ")
    parts.append(URGENCY_TTS[urgency])

    phrase = "".join(parts)
    # Los textos del catálogo van en minúscula, así que la oración empezaría en
    # minúscula ahora que el antiguo prefijo "Atención comboy: " ya no está.
    return phrase[:1].upper() + phrase[1:]


__all__ = ["LOW_CONFIDENCE_PREFIX", "build_phrase"]
