# 06 — Códigos y Logs

## Catálogo de códigos de peligro

Cada peligro se codifica en un byte (`hazard`), definido de forma cerrada. Un
vocabulario cerrado es lo que permite que el clasificador sea determinista y que
la trama tenga tamaño fijo.

| Valor | Código | Descripción | Texto para TTS |
|---|---|---|---|
| `0x00` | `DESCONOCIDO` | Peligro no identificado | "peligro no identificado" |
| `0x01` | `ACCIDENTE` | Accidente o choque | "accidente en la calzada" |
| `0x02` | `PIEDRAS` | Piedras u objetos sobre la ruta | "piedras en la calzada" |
| `0x03` | `ANIMAL` | Animal suelto | "animal sobre la calzada" |
| `0x04` | `PEATON` | Persona en la ruta o banquina | "persona sobre la ruta" |
| `0x05` | `VEHICULO_DETENIDO` | Vehículo detenido o averiado | "vehículo detenido en la ruta" |
| `0x06` | `BACHE` | Bache o pozo profundo | "bache en la calzada" |
| `0x07` | `OBRA` | Obra vial o maquinaria | "obra en la ruta" |
| `0x08` | `CONTROL` | Control policial o retén | "control en la ruta" |
| `0x09` | `NIEBLA` | Niebla, neblina o humo | "baja visibilidad por niebla" |
| `0x0A` | `LLUVIA` | Lluvia o calzada resbaladiza | "calzada resbaladiza por lluvia" |
| `0x0B` | `HIELO` | Hielo, escarcha o nieve | "hielo sobre la calzada" |
| `0x0C` | `DERRUMBE` | Derrumbe o deslizamiento | "derrumbe sobre la ruta" |
| `0x0D` | `CURVA` | Curva peligrosa | "curva peligrosa" |
| `0x0E` | `CONTRAMANO` | Vehículo en contramano | "vehículo en contramano" |
| `0x0F` | `CRECIDA` | Crecida de río o cruce inundado | "crecida del río" |
| `0x10` | `POLVO` | Polvo en suspensión | "baja visibilidad por polvo" |

Quedan 238 valores libres. El catálogo se amplía solo si aparece una necesidad
concreta y recurrente.

### Por qué `CRECIDA` no es `LLUVIA`

`LLUVIA` describe un problema de **tracción** —la calzada resbala— y la respuesta
es moderar la velocidad. Una crecida es un problema de **pasabilidad**: el agua
puede arrastrar el vehículo, y la respuesta es no cruzar. Son riesgos distintos y
por eso son códigos distintos.

### Por qué `POLVO` no es `NIEBLA`

Ambos reducen la visibilidad, pero la causa y el texto hablado difieren. `NIEBLA`
agrupa los fenómenos **atmosféricos** (niebla, neblina, humo); `POLVO` es
particulado levantado de la ruta —por un vehículo adelante o por una banquina
suelta—. Decir "niebla" cuando el conductor ve polvo sería engañoso.

### Compatibilidad hacia atrás

Un nodo que corra un catálogo anterior (hasta `0x0E`) y reciba `0x0F` o `0x10`
no falla: :func:`comboy.codes.as_hazard` lo degrada a `DESCONOCIDO` y la frase
sale como "peligro no identificado". Se pierde el detalle, nunca la alerta. Por
eso ampliar el catálogo es seguro en una red con versiones mezcladas.

## Códigos de carril

| Valor | Código | Texto para TTS |
|---|---|---|
| `0x00` | `SIN_ESPECIFICAR` | "" (se omite en la frase) |
| `0x01` | `IZQUIERDO` | "carril izquierdo" |
| `0x02` | `DERECHO` | "carril derecho" |
| `0x03` | `TODA_LA_RUTA` | "toda la ruta" |
| `0x04` | `BANQUINA` | "sobre la banquina" |
| `0x05` | `CALZADA` | "sobre la calzada" |

## Códigos de urgencia

| Valor | Código | Texto para TTS |
|---|---|---|
| `0x00` | `INFO` | "Solo informativo." |
| `0x01` | `PRECAUCION` | "Precaución." |
| `0x02` | `DETENERSE` | "Deténgase." |

## Códigos de confianza

| Valor | Código | Efecto en la frase |
|---|---|---|
| `0x00` | `BAJA` | La advertencia se prefija con "Posible" |
| `0x01` | `ALTA` | La advertencia se emite como afirmación |

## Distancia

`dist_km` es un byte que representa la distancia declarada por el conductor:

| Valor | Significado |
|---|---|
| `0` | "aquí mismo" / menos de 500 m |
| `1`–`15` | La cantidad de kilómetros declarada |
| `255` | Desconocida; la frase omite la distancia |

La distancia la estima el conductor. No hay GPS (D5) y no se infiere de la radio
ni del movimiento. Es una aproximación deliberada y suficiente: el objetivo es
que el conductor que viene atrás sepa que hay algo adelante, no darle una
coordenada.

## Ejemplo de codificación completo

Conductor dice:

> "Atención comboy, hay piedras en el carril derecho a dos kilómetros."

Resultado:

```
hazard     = 0x02  (PIEDRAS)
lane       = 0x02  (DERECHO)
dist_km    = 2
urgency    = 0x01  (PRECAUCION)
confidence = 0x01  (ALTA)
```

Frase que escuchan los receptores:

> "Piedras en la calzada, carril derecho, a 2 kilómetros. Precaución."

## Formato de logs (modo desarrollo)

> **Alcance:** logs de texto plano para desarrollo y prueba (D6). No son logs de
> auditoría. No hay timestamps confiables, no hay cadena de hashes y no hay
> firmas.

### Sin reloj confiable

La Pi 4 no tiene reloj con batería, y no hay GPS ni NTP. El reloj de pared,
entonces, es **poco confiable** hasta que alguien lo ajuste manualmente. Por eso
cada línea registra **dos marcas de tiempo**:

- **Reloj de pared**: útil solo si fue ajustado a mano; puede estar mal.
- **Tiempo de actividad monotónico**: milisegundos desde el arranque del proceso.
  Es la marca **confiable y ordenable** dentro de una sesión.

Además cada línea lleva un `boot_id`, para distinguir eventos de distintas
ejecuciones del sistema.

### Formato de línea

Formato propuesto, legible por humanos y fácil de filtrar con `grep` y `awk`:

```
<marca_de_pared> <uptime_ms> <boot_id> <nodo> <rol> <nivel> <evento> <clave=valor>...
```

Ejemplos:

```
2026-09-18T14:32:11.123 +0001234567 boot=7f3a node=3 role=follower INFO  boot          version=0.1.0 config=loaded local=192.168.25.159:45550
2026-09-18T14:32:12.004 +0001235448 boot=7f3a node=3 role=follower INFO  radio.init    sf=10 bw=125 freq=915000000 tx_dbm=20
2026-09-18T14:33:05.771 +0001289215 boot=7f3a node=3 role=follower INFO  wake_word     phrase="atencion comboy" score=0.87
2026-09-18T14:33:06.402 +0001289846 boot=7f3a node=3 role=follower INFO  capture.end   ms=631 reason=vad_silence
2026-09-18T14:33:07.510 +0001290954 boot=7f3a node=3 role=follower INFO  stt.result    ms=1108 text="hay piedras en el carril derecho a dos kilometros"
2026-09-18T14:33:07.521 +0001290965 boot=7f3a node=3 role=follower INFO  classify      hazard=PIEDRAS lane=DERECHO dist_km=2 urgency=PRECAUCION confidence=ALTA
2026-09-18T14:33:08.104 +0001291548 boot=7f3a node=3 role=follower INFO  alert.tx      alert_id=a7f3c9e1 hop=0 flood_attempt=1
2026-09-18T14:33:09.338 +0001292782 boot=7f3a node=3 role=follower INFO  alert.echo    alert_id=a7f3c9e1 from_node=1 role=leader rebroadcast=true
2026-09-18T14:33:09.402 +0001292846 boot=7f3a node=3 role=follower INFO  alert.ack     alert_id=a7f3c9e1 heard_from=1,2,4 missing=5
2026-09-18T14:33:09.450 +0001292894 boot=7f3a node=3 role=follower WARN  roster.absent node=5 last_seen_ms=48210
2026-09-18T14:36:08.104 +0001308342 boot=7f3a node=3 role=follower INFO  alert.expired alert_id=a7f3c9e1 active_ms=180000
```

### Catálogo de eventos

| Evento | Nivel | Descripción |
|---|---|---|
| `boot` | INFO | Arranque del proceso, versión, resultado de la carga de configuración y dirección local (`local=`) cuando el transporte es UDP: es el dato que el otro nodo necesita para apuntarle |
| `shutdown` | INFO | Apagado limpio |
| `radio.init` | INFO | Inicialización de la radio y parámetros activos |
| `radio.error` | ERROR | Falla de la radio |
| `frame.invalid` | WARN | Trama descartada por longitud, versión o CRC inválidos |
| `wake_word` | INFO | Wake word detectada, con puntaje |
| `capture.start` | DEBUG | Comienzo de captura |
| `capture.end` | DEBUG | Fin de captura, con duración y motivo |
| `stt.result` | INFO | Transcripción obtenida |
| `stt.empty` | WARN | No se obtuvo transcripción usable |
| `classify` | INFO | Código resultante de la clasificación, con similitud y margen |
| `classify.unknown` | WARN | No se reconoció ningún peligro del catálogo, o la frase lo negaba |
| `classify.unavailable` | WARN | Servicio de embeddings no disponible o con fallo; se clasifica como `DESCONOCIDO` con confianza baja |
| `embedding.index` | INFO | Construcción del índice de referencia en varios lotes hacia Ollama; registra la cantidad de frases (`phrases=`) y de peticiones (`batches=`) |
| `alert.tx` | INFO | Alerta transmitida |
| `alert.rx` | INFO | Alerta recibida de otro nodo |
| `alert.echo` | DEBUG | Reemisión escuchada de otro nodo (acuse implícito) |
| `alert.ack` | INFO | Resumen de quiénes se escucharon y quiénes no |
| `alert.duplicate` | DEBUG | Trama duplicada descartada por la caché |
| `alert.rebroadcast` | DEBUG | Este nodo reemitió una alerta |
| `alert.expired` | INFO | La alerta expiró tras 180 s |
| `heartbeat.tx` | DEBUG | Heartbeat enviado |
| `heartbeat.rx` | DEBUG | Heartbeat recibido |
| `roster.present` | INFO | Nodo detectado como presente |
| `roster.absent` | WARN | Nodo marcado como ausente |
| `tts.play` | INFO | Reproducción de TTS, con el texto |
| `tts.unavailable` | WARN | Motor de TTS no disponible; el nodo continúa sin audio |
| `mic.unavailable` | WARN | Micrófono no disponible (`arecord` ausente o falló); el nodo continúa sin captura |
| `wakeword.unavailable` | WARN | Modelo de wake word ausente o no cargable; la detección queda desactivada |
| `led.state` | DEBUG | Cambio de estado del LED |
| `power.low` | ERROR | Tensión de alimentación fuera de rango, si se mide |

Los eventos de nivel DEBUG deberían poder desactivarse con `log.level` para no
saturar la SD durante el uso normal.

### Rotación y límites

El almacenamiento no puede crecer sin control, y la SD es el componente menos
confiable del nodo.

- Rotación diaria o por tamaño (por ejemplo 10 MB por archivo).
- Máximo de archivos retenidos (por ejemplo 5).
- En operación normal, `log.level: info` para reducir escrituras.
- Evaluar dirigir los logs a tmpfs y volcarlos periódicamente, o directamente a
  un SSD por USB.

### Consulta de logs en campo

Como no hay internet, la forma práctica de revisar los logs en la ruta es:

- Un script que imprima el resumen de la última sesión.
- Un punto de acceso WiFi temporal en la Pi, para conectarse con un celular o
  notebook y leer los archivos.
- Extraer la SD o el SSD y leerlo en otro equipo.

## Trabajo de auditoría diferido

Cuando la auditoría pase a ser prioridad (D6, hoy diferida), harán falta al
menos estos componentes, en este orden:

1. **RTC de hardware (DS3231) por nodo**, para tener hora real y confiable.
2. **Registro append-only con cadena de hashes**, para que la manipulación sea
   detectable: cada registro incluye el hash del anterior.
3. **Firma Ed25519 por nodo emisor**, para no repudio: poder demostrar
   criptográficamente qué nodo emitió qué alerta.
4. **Sincronización aproximada entre nodos**, para que los registros de distintos
   vehículos se puedan correlacionar.

Nada de esto tiene sentido sin el paso 1. Sin una fuente de tiempo real, los
timestamps son relativos a la sesión y no sirven como evidencia.

## Privacidad

- **Nunca se persiste audio.** Solo se registra la transcripción (D8).
- La transcripción es texto del conductor en su propio vehículo, lo que reduce
  fuertemente el riesgo desde el punto de vista de la Ley 25.326 de Protección de
  Datos Personales.
- Aun así, conviene que los logs tengan rotación corta y que el conductor sepa
  que sus frases quedan registradas.
- La futura cámara de somnolencia introduce una categoría de dato más sensible:
  video del conductor. Debe procesarse localmente y no persistirse por defecto.
