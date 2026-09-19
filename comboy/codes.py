"""Catálogo de códigos del protocolo (ver docs/06-codigos-y-logs.md).

Los identificadores de dominio se mantienen en español porque así los definen
los documentos de diseño (PIEDRAS, DERECHO, PRECAUCION, ...): son constantes
del protocolo, no prosa. El resto de la prosa del proyecto también va en
español.
"""

from __future__ import annotations

from enum import IntEnum


class MsgType(IntEnum):
    """Tipo de mensaje llevado en el byte 1 de una trama."""

    ALERTA = 1
    HEARTBEAT = 2
    JOIN = 3
    LEAVE = 4


class Role(IntEnum):
    """Rol del emisor original llevado en ``origin_role``."""

    LIDER = 0
    SEGUIDOR = 1


#: Representación de cada rol en logs/config (el archivo de config usa nombres en inglés).
ROLE_NAMES: dict[Role, str] = {
    Role.LIDER: "leader",
    Role.SEGUIDOR: "follower",
}

#: Búsqueda inversa usada al parsear la config YAML.
ROLE_BY_NAME: dict[str, Role] = {
    "leader": Role.LIDER,
    "follower": Role.SEGUIDOR,
}


class Hazard(IntEnum):
    """Catálogo de peligros. Quedan 240 valores libres para peligros futuros."""

    DESCONOCIDO = 0x00
    ACCIDENTE = 0x01
    PIEDRAS = 0x02
    ANIMAL = 0x03
    PEATON = 0x04
    VEHICULO_DETENIDO = 0x05
    BACHE = 0x06
    OBRA = 0x07
    CONTROL = 0x08
    NIEBLA = 0x09
    LLUVIA = 0x0A
    HIELO = 0x0B
    DERRUMBE = 0x0C
    CURVA = 0x0D
    CONTRAMANO = 0x0E


class Lane(IntEnum):
    """Catálogo de carril / posición en la ruta."""

    SIN_ESPECIFICAR = 0x00
    IZQUIERDO = 0x01
    DERECHO = 0x02
    TODA_LA_RUTA = 0x03
    BANQUINA = 0x04
    CALZADA = 0x05


class Urgency(IntEnum):
    """Catálogo de urgencia, ascendente en severidad (valor mayor = más urgente)."""

    INFO = 0x00
    PRECAUCION = 0x01
    DETENERSE = 0x02


class Confidence(IntEnum):
    """Catálogo de confianza de la clasificación."""

    BAJA = 0x00
    ALTA = 0x01


#: Texto de TTS para cada peligro, tomado de docs/06-codigos-y-logs.md.
HAZARD_TTS: dict[Hazard, str] = {
    Hazard.DESCONOCIDO: "peligro no identificado",
    Hazard.ACCIDENTE: "accidente en la calzada",
    Hazard.PIEDRAS: "piedras en la calzada",
    Hazard.ANIMAL: "animal sobre la calzada",
    Hazard.PEATON: "persona sobre la ruta",
    Hazard.VEHICULO_DETENIDO: "vehículo detenido en la ruta",
    Hazard.BACHE: "bache en la calzada",
    Hazard.OBRA: "obra en la ruta",
    Hazard.CONTROL: "control en la ruta",
    Hazard.NIEBLA: "baja visibilidad por niebla",
    Hazard.LLUVIA: "calzada resbaladiza por lluvia",
    Hazard.HIELO: "hielo sobre la calzada",
    Hazard.DERRUMBE: "derrumbe sobre la ruta",
    Hazard.CURVA: "curva peligrosa",
    Hazard.CONTRAMANO: "vehículo en contramano",
}

#: Texto de TTS para cada carril. Un carril sin especificar se omite de la frase.
LANE_TTS: dict[Lane, str] = {
    Lane.SIN_ESPECIFICAR: "",
    Lane.IZQUIERDO: "carril izquierdo",
    Lane.DERECHO: "carril derecho",
    Lane.TODA_LA_RUTA: "toda la ruta",
    Lane.BANQUINA: "sobre la banquina",
    Lane.CALZADA: "sobre la calzada",
}

#: Texto de TTS para cada nivel de urgencia.
URGENCY_TTS: dict[Urgency, str] = {
    Urgency.INFO: "Solo informativo.",
    Urgency.PRECAUCION: "Precaución.",
    Urgency.DETENERSE: "Deténgase.",
}

#: Valores centinela de ``dist_km``.
DIST_HERE = 0
DIST_UNKNOWN = 255


def _coerce(enum_type: type[IntEnum], value: int, default: IntEnum) -> IntEnum:
    """Devuelve el miembro del enum para ``value``, o ``default`` si es desconocido.

    El formato de cable es un catálogo cerrado, pero un par que corra un
    catálogo más nuevo (o una trama corrupta pero con CRC válido) nunca debe
    tumbar este nodo.
    """

    try:
        return enum_type(value)
    except ValueError:
        return default


def as_hazard(value: int) -> Hazard:
    return _coerce(Hazard, value, Hazard.DESCONOCIDO)  # type: ignore[return-value]


def as_lane(value: int) -> Lane:
    return _coerce(Lane, value, Lane.SIN_ESPECIFICAR)  # type: ignore[return-value]


def as_urgency(value: int) -> Urgency:
    # Por defecto el nivel medio: una urgencia desconocida no debe ni quedar en
    # silencio (INFO) ni escalar a una alarma (DETENERSE), así que PRECAUCION es
    # el respaldo seguro y conservador.
    return _coerce(Urgency, value, Urgency.PRECAUCION)  # type: ignore[return-value]


def as_confidence(value: int) -> Confidence:
    return _coerce(Confidence, value, Confidence.BAJA)  # type: ignore[return-value]


def role_from_name(name: str) -> Role:
    """Parsea un nombre de rol de config (``leader``/``follower``) a un :class:`Role`."""

    try:
        return ROLE_BY_NAME[name.strip().lower()]
    except KeyError as exc:
        raise ValueError(f"rol desconocido: {name!r} (se esperaba 'leader' o 'follower')") from exc


__all__ = [
    "DIST_HERE",
    "DIST_UNKNOWN",
    "HAZARD_TTS",
    "LANE_TTS",
    "ROLE_BY_NAME",
    "ROLE_NAMES",
    "URGENCY_TTS",
    "Confidence",
    "Hazard",
    "Lane",
    "MsgType",
    "Role",
    "Urgency",
    "as_confidence",
    "as_hazard",
    "as_lane",
    "as_urgency",
    "role_from_name",
]
