"""Tests de los clientes de embeddings, sin red."""

from __future__ import annotations

import json
from typing import Any

import pytest
from comboy.config import EmbeddingConfig
from comboy.embedding import (
    EmbeddingUnavailable,
    NullEmbedding,
    OllamaEmbedding,
    cosine,
    create_embedding_client,
)


class _RespuestaFalsa:
    """Doble mínimo de una respuesta HTTP: solo lo que usa el cliente."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _RespuestaFalsa:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


def _opener(body: bytes, capturado: dict[str, Any]) -> Any:
    def abrir(request: Any, timeout: float | None = None) -> _RespuestaFalsa:
        capturado["url"] = request.full_url
        capturado["body"] = request.data
        capturado["timeout"] = timeout
        return _RespuestaFalsa(body)

    return abrir


def test_cosine_de_vectores_identicos() -> None:
    assert cosine([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_de_vectores_ortogonales() -> None:
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_de_longitudes_distintas_es_cero() -> None:
    assert cosine([1.0, 2.0], [1.0]) == 0.0
    assert cosine([], []) == 0.0


def test_cosine_con_norma_nula_es_cero() -> None:
    assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_null_embedding_es_determinista() -> None:
    frase = "hay piedras en la calzada"
    primero = NullEmbedding().embed([frase])[0]
    segundo = NullEmbedding().embed([frase])[0]
    assert primero == segundo
    assert len(primero) > 0


def test_null_embedding_acerca_frases_por_palabras_compartidas() -> None:
    cliente = NullEmbedding()
    consulta, similar, distinta = cliente.embed(
        ["hay piedras en la calzada", "hay piedras en la ruta", "me gusta el asado"]
    )
    assert cosine(consulta, similar) > cosine(consulta, distinta)


def test_null_embedding_mantiene_el_orden() -> None:
    vectores = NullEmbedding().embed(["a", "b", "c"])
    assert len(vectores) == 3


def test_ollama_parsea_la_respuesta_y_arma_el_pedido() -> None:
    capturado: dict[str, Any] = {}
    body = json.dumps({"embeddings": [[1, 2, 3], [4, 5, 6]]}).encode("utf-8")
    cliente = OllamaEmbedding(
        "http://localhost:11434/",
        "qwen3-embedding:0.6b",
        opener=_opener(body, capturado),
    )

    vectores = cliente.embed(["uno", "dos"])

    assert vectores == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
    assert capturado["url"] == "http://localhost:11434/api/embed"
    payload = json.loads(capturado["body"].decode("utf-8"))
    assert payload["model"] == "qwen3-embedding:0.6b"
    assert payload["input"] == ["uno", "dos"]
    assert cliente.available is True


def test_ollama_sin_textos_no_llama_al_servicio() -> None:
    def abrir(*args: object, **kwargs: object) -> _RespuestaFalsa:
        raise AssertionError("no debe llamarse")

    assert OllamaEmbedding("http://x", "m", opener=abrir).embed([]) == []


def test_ollama_lanza_unavailable_si_falla_la_red() -> None:
    def abrir(*args: object, **kwargs: object) -> _RespuestaFalsa:
        raise OSError("conexión rechazada")

    cliente = OllamaEmbedding("http://localhost:11434", "m", opener=abrir)

    with pytest.raises(EmbeddingUnavailable):
        cliente.embed(["uno"])


def test_ollama_se_recupera_de_un_fallo_transitorio() -> None:
    intentos = {"n": 0}
    body = json.dumps({"embeddings": [[1.0]]}).encode("utf-8")

    def abrir(*args: object, **kwargs: object) -> _RespuestaFalsa:
        intentos["n"] += 1
        if intentos["n"] == 1:
            raise OSError("corte transitorio")
        return _RespuestaFalsa(body)

    cliente = OllamaEmbedding("http://localhost:11434", "m", opener=abrir)

    with pytest.raises(EmbeddingUnavailable):
        cliente.embed(["uno"])
    # Un fallo no deja al cliente muerto: la próxima llamada reintenta.
    assert cliente.embed(["uno"]) == [[1.0]]


def test_ollama_lanza_unavailable_si_la_respuesta_esta_mal_formada() -> None:
    cliente = OllamaEmbedding(
        "http://localhost:11434",
        "m",
        opener=_opener(b'{"modelo": "x"}', {}),
    )

    with pytest.raises(EmbeddingUnavailable):
        cliente.embed(["uno"])


def test_ollama_lanza_unavailable_si_falta_un_vector() -> None:
    body = json.dumps({"embeddings": [[1.0]]}).encode("utf-8")
    cliente = OllamaEmbedding("http://localhost:11434", "m", opener=_opener(body, {}))

    with pytest.raises(EmbeddingUnavailable):
        cliente.embed(["uno", "dos"])


def test_factory_construye_null_y_ollama() -> None:
    assert isinstance(create_embedding_client(EmbeddingConfig(kind="null")), NullEmbedding)
    assert isinstance(create_embedding_client(EmbeddingConfig(kind="ollama")), OllamaEmbedding)


def test_factory_rechaza_un_tipo_desconocido() -> None:
    with pytest.raises(ValueError):
        create_embedding_client(EmbeddingConfig(kind="otro"))
