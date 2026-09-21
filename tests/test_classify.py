"""Tests del clasificador: decisión, confianza, negación y reglas."""

from __future__ import annotations

import io

import pytest
from comboy.classify import Classification, classify
from comboy.codes import Confidence, Hazard, Lane, Urgency
from comboy.config import EmbeddingConfig
from comboy.corpus import FRASES_POR_PELIGRO
from comboy.embedding import EmbeddingUnavailable, NullEmbedding
from comboy.extract import extract_distance, extract_lane, extract_urgency
from comboy.logging_setup import Logger
from comboy.normalize import normalize

#: Dimensión de trabajo: un eje por peligro del catálogo.
DIM = len(Hazard)

# El caché en disco se deshabilita acá: estos tests construyen clientes falsos
# que no comparten vectores con el corpus real. La persistencia tiene sus
# propios tests en ``test_reference_cache.py``.
CONFIG = EmbeddingConfig(kind="null", cache_path="")


def _vector_peligro(hazard: Hazard) -> list[float]:
    vector = [0.0] * DIM
    vector[int(hazard)] = 1.0
    return vector


class _ClienteFalso:
    """Cliente con vectores explícitos por texto ya normalizado."""

    def __init__(self, mapping: dict[str, list[float]], disponible: bool = True) -> None:
        self._mapping = mapping
        self._disponible = disponible

    @property
    def available(self) -> bool:
        return self._disponible

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._mapping[text] for text in texts]


class _ClienteQueFalla:
    @property
    def available(self) -> bool:
        return True

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingUnavailable("boom")


def _cliente(
    query: str,
    query_vector: list[float],
    *,
    por_peligro: dict[Hazard, list[float]] | None = None,
) -> _ClienteFalso:
    por_peligro = por_peligro or {}
    mapping: dict[str, list[float]] = {}
    for hazard, phrases in FRASES_POR_PELIGRO.items():
        vector = por_peligro.get(hazard, _vector_peligro(hazard))
        for phrase in phrases:
            mapping[normalize(phrase)] = vector
    mapping[normalize(query)] = query_vector
    return _ClienteFalso(mapping)


def _logger(buffer: io.StringIO) -> Logger:
    return Logger(node_id=1, role="leader", stream=buffer)


# ── Decisión y confianza ─────────────────────────────────────────────────────


def test_acierto_claro_da_confianza_alta() -> None:
    query = "hubo un accidente en la ruta"
    cliente = _cliente(query, _vector_peligro(Hazard.ACCIDENTE))
    buffer = io.StringIO()

    result = classify(query, cliente, CONFIG, _logger(buffer))

    assert result.hazard is Hazard.ACCIDENTE
    assert result.confidence is Confidence.ALTA
    assert result.similarity == pytest.approx(1.0)
    assert result.margin > CONFIG.min_margin
    assert "classify " in buffer.getvalue()


def test_similitud_baja_da_desconocido_y_baja() -> None:
    query = "una frase cualquiera sin relacion"
    cliente = _cliente(query, [1.0] * DIM)
    buffer = io.StringIO()

    result = classify(query, cliente, CONFIG, _logger(buffer))

    assert result.hazard is Hazard.DESCONOCIDO
    assert result.confidence is Confidence.BAJA
    assert result.similarity < CONFIG.min_similarity
    assert "classify.unknown" in buffer.getvalue()


def test_margen_chico_baja_la_confianza_aunque_la_similitud_sea_alta() -> None:
    query = "hay algo en la ruta"
    todos_juntos = [1.0, 0.0]
    cliente = _cliente(
        query,
        [1.0, 0.0],
        por_peligro={hazard: todos_juntos for hazard in FRASES_POR_PELIGRO},
    )

    result = classify(query, cliente, CONFIG, _logger(io.StringIO()))

    assert result.hazard is not Hazard.DESCONOCIDO
    assert result.confidence is Confidence.BAJA
    assert result.margin < CONFIG.min_margin


def test_bajo_el_umbral_nunca_hay_peligro_con_alta() -> None:
    # El invariante de la Fase 1, ejercitado de frente.
    cliente = _cliente("texto sin sentido", [1.0] * DIM)

    result = classify("texto sin sentido", cliente, CONFIG, _logger(io.StringIO()))

    assert result.similarity < CONFIG.min_similarity
    assert not (result.hazard is not Hazard.DESCONOCIDO and result.confidence is Confidence.ALTA)


# ── Negación ─────────────────────────────────────────────────────────────────


def test_la_negacion_del_peligro_da_desconocido() -> None:
    query = "no hay piedras en la ruta"
    cliente = _cliente(query, _vector_peligro(Hazard.PIEDRAS))
    buffer = io.StringIO()

    result = classify(query, cliente, CONFIG, _logger(buffer))

    assert result.hazard is Hazard.DESCONOCIDO
    assert result.confidence is Confidence.BAJA
    assert "negacion" in buffer.getvalue()


def test_no_toda_aparicion_de_no_niega_el_peligro() -> None:
    # "no se ve nada de la niebla" confirma la niebla, no la niega.
    query = "no se ve nada de la niebla"
    cliente = _cliente(query, _vector_peligro(Hazard.NIEBLA))

    result = classify(query, cliente, CONFIG, _logger(io.StringIO()))

    assert result.hazard is Hazard.NIEBLA


# ── Degradación sin excepciones ──────────────────────────────────────────────


def test_cliente_no_disponible_no_lanza() -> None:
    buffer = io.StringIO()
    cliente = _ClienteFalso({}, disponible=False)

    result = classify("hay piedras en la calzada", cliente, CONFIG, _logger(buffer))

    assert result.hazard is Hazard.DESCONOCIDO
    assert result.confidence is Confidence.BAJA
    assert "classify.unavailable" in buffer.getvalue()


def test_fallo_del_embedding_no_lanza() -> None:
    buffer = io.StringIO()

    result = classify("hay piedras en la calzada", _ClienteQueFalla(), CONFIG, _logger(buffer))

    assert result.hazard is Hazard.DESCONOCIDO
    assert result.confidence is Confidence.BAJA
    assert "classify.unavailable" in buffer.getvalue()


def test_la_reglas_se_aplican_aunque_el_peligro_sea_desconocido() -> None:
    query = "frena hay piedras en el carril derecho a dos kilometros"
    cliente = _cliente(query, [1.0] * DIM)

    result = classify(query, cliente, CONFIG, _logger(io.StringIO()))

    assert result.hazard is Hazard.DESCONOCIDO
    assert result.lane is Lane.DERECHO
    assert result.dist_km == 2
    assert result.urgency is Urgency.DETENERSE


# ── Integración con NullEmbedding (sin red) ──────────────────────────────────


def test_null_embedding_reconoce_una_frase_del_corpus() -> None:
    result = classify(
        "se vino la montaña abajo",
        NullEmbedding(),
        CONFIG,
        _logger(io.StringIO()),
    )

    assert result.hazard is Hazard.DERRUMBE
    assert result.confidence is Confidence.ALTA


def test_null_embedding_no_inventa_peligros_en_texto_sin_relacion() -> None:
    result = classify("zzz qqq wwww", NullEmbedding(), CONFIG, _logger(io.StringIO()))

    assert result.hazard is Hazard.DESCONOCIDO
    assert result.confidence is Confidence.BAJA


# ── Reglas de carril ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("frase", "esperado"),
    [
        ("hay algo en el carril derecho", Lane.DERECHO),
        ("viene por la mano derecha", Lane.DERECHO),
        ("hay algo en el carril izquierdo", Lane.IZQUIERDO),
        ("viene por la mano izquierda", Lane.IZQUIERDO),
        ("hay algo en toda la ruta", Lane.TODA_LA_RUTA),
        ("esta cortada toda la calzada", Lane.TODA_LA_RUTA),
        ("hay un auto en la banquina", Lane.BANQUINA),
        ("hay piedras en la calzada", Lane.SIN_ESPECIFICAR),
        ("hay algo en la ruta", Lane.SIN_ESPECIFICAR),
    ],
)
def test_extract_lane(frase: str, esperado: Lane) -> None:
    assert extract_lane(normalize(frase)) is esperado


# ── Reglas de distancia ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("frase", "esperado"),
    [
        ("a dos kilometros", 2),
        ("a cinco kilometros", 5),
        ("un kilometro y medio", 2),
        ("a 200 metros", 0),
        ("aqui mismo", 0),
        ("aca nomas", 0),
        ("en el medio", 0),
        ("hay piedras en la ruta", 255),
        ("a veinte kilometros", 255),
        ("a 2000 metros", 2),
    ],
)
def test_extract_distance(frase: str, esperado: int) -> None:
    assert extract_distance(normalize(frase)) == esperado


# ── Reglas de urgencia ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("frase", "esperado"),
    [
        ("hay piedras en la calzada", Urgency.PRECAUCION),
        ("frena que hay un choque", Urgency.DETENERSE),
        ("para un momento", Urgency.DETENERSE),
        ("detenete ahora", Urgency.DETENERSE),
        ("detengase por favor", Urgency.DETENERSE),
        ("solo para avisar que hay piedras", Urgency.INFO),
        ("solo aviso que hay un control", Urgency.INFO),
        # "aviso" suelto es una advertencia real, no un aviso informativo.
        ("les aviso que hay un control", Urgency.PRECAUCION),
        # "para" preposicional no debe escalar la urgencia.
        ("cuanto falta para el cruce", Urgency.PRECAUCION),
    ],
)
def test_extract_urgency(frase: str, esperado: Urgency) -> None:
    assert extract_urgency(normalize(frase)) is esperado


def test_classification_expone_los_siete_campos() -> None:
    cliente = _cliente("hubo un accidente", _vector_peligro(Hazard.ACCIDENTE))

    result = classify("hubo un accidente", cliente, CONFIG, _logger(io.StringIO()))

    assert isinstance(result, Classification)
    assert result.similarity > 0.0
