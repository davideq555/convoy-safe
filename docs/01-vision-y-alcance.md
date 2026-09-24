# 01 — Visión y Alcance

## Problema

Un convoy de 2 a 6 vehículos circula junto por caminos de montaña en Argentina.
Esos caminos no tienen cobertura celular, y el convoy no cuenta con acceso a
internet ni con receptores GPS. Los vehículos pueden llegar a separarse hasta
unos 5 km en total.

Cuando el conductor que va adelante encuentra un peligro en la ruta —un
accidente, piedras caídas, un derrumbe, un animal, un vehículo detenido, hielo,
niebla— los conductores que vienen detrás no tienen forma confiable de enterarse
a tiempo para reaccionar. Estar 1 a 5 km atrás da entre 40 segundos y 3 minutos
de margen a velocidades de camino de montaña, pero solo si la advertencia
efectivamente llega.

Las alternativas existentes son insuficientes:

- **Radio de voz (VHF/handy)**: requiere una banda licenciada o un canal
  compartido, no ofrece datos estructurados, no registra eventos y no permite
  procesamiento automático.
- **Celular**: no existe en esas rutas.
- **Bocina o luces de freno**: funcionan solo a distancia visual, que el terreno
  anula con facilidad.

## Objetivo

Darle a cada vehículo del convoy advertencia automática, estructurada, sonora y
visual de los peligros reportados por cualquier otro vehículo, usando
únicamente hardware embarcado y un enlace de radio de uso libre, sin ninguna
infraestructura.

## Escenario principal

1. El líder dobla una curva y encuentra piedras sobre el carril derecho, unos
   2 km delante de los vehículos que vienen atrás.
2. El conductor dice: *"Atención comboy, hay piedras en el carril derecho a dos
   kilómetros."*
3. El nodo detecta la wake word, transcribe el enunciado y lo clasifica en el
   código estructurado
   `{peligro: PIEDRAS, carril: DERECHO, dist_km: 2, urgencia: PRECAUCION, confianza: ALTA}`.
4. El código se difunde por LoRa a todo el convoy.
5. Cada nodo receptor pronuncia la advertencia en voz alta en español y enciende
   un LED ámbar. La alerta permanece activa 180 segundos y luego expira.

## Requisitos funcionales

| ID | Requisito |
|---|---|
| RF1 | Cada nodo debe detectar la wake word "atención comboy" con el vehículo en movimiento |
| RF2 | Después de la wake word, el nodo debe capturar el enunciado siguiente y transcribirlo localmente |
| RF3 | La transcripción debe clasificarse en un código de peligro estructurado |
| RF4 | El código debe difundirse a todos los demás nodos del convoy |
| RF5 | La alerta debe retransmitirse cuando no se confirma su recepción |
| RF6 | Las transmisiones del líder deben tener prioridad sobre las de los seguidores |
| RF7 | Cada nodo receptor debe sintetizar la advertencia como habla en español |
| RF8 | Cada nodo receptor debe indicar una alerta activa mediante un LED |
| RF9 | Todo evento significativo debe escribirse en un log de texto plano |
| RF10 | Las alertas activas deben expirar automáticamente a los 180 segundos de su emisión |
| RF11 | Los nodos deben descubrirse entre sí y mantener el conocimiento de la membresía del convoy |

## Requisitos no funcionales

| ID | Requisito |
|---|---|
| RNF1 | El sistema debe operar sin internet, sin GPS y sin infraestructura |
| RNF2 | Una advertencia hablada debe llegar al último vehículo bastante antes de que ese vehículo llegue al peligro |
| RNF3 | El sistema debe degradarse con elegancia cuando el terreno interrumpe la línea de vista |
| RNF4 | El sistema debe correr en una Raspberry Pi 4 (8 GB) sin hardware acelerador |
| RNF5 | Todo el procesamiento debe ser local y offline |
| RNF6 | El audio nunca debe transmitirse por el enlace de radio ni persistirse |

## No-objetivos (MVP)

- Sin detección de somnolencia del conductor. La cámara está prevista en el plan
  de hardware, pero la funcionalidad queda diferida.
- Sin detección visual automática de peligros. La cámara apuntará al conductor,
  no al camino (ver [05-hardware.md](05-hardware.md)).
- Sin LLM en el camino crítico. La clasificación usa embeddings y reglas; el LLM
  queda diferido para el fallo elegante (ver [04-audio-e-ia.md](04-audio-e-ia.md)).
- Sin GPS, sin coordenadas, sin integración con mapas.
- Sin internet, sin nube, sin telemetría remota.
- Sin botones físicos.
- Sin logging de nivel auditoría: sin timestamps confiables, sin cadena de
  hashes, sin firmas.
- Sin mensaje manual de "vía libre". Las alertas expiran por timeout.
- Sin liderazgo dinámico. El líder queda fijo por configuración.
- Sin tablas de ruteo multi-salto. El alcance se logra por flooding.

## Presupuesto de tiempo de reacción

Este presupuesto es la razón por la que varias decisiones de diseño resultan
aceptables.

| Distancia en el convoy | Tiempo a 60 km/h | Tiempo a 90 km/h |
|---|---|---|
| 1 km | 60 s | 40 s |
| 3 km | 180 s | 120 s |
| 5 km | 300 s | 200 s |

Un pipeline completo de voz a advertencia que tarde entre 5 y 10 segundos —wake
word, VAD, STT, clasificación, transmisión, síntesis— consume solo una fracción
del margen disponible. Esto es lo que hace viable el reconocimiento de habla
local, aun estando lejos de ser "tiempo real" en el sentido de milisegundos.

## ¿Por qué no usar directamente radio de voz?

Un enlace de radio de voz, licenciado o de uso libre, transportaría voz real.
Se descarta porque no ofrece:

- payload estructurado, y por lo tanto no permite indicación por LED ni logging
  automáticos,
- arbitraje de canal ni acuse de recibo,
- identidad por nodo dentro del flujo de datos,
- ningún camino hacia procesamiento automático o funcionalidades futuras.

El enfoque de código estructurado cuesta un poco de expresividad y a cambio
compra confiabilidad, observabilidad y extensibilidad.
