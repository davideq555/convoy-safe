"""Carga del corpus de frases de ejemplo por código de peligro.

El clasificador es semántico: compara la frase del conductor contra **frases
completas**, no contra un léxico de palabras sueltas. Enseñarle cobertura es
agregar frases, sin reentrenar nada.

Los datos ya **no viven en este módulo**: el corpus completo (4 a 6 frases por
código) está en ``datos/corpus.json`` y las frases reservadas para medir están
en ``datos/medicion.json``. Este módulo es el cargador del dominio y expone
:func:`cargar_corpus`, que lee la base y, si hay, fusiona el corpus extra
indicado por ``COMBOY_CORPUS_PATH``. El detalle del formato y las reglas de
error están en :mod:`comboy.datos`.
"""

from __future__ import annotations

from .datos import cargar_corpus

__all__ = ["cargar_corpus"]
