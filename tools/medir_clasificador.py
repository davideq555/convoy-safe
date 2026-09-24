"""Arnés de medición de la calidad del clasificador sobre frases reservadas.

Este instrumento responde **cuánto** acierta el clasificador, no *sí/no*. La
validación funcional (nivel L1, ``python -m convoy text``) clasifica una frase y
pasa o falla; la medición clasifica **todas** las frases reservadas de
``datos/medicion.json`` y devuelve un porcentaje y un puñado de conteos.

Vive en ``tools/`` y no en ``tests/`` a propósito:

* ``tests/conftest.py`` borra las variables ``CONVOY_*`` en cada test, así que
  un arnés dentro de la suite no podría configurarse por entorno;
* ``pyproject.toml`` agrega ``-q`` a pytest, que silenciaría justamente el
  reporte que este instrumento produce.

La lógica de cálculo (``calcular_resumen``) es pura y se prueba sin red; la
única parte que toca Ollama es la clasificación en sí.

Uso::

    python tools/medir_clasificador.py
    python tools/medir_clasificador.py --url http://eevee.local:11434
    python tools/medir_clasificador.py --min-similarity 0.75
    python tools/medir_clasificador.py --json

Códigos de salida: ``0`` si no hay errores confiados ni falsos positivos, ``1``
si los hay, ``2`` si el instrumento no pudo medir (datos ilegibles o servicio de
embeddings caído). Un problema del instrumento nunca se cuenta como error
confiado del clasificador.
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

# Al correr ``python tools/medir_clasificador.py``, ``sys.path[0]`` es ``tools/``
# y no la raíz del repositorio, así que ``convoy`` no sería importable. Se agrega
# la raíz antes de importar el paquete. Los imports de abajo llevan E402 (import
# fuera del encabezado) a propósito, por este ajuste.
_RAIZ_DEL_REPOSITORIO = Path(__file__).resolve().parent.parent
if str(_RAIZ_DEL_REPOSITORIO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_DEL_REPOSITORIO))

from convoy.classify import Classification, classify
from convoy.codes import Confidence, Hazard
from convoy.config import EmbeddingConfig, load_config
from convoy.datos import DatosInvalidos, Medicion, cargar_medicion
from convoy.embedding import EmbeddingClient, EmbeddingUnavailable, create_embedding_client
from convoy.logging_setup import Logger

#: Ancho con el que se alinea la etiqueta de cada línea de detalle.
ANCHO_ETIQUETA = 14

#: Frase mínima con la que se comprueba que el servicio de embeddings responde.
FRASE_DE_PRUEBA = "prueba de conexión"

#: Cliente de embeddings que sí entiende español; cualquier otro no mide nada.
KIND_MEDIBLE = "ollama"


@dataclass(frozen=True)
class Observacion:
    """Resultado de clasificar una frase de medición.

    ``esperado`` es el peligro anotado en ``datos/medicion.json``, o ``None`` si
    la frase es de ruido. El resto son los campos del :class:`Classification`
    que el reporte necesita.
    """

    frase: str
    esperado: Hazard | None
    hazard: Hazard
    confidence: Confidence
    similarity: float
    margin: float


@dataclass(frozen=True)
class Resumen:
    """Conteo de las métricas de la medición, más los extremos de similitud."""

    total_peligros: int
    total_ruido: int
    aciertos: int
    abstenciones: int
    fallos: int
    errores_confiados: int
    falsos_positivos: int
    ruido_dudoso: int
    min_similitud_aciertos: float | None
    max_similitud_ruido: float | None

    @property
    def tasa_aciertos(self) -> float:
        """Proporción de frases de peligro con el código correcto (0..1)."""

        if self.total_peligros == 0:
            return 0.0
        return self.aciertos / self.total_peligros

    @property
    def calibracion(self) -> float | None:
        """Separación entre el peor acierto y el ruido más parecido a un peligro.

        Positiva: existe un umbral de similitud que deja pasar todos los
        aciertos y rechaza todo el ruido. Negativa: los dos conjuntos se solapan
        y ningún umbral los separa. ``None`` cuando falta alguno de los dos
        extremos.
        """

        if self.min_similitud_aciertos is None or self.max_similitud_ruido is None:
            return None
        return self.min_similitud_aciertos - self.max_similitud_ruido

    def requiere_fallo(self) -> bool:
        """``True`` si hay errores confiados o falsos positivos."""

        return self.errores_confiados > 0 or self.falsos_positivos > 0

    def a_dict(self) -> dict[str, Any]:
        """El resumen como diccionario listo para serializar a JSON."""

        calibracion = self.calibracion
        return {
            "total_peligros": self.total_peligros,
            "total_ruido": self.total_ruido,
            "aciertos": self.aciertos,
            "abstenciones": self.abstenciones,
            "fallos": self.fallos,
            "errores_confiados": self.errores_confiados,
            "falsos_positivos": self.falsos_positivos,
            "ruido_dudoso": self.ruido_dudoso,
            "tasa_aciertos": round(self.tasa_aciertos, 4),
            "calibracion": None if calibracion is None else round(calibracion, 4),
            "min_similitud_aciertos": self.min_similitud_aciertos,
            "max_similitud_ruido": self.max_similitud_ruido,
        }


def calcular_resumen(observaciones: Iterable[Observacion]) -> Resumen:
    """Calcula las métricas a partir de las observaciones.

    Función pura: no toca red, archivos ni reloj. Las reglas son las del
    invariante del clasificador:

    * una **abstención** es decir ``DESCONOCIDO`` ante un peligro real: no es un
      fallo, es el respaldo seguro;
    * un **error confiado** es un código equivocado con confianza ``ALTA``;
    * un **falso positivo** es una frase de ruido clasificada como peligro con
      confianza ``ALTA``;
    * un peligro con confianza ``BAJA`` sobre ruido se cuenta aparte como
      ``ruido_dudoso``: avisa, pero no dispara el fallo del instrumento.
    """

    total_peligros = 0
    total_ruido = 0
    aciertos = 0
    abstenciones = 0
    fallos = 0
    errores_confiados = 0
    falsos_positivos = 0
    ruido_dudoso = 0
    similitudes_aciertos: list[float] = []
    similitudes_ruido: list[float] = []

    for observacion in observaciones:
        if observacion.esperado is not None:
            total_peligros += 1
            if observacion.hazard == observacion.esperado:
                aciertos += 1
                similitudes_aciertos.append(observacion.similarity)
            elif observacion.hazard == Hazard.DESCONOCIDO:
                abstenciones += 1
            else:
                fallos += 1
                if observacion.confidence == Confidence.ALTA:
                    errores_confiados += 1
        else:
            total_ruido += 1
            similitudes_ruido.append(observacion.similarity)
            if observacion.hazard != Hazard.DESCONOCIDO:
                if observacion.confidence == Confidence.ALTA:
                    falsos_positivos += 1
                else:
                    ruido_dudoso += 1

    return Resumen(
        total_peligros=total_peligros,
        total_ruido=total_ruido,
        aciertos=aciertos,
        abstenciones=abstenciones,
        fallos=fallos,
        errores_confiados=errores_confiados,
        falsos_positivos=falsos_positivos,
        ruido_dudoso=ruido_dudoso,
        min_similitud_aciertos=min(similitudes_aciertos) if similitudes_aciertos else None,
        max_similitud_ruido=max(similitudes_ruido) if similitudes_ruido else None,
    )


def _etiqueta(observacion: Observacion) -> str:
    """Etiqueta corta que resume el veredicto de una observación."""

    if observacion.esperado is not None:
        if observacion.hazard == observacion.esperado:
            return "ok"
        if observacion.hazard == Hazard.DESCONOCIDO:
            return "ABSTIENE"
        return "FALLA"
    if observacion.hazard == Hazard.DESCONOCIDO:
        return "ok ruido"
    if observacion.confidence == Confidence.ALTA:
        return "FALSO POSITIVO"
    return "RUIDO DUDOSO"


def formatear_observacion(observacion: Observacion) -> str:
    """Devuelve la línea de detalle de una observación, sin salto de línea."""

    etiqueta = _etiqueta(observacion)
    frase = f"'{observacion.frase}'"
    similitud = f"{observacion.similarity:.3f}"

    if observacion.esperado is not None:
        esperado = observacion.esperado.name
        if observacion.hazard == observacion.esperado:
            detalle = (
                f"{frase} -> {observacion.hazard.name} "
                f"({similitud}, margen {observacion.margin:+.3f}, "
                f"{observacion.confidence.name})"
            )
        elif observacion.hazard == Hazard.DESCONOCIDO:
            detalle = f"{frase} ({similitud})  esperado {esperado}"
        else:
            detalle = (
                f"{frase} -> {observacion.hazard.name} "
                f"({similitud}, {observacion.confidence.name})  esperado {esperado}"
            )
    elif observacion.hazard == Hazard.DESCONOCIDO:
        detalle = f"{frase} (max {similitud})"
    else:
        detalle = (
            f"{frase} -> {observacion.hazard.name} ({similitud}, {observacion.confidence.name})"
        )

    return f"  {etiqueta:<{ANCHO_ETIQUETA}}  {detalle}"


def _formatear_calibracion(resumen: Resumen) -> str:
    """Texto de la métrica de calibración, con sus dos extremos."""

    calibracion = resumen.calibracion
    if calibracion is None:
        return "sin datos suficientes"
    return (
        f"{calibracion:+.3f}  (mínimo de aciertos {resumen.min_similitud_aciertos:.3f} - "
        f"máximo de ruido {resumen.max_similitud_ruido:.3f})"
    )


def _lectura_aciertos(resumen: Resumen) -> str:
    """Lectura de la tasa de aciertos según la tabla de docs/09."""

    if resumen.total_peligros == 0:
        return "sin frases de peligro: no hay nada que medir"
    if resumen.tasa_aciertos >= 0.90:
        return "aciertos >= 90%: listo para la ruta"
    if resumen.tasa_aciertos >= 0.75:
        return "aciertos 75-90%: aceptable para el MVP; seguir agregando frases"
    return "aciertos < 75%: el corpus o el modelo no alcanzan"


def _lectura_errores(resumen: Resumen) -> str:
    """Lectura de la métrica que manda: errores confiados y falsos positivos."""

    if resumen.requiere_fallo():
        return (
            f"FALLA: {resumen.errores_confiados} errores confiados y "
            f"{resumen.falsos_positivos} falsos positivos; "
            "el sistema le mentiría al conductor con seguridad"
        )
    return "OK: sin errores confiados ni falsos positivos"


def formatear_resumen(resumen: Resumen) -> str:
    """Devuelve el resumen completo, sin salto de línea final."""

    lineas = [
        "",
        "Resumen",
        f"  frases de peligro : {resumen.total_peligros}",
        f"  frases de ruido   : {resumen.total_ruido}",
        f"  aciertos          : {resumen.aciertos} ({resumen.tasa_aciertos:.1%})",
        f"  abstenciones      : {resumen.abstenciones}",
        f"  fallos            : {resumen.fallos}",
        f"  errores confiados : {resumen.errores_confiados}",
        f"  falsos positivos  : {resumen.falsos_positivos}",
        f"  calibración       : {_formatear_calibracion(resumen)}",
    ]
    if resumen.ruido_dudoso:
        lineas.append(
            f"  ruido dudoso      : {resumen.ruido_dudoso} "
            "(peligro con confianza BAJA; no cuenta como falso positivo)"
        )
    lineas += ["", f"  {_lectura_aciertos(resumen)}", f"  {_lectura_errores(resumen)}"]
    return "\n".join(lineas)


def _observacion(frase: str, esperado: Hazard | None, resultado: Classification) -> Observacion:
    """Adapta el resultado del clasificador a una observación del reporte."""

    return Observacion(
        frase=frase,
        esperado=esperado,
        hazard=resultado.hazard,
        confidence=resultado.confidence,
        similarity=resultado.similarity,
        margin=resultado.margin,
    )


def _clasificar_medicion(
    medicion: Medicion,
    client: EmbeddingClient,
    embedding: EmbeddingConfig,
    logger: Logger,
) -> list[Observacion]:
    """Clasifica todas las frases reservadas: primero peligros, después ruido."""

    observaciones: list[Observacion] = []
    for hazard, frases in medicion.peligros.items():
        for frase in frases:
            observaciones.append(
                _observacion(frase, hazard, classify(frase, client, embedding, logger))
            )
    for frase in medicion.ruido:
        observaciones.append(_observacion(frase, None, classify(frase, client, embedding, logger)))
    return observaciones


def _encabezado(medicion: Medicion, embedding: EmbeddingConfig) -> str:
    """Bloque inicial con lo que se va a medir y con qué configuración."""

    total_peligros = sum(len(frases) for frases in medicion.peligros.values())
    cache = embedding.cache_path or "deshabilitado"
    return (
        f"Medición del clasificador - {total_peligros} frases de peligro, "
        f"{len(medicion.ruido)} de ruido\n"
        f"  embedding : {embedding.kind} {embedding.model} en {embedding.url}\n"
        f"  umbrales  : min_similarity={embedding.min_similarity} "
        f"min_margin={embedding.min_margin} caché={cache}\n"
        "Detalle por frase:"
    )


def _resolver_embedding(args: argparse.Namespace, base: EmbeddingConfig) -> EmbeddingConfig:
    """Aplica los overrides de la línea de comandos sobre la config de embeddings."""

    embedding = base
    if args.url:
        embedding = replace(embedding, url=args.url)
    if args.model:
        embedding = replace(embedding, model=args.model)
    if args.min_similarity is not None:
        embedding = replace(embedding, min_similarity=args.min_similarity)
    if args.min_margin is not None:
        embedding = replace(embedding, min_margin=args.min_margin)
    if args.sin_cache:
        # Cadena vacía: el clasificador reconstruye el índice siempre.
        embedding = replace(embedding, cache_path="")
    return embedding


def _parsear_argumentos(argv: Sequence[str] | None) -> argparse.Namespace:
    """Construye el parser del arnés y parsea ``argv``."""

    parser = argparse.ArgumentParser(
        prog="python tools/medir_clasificador.py",
        description="Mide la calidad del clasificador semántico sobre las frases reservadas.",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="sobrescribe embedding.url (por defecto, el de la configuración)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="sobrescribe embedding.model (por defecto, el de la configuración)",
    )
    parser.add_argument(
        "--min-similarity",
        type=float,
        default=None,
        help="sobrescribe embedding.min_similarity para calibrar sin tocar archivos",
    )
    parser.add_argument(
        "--min-margin",
        type=float,
        default=None,
        help="sobrescribe embedding.min_margin para calibrar sin tocar archivos",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="imprime solo el resumen como JSON y suprime el detalle por frase",
    )
    parser.add_argument(
        "--sin-cache",
        action="store_true",
        help="deshabilita el caché en disco y mide desde cero",
    )
    return parser.parse_args(argv)


def _validar_umbrales(args: argparse.Namespace) -> str | None:
    """Valida los umbrales de la línea de comandos; devuelve el error o ``None``."""

    for nombre, valor in (
        ("--min-similarity", args.min_similarity),
        ("--min-margin", args.min_margin),
    ):
        if valor is not None and not 0.0 <= valor <= 1.0:
            return f"{nombre} debe estar en 0..1, se obtuvo {valor}"
    return None


def main(argv: Sequence[str] | None = None) -> int:
    """Corre la medición y devuelve el código de salida del proceso."""

    args = _parsear_argumentos(argv)

    error_umbral = _validar_umbrales(args)
    if error_umbral is not None:
        print(f"error: {error_umbral}", file=sys.stderr)
        return 2

    logger = Logger(node_id=1, role="follower", level="error")
    try:
        try:
            medicion = cargar_medicion(logger)
        except DatosInvalidos as exc:
            print(f"error: no se pudieron leer las frases de medición: {exc}", file=sys.stderr)
            return 2

        if not medicion.peligros and not medicion.ruido:
            print("error: no hay frases de medición en datos/medicion.json", file=sys.stderr)
            return 2

        embedding = _resolver_embedding(args, load_config(None).embedding)

        try:
            client = create_embedding_client(embedding, logger)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

        if embedding.kind.strip().lower() != KIND_MEDIBLE:
            print(
                f"aviso: embedding.kind es {embedding.kind!r}; para medir de verdad se "
                f"necesita {KIND_MEDIBLE!r}, que entiende español",
                file=sys.stderr,
            )

        try:
            client.embed([FRASE_DE_PRUEBA])
        except EmbeddingUnavailable as exc:
            print(
                "error: el servicio de embeddings no responde; "
                f"verificá que Ollama corra en {embedding.url}: {exc}",
                file=sys.stderr,
            )
            return 2

        if not args.json:
            print(_encabezado(medicion, embedding))
        observaciones = _clasificar_medicion(medicion, client, embedding, logger)
        resumen = calcular_resumen(observaciones)
    finally:
        logger.close()

    if args.json:
        print(json.dumps(resumen.a_dict(), ensure_ascii=False, indent=2))
    else:
        for observacion in observaciones:
            print(formatear_observacion(observacion))
        print(formatear_resumen(resumen))

    if resumen.requiere_fallo():
        return 1
    return 0


__all__ = [
    "ANCHO_ETIQUETA",
    "FRASE_DE_PRUEBA",
    "KIND_MEDIBLE",
    "Observacion",
    "Resumen",
    "calcular_resumen",
    "formatear_observacion",
    "formatear_resumen",
    "main",
]


if __name__ == "__main__":
    sys.exit(main())
