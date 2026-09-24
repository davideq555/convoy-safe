"""Carga del corpus y de las frases de medición desde archivos JSON.

Los datos **no son código**: este módulo define el esquema y carga los archivos
en runtime. Agregar una frase de ejemplo es editar ``datos/corpus.json``, sin
tocar Python ni reentrenar nada.

El archivo base siempre se lee de :data:`DEFAULT_CORPUS_PATH` y
:data:`DEFAULT_MEDICION_PATH`. Sobre él se fusiona un **archivo extra** opcional,
cuya ruta se resuelve desde el entorno (:data:`CORPUS_PATH_VAR` y
:data:`MEDICION_PATH_VAR`): las frases del extra se agregan a las de la base, de
modo que el corpus versionado nunca se modifica.

Reglas de error (distintas a propósito):

* falta el archivo **base**: se registra ``datos.corpus``/``datos.medicion`` con
  ``result=base_ausente`` y se devuelve un conjunto vacío. El nodo sigue vivo y
  puede retransmitir alertas de otros, aunque no pueda crear las propias;
* falta el archivo **extra**: se ignora, con una línea ``info``;
* **JSON malformado**, estructura inesperada o **código de peligro inválido**:
  error duro (:class:`DatosInvalidos`). Es un bug del dato, no una condición de
  runtime: un hueco de cobertura invisible se convierte en un error visible.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .codes import Hazard
from .logging_setup import Logger
from .normalize import normalize

#: Variable de entorno con la ruta del corpus extra, o vacía si no hay.
CORPUS_PATH_VAR = "CONVOY_CORPUS_PATH"

#: Variable de entorno con la ruta de la medición extra, o vacía si no hay.
MEDICION_PATH_VAR = "CONVOY_MEDICION_PATH"

#: Corpus base, versionado con el repositorio, relativo al directorio de trabajo.
DEFAULT_CORPUS_PATH = Path("datos/corpus.json")

#: Frases de medición base, versionadas con el repositorio.
DEFAULT_MEDICION_PATH = Path("datos/medicion.json")


class DatosInvalidos(ValueError):
    """Un archivo de datos existe, pero su contenido es inválido."""


@dataclass(frozen=True)
class Medicion:
    """Frases reservadas para medir el clasificador.

    ``peligros`` son frases con un código conocido y ``ruido`` frases que no son
    peligro. Ninguna debería estar en el corpus: una frase del corpus se compara
    contra sí misma con similitud ``1.0`` y no mide nada.
    """

    peligros: dict[Hazard, list[str]]
    ruido: list[str]


#: Claves ya reportadas en este proceso, para no repetir la línea en cada carga.
_REPORTADOS: set[str] = set()


def _ruta_extra(variable: str) -> Path | None:
    """Ruta declarada por ``variable``, o ``None`` si no está definida o está vacía."""

    raw = os.environ.get(variable)
    if raw is None or not raw.strip():
        return None
    return Path(raw)


def ruta_corpus() -> Path | None:
    """Ruta del corpus **extra** declarada en el entorno, o ``None`` si no hay."""

    return _ruta_extra(CORPUS_PATH_VAR)


def ruta_medicion() -> Path | None:
    """Ruta de la medición **extra** declarada en el entorno, o ``None`` si no hay."""

    return _ruta_extra(MEDICION_PATH_VAR)


def _resolver_extra(variable: str) -> tuple[Path | None, Path | None]:
    """Devuelve ``(ruta declarada, ruta existente)`` para el archivo extra."""

    declarada = _ruta_extra(variable)
    if declarada is None:
        return None, None
    return declarada, declarada if declarada.exists() else None


def _reportar(logger: Logger | None, nivel: str, evento: str, clave: str, **campos: Any) -> None:
    """Emite una línea de log una sola vez por proceso, si hay logger."""

    if logger is None or clave in _REPORTADOS:
        return
    _REPORTADOS.add(clave)
    getattr(logger, nivel)(evento, **campos)


def _leer(path: Path) -> dict[str, Any]:
    """Lee un objeto JSON **crudo**, o lanza :class:`DatosInvalidos` con el motivo.

    Devuelve el objeto con las claves de metadatos (las que empiezan con ``_``)
    todavía adentro. ``_nota`` es documentación y las secciones la ignoran solas
    porque usan ``.get()``; ``_quitar`` sí se lee, para saber qué frases excluir.
    """

    try:
        with path.open("r", encoding="utf-8") as handle:
            datos = json.load(handle)
    except json.JSONDecodeError as exc:
        raise DatosInvalidos(f"JSON malformado en {path}: {exc}") from exc
    except OSError as exc:
        raise DatosInvalidos(f"no se pudo leer {path}: {exc}") from exc
    if not isinstance(datos, dict):
        raise DatosInvalidos(f"la raíz de {path} debe ser un objeto JSON")
    return datos


def _frases_a_quitar(datos: dict[str, Any], path: Path) -> set[str]:
    """Frases que el archivo pide excluir del resultado, en forma normalizada.

    La fusión **solo suma**, así que sin esto una frase de la base sería
    imposible de sacar sin editarla — y la base está pensada para no tocarse.
    Se comparan normalizadas, que es como el clasificador compara frases.
    """

    crudo = datos.get("_quitar", [])
    if not isinstance(crudo, list) or not all(isinstance(frase, str) for frase in crudo):
        raise DatosInvalidos(f"en {path}: '_quitar' debe ser una lista de textos")
    return {normalize(frase) for frase in crudo}


def _aplicar_quitas(frases: Iterable[str], quitar: set[str]) -> list[str]:
    """Descarta las frases cuya forma normalizada esté en ``quitar``."""

    if not quitar:
        return list(frases)
    return [frase for frase in frases if normalize(frase) not in quitar]


def _hazard(nombre: str, path: Path) -> Hazard:
    """Traduce un nombre de peligro a :class:`Hazard`, o lanza con los válidos."""

    try:
        return Hazard[nombre]
    except KeyError as exc:
        validos = ", ".join(miembro.name for miembro in Hazard)
        raise DatosInvalidos(
            f"en {path}: código de peligro inválido {nombre!r}; válidos: {validos}"
        ) from exc


def _peligros(datos: dict[str, Any], path: Path) -> dict[Hazard, list[str]]:
    """Valida y convierte la sección ``peligros`` de un archivo de datos."""

    crudo = datos.get("peligros", {})
    if not isinstance(crudo, dict):
        raise DatosInvalidos(f"en {path}: 'peligros' debe ser un objeto JSON")
    resultado: dict[Hazard, list[str]] = {}
    for nombre, frases in crudo.items():
        if not isinstance(nombre, str):
            raise DatosInvalidos(f"en {path}: las claves de 'peligros' deben ser textos")
        if not isinstance(frases, list) or not all(isinstance(frase, str) for frase in frases):
            raise DatosInvalidos(
                f"en {path}: las frases de {nombre!r} deben ser una lista de textos"
            )
        resultado[_hazard(nombre, path)] = list(frases)
    return resultado


def _ruido(datos: dict[str, Any], path: Path) -> list[str]:
    """Valida y convierte la sección ``ruido`` de un archivo de datos."""

    crudo = datos.get("ruido", [])
    if not isinstance(crudo, list) or not all(isinstance(frase, str) for frase in crudo):
        raise DatosInvalidos(f"en {path}: 'ruido' debe ser una lista de textos")
    return list(crudo)


def _frases_unicas(frases: Iterable[str]) -> list[str]:
    """Quita frases repetidas comparando por su forma normalizada, y conserva el orden."""

    vistas: set[str] = set()
    unicas: list[str] = []
    for frase in frases:
        clave = normalize(frase)
        if clave in vistas:
            continue
        vistas.add(clave)
        unicas.append(frase)
    return unicas


def _fusionar_peligros(
    base: dict[Hazard, list[str]], extra: dict[Hazard, list[str]]
) -> dict[Hazard, list[str]]:
    """Agrega las frases del extra a las de la base, sin repetir."""

    fusionados: dict[Hazard, list[str]] = {hazard: list(frases) for hazard, frases in base.items()}
    for hazard, frases in extra.items():
        fusionados[hazard] = fusionados.get(hazard, []) + list(frases)
    return {hazard: _frases_unicas(frases) for hazard, frases in fusionados.items()}


@lru_cache(maxsize=1)
def _corpus_fusionado(base: str, extra: str | None) -> dict[Hazard, list[str]]:
    peligros = _peligros(_leer(Path(base)), Path(base))
    if extra is None:
        return _fusionar_peligros(peligros, {})
    extra_datos = _leer(Path(extra))
    fusionado = _fusionar_peligros(peligros, _peligros(extra_datos, Path(extra)))
    quitar = _frases_a_quitar(extra_datos, Path(extra))
    if not quitar:
        return fusionado
    return {hazard: _aplicar_quitas(frases, quitar) for hazard, frases in fusionado.items()}


@lru_cache(maxsize=1)
def _medicion_fusionada(base: str, extra: str | None) -> Medicion:
    base_datos = _leer(Path(base))
    peligros = _peligros(base_datos, Path(base))
    ruido = _ruido(base_datos, Path(base))
    if extra is None:
        return Medicion(peligros=peligros, ruido=ruido)
    extra_datos = _leer(Path(extra))
    quitar = _frases_a_quitar(extra_datos, Path(extra))
    peligros = _fusionar_peligros(peligros, _peligros(extra_datos, Path(extra)))
    ruido = _frases_unicas([*ruido, *_ruido(extra_datos, Path(extra))])
    if not quitar:
        return Medicion(peligros=peligros, ruido=ruido)
    return Medicion(
        peligros={hazard: _aplicar_quitas(frases, quitar) for hazard, frases in peligros.items()},
        ruido=_aplicar_quitas(ruido, quitar),
    )


def cargar_corpus(logger: Logger | None = None) -> dict[Hazard, list[str]]:
    """Carga el corpus fusionado (base + extra), cacheado.

    Falta la base: registra un error y devuelve ``{}`` sin lanzar. Falta el
    extra: se ignora. Un JSON malformado o un peligro inválido lanzan
    :class:`DatosInvalidos`.
    """

    base = DEFAULT_CORPUS_PATH
    if not base.exists():
        _reportar(
            logger,
            "error",
            "datos.corpus",
            f"corpus:{base}",
            result="base_ausente",
            path=str(base),
        )
        return {}

    declarada, existente = _resolver_extra(CORPUS_PATH_VAR)
    corpus = _corpus_fusionado(str(base), str(existente) if existente else None)
    _reportar(
        logger,
        "info",
        "datos.corpus",
        f"corpus:{base}:{existente}",
        peligros=len(corpus),
        frases=sum(len(frases) for frases in corpus.values()),
        extra=str(existente) if existente else "-",
        result="extra_ausente" if declarada is not None and existente is None else "ok",
    )
    return corpus


def cargar_medicion(logger: Logger | None = None) -> Medicion:
    """Carga las frases de medición fusionadas (base + extra), cacheadas.

    Falta la base: registra un error y devuelve una medición vacía sin lanzar.
    Falta el extra: se ignora. Un contenido inválido lanza :class:`DatosInvalidos`.
    """

    base = DEFAULT_MEDICION_PATH
    if not base.exists():
        _reportar(
            logger,
            "error",
            "datos.medicion",
            f"medicion:{base}",
            result="base_ausente",
            path=str(base),
        )
        return Medicion(peligros={}, ruido=[])

    declarada, existente = _resolver_extra(MEDICION_PATH_VAR)
    medicion = _medicion_fusionada(str(base), str(existente) if existente else None)
    _reportar(
        logger,
        "info",
        "datos.medicion",
        f"medicion:{base}:{existente}",
        peligros=len(medicion.peligros),
        ruido=len(medicion.ruido),
        extra=str(existente) if existente else "-",
        result="extra_ausente" if declarada is not None and existente is None else "ok",
    )
    return medicion


def limpiar_cache() -> None:
    """Invalida las cachés del cargador. Pensado para los tests."""

    _corpus_fusionado.cache_clear()
    _medicion_fusionada.cache_clear()
    _REPORTADOS.clear()


__all__ = [
    "CORPUS_PATH_VAR",
    "DEFAULT_CORPUS_PATH",
    "DEFAULT_MEDICION_PATH",
    "MEDICION_PATH_VAR",
    "DatosInvalidos",
    "Medicion",
    "cargar_corpus",
    "cargar_medicion",
    "limpiar_cache",
    "ruta_corpus",
    "ruta_medicion",
]
