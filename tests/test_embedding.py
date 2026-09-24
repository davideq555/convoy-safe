"""Tests de los clientes de embeddings, sin red."""

from __future__ import annotations

import io
import json
from typing import Any

import pytest
from convoy.config import EmbeddingConfig
from convoy.embedding import (
    EmbeddingUnavailable,
    NullEmbedding,
    OllamaEmbedding,
    cosine,
    create_embedding_client,
)
from convoy.logging_setup import Logger


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


def _opener_por_lotes(peticiones: list[list[str]], *, fallar_en: int | None = None) -> Any:
    """Opener falso que registra cada lote y devuelve un vector por texto.

    El vector devuelto es ``[float(texto[1:])]``: así el orden del resultado
    delata si la concatenación de lotes mezcló posiciones.
    """

    def abrir(request: Any, timeout: float | None = None) -> _RespuestaFalsa:
        payload = json.loads(request.data.decode("utf-8"))
        peticiones.append(payload["input"])
        if fallar_en is not None and len(peticiones) == fallar_en:
            raise OSError("corte en el lote")
        embeddings = [[float(text[1:])] for text in payload["input"]]
        return _RespuestaFalsa(json.dumps({"embeddings": embeddings}).encode("utf-8"))

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


def test_ollama_parte_en_lotes_y_conserva_el_orden() -> None:
    peticiones: list[list[str]] = []
    cliente = OllamaEmbedding(
        "http://localhost:11434", "m", batch_size=16, opener=_opener_por_lotes(peticiones)
    )

    vectores = cliente.embed([f"t{index}" for index in range(70)])

    assert len(peticiones) == 5
    assert [len(peticion) for peticion in peticiones] == [16, 16, 16, 16, 6]
    assert vectores == [[float(index)] for index in range(70)]


def test_ollama_una_sola_peticion_si_el_lote_cubre_todo() -> None:
    peticiones: list[list[str]] = []
    cliente = OllamaEmbedding(
        "http://localhost:11434", "m", batch_size=16, opener=_opener_por_lotes(peticiones)
    )

    vectores = cliente.embed(["t0", "t1", "t2"])

    assert len(peticiones) == 1
    assert peticiones[0] == ["t0", "t1", "t2"]
    assert vectores == [[0.0], [1.0], [2.0]]


def test_ollama_lanza_unavailable_si_falla_un_lote_posterior() -> None:
    peticiones: list[list[str]] = []
    cliente = OllamaEmbedding(
        "http://localhost:11434",
        "m",
        batch_size=2,
        opener=_opener_por_lotes(peticiones, fallar_en=2),
    )

    with pytest.raises(EmbeddingUnavailable):
        cliente.embed(["t0", "t1", "t2", "t3"])

    # El primer lote se pidió; el segundo fue el que falló.
    assert len(peticiones) == 2


def test_ollama_batch_size_invalido_falla() -> None:
    with pytest.raises(ValueError, match="batch_size"):
        OllamaEmbedding("http://localhost:11434", "m", batch_size=0)


def test_ollama_avisa_cuando_construye_el_indice_en_lotes() -> None:
    peticiones: list[list[str]] = []
    buffer = io.StringIO()
    logger = Logger(node_id=1, role="follower", level="info", stream=buffer)
    cliente = OllamaEmbedding(
        "http://localhost:11434",
        "m",
        batch_size=16,
        logger=logger,
        opener=_opener_por_lotes(peticiones),
    )

    cliente.embed([f"t{index}" for index in range(70)])

    salida = buffer.getvalue()
    assert "embedding.index" in salida
    assert "phrases=70" in salida
    assert "batches=5" in salida


def test_ollama_no_avisa_el_indice_en_una_sola_peticion() -> None:
    peticiones: list[list[str]] = []
    buffer = io.StringIO()
    logger = Logger(node_id=1, role="follower", level="info", stream=buffer)
    cliente = OllamaEmbedding(
        "http://localhost:11434",
        "m",
        batch_size=16,
        logger=logger,
        opener=_opener_por_lotes(peticiones),
    )

    cliente.embed(["t0"])

    assert "embedding.index" not in buffer.getvalue()


def test_factory_propaga_timeout_y_batch_size(monkeypatch: pytest.MonkeyPatch) -> None:
    peticiones: list[list[str]] = []
    tiempos: list[float | None] = []

    def abrir(request: Any, timeout: float | None = None) -> _RespuestaFalsa:
        payload = json.loads(request.data.decode("utf-8"))
        peticiones.append(payload["input"])
        tiempos.append(timeout)
        embeddings = [[float(text[1:])] for text in payload["input"]]
        return _RespuestaFalsa(json.dumps({"embeddings": embeddings}).encode("utf-8"))

    monkeypatch.setattr("convoy.embedding.urllib.request.urlopen", abrir)
    cliente = create_embedding_client(EmbeddingConfig(timeout_s=12.5, batch_size=2))

    vectores = cliente.embed(["t0", "t1", "t2"])

    assert [len(peticion) for peticion in peticiones] == [2, 1]
    assert tiempos == [12.5, 12.5]
    assert vectores == [[0.0], [1.0], [2.0]]
