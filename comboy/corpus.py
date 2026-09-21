"""Frases de ejemplo por código de peligro, y el conjunto de control.

El clasificador es semántico: compara la frase del conductor contra **frases
completas**, no contra un léxico de palabras sueltas. Enseñarle cobertura es
agregar frases acá, sin reentrenar nada.

:data:`FRASES_POR_PELIGRO` cubre los 16 peligros reales del catálogo (todos
menos ``DESCONOCIDO``), con variantes coloquiales incluidas. :data:`FRASES_RUIDO`
son frases de conductor que **no** son peligro: sirven para comprobar que el
clasificador no inventa amenazas donde no las hay.

Las frases se escriben en español normal. El clasificador las normaliza antes de
embeberlas, así que las tildes o los números en dígitos no cambian el resultado.
"""

from __future__ import annotations

from .codes import Hazard

__all__ = ["FRASES_POR_PELIGRO", "FRASES_RUIDO"]

#: Frases de ejemplo por peligro. Cada lista tiene entre 4 y 6 frases.
FRASES_POR_PELIGRO: dict[Hazard, list[str]] = {
    Hazard.ACCIDENTE: [
        "hubo un accidente en la ruta",
        "chocaron dos autos en la calzada",
        "hay un vuelco en la curva",
        "frena que hay un choque adelante",
        "hay un siniestro sobre la ruta",
    ],
    Hazard.PIEDRAS: [
        "hay piedras en la calzada",
        "hay un montón de piedras en el medio",
        "se desprendieron rocas de la montaña",
        "hay una piedra grande en la ruta",
        "cuidado con las piedras sueltas",
    ],
    Hazard.ANIMAL: [
        "hay un animal en la ruta",
        "se nos cruzó un bicho en el camino",
        "hay una vaca suelta en la calzada",
        "viene un caballo por la banquina",
        "hay ovejas cruzando la ruta",
    ],
    Hazard.PEATON: [
        "hay gente caminando al costado",
        "hay una persona en la ruta",
        "hay un peatón en la banquina",
        "va caminando gente por el camino",
    ],
    Hazard.VEHICULO_DETENIDO: [
        "hay un camión parado en la ruta",
        "hay un auto detenido en la calzada",
        "hay un vehículo averiado sobre la ruta",
        "alguien quedó parado en el carril derecho",
    ],
    Hazard.BACHE: [
        "la ruta está hecha un colador de pozos",
        "hay un bache enorme en la calzada",
        "hay un pozo profundo en la ruta",
        "cuidado con el bache del carril derecho",
    ],
    Hazard.OBRA: [
        "están arreglando la ruta más adelante",
        "hay una obra en la ruta",
        "hay maquinaria trabajando en la calzada",
        "hay un desvío por obra",
    ],
    Hazard.CONTROL: [
        "nos van a parar en un control",
        "hay un control policial adelante",
        "hay gendarmería en la ruta",
        "hay un retén en la ruta",
    ],
    Hazard.NIEBLA: [
        "hay mucha niebla en la ruta",
        "la visibilidad es muy baja por la neblina",
        "hay humo sobre la calzada",
        "hay una cortina de niebla en el camino",
    ],
    Hazard.LLUVIA: [
        "está lloviendo muy fuerte",
        "la ruta está mojada y resbaladiza",
        "hay mucha agua sobre la calzada",
        "llueve y el asfalto resbala",
    ],
    Hazard.HIELO: [
        "está todo blanco de escarcha",
        "hay hielo sobre la calzada",
        "la ruta está congelada",
        "hay nieve en la ruta",
        "cuidado con el hielo en el asfalto",
    ],
    Hazard.DERRUMBE: [
        "se vino la montaña abajo",
        "hay un derrumbe en la ruta",
        "hubo un deslizamiento de tierra",
        "la ruta está tapada por un derrumbe",
    ],
    Hazard.CURVA: [
        "se viene una curva muy cerrada",
        "hay una curva peligrosa adelante",
        "viene una contracurva complicada",
        "atento a la curva cerrada",
    ],
    Hazard.CONTRAMANO: [
        "hay un loco manejando en contra",
        "viene un auto en contramano",
        "hay un vehículo en contra de la mano",
        "alguien viene en sentido contrario",
    ],
    Hazard.CRECIDA: [
        "el río creció y tapó la ruta",
        "hay una crecida en el cruce del río",
        "el agua del río está cruzando la ruta",
        "hay un badén inundado",
        "viene mucha agua por el río",
    ],
    Hazard.POLVO: [
        "hay mucho polvo en suspensión",
        "no se ve nada por el polvo",
        "hay una nube de tierra en la ruta",
        "el polvo no deja ver el camino",
        "levantó tierra y no se ve nada",
    ],
}

#: Frases de conductor que NO son peligro. Son el conjunto de control: si el
#: clasificador les asigna un peligro con confianza alta, hay un falso positivo.
FRASES_RUIDO: list[str] = [
    "che falta mucho",
    "paramos a cargar nafta",
    "el tanque está por la mitad",
    "me gusta el asado",
    "llegamos en dos horas",
    "ponete el cinturón",
    "bajate a comprar algo",
    "pasame el mate",
    "qué lindo día",
    "apagá la radio",
    "bajá un poco la ventanilla",
    "tenemos que comer algo",
    "llamame cuando llegues",
    "subí la música más fuerte",
    "vamos a parar en el próximo pueblo",
    "el nene se durmió",
    "subí el aire acondicionado",
    "cuánto falta para el cruce",
    "el motor anda bien",
    "vamos bien de tiempo",
    "tengo sed",
    "esa nube es linda",
]
