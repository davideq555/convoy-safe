"""Normalización de texto en español para el clasificador semántico.

El clasificador compara una frase del conductor contra frases de ejemplo. Antes
de comparar conviene borrar las diferencias que no aportan significado:

* mayúsculas y minúsculas,
* tildes y diéresis (y la tilde de la ``ñ``, que se reduce a ``n``),
* puntuación,
* espacios repetidos,
* números escritos con dígitos, que pasan a palabras (``"2 kilómetros"`` se
  convierte en ``"dos kilometros"``).

La puerta de entrada es :func:`normalize`. :func:`strip_accents` y
:func:`digits_to_words` se exponen por separado porque también sirven para
diagnóstico y pruebas puntuales.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["digits_to_words", "normalize", "strip_accents"]

#: Palabras de ``0`` a ``29`` en español.
UNIDADES: dict[int, str] = {
    0: "cero",
    1: "uno",
    2: "dos",
    3: "tres",
    4: "cuatro",
    5: "cinco",
    6: "seis",
    7: "siete",
    8: "ocho",
    9: "nueve",
    10: "diez",
    11: "once",
    12: "doce",
    13: "trece",
    14: "catorce",
    15: "quince",
    16: "dieciseis",
    17: "diecisiete",
    18: "dieciocho",
    19: "diecinueve",
    20: "veinte",
    21: "veintiuno",
    22: "veintidos",
    23: "veintitres",
    24: "veinticuatro",
    25: "veinticinco",
    26: "veintiseis",
    27: "veintisiete",
    28: "veintiocho",
    29: "veintinueve",
}

#: Decenas exactas (``30``..``90``).
DECENAS: dict[int, str] = {
    30: "treinta",
    40: "cuarenta",
    50: "cincuenta",
    60: "sesenta",
    70: "setenta",
    80: "ochenta",
    90: "noventa",
}

#: Centenas exactas a partir de ``200``. El ``100`` exacto se maneja aparte
#: (``cien``) porque ``ciento`` solo aparece en las composiciones.
CENTENAS: dict[int, str] = {
    1: "ciento",
    2: "doscientos",
    3: "trescientos",
    4: "cuatrocientos",
    5: "quinientos",
    6: "seiscientos",
    7: "setecientos",
    8: "ochocientos",
    9: "novecientos",
}

#: Máximo entero que se convierte a palabras. De ahí para arriba se deja el
#: número tal cual: no aportan al dominio (distancias de 0 a 15 km) y evitan
#: arrastrar la gramática de los miles.
MAX_NUMERO_EN_PALABRAS = 999

_DIGITS_RE = re.compile(r"\d+")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def _int_to_words(value: int) -> str:
    """Convierte ``value`` a palabras en español, hasta :data:`MAX_NUMERO_EN_PALABRAS`.

    Un valor fuera de rango se devuelve como dígitos: el normalizador no es un
    conversor numérico general.
    """

    if not 0 <= value <= MAX_NUMERO_EN_PALABRAS:
        return str(value)
    if value < 30:
        return UNIDADES[value]
    if value < 100:
        decena = (value // 10) * 10
        resto = value % 10
        if resto == 0:
            return DECENAS[decena]
        return f"{DECENAS[decena]} y {UNIDADES[resto]}"

    centena = value // 100
    resto = value % 100
    if centena == 1 and resto == 0:
        return "cien"
    palabra = CENTENAS[centena]
    if resto == 0:
        return palabra
    return f"{palabra} {_int_to_words(resto)}"


def strip_accents(text: str) -> str:
    """Quita las marcas diacríticas (tildes, diéresis) de ``text``.

    Se descompone en ``NFD`` —cada letra acentuada pasa a letra base más una
    marca combinante— y se descartan las marcas. La ``ñ`` se reduce a ``n``.
    """

    decomposed = unicodedata.normalize("NFD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def digits_to_words(text: str) -> str:
    """Reemplaza cada corrida de dígitos de ``text`` por su forma en palabras."""

    return _DIGITS_RE.sub(lambda match: _int_to_words(int(match.group())), text)


def normalize(text: str) -> str:
    """Normaliza ``text`` para el clasificador.

    Aplica, en orden: minúsculas, sin tildes, números a palabras, puntuación a
    espacios y colapso de espacios. El resultado siempre tiene palabras
    separadas por un único espacio y no tiene espacios al borde.
    """

    lowered = strip_accents(text.lower())
    with_words = digits_to_words(lowered)
    cleaned = _PUNCT_RE.sub(" ", with_words)
    return " ".join(cleaned.split())
