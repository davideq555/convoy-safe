# 08 — Hoja de Ruta

## Principio rector

Los tres riesgos críticos (R1 wake word como único camino de entrada, R2 ruido de
cabina, R4 antena mal montada) **solo se validan en campo**. Pero hay una
segunda realidad que ordena el trabajo: **la mayor parte del sistema se puede
construir y validar hoy**, sin LoRa, usando el banco de pruebas descrito en
[09-banco-de-pruebas.md](09-banco-de-pruebas.md).

El orden es software primero, radio después. Así se llega al banco de radio con
el protocolo ya probado y solo queda medir el enlace físico.

## Definición del MVP

El MVP es la suma de las **Fases 0 a 6**. Al terminarlas, dos vehículos equipados
deberían poder viajar en un comboy de montaña y advertirse mutuamente peligros
por voz, sin internet, sin GPS y sin infraestructura.

Las Fases 0 a 4 **no requieren ningún hardware nuevo**: alcanzan el PC, la
Raspberry Pi y la red WiFi que ya existen.

---

## Etapa 1 — Software sobre UDP

No requiere LoRa. Se puede empezar hoy.

### Fase 0 — Esqueleto, roles y transporte

**Objetivo:** un solo programa con roles, que mueva una trama de 17 bytes por UDP
y que la Pi la pronuncie. Es el nivel L0.

**Entregables:**

- Estructura del proyecto Python y archivo de configuración.
- `Transport` con `UdpTransport`, `NullTransport` y `LossyTransport`.
- Codec de trama de 17 bytes con CRC-16.
- Logger en texto plano con el formato de
  [06-codigos-y-logs.md](06-codigos-y-logs.md#formato-de-línea).
- TTS en la Pi (primero `espeak-ng` para arrancar rápido, después Piper).

**Criterios de salida:**

- El PC envía una trama fija y la Pi la pronuncia correctamente.
- Ambos nodos registran el evento en su log.
- Una trama corrupta se descarta sin romper el proceso.

**Riesgos atacados:** R5, R19.

---

### Fase 1 — Clasificación semántica

**Objetivo:** convertir una frase escrita en un código de peligro. Es el nivel L1.

**Entregables:**

- Normalizador de texto en español (minúsculas, sin tildes, números a palabras).
- Modelo de embeddings multilingüe, con frases de ejemplo por código.
- Extractores por reglas de carril, distancia y urgencia.
- Cálculo de confianza.
- Conjunto de pruebas con frases reales, incluidas variantes coloquiales.

**Criterios de salida:**

- Acierto aceptable sobre el conjunto de pruebas.
- Ante la duda, el resultado es `DESCONOCIDO` con confianza baja — **nunca** un
  código incorrecto con confianza alta.
- El comando de entrada por texto funciona para depurar sin micrófono.

**Riesgos atacados:** R12, R13.

---

### Fase 2 — Pipeline de audio completo

**Objetivo:** hablarle al PC y que el sistema produzca el código correcto. Es el
nivel L2.

**Entregables:**

- Detector de wake word corriendo de forma continua.
- VAD para detectar el fin de frase.
- Integración de Vosk con el modelo en español.
- FSM de audio con half-duplex y confirmación local por TTS.
- Regla de adelantamiento: una alerta remota interrumpe la captura local.

**Criterios de salida:**

- El pipeline completo funciona de punta a punta.
- Sin auto-disparos durante la reproducción de TTS.
- Tasa de detección de wake word aceptable en un ambiente ruidoso.

**Riesgos atacados:** R1, R2, R19.

---

### Fase 3 — Protocolo completo y LED

**Objetivo:** que las alertas viajen de forma confiable y se muestren. Es el
nivel L3.

**Entregables:**

- Flooding con caché de deduplicación y límite de saltos.
- Backoff diferenciado por rol y CAD antes de transmitir.
- Acuse implícito por reemisión.
- Roster por heartbeats.
- FSM de alertas con expiración a 180 segundos.
- Indicador LED (el LED de actividad de la Pi alcanza para validar).

**Criterios de salida:**

- Una alerta emitida por cualquier nodo llega a todos los demás.
- Con `LossyTransport` al 10% de pérdida, las alertas siguen llegando o el
  sistema informa correctamente quién no las recibió.
- Con pérdida al 40%, el sistema falla de forma visible y ordenada, no en
  silencio.
- Las alertas expiran correctamente a los 180 segundos.

**Riesgos atacados:** R10, R16, R17, R18.

---

### Fase 4 — Medición en hardware objetivo

**Objetivo:** saber si la Pi 4 aguanta el pipeline. Es la incógnita más grande
del proyecto y se resuelve en diez minutos.

**Entregables:**

- Medición del real-time factor de Vosk en la Pi.
- Medición del tiempo de síntesis de Piper en la Pi.
- Consumo de CPU con Porcupine, Vosk y Piper corriendo juntos.
- Temperatura del SoC sostenida bajo carga.

**Criterios de salida:**

- RTF del STT menor que 1, idealmente menor que 0,5.
- CPU con margen suficiente para cargas futuras.
- Sin estrangulamiento térmico sostenido.

**Riesgos atacados:** R7, R14.

---

## Etapa 2 — Radio y campo

Requiere el hardware LoRa.

### Fase 5 — Banco de radio y alcance

**Objetivo:** medir el enlace real. Es el nivel L4.

**Entregables:**

- `LoraTransport` implementado sobre la misma interfaz.
- Script de prueba que registre RSSI, SNR y tasa de error por paquete.
- Tabla de resultados a 1, 3 y 5 km, con y sin línea de vista.
- Comparación entre antena dentro y fuera de la cabina.

**Criterios de salida:**

- La migración no requirió tocar el protocolo, el clasificador ni la FSM (ver el
  [checklist de migración](09-banco-de-pruebas.md#checklist-de-migración-a-lora)).
- Se determinó el spreading factor definitivo **con datos**, no con estimaciones.
- Se cuantificó el efecto real del montaje de la antena.

**Riesgos atacados:** R3, R4, R11.

---

### Fase 6 — Integración y prueba en ruta

**Objetivo:** el sistema completo, en vehículos, durante un viaje real.

**Entregables:**

- Dos a seis nodos integrados en vehículos.
- Un recorrido de prueba en un camino de montaña representativo.
- Logs de toda la sesión y un informe de resultados.

**Criterios de salida:**

- Una advertencia hablada emitida por el primer vehículo se escucha y se ve en el
  último.
- El sistema corre durante todo el viaje sin reinicios ni fallas.
- Ninguna alerta real se pierde.
- La tasa de detección de la wake word con ruido de ruta real es aceptable.

**Riesgos atacados:** R6, R8.

---

## Etapa 3 — Futuro

### Fase 7 — Extensiones

Sin orden comprometido. Se priorizan según lo que aparezca en la Fase 6.

| Extensión | Valor | Notas |
|---|---|---|
| Botón físico de emergencia | Elimina el riesgo crítico R1 | Requiere definir el mapeo de botones |
| Mensaje de "vía libre" | Cierra las alertas antes del timeout | Resuelve R10 |
| Reanunciación periódica de alertas activas | Cubre nodos que se suman tarde y cortes de energía | Resuelve R10 y R16 |
| RTC por nodo | Habilita auditoría real | Ver [06-codigos-y-logs.md](06-codigos-y-logs.md#trabajo-de-auditoría-diferido) |
| Auditoría con cadena de hashes y firmas | Valor probatorio para seguros o reclamos | Depende del RTC |
| Detección de somnolencia | Valor de seguridad independiente | Requiere cámara IR y presupuesto de CPU |
| LLM con gramática restringida | Manejo de lenguaje más flexible | Solo si las reglas resultan insuficientes |
| Liderazgo dinámico | Tolerancia a la salida del líder | — |
| Rate adaptativo (ADR) | Mejor uso del canal | Solo si aparece congestión |

---

## Resumen

| Fase | Foco | Hardware necesario | Riesgos atacados |
|---|---|---|---|
| 0 | Esqueleto, roles y transporte (L0) | El actual | R5, R19 |
| 1 | Clasificación semántica (L1) | El actual | R12, R13 |
| 2 | Pipeline de audio (L2) | El actual | R1, R2, R19 |
| 3 | Protocolo completo y LED (L3) | El actual | R10, R16, R17, R18 |
| 4 | Medición en la Pi | El actual | R7, R14 |
| 5 | Banco de radio y alcance (L4) | **LoRa** | R3, R4, R11 |
| 6 | Prueba en ruta | **LoRa + vehículos** | R6, R8 |
| 7 | Extensiones | Variable | R1, R9, R10, R16 |

## Antes de empezar

Dos cosas quedan pendientes y conviene resolverlas antes de escribir código:

1. **Hardware de micrófono** — se decide con pruebas de ruido real, pero hay que
   comprar algo para empezar. Mientras tanto, el micrófono de la computadora
   sirve para desarrollar.
2. **Verificación regulatoria** — confirmar los límites de potencia aplicables en
   902–928 MHz antes de las pruebas en ruta. No bloquea la Etapa 1.

El lenguaje ya no es una decisión pendiente: es **Python** (D13). El
almacenamiento de la Raspberry Pi también conviene revisarlo antes de la Fase 6,
por la rotación de logs.
