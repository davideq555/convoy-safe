"""Clientes de embeddings para el clasificador semántico.

El clasificador no habla con Ollama directamente: habla con :class:`EmbeddingClient`.
Eso deja el resto del sistema aislado del proveedor y permite correr sin red con
:class:`NullEmbedding`.

Solo se usa la biblioteca estándar. El cliente HTTP de Ollama se apoya en
``urllib.request`` a propósito: el proyecto no agrega dependencias.

Si el servicio no responde, el cliente lanza :class:`EmbeddingUnavailable`, que
es una excepción del proyecto y nunca un ``URLError`` crudo.
"""

from __future__ import annotations

import hashlib
import json
import math
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any, Protocol, runtime_checkable

from .config import EmbeddingConfig
from .logging_setup import Logger

#: Segundos de espera para una llamada a Ollama.
DEFAULT_TIMEOUT_S = 30.0

#: Dimensión de los vectores de :class:`NullEmbedding`.
NULL_DIMENSION = 128


class EmbeddingUnavailable(RuntimeError):
    """El servicio de embeddings no está disponible o devolvió algo inutilizable."""


@runtime_checkable
class EmbeddingClient(Protocol):
    """Interfaz que el clasificador espera de un proveedor de embeddings."""

    @property
    def available(self) -> bool:
        """``True`` si el cliente puede intentar embeber."""

        ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Devuelve un vector por cada texto, en el mismo orden."""

        ...


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Similitud coseno entre ``a`` y ``b``.

    Devuelve ``0.0`` ante vectores vacíos, de distinta longitud o de norma
    nula: el clasificador prefiere una similitud nula a una excepción.
    """

    if not a or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for value_a, value_b in zip(a, b, strict=True):
        dot += value_a * value_b
        norm_a += value_a * value_a
        norm_b += value_b * value_b
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


class OllamaEmbedding:
    """Cliente HTTP contra ``POST {url}/api/embed`` de Ollama.

    El cuerpo que espera el endpoint es ``{"model": ..., "input": [...]}`` y la
    respuesta trae los vectores bajo la clave ``embeddings``.
    """

    def __init__(
        self,
        url: str,
        model: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_S,
        logger: Logger | None = None,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self._url = url.rstrip("/")
        self._model = model
        self._timeout = float(timeout)
        self._logger = logger
        # Costura para los tests: permite inyectar un ``urlopen`` falso sin red.
        self._opener = opener or urllib.request.urlopen

    @property
    def available(self) -> bool:
        """``True``: Ollama no tiene un artefacto local que verificar.

        Un fallo real se reporta por :class:`EmbeddingUnavailable` y se vuelve a
        intentar en la próxima llamada. Marcar el cliente como no disponible
        dejaría al nodo sin clasificador para siempre tras un corte transitorio.
        """

        return True

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embebe ``texts`` contra Ollama.

        Lanza :class:`EmbeddingUnavailable` ante cualquier fallo de red, de
        protocolo o de formato. Nunca deja escapar una excepción cruda de
        ``urllib``.
        """

        items = list(texts)
        if not items:
            return []

        request = urllib.request.Request(
            f"{self._url}/api/embed",
            data=json.dumps({"model": self._model, "input": items}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                body = response.read()
            payload = json.loads(body.decode("utf-8"))
            embeddings = payload["embeddings"]
            if not isinstance(embeddings, list) or len(embeddings) != len(items):
                raise EmbeddingUnavailable(
                    f"respuesta inesperada de {self._url}: se esperaban {len(items)} embeddings"
                )
            vectors = [[float(component) for component in vector] for vector in embeddings]
        except EmbeddingUnavailable:
            raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            # ``urllib.error.URLError`` (y ``HTTPError``) son subclases de
            # ``OSError``; ``json.JSONDecodeError`` lo es de ``ValueError``.
            raise EmbeddingUnavailable(f"no se pudo consultar {self._url}: {exc}") from exc

        return vectors


class NullEmbedding:
    """Cliente determinista para tests y para depurar sin Ollama.

    Construye un vector por *feature hashing*: cada palabra de la frase vota en
    una posición derivada de su ``sha256`` con un signo fijo. El resultado es
    reproducible entre corridas y procesos —a diferencia de ``hash()``, que está
    salteado por proceso—, y frases que comparten palabras quedan más cerca.
    """

    def __init__(self, *, dimension: int = NULL_DIMENSION, logger: Logger | None = None) -> None:
        self._dimension = int(dimension)
        self._logger = logger

    @property
    def available(self) -> bool:
        return True

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        for token in text.split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(component * component for component in vector))
        if norm == 0.0:
            return vector
        return [component / norm for component in vector]


def create_embedding_client(
    config: EmbeddingConfig, logger: Logger | None = None
) -> EmbeddingClient:
    """Construye el cliente de embeddings descrito por ``config``.

    Los tipos soportados son ``"ollama"`` (red local, el de producción) y
    ``"null"`` (determinista, sin red, para tests y depuración).
    """

    kind = config.kind.strip().lower()
    if kind == "null":
        return NullEmbedding(logger=logger)
    if kind == "ollama":
        return OllamaEmbedding(config.url, config.model, logger=logger)
    raise ValueError(f"tipo de embedding no soportado: {config.kind!r}")


__all__ = [
    "DEFAULT_TIMEOUT_S",
    "NULL_DIMENSION",
    "EmbeddingClient",
    "EmbeddingUnavailable",
    "NullEmbedding",
    "OllamaEmbedding",
    "cosine",
    "create_embedding_client",
]
