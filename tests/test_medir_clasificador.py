"""Tests del arnés de medición (``tools/medir_clasificador.py``).

**Por qué existe este archivo.** El arnés es el instrumento que decide: sus
números determinan si se cambia el corpus, el modelo o el umbral. Si el conteo
de métricas estuviera mal, toda medición sería falsa y no habría forma de
notarlo desde afuera, porque se está midiendo con el instrumento roto. Estos
tests calibran la balanza antes de pesar.

**Qué NO se testea acá**: el formato del reporte (se ve al correr la
herramienta) ni el cableado de argparse. Tampoco se toca la red: las
observaciones son sintéticas y el cliente es determinista.
"""

from __future__ import annotations

from comboy.codes import Confidence, Hazard
from comboy.embedding import EmbeddingUnavailable, NullEmbedding
from tools import medir_clasificador
from tools.medir_clasificador import (
    Observacion,
    calcular_resumen,
)


def _observacion(
    frase: str,
    esperado: Hazard | None,
    hazard: Hazard,
    *,
    confidence: Confidence = Confidence.ALTA,
    similarity: float = 0.8,
    margin: float = 0.1,
) -> Observacion:
    return Observacion(
        frase=frase,
        esperado=esperado,
        hazard=hazard,
        confidence=confidence,
        similarity=similarity,
        margin=margin,
    )


# ── El conteo de métricas ────────────────────────────────────────────────────


def test_acierto_cuenta_y_guarda_su_similitud() -> None:
    resumen = calcular_resumen(
        [
            _observacion("a", Hazard.PIEDRAS, Hazard.PIEDRAS, similarity=0.81),
            _observacion("b", Hazard.BACHE, Hazard.BACHE, similarity=0.70),
        ]
    )

    assert resumen.aciertos == 2
    assert resumen.tasa_aciertos == 1.0
    assert resumen.min_similitud_aciertos == 0.70
    assert resumen.requiere_fallo() is False


def test_abstencion_no_es_fallo() -> None:
    """Decir ``DESCONOCIDO`` es el fallback seguro, no un error."""

    resumen = calcular_resumen(
        [_observacion("a", Hazard.PIEDRAS, Hazard.DESCONOCIDO, confidence=Confidence.BAJA)]
    )

    assert resumen.abstenciones == 1
    assert resumen.fallos == 0
    assert resumen.errores_confiados == 0
    assert resumen.requiere_fallo() is False


def test_fallo_con_confianza_baja_no_es_error_confiado() -> None:
    resumen = calcular_resumen(
        [_observacion("a", Hazard.DERRUMBE, Hazard.POLVO, confidence=Confidence.BAJA)]
    )

    assert resumen.fallos == 1
    assert resumen.errores_confiados == 0
    assert resumen.requiere_fallo() is False


def test_fallo_con_confianza_alta_es_error_confiado() -> None:
    """La métrica que manda: código incorrecto con ``ALTA`` le miente al conductor."""

    resumen = calcular_resumen(
        [_observacion("a", Hazard.DERRUMBE, Hazard.POLVO, confidence=Confidence.ALTA)]
    )

    assert resumen.fallos == 1
    assert resumen.errores_confiados == 1
    assert resumen.requiere_fallo() is True


def test_ruido_con_peligro_alta_es_falso_positivo() -> None:
    resumen = calcular_resumen(
        [_observacion("me gusta el asado", None, Hazard.DERRUMBE, confidence=Confidence.ALTA)]
    )

    assert resumen.total_ruido == 1
    assert resumen.falsos_positivos == 1
    assert resumen.ruido_dudoso == 0
    assert resumen.requiere_fallo() is True


def test_ruido_con_peligro_baja_no_es_falso_positivo() -> None:
    """El margen chico salva al ruido: se reporta aparte y no dispara el fallo."""

    resumen = calcular_resumen(
        [_observacion("me gusta el asado", None, Hazard.DERRUMBE, confidence=Confidence.BAJA)]
    )

    assert resumen.falsos_positivos == 0
    assert resumen.ruido_dudoso == 1
    assert resumen.requiere_fallo() is False


def test_ruido_abstenido_es_lo_esperado() -> None:
    resumen = calcular_resumen(
        [_observacion("che cuánto falta", None, Hazard.DESCONOCIDO, confidence=Confidence.BAJA)]
    )

    assert resumen.falsos_positivos == 0
    assert resumen.ruido_dudoso == 0
    assert resumen.max_similitud_ruido == 0.8


def test_calibracion_es_minimo_de_aciertos_menos_maximo_de_ruido() -> None:
    resumen = calcular_resumen(
        [
            _observacion("a", Hazard.PIEDRAS, Hazard.PIEDRAS, similarity=0.90),
            _observacion("b", Hazard.BACHE, Hazard.BACHE, similarity=0.75),
            _observacion("ruido", None, Hazard.DESCONOCIDO, similarity=0.55),
        ]
    )

    assert resumen.min_similitud_aciertos == 0.75
    assert resumen.max_similitud_ruido == 0.55
    assert resumen.calibracion == 0.75 - 0.55


def test_calibracion_es_none_sin_aciertos_o_sin_ruido() -> None:
    sin_aciertos = calcular_resumen(
        [_observacion("a", Hazard.PIEDRAS, Hazard.DESCONOCIDO, similarity=0.4)]
    )
    sin_ruido = calcular_resumen([_observacion("a", Hazard.PIEDRAS, Hazard.PIEDRAS)])

    assert sin_aciertos.calibracion is None
    assert sin_ruido.calibracion is None


def test_el_json_incluye_las_metricas_y_la_tasa() -> None:
    """El ``--json`` es un contrato: alguien lo va a parsear desde un script."""

    resumen = calcular_resumen(
        [
            _observacion("a", Hazard.PIEDRAS, Hazard.PIEDRAS, similarity=0.9),
            _observacion("b", Hazard.BACHE, Hazard.DESCONOCIDO, similarity=0.4),
            _observacion("ruido", None, Hazard.DESCONOCIDO, similarity=0.5),
        ]
    )

    datos = resumen.a_dict()

    assert datos["total_peligros"] == 2
    assert datos["total_ruido"] == 1
    assert datos["aciertos"] == 1
    assert datos["abstenciones"] == 1
    assert datos["fallos"] == 0
    assert datos["errores_confiados"] == 0
    assert datos["falsos_positivos"] == 0
    assert datos["tasa_aciertos"] == 0.5
    assert datos["calibracion"] == round(0.9 - 0.5, 4)


def test_sin_observaciones_el_resumen_no_revienta() -> None:
    resumen = calcular_resumen([])

    assert resumen.tasa_aciertos == 0.0
    assert resumen.requiere_fallo() is False
    assert resumen.a_dict()["aciertos"] == 0


# ── La regla del código de salida (1 si y solo si hay fallos graves) ─────────


def _usar_cliente_sin_red(monkeypatch) -> None:
    """Reemplaza el cliente real por el determinista, sin tocar la red."""

    monkeypatch.setattr(
        medir_clasificador,
        "create_embedding_client",
        lambda config, logger=None: NullEmbedding(),
    )


def _forzar_observaciones(monkeypatch, observaciones: list[Observacion]) -> None:
    """Fija las observaciones de ``main`` sin depender de la clasificación real."""

    _usar_cliente_sin_red(monkeypatch)
    monkeypatch.setattr(
        medir_clasificador, "_clasificar_medicion", lambda *args, **kwargs: observaciones
    )


def test_main_sin_ollama_devuelve_2_sin_traza(monkeypatch, capsys) -> None:
    """Un servicio caído no es un error confiado: es un instrumento que no puede medir."""

    class _ClienteCaido:
        @property
        def available(self) -> bool:
            return False

        def embed(self, texts: object) -> list[list[float]]:
            raise EmbeddingUnavailable("conexión rechazada")

    monkeypatch.setattr(
        medir_clasificador,
        "create_embedding_client",
        lambda config, logger=None: _ClienteCaido(),
    )

    codigo = medir_clasificador.main(["--url", "http://127.0.0.1:1", "--sin-cache"])

    capturado = capsys.readouterr()
    assert codigo == 2
    assert "no responde" in capturado.err
    assert "Traceback" not in capturado.err


def test_main_devuelve_1_con_error_confiado(monkeypatch) -> None:
    _forzar_observaciones(
        monkeypatch,
        [
            _observacion(
                "hay tierra sobre la ruta",
                Hazard.DERRUMBE,
                Hazard.POLVO,
                confidence=Confidence.ALTA,
            )
        ],
    )

    assert medir_clasificador.main(["--json", "--sin-cache"]) == 1


def test_main_devuelve_1_con_falso_positivo(monkeypatch) -> None:
    _forzar_observaciones(
        monkeypatch,
        [_observacion("me gusta el asado", None, Hazard.DERRUMBE, confidence=Confidence.ALTA)],
    )

    assert medir_clasificador.main(["--json", "--sin-cache"]) == 1


def test_main_devuelve_0_sin_fallos_graves(monkeypatch) -> None:
    """Abstenciones y fallos con confianza baja no disparan el código de error."""

    _forzar_observaciones(
        monkeypatch,
        [
            _observacion(
                "se viene una curva", Hazard.CURVA, Hazard.DESCONOCIDO, confidence=Confidence.BAJA
            ),
            _observacion("a", Hazard.BACHE, Hazard.PIEDRAS, confidence=Confidence.BAJA),
        ],
    )

    assert medir_clasificador.main(["--json", "--sin-cache"]) == 0
