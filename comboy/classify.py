"""Clasificación semántica de una frase de peligro (nivel L1).

El clasificador combina dos motores: embeddings para identificar el peligro y
reglas para extraer carril, distancia y urgencia.

Invariante del sistema
----------------------

    Ante la duda, ``DESCONOCIDO`` con confianza baja. **Nunca** un código
    incorrecto con confianza alta.

Ese invariante se respeta en todos los caminos:

* si la similitud con el vecino más cercano no supera ``min_similarity``, el
  resultado es ``DESCONOCIDO`` con confianza baja;
* la confianza ``ALTA`` exige además un margen mínimo contra el segundo peligro;
* si el cliente de embeddings no está disponible o falla, se registra
  ``classify.unavailable`` y se devuelve ``DESCONOCIDO`` con confianza baja;
  :func:`classify` **nunca** lanza.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from .codes import Confidence, Hazard, Lane, Urgency
from .config import EmbeddingConfig
from .corpus import FRASES_POR_PELIGRO
from .embedding import EmbeddingClient, EmbeddingUnavailable, cosine
from .extract import extract_distance, extract_lane, extract_urgency
from .logging_setup import Logger
from .normalize import normalize

__all__ = ["Classification", "classify"]

#: Palabras que niegan un peligro cuando aparecen justo antes de nombrarlo.
MARCADORES_NEGACION = frozenset({"no", "sin", "nunca", "tampoco", "jamas", "ningun", "ninguna"})

#: Cuántas palabras después de la negación se miran buscando el peligro.
VENTANA_NEGACION = 3

#: Longitud mínima de una palabra para considerarla "contenido" en la negación.
#: Deja afuera conectores cortos como ``hay`` o ``con``.
LONGITUD_MINIMA_CLAVE = 4


@dataclass(frozen=True)
class Classification:
    """Resultado estructurado de clasificar una frase."""

    hazard: Hazard
    lane: Lane
    dist_km: int
    urgency: Urgency
    confidence: Confidence
    similarity: float
    margin: float


@dataclass(frozen=True)
class _Reference:
    """Una frase de ejemplo con su vector ya calculado."""

    hazard: Hazard
    phrase: str
    vector: list[float]


class _ReferenceIndex:
    """Índice de frases de ejemplo con sus vectores, agrupado por peligro."""

    def __init__(self, references: list[_Reference]) -> None:
        self._by_hazard: dict[Hazard, list[_Reference]] = {}
        for reference in references:
            self._by_hazard.setdefault(reference.hazard, []).append(reference)

    @classmethod
    def build(cls, client: EmbeddingClient) -> _ReferenceIndex:
        """Embebe todas las frases del corpus y arma el índice.

        Las frases se normalizan antes de embeber: la consulta también se
        normaliza, así que ambos lados quedan en el mismo espacio.
        """

        pairs: list[tuple[Hazard, str]] = []
        for hazard, phrases in FRASES_POR_PELIGRO.items():
            for phrase in phrases:
                pairs.append((hazard, normalize(phrase)))
        vectors = client.embed([phrase for _, phrase in pairs])
        references = [
            _Reference(hazard, phrase, vector)
            for (hazard, phrase), vector in zip(pairs, vectors, strict=True)
        ]
        return cls(references)

    def score(self, vector: list[float]) -> tuple[_Reference, float, float]:
        """Devuelve ``(mejor_referencia, similitud, margen)``.

        La similitud de cada peligro es el máximo sobre sus frases. El margen es
        la diferencia contra el **segundo peligro distinto**: comparar frases
        del mismo peligro no aporta a la decisión.
        """

        ranked: list[tuple[float, _Reference]] = []
        for references in self._by_hazard.values():
            best_similarity = -1.0
            best_reference = references[0]
            for reference in references:
                similarity = cosine(vector, reference.vector)
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_reference = reference
            ranked.append((best_similarity, best_reference))

        ranked.sort(key=lambda item: item[0], reverse=True)
        best_similarity, best_reference = ranked[0]
        second_similarity = ranked[1][0] if len(ranked) > 1 else 0.0
        return best_reference, best_similarity, best_similarity - second_similarity


@lru_cache(maxsize=8)
def _reference_index(client: EmbeddingClient, model: str) -> _ReferenceIndex:
    """Índice cacheado por cliente y modelo.

    ``model`` solo participa de la clave: el índice depende del cliente, pero
    cambiar el modelo invalida la caché. El cliente debe ser *hashable* (lo es
    cualquier objeto sin ``__eq__`` propio).
    """

    return _ReferenceIndex.build(client)


def _esta_negado(words: list[str], reference: _Reference) -> bool:
    """Detecta una negación inmediatamente antes de la zona del peligro.

    Se mira una ventana corta después de cada negación y se busca una palabra de
    contenido que también esté en la frase de referencia. Así ``"no hay piedras"``
    se niega, pero ``"no se ve nada de la niebla"`` —donde la niebla sí existe—
    no se confunde con una negación del peligro.
    """

    reference_words = {
        word for word in reference.phrase.split() if len(word) >= LONGITUD_MINIMA_CLAVE
    }
    for index, word in enumerate(words):
        if word not in MARCADORES_NEGACION:
            continue
        window = words[index + 1 : index + 1 + VENTANA_NEGACION]
        if any(candidate in reference_words for candidate in window):
            return True
    return False


def classify(
    text: str,
    client: EmbeddingClient,
    config: EmbeddingConfig,
    logger: Logger,
) -> Classification:
    """Clasifica ``text`` en un :class:`Classification`.

    Extrae las reglas primero (son baratas y no dependen de la red) y recién
    después resuelve el peligro por embeddings. Nunca lanza: cualquier fallo del
    cliente se traduce en ``DESCONOCIDO`` con confianza baja.
    """

    normalized = normalize(text)
    lane = extract_lane(normalized)
    dist_km = extract_distance(normalized)
    urgency = extract_urgency(normalized)

    def desconocido(similarity: float = 0.0, margin: float = 0.0) -> Classification:
        return Classification(
            hazard=Hazard.DESCONOCIDO,
            lane=lane,
            dist_km=dist_km,
            urgency=urgency,
            confidence=Confidence.BAJA,
            similarity=similarity,
            margin=margin,
        )

    if not client.available:
        logger.warn("classify.unavailable", reason="cliente no disponible")
        return desconocido()

    try:
        vector = client.embed([normalized])[0]
        reference, similarity, margin = _reference_index(client, config.model).score(vector)
    except EmbeddingUnavailable as exc:
        logger.warn("classify.unavailable", error=str(exc))
        return desconocido()
    except Exception as exc:
        # Defensa en profundidad: un cliente roto no puede tumbar al nodo.
        logger.warn("classify.unavailable", error=type(exc).__name__)
        return desconocido()

    if similarity < config.min_similarity:
        logger.warn(
            "classify.unknown",
            similarity=round(similarity, 4),
            margin=round(margin, 4),
        )
        return desconocido(similarity, margin)

    if _esta_negado(normalized.split(), reference):
        logger.warn(
            "classify.unknown",
            similarity=round(similarity, 4),
            margin=round(margin, 4),
            reason="negacion",
        )
        return desconocido(similarity, margin)

    confidence = Confidence.ALTA if margin >= config.min_margin else Confidence.BAJA
    result = Classification(
        hazard=reference.hazard,
        lane=lane,
        dist_km=dist_km,
        urgency=urgency,
        confidence=confidence,
        similarity=similarity,
        margin=margin,
    )
    logger.info(
        "classify",
        hazard=result.hazard.name,
        lane=result.lane.name,
        dist_km=result.dist_km,
        urgency=result.urgency.name,
        confidence=result.confidence.name,
        similarity=round(similarity, 4),
        margin=round(margin, 4),
    )
    return result
