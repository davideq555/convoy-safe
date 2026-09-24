"""Tests del normalizador de texto en español."""

from __future__ import annotations

from convoy.normalize import digits_to_words, normalize, strip_accents


def test_baja_a_minusculas() -> None:
    assert normalize("Atención Comboy") == "atencion comboy"


def test_quita_tildes_y_ene() -> None:
    assert normalize("montaña, kilómetros, dieciséis") == "montana kilometros dieciseis"


def test_strip_accents_conserva_el_resto() -> None:
    assert strip_accents("áéíóúüñ") == "aeiouun"


def test_colapsa_espacios() -> None:
    assert normalize("  hay   muchas    piedras  ") == "hay muchas piedras"


def test_quita_puntuacion() -> None:
    assert normalize("¡hay piedras, cuidado!") == "hay piedras cuidado"


def test_digitos_a_palabras() -> None:
    assert normalize("faltan 2 kilómetros") == "faltan dos kilometros"


def test_decenas_a_palabras() -> None:
    assert normalize("hay 15 metros y 20 autos") == "hay quince metros y veinte autos"


def test_numeros_compuestos() -> None:
    assert normalize("faltan 34") == "faltan treinta y cuatro"


def test_centenas_a_palabras() -> None:
    assert normalize("a 200 metros") == "a doscientos metros"


def test_numeros_grandes_se_dejan_en_digitos() -> None:
    # El normalizador no es un conversor general: de 1000 para arriba deja el
    # número tal cual, porque no hay miles en el dominio de distancias.
    assert normalize("a 2000 metros") == "a 2000 metros"


def test_digits_to_words_no_toca_el_texto() -> None:
    assert digits_to_words("a 3 km") == "a tres km"
