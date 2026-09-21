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

import contextlib
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .codes import Confidence, Hazard, Lane, Urgency
from .config import EmbeddingConfig
from .corpus import FRASES_POR_PELIGRO
from .embedding import EmbeddingClient, EmbeddingUnavailable, cosine
from .extract import extract_distance, extract_lane, extract_urgency
from .logging_setup import Logger
from .normalize import normalize

__all__ = ["Classification", "classify"]

#: Versión del formato del caché en disco. Cambiarla invalida todos los cachés.
CACHE_VERSION = 1

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
        self._references = list(references)
        self._by_hazard: dict[Hazard, list[_Reference]] = {}
        for reference in self._references:
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

    def to_payload(self, *, fingerprint: str, model: str) -> dict[str, Any]:
        """Serializa el índice al formato JSON del caché en disco.

        Respeta el orden del corpus: el mismo orden con el que se construyó, así
        el archivo es reproducible y legible.
        """

        return {
            "version": CACHE_VERSION,
            "fingerprint": fingerprint,
            "model": model,
            "references": [
                {
                    "hazard": reference.hazard.name,
                    "phrase": reference.phrase,
                    "vector": reference.vector,
                }
                for reference in self._references
            ],
        }

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


def _corpus_fingerprint(config: EmbeddingConfig) -> str:
    """Huella de la configuración de embeddings y del contenido a embeber.

    Cubre la versión de formato, el proveedor (``kind``), la ``url``, el modelo y
    todas las frases del corpus en orden, con su peligro. Cambiar cualquiera de
    ellos cambia la huella y obliga a reconstruir el índice; es exactamente lo que
    se quiere. En particular, un caché escrito por un proveedor nunca se reutiliza
    con otro, ni siquiera cuando el nombre del modelo coincide: los vectores de
    proveedores distintos pueden tener dimensiones y espacios diferentes.
    """

    digest = hashlib.sha256()
    digest.update(
        f"v{CACHE_VERSION}\x00{config.kind}\x00{config.url}\x00{config.model}\x00".encode()
    )
    for hazard, phrases in FRASES_POR_PELIGRO.items():
        for phrase in phrases:
            digest.update(f"{hazard.name}\x00{normalize(phrase)}\x00".encode())
    return digest.hexdigest()


def _reference_from_payload(entry: Any) -> _Reference:
    """Reconstruye una referencia desde una entrada del caché.

    Lanza ``KeyError``/``TypeError``/``ValueError`` ante un formato inesperado:
    el llamador lo interpreta como caché corrupto.
    """

    if not isinstance(entry, dict):
        raise TypeError("la referencia no es un objeto")
    hazard = Hazard[str(entry["hazard"])]
    phrase = entry["phrase"]
    vector = entry["vector"]
    if not isinstance(phrase, str) or not isinstance(vector, list):
        raise TypeError("la referencia tiene campos inesperados")
    return _Reference(hazard, phrase, [float(component) for component in vector])


def _load_cached_index(path: Path, fingerprint: str) -> tuple[_ReferenceIndex | None, str]:
    """Lee el caché en disco si sigue siendo válido.

    Devuelve ``(índice, "")`` cuando sirve, o ``(None, motivo)`` cuando hay que
    reconstruir. Nunca lanza: un archivo ausente, ilegible o corrupto es un
    motivo más para reconstruir, no un error del clasificador.
    """

    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return None, "ausente"
    except OSError:
        return None, "ilegible"
    except ValueError:
        # ``json.JSONDecodeError`` y ``UnicodeDecodeError`` heredan de ValueError.
        return None, "corrupto"

    if not isinstance(payload, dict):
        return None, "corrupto"
    if payload.get("fingerprint") != fingerprint:
        return None, "fingerprint"
    raw_references = payload.get("references")
    if not isinstance(raw_references, list):
        return None, "corrupto"
    try:
        references = [_reference_from_payload(entry) for entry in raw_references]
    except (KeyError, TypeError, ValueError):
        return None, "corrupto"
    return _ReferenceIndex(references), ""


def _save_cached_index(
    path: Path, index: _ReferenceIndex, fingerprint: str, model: str, logger: Logger
) -> None:
    """Escribe el caché de forma atómica.

    Arma el archivo en un temporal del mismo directorio y recién después lo mueve
    con ``os.replace``: un corte de energía a mitad de escritura no deja un caché
    a medias que rompa la próxima corrida. Un fallo al escribir nunca se propaga;
    solo deja una línea de log.
    """

    payload = index.to_payload(fingerprint=fingerprint, model=model)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            os.replace(temporary, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise
    except (OSError, TypeError, ValueError) as exc:
        logger.warn(
            "embedding.cache",
            result="error",
            path=str(path),
            reason=type(exc).__name__,
        )


def _resolve_reference_index(
    client: EmbeddingClient,
    config: EmbeddingConfig,
    logger: Logger,
) -> _ReferenceIndex:
    """Resuelve el índice contra el disco, o lo construye si no sirve.

    ``config.cache_path`` vacío deshabilita el disco y va directo al cómputo. La
    huella cubre la configuración de embeddings completa (proveedor, url y modelo)
    además del corpus, así que un caché escrito por un proveedor nunca se lee con
    otro. Tras un *miss* el índice recién construido se persiste para la próxima
    corrida.
    """

    raw_path = config.cache_path.strip()
    if not raw_path:
        return _ReferenceIndex.build(client)

    path = Path(raw_path)
    fingerprint = _corpus_fingerprint(config)
    cached, reason = _load_cached_index(path, fingerprint)
    if cached is not None:
        logger.info("embedding.cache", result="hit", path=raw_path)
        return cached
    logger.info("embedding.cache", result="miss", path=raw_path, reason=reason)
    index = _ReferenceIndex.build(client)
    _save_cached_index(path, index, fingerprint, config.model, logger)
    return index


@lru_cache(maxsize=8)
def _reference_index(
    client: EmbeddingClient, config: EmbeddingConfig, logger: Logger
) -> _ReferenceIndex:
    """Índice cacheado en memoria, por cliente, configuración y logger.

    Orden de resolución: memoria → disco → cómputo. La ``config`` solo participa
    de la clave: el índice depende del cliente, pero cambiar cualquier campo que
    entre en la huella —proveedor, url o modelo— o desactivar el disco debe
    invalidar la caché en memoria. El ``logger`` también participa para que
    ``embedding.cache`` se emita una sola vez por combinación y no en cada
    clasificación de un proceso largo.
    """

    return _resolve_reference_index(client, config, logger)


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
        reference, similarity, margin = _reference_index(client, config, logger).score(vector)
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
