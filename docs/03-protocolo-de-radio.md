# 03 — Protocolo de Radio

## Parámetros de capa física

| Parámetro | Valor | Justificación |
|---|---|---|
| Frecuencia | 915 MHz (banda ISM 902–928 MHz) | De uso libre en Argentina; la banda que soportan los módulos LoRa de 915 MHz |
| Spreading factor | **SF10** (provisional) | Compromiso entre alcance de 5 km con obstrucción parcial y tiempo de canal |
| Ancho de banda | 125 kHz | Canal estándar; además el máximo de los módulos SX1262 comunes |
| Tasa de codificación | 4/5 | Corrección de errores por defecto; aumenta la robustez a un costo moderado |
| Preámbulo | 8 símbolos | Estándar |
| CRC | Habilitado | Integridad de trama |
| Encabezado | Explícito | Permite que el largo del payload varíe |
| Sync word | Valor privado | Reduce la interferencia con tráfico LoRa ajeno |
| Potencia de TX | 20 dBm (provisional) | Deben confirmarse los límites legales en Argentina — ver [05-hardware.md](05-hardware.md) |
| CAD | Habilitado antes de transmitir | Escuchar antes de hablar |

### Compromiso del spreading factor

| SF | Tasa nominal | ToA de una trama de 17 bytes | Alcance práctico |
|---|---|---|---|
| SF7 | ~5,5 kbps | ~50 ms | 2–5 km, requiere línea de vista limpia |
| SF9 | ~1,76 kbps | ~165 ms | 6–10 km, línea de vista rural |
| **SF10** | **~980 bps** | **~340 ms** | **Mejor candidato para terreno montañoso con obstrucción** |
| SF12 | ~293 bps | ~1,25 s | Alcance máximo, pero cada alerta ocupa el canal durante segundos |

Se parte de SF10 porque tolera obstrucción parcial sin volver inaceptablemente
caro un alerta con flooding. **Esto debe validarse con mediciones de campo** en
los caminos reales; si los enlaces resultan marginales, pasar a SF11 duplica
aproximadamente el tiempo de aire pero agrega un margen considerable.

### Costo de canal de una alerta para todo el comboy

A SF10, una trama de 17 bytes ocupa el canal unos 340 ms.

| Escenario | Transmisiones | Tiempo de canal |
|---|---|---|
| Difusión simple, sin reemisión | 1 | ~0,34 s |
| El emisor repite dos veces | 3 | ~1,0 s |
| Flood completo, 6 nodos reemiten una vez cada uno | 6 | ~2,0 s |
| Flood más retransmisiones del emisor | ~9 | ~3,1 s |

Con peligros que ocurren unas pocas veces por hora, se espera un ciclo de
trabajo del canal bastante por debajo del 1%. La congestión del canal no es una
preocupación a esta escala; la simplicidad del mecanismo de confiabilidad vale
más que la optimización del tiempo de aire.

## Formato de trama

Todos los campos multibyte son little-endian.

| Offset | Campo | Tipo | Descripción |
|---|---|---|---|
| 0 | `version` | u8 | Versión del protocolo, actualmente `1` |
| 1 | `msg_type` | u8 | `1` ALERTA, `2` HEARTBEAT, `3` JOIN, `4` LEAVE |
| 2–5 | `alert_id` | u32 | Identificador aleatorio, único por alerta. Clave de deduplicación. Cero en tramas que no son alertas |
| 6 | `origin_id` | u8 | ID de nodo configurado del emisor original |
| 7 | `origin_role` | u8 | `0` líder, `1` seguidor |
| 8 | `hop` | u8 | Incrementado por cada nodo que reemite |
| 9 | `ttl` | u8 | Saltos restantes permitidos |
| 10 | `hazard` | u8 | Código de tipo de peligro — ver [06-codigos-y-logs.md](06-codigos-y-logs.md) |
| 11 | `lane` | u8 | Código de carril o posición en la ruta |
| 12 | `dist_km` | u8 | Distancia declarada por el conductor, `0`–`15` km, `255` desconocida |
| 13 | `urgency` | u8 | `0` info, `1` precaución, `2` detenerse (severidad ascendente) |
| 14 | `confidence` | u8 | `0` baja, `1` alta |
| 15–16 | `crc16` | u16 | CRC-16/CCITT sobre los bytes 0–14 — variante exacta en [CRC de la trama](#crc-de-la-trama) |

**Total: 17 bytes.**

La trama es deliberadamente de tamaño fijo. Un payload de largo variable
complicaría el decodificador sin ningún beneficio, dado que el vocabulario de
peligros es cerrado y pequeño.

### CRC de la trama

El diseño original decía solo "CRC-16/CCITT", lo cual es ambiguo: ese nombre
cubre varias variantes (CCITT-FALSE, XMODEM, KERMIT, X-25, ...) que difieren en
el valor inicial, la reflexión de entrada/salida y el xor de salida.

La implementación usa **CRC-16/CCITT-FALSE**:

| Parámetro | Valor |
|---|---|
| Polinomio | `0x1021` |
| Init | `0xFFFF` |
| RefIn | no |
| RefOut | no |
| XorOut | `0x0000` |

Vector de verificación obligatorio: los bytes ASCII de `"123456789"` deben dar
`0x29B1`.

> **Esto fue una elección de implementación, no una decisión de diseño.** Surgió
> al programar el códec, no en la etapa de diseño del protocolo. Como los dos
> extremos de la comunicación son código propio, cualquier variante funcionaría
> mientras ambos lados coincidan. Debe revisarse si alguna vez hay que
> interoperar con un sistema externo (otro firmware, un gateway, una librería de
> terceros) o si se prefiere otra variante por razones de ecosistema. Es una
> decisión consciente y reversible, no un descuido.

### Lo que *no* está en la trama

- **Ninguna transcripción.** Las palabras habladas nunca salen del nodo de
  origen. Esto es a la vez una decisión de ancho de banda y una decisión de
  privacidad (D8).
- **Ninguna coordenada.** No hay GPS (D5) y la ubicación es solo distancia (D9).
- **Ningún timestamp absoluto.** No hay reloj confiable (D6). La frescura es
  implícita: una alerta está activa 180 segundos desde el momento en que se
  recibe.
- **Ningún audio.** Jamás.

## Tipos de mensaje

| Tipo | Propósito | Frecuencia |
|---|---|---|
| `ALERTA` | Reportar un peligro al comboy | A pedido del conductor |
| `HEARTBEAT` | Anunciar presencia y mantener el roster | Cada 30–60 s por nodo, con jitter |
| `JOIN` | Anunciar que un nodo acaba de arrancar | Una vez al inicio |
| `LEAVE` | Anunciar un apagado limpio | Una vez al apagado |

`JOIN` y `LEAVE` son comodidades. El roster no depende de ellos: un nodo que
deja de mandar heartbeats termina marcado como ausente, y uno que arranca se
detecta en el siguiente heartbeat. Esto vuelve al roster robusto ante cortes de
energía, que es el caso común en un vehículo.

## Flooding controlado

El flooding es el único mecanismo que entrega tres requisitos a la vez: broadcast
confiable (D3), alcance más allá del rango directo, y acuse de recibo implícito.

### Algoritmo

```
Al recibir una trama de ALERTA F:

  si F.alert_id está en la caché de deduplicación:
      descartar F
      registrar "duplicado escuchado del origen X" para el acuse implícito
      return

  agregar F.alert_id a la caché de deduplicación
  entregar F a la FSM de alertas (es la primera vez que la vemos)

  si F.ttl == 0:
      return

  demora = backoff(F)
  tras la demora:
      si el canal está libre (CAD):
          reemitir F con hop+1 y ttl-1
      si no:
          esperar un intervalo más con jitter, reintentar una vez, y abandonar
```

### Caché de deduplicación

- Indexada por `alert_id`.
- Las entradas viven 180 segundos, igual que la vida de la alerta, más un
  pequeño margen de seguridad. Después de expirar, el mismo ID podría en teoría
  volver a difundirse, pero `alert_id` es un valor aleatorio de 32 bits y las
  colisiones son despreciables a esta tasa de eventos.
- Alcanza con un búfer circular de tamaño fijo de unos pocos cientos de entradas.

### Acuse de recibo implícito

El nodo de origen no necesita tramas de ACK explícitas. Simplemente escucha.

| Observación | Interpretación |
|---|---|
| Una reemisión del nodo X, cuyo registro está presente en el roster | X recibió la alerta |
| Ninguna reemisión del nodo Y después de la ventana esperada | Y probablemente no la recibió |

Después de la transmisión inicial, el origen espera una ventana de asentamiento
(unos pocos segundos, escalada al tamaño del flood) y revisa qué miembros del
roster escuchó. Para los que no escuchó, retransmite la alerta una o dos veces
más con un flood nuevo. Dos retransmisiones es el tope del MVP; más reintentos
consumen tiempo de canal y rara vez ayudan en un enlace marginal.

Este diseño elimina por completo la necesidad de un tipo de mensaje ACK. La
reemisión *es* el acuse de recibo.

### Por qué no ACKs explícitos

Con 6 nodos y un líder, ACKs explícitos implicarían hasta 6 tramas de
confirmación por alerta, más un protocolo de ventana, más estado de reintento por
par. Eso es bastante más código y más tráfico de canal que el flooding, y aun
así necesitaría un mecanismo de respaldo para el caso en que el propio ACK se
pierda. El flooding es más simple y su redundancia es una ventaja en lugar de un
costo.

### Alcance más allá del rango directo — gratis

Si el vehículo de cola no puede escuchar al líder directamente porque hay una
loma en el medio, un vehículo intermedio reemite y el mensaje llega. Esto es
entrega multi-salto sin tablas de ruteo, sin descubrimiento de rutas y sin estado
de topología. Dado que el terreno de montaña vuelve *normal* la pérdida
intermitente de línea de vista (D5), que esto salga naturalmente del mecanismo
de confiabilidad es la razón principal por la que se eligió flooding.

`ttl` se inicializa en **3**, más que suficiente para un comboy de 6, y evita que
un nodo mal configurado propague tramas indefinidamente.

## Prioridad y arbitraje de canal

LoRa no tiene acceso múltiple por detección de portadora con detección de
colisiones, ni adelantamiento a mitad de una transmisión. La prioridad se reduce
entonces a **quién gana la carrera por el canal**, implementado con backoff
diferenciado.

| Emisor | Backoff antes de la primera transmisión | Backoff antes de reemitir |
|---|---|---|
| Líder | 0–150 ms | 0–200 ms |
| Seguidor | 150–600 ms | 200–800 ms |

Además:

- Todos los nodos ejecutan **CAD** antes de transmitir. Si el canal está ocupado,
  esperan y reintentan una vez.
- Cuando un nodo recibe una trama marcada `origin_role = líder` mientras tiene su
  propia alerta pendiente de transmisión, **retira su transmisión pendiente** y
  reemite la alerta del líder en su lugar. Al conductor local se le pide que
  repita después de que el canal se asiente.
- La prioridad es una convención, no una imposición. Si la trama del líder
  colisiona con la de un seguidor, ambas se pierden y la lógica de
  retransmisión se recupera. Esto es aceptable dada la rareza de los eventos.

Dos reportes de peligro simultáneos se manejan por deduplicación: llevan
valores distintos de `alert_id`, así que ambos sobreviven y ambos se anuncian. El
LED muestra la urgencia más alta.

## Roster y heartbeats

Cada nodo difunde un `HEARTBEAT` cada 30–60 segundos, con el intervalo
randomizado por nodo para evitar ráfagas sincronizadas de todos los vehículos a
la vez.

La entrada del roster de un par registra:

| Campo | Significado |
|---|---|
| `node_id` | Identidad configurada |
| `role` | Líder o seguidor |
| `last_seen` | Timestamp monotónico de la última trama recibida de este nodo |
| `state` | `presente` o `ausente` |

Un nodo se marca como `ausente` tras tres intervalos de heartbeat perdidos. Esto
se registra como un evento informativo, no como una alarma: en terreno de
montaña, perder un par temporalmente es lo esperado. El roster existe
principalmente para que el originador pueda juzgar si su alerta llegó a todos.

Los heartbeats también le dan a cada nodo una vista pasiva del tamaño del
comboy, que es contexto útil en los logs y para funcionalidades futuras.

## Expiración de la alerta

No hay mensaje explícito de "vía libre" en el MVP (D7). Una alerta expira
**180 segundos después de su emisión**.

- El origen marca la alerta al momento de transmitir y arranca su propio
  temporizador de 180 s.
- Los nodos receptores arrancan su temporizador al recibir. El error introducido
  por la latencia de transmisión es menor a un segundo y es irrelevante a esta
  escala de tiempo.
- Al expirar, el LED se apaga y la expiración se registra.
- Un peligro nuevo reportado tras la expiración produce un `alert_id` nuevo y un
  anuncio fresco.

### Limitación conocida

Un peligro que se despeja a los 20 segundos igual ocupa el LED durante 180
segundos, y un nodo que se incorpora al comboy después de que la alerta fue
difundida nunca se entera. Un mensaje manual de "vía libre" y la reanunciación
periódica mientras la alerta está activa resolverían ambas cosas. Las dos están
explícitamente diferidas — ver [07-riesgos.md](07-riesgos.md) y
[08-hoja-de-ruta.md](08-hoja-de-ruta.md).

## Nota regulatoria

La operación en 902–928 MHz en Argentina está sujeta a la regulación de ENACOM.
La potencia de transmisión, el ancho de banda y las aplicaciones permitidas están
restringidos, y usar una configuración de 20 dBm sin confirmar los límites
aplicables puede resultar no conforme. Esto debe verificarse con la regulación
vigente y, si corresponde, con un profesional habilitado, antes de cualquier
despliegue en campo más allá de pruebas de banco. Ver
[05-hardware.md](05-hardware.md) para la discusión del lado del hardware.
