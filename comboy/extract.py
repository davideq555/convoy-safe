"""Extracción por reglas de carril, distancia y urgencia.

La identificación del peligro es semántica (embeddings), pero estos tres campos
son datos estructurados —números, direcciones, señales explícitas— y las reglas
son más exactas y auditables que cualquier modelo.

Las funciones reciben el texto **ya normalizado** por
:func:`comboy.normalize.normalize`, así que los números llegan como palabras
(``"dos kilometros"``) y no como dígitos.
"""

from __future__ import annotations

import math

from .codes import DIST_HERE, DIST_UNKNOWN, Lane, Urgency
from .normalize import CENTENAS, DECENAS, UNIDADES

__all__ = ["extract_distance", "extract_lane", "extract_urgency"]

#: Valor numérico de cada palabra-número que produce el normalizador. Se arma
#: desde los mismos diccionarios para que no puedan quedar desincronizados.
#: Las centenas guardan su índice (``1``..``9``), así que se reescalan a ``100``.
_VALOR: dict[str, int] = {palabra: valor for valor, palabra in UNIDADES.items()}
_VALOR.update({palabra: valor for valor, palabra in DECENAS.items()})
_VALOR.update({palabra: valor * 100 for valor, palabra in CENTENAS.items()})
_VALOR.setdefault("cien", 100)
_VALOR.setdefault("un", 1)
_VALOR.setdefault("una", 1)

#: Marcadores de "acá mismo": distancia cero.
_MARCADORES_CERO = ("aqui mismo", "aca mismo", "aca nomas", "en el medio")

#: Unidades de distancia, de mayor a menor, para no confundir "kilometros" con
#: "metros" cuando aparece la subcadena.
_UNIDADES_KM = ("kilometro", "kilometros")
_UNIDADES_M = ("metro", "metros")

#: Máximo de palabras hacia atrás que se miran para armar el número de una
#: distancia. Alcanza para "a dos kilometros" o "un kilometro y medio".
_VENTANA_NUMERO = 4

#: Señales que suben la urgencia a ``DETENERSE``.
_SENALES_DETENERSE = (
    "frena",
    "frenar",
    "frene",
    "frenen",
    "detenete",
    "detente",
    "detengase",
    "detenganse",
)

#: Marcadores que bajan la urgencia a ``INFO``.
#:
#: ``"aviso"`` solo no alcanza: ``"les aviso que hay piedras"`` es una advertencia
#: real, y bajarla a ``INFO`` la silenciaría. Hace falta el marcador explícito.
_MARCADORES_INFO = (
    "solo para avisar",
    "solo aviso",
    "solo informativo",
    "informativo",
)


def extract_lane(normalized: str) -> Lane:
    """Extrae el carril o la posición en la ruta.

    ``"calzada"`` sola **no** mapea a :attr:`Lane.CALZADA`: aparece en el texto
    de casi todos los peligros y no aporta información de posición. La posición
    se deja como :attr:`Lane.SIN_ESPECIFICAR`.
    """

    if "carril derecho" in normalized or "mano derecha" in normalized:
        return Lane.DERECHO
    if "carril izquierdo" in normalized or "mano izquierda" in normalized:
        return Lane.IZQUIERDO
    if "toda la ruta" in normalized or "toda la calzada" in normalized:
        return Lane.TODA_LA_RUTA
    if "banquina" in normalized:
        return Lane.BANQUINA
    return Lane.SIN_ESPECIFICAR


def _sumar_numero(palabras: list[str]) -> int | None:
    """Suma las palabras-número de ``palabras``, ignorando el resto.

    Devuelve ``None`` si no encontró ninguna. Alcanza para la gramática aditiva
    de las distancias del dominio (``"treinta y dos"``, ``"dos"``).
    """

    total = 0
    encontrado = False
    for palabra in palabras:
        if palabra == "y":
            continue
        if palabra.isdigit():
            total += int(palabra)
            encontrado = True
            continue
        valor = _VALOR.get(palabra)
        if valor is None:
            continue
        total += valor
        encontrado = True
    return total if encontrado else None


def _distancia_km(palabras: list[str]) -> float | None:
    """Devuelve la distancia en kilómetros mencionada, o ``None``.

    Unidades en metros se convierten a kilómetros para que el redondeo final las
    reduzca a ``0`` cuando quedan por debajo de 500 m.
    """

    for indice, palabra in enumerate(palabras):
        if palabra in _UNIDADES_KM:
            prefijo = palabras[max(0, indice - _VENTANA_NUMERO) : indice]
            valor = _sumar_numero(prefijo) or 0
            cierre = palabras[indice + 1 : indice + 3]
            if "medio" in cierre:
                valor += 0.5
            return float(valor)
        if palabra in _UNIDADES_M:
            prefijo = palabras[max(0, indice - _VENTANA_NUMERO) : indice]
            valor = _sumar_numero(prefijo)
            if valor is None:
                return None
            return valor / 1000.0
    return None


def extract_distance(normalized: str) -> int:
    """Extrae ``dist_km`` del texto normalizado (``0..15`` o ``255``).

    Prioridad: un marcador de "acá mismo" gana sobre cualquier número. Un valor
    que redondea fuera de ``0..15`` se considera desconocido.
    """

    if any(marcador in normalized for marcador in _MARCADORES_CERO):
        return DIST_HERE

    km = _distancia_km(normalized.split())
    if km is None:
        return DIST_UNKNOWN

    valor = math.floor(km + 0.5)
    if not 0 <= valor <= 15:
        return DIST_UNKNOWN
    return valor


def extract_urgency(normalized: str) -> Urgency:
    """Extrae la urgencia del texto normalizado.

    Por defecto ``PRECAUCION``. Sube a ``DETENERSE`` con una señal explícita y
    baja a ``INFO`` solo con un marcador explícito. La señal de detenerse gana
    sobre el marcador informativo si aparecen juntas.
    """

    palabras = normalized.split()
    if any(senal in palabras for senal in _SENALES_DETENERSE):
        return Urgency.DETENERSE
    if any(marcador in normalized for marcador in _MARCADORES_INFO):
        return Urgency.INFO
    # ``"para"`` es homógrafa: imperativo ("pará un momento") y preposición
    # ("cuánto falta para el cruce"). El imperativo encabeza la frase y la
    # preposición aparece en el medio, así que solo se mira el arranque.
    if "para" in palabras[:2]:
        return Urgency.DETENERSE
    return Urgency.PRECAUCION
