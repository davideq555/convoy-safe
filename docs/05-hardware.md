# 05 — Hardware

## Lista de materiales por nodo

| Ítem | Recomendación | Notas |
|---|---|---|
| Computadora | **Raspberry Pi 4 Model B, 8 GB** | Definido por el proyecto |
| Almacenamiento | microSD de 32 GB clase A2, o mejor un SSD por USB | Ver "Almacenamiento" más abajo |
| Radio LoRa | HAT con **SX1262** (por ejemplo Waveshare LoRa HAT) | Preferir SX1262 sobre el viejo SX1276 |
| Antena | Antena de 915 MHz con conector y base, **montada fuera del vehículo** | Crítico: ver "Antena" |
| Micrófono | Array de 2 micrófonos (por ejemplo ReSpeaker) o micrófono de solapa | El factor decisivo es el desempeño con ruido de cabina |
| Salida de audio | Amplificador HAT (por ejemplo MAX98357A) + parlante, o parlante USB | La Pi no tiene salida de audio analógica útil |
| Indicador | LED RGB (WS2812 o similar) montado en el tablero | Ver el mapeo de estados en [04-audio-e-ia.md](04-audio-e-ia.md#indicador-led) |
| Fuente | Convertidor DC-DC **automotriz** 12 V → 5 V, 3 A mínimo | Ver "Energía" |
| Enfriamiento | Disipador + ventilador, con ventilación en el gabinete | Ver "Térmica" |
| Gabinete | Caja con ventilación, fijada lejos del calor del motor | — |
| Cámara (diferida) | Módulo de cámara o webcam USB, con LEDs IR | Solo para la futura detección de somnolencia |

## Radio: por qué SX1262 y no SX1276

| Aspecto | SX1262 | SX1276 |
|---|---|---|
| Sensibilidad | Mejor (~−148 dBm a SF12) | Peor |
| Consumo en recepción | Menor | Mayor |
| Rango de frecuencia | 150–960 MHz | 137–1020 MHz |
| CAD | Sí, con mejor desempeño | Sí |
| Soporte de la comunidad | Creciente | Maduro pero envejecido |

Para un enlace de 5 km en terreno montañoso, cada dB de sensibilidad cuenta. El
SX1262 además consume menos, lo que importa en un nodo alimentado desde el
sistema eléctrico del vehículo.

## Antena: el error más común y más caro

**La antena debe montarse fuera del vehículo.** La carrocería metálica es una
jaula de Faraday: una antena de 915 MHz dentro de la cabina puede perder entre 10
y 20 dB respecto de una montada en el techo o el baúl.

Ese margen es exactamente el que se necesita para cubrir los 5 km en terreno con
obstrucción. Montar la antena adentro puede convertir un enlace funcional en uno
inutilizable, y el síntoma va a aparecer únicamente en condiciones de ruta, que
es el peor lugar para descubrirlo.

Recomendaciones:

- Antena de 915 MHz con la impedancia y el conector correctos para el módulo.
- Montaje en el techo o, como mínimo, sobre el baúl.
- Cable coaxial corto y de buena calidad: cada metro de cable barato agrega
  pérdida.
- Verificar la ROE (relación de onda estacionaria) del conjunto si es posible.

## Energía: esto no es un cargador de celular

La red eléctrica de un vehículo es hostil para la electrónica:

| Fenómeno | Magnitud | Consecuencia si no se protege |
|---|---|---|
| Picos de arranque (cranking) | La tensión cae a 6–8 V | La Pi se reinicia o se corrompe la SD |
| Load dump | Picos de decenas de volts | Destrucción del convertidor y de la Pi |
| Ruido de alternador | Rizado de alta frecuencia | Reinicios aleatorios, fallas de audio |

**No usar un cargador USB de auto.** Hace falta un convertidor DC-DC de grado
automotriz:

- Entrada nominal de 12 V con rango de operación amplio (por ejemplo 9–36 V).
- Protección contra load dump, inversión de polaridad y sobretensión.
- Salida de 5 V con al menos 3 A, porque la Pi 4 más periféricos puede superar
  los 2 A de pico.
- Protección por fusible en la entrada.

La Pi 4 consume entre 3 y 7 W típicamente, y puede acercarse a 10 W con
periféricos. A 5 V eso es hasta 2 A de pico; el margen a 3 A es necesario.

## Térmica

Una Raspberry Pi 4 dentro de un vehículo, en verano argentino y bajo el sol,
puede superar los 80 °C y empezar a reducir su frecuencia (*throttling*). El
síntoma es sutil: el sistema sigue funcionando, pero el STT y el TTS se vuelven
lentos, justo cuando más se los necesita.

Mitigaciones:

- Disipador y ventilador activo sobre el SoC.
- Gabinete con ventilación real, no sellado.
- Ubicación alejada del motor y de la exposición directa al sol.
- Verificar la temperatura bajo carga antes de desplegar.

## Almacenamiento

- La microSD es el componente menos confiable de todo el sistema, y el corte de
  energía en un vehículo es lo habitual, no la excepción.
- Opciones, de mejor a peor:
  1. SSD por USB como disco raíz, con la SD solo para el arranque.
  2. Sistema de archivos raíz de solo lectura, con las escrituras de log
     dirigidas a tmpfs y volcadas periódicamente.
  3. MicroSD de clase A2 de buena calidad, con sistema de archivos tolerante y
     rotación de logs agresiva.
- Los logs deben rotar y tener un tope de tamaño. Ver
  [06-codigos-y-logs.md](06-codigos-y-logs.md).

## Micrófono

El micrófono es probablemente **el punto más frágil de todo el sistema**, más
incluso que la radio. A 90–100 km/h con ruido de ruta, un micrófono USB barato
tiene una relación señal-ruido muy pobre, y la wake word depende de esa señal.

Opciones, en orden de preferencia:

1. **Array de micrófonos con beamforming** (por ejemplo ReSpeaker de 2 o 4
   micrófonos), apuntado al conductor. El beamforming mejora la relación
   señal-ruido de forma sustancial.
2. **Micrófono de solapa** o de close-talk. Es la opción más robusta acústicamente
   pero requiere que el conductor lo use.
3. **Micrófono USB simple** con supresión de ruido por software. Es la opción de
   menor costo y la que más probablemente falle.

La ubicación importa tanto como el hardware: lejos del viento de la ventanilla,
orientado hacia la boca del conductor, y no apoyado sobre superficies que
vibren.

## Cámara (diferida)

La cámara está prevista para una futura detección de somnolencia del conductor,
y hay que diseñarla desde ahora aunque no se implemente todavía.

Puntos a tener en cuenta cuando se aborde:

- **Apuntará al conductor, no al camino.** Eso significa que no puede usarse como
  dashcam ni para detección de peligros en la ruta. Son objetivos mutuamente
  excluyentes con una sola cámara.
- **De noche no funciona sin infrarrojo.** Las webcams comunes tienen filtro
  IR-cut y no ven en oscuridad. La detección de somnolencia nocturna requiere una
  cámara sin filtro IR más iluminación infrarroja.
- **Carga de CPU.** Sin acelerador, el procesamiento de visión compite
  directamente con Porcupine, Vosk y Piper. Habrá que elegir una frecuencia baja
  de análisis (por ejemplo 5–10 FPS a baja resolución) y un modelo liviano.
- **Privacidad.** El video del conductor es un dato personal sensible. Debe
  procesarse localmente y no persistirse por defecto.

## Regulación en Argentina

La banda de 902–928 MHz es de uso libre en Argentina bajo regulación de ENACOM,
pero con límites de potencia, ancho de banda y aplicación. Los puntos a verificar
con la normativa vigente antes de cualquier despliegue en campo:

- Potencia máxima de transmisión permitida (típicamente expresada en EIRP).
- Si la técnica de espectro ensanchado de LoRa califica dentro de las categorías
  permitidas.
- Restricciones de ciclo de trabajo, si las hubiera, para esta banda.
- Requisitos de equipamiento homologado, si aplican.

**Esto no es un detalle burocrático menor.** Operar fuera de los límites
permitidos puede significar interferencia a servicios primarios y exposición a
sanciones. La recomendación es confirmar los parámetros aplicables antes de
pasar de pruebas de banco a pruebas en ruta, y ajustar `tx_power_dbm` en
consecuencia.

## Instalación en el vehículo

Consideraciones de montaje:

- **Antena**: techo o baúl, exterior, cable coaxil corto.
- **Electrónica**: dentro de la cabina, protegida de calor, humedad y polvo.
- **Micrófono**: orientado al conductor, protegido del viento directo.
- **Parlante**: suficientemente audible por encima del ruido de ruta.
- **LED**: visible en el campo visual del conductor sin quitarle atención del
  camino.
- **Energía**: alimentación con llave de contacto, o con un interruptor dedicado,
  para no drenar la batería con el vehículo apagado.

## Ítems todavía abiertos

| Ítem | Motivo |
|---|---|
| Modelo exacto de micrófono | Se decide con pruebas reales de ruido en cabina |
| Potencia de transmisión definitiva | Depende de la verificación regulatoria |
| Spreading factor definitivo | Depende de mediciones de alcance en los caminos reales |
| MicroSD versus SSD | Depende del presupuesto y de la tolerancia a fallas deseada |
| Alimentación conmutada por llave | Depende del vehículo y del método de instalación |
