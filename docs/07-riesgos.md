# 07 — Riesgos

## Escala

| Nivel | Significado |
|---|---|
| **Crítico** | Puede impedir que una alerta llegue. Compromete el propósito del sistema |
| **Alto** | Degrada seriamente la confiabilidad o la usabilidad |
| **Medio** | Molesto, con mitigación conocida |
| **Bajo** | Aceptable, se monitorea |

La **probabilidad** se estima como Alta / Media / Baja.

---

## Registro de riesgos

### R1 — El wake word es el único camino de entrada

| | |
|---|---|
| **Descripción** | No hay botones físicos (D10). Si el wake word no se detecta, no hay ninguna otra forma de emitir una alerta |
| **Impacto** | **Crítico**. Es un punto único de falla en el camino de entrada |
| **Probabilidad** | Media |
| **Mitigación** | Validar la detección en un vehículo real antes de construir el resto. Ajustar la sensibilidad del detector. Considerar un botón como respaldo en una fase futura |
| **Estado** | **Riesgo aceptado explícitamente.** Es la consecuencia directa de D10 |

> Este es el riesgo más importante del proyecto. Se acepta por decisión de
> alcance, pero conviene tenerlo presente: todo lo demás puede funcionar
> perfectamente y el sistema ser inútil si la wake word no dispara con ruido de
> ruta.

### R2 — Ruido de cabina degrada el reconocimiento

| | |
|---|---|
| **Descripción** | A 90–100 km/h, con ventanillas o música, la relación señal-ruido del micrófono puede volver inutilizable tanto la wake word como el STT |
| **Impacto** | **Crítico** |
| **Probabilidad** | Alta |
| **Mitigación** | Usar array de micrófonos con beamforming o micrófono close-talk. Probar en ruta, no en banco. Ubicar el micrófono lejos del viento |

### R3 — Pérdida intermitente de línea de vista en montaña

| | |
|---|---|
| **Descripción** | El terreno puede separar vehículos aun estando a corta distancia. El alcance real de 5 km no está garantizado en quebradas |
| **Impacto** | **Alto** |
| **Probabilidad** | Alta |
| **Mitigación** | El flooding entrega alcance multi-salto de forma gratuita. Partir de SF10 y subir a SF11 si las mediciones lo justifican |

### R4 — Antena mal montada

| | |
|---|---|
| **Descripción** | Una antena dentro de la cabina pierde 10–20 dB respecto de una montada afuera. Convierte un enlace funcional en uno inutilizable |
| **Impacto** | **Crítico** |
| **Probabilidad** | Media si no se documenta; Baja si se sigue el plan |
| **Mitigación** | Montaje exterior obligatorio. Ver [05-hardware.md](05-hardware.md#antena-el-error-más-común-y-más-caro) |

### R5 — Sin retroalimentación de audio, el conductor no sabe si fue entendido

| | |
|---|---|
| **Descripción** | Si el sistema falla silenciosamente, el conductor cree que alertó al comboy cuando en realidad no pasó nada |
| **Impacto** | **Alto** |
| **Probabilidad** | Media |
| **Mitigación** | Confirmación local por TTS ("Alerta enviada") después de cada transmisión. Es parte del diseño de la FSM de audio |

### R6 — Energía automotriz

| | |
|---|---|
| **Descripción** | Picos de arranque, load dump y ruido del alternador pueden reiniciar o destruir el nodo |
| **Impacto** | **Alto** |
| **Probabilidad** | Alta sin protección; Baja con un DC-DC automotriz |
| **Mitigación** | Convertidor automotriz con rango 9–36 V, protección de load dump, fusible. Nunca un cargador USB de auto |

### R7 — Estrangulamiento térmico

| | |
|---|---|
| **Descripción** | Una Pi 4 en un vehículo al sol supera los 80 °C y reduce frecuencia. El STT y el TTS se vuelven lentos justo cuando se los necesita |
| **Impacto** | **Alto** |
| **Probabilidad** | Media en verano |
| **Mitigación** | Disipador y ventilador, gabinete ventilado, ubicación lejos del motor y del sol directo |

### R8 — Corrupción de la tarjeta SD

| | |
|---|---|
| **Descripción** | Los cortes de energía en un vehículo son habituales. La SD es el componente menos confiable |
| **Impacto** | **Alto**. Un nodo que no arranca es un nodo que no advierte |
| **Probabilidad** | Media–Alta |
| **Mitigación** | SSD por USB, o raíz de solo lectura con logs en tmpfs, o rotación agresiva. Ver [05-hardware.md](05-hardware.md#almacenamiento) |

### R9 — Ubicación imprecisa por falta de GPS

| | |
|---|---|
| **Descripción** | Sin GPS (D5), la ubicación es una distancia estimada a ojo. Puede ser imprecisa o directamente equivocada |
| **Impacto** | **Medio** |
| **Probabilidad** | Alta |
| **Mitigación** | Aceptado por diseño (D9). La advertencia de "hay peligro adelante" sigue siendo útil aunque la distancia sea aproximada |

### R10 — Alertas obsoletas y nodos que se incorporan tarde

| | |
|---|---|
| **Descripción** | Un peligro que se despeja en 20 segundos igual mantiene el LED 180 segundos (D7). Y un nodo que se suma al comboy después de la difusión nunca se entera |
| **Impacto** | **Medio** |
| **Probabilidad** | Alta |
| **Mitigación** | Diferido. Futuro: mensaje manual de "vía libre" y reanunciación periódica mientras la alerta está activa. Ver [08-hoja-de-ruta.md](08-hoja-de-ruta.md) |

### R11 — No conformidad regulatoria

| | |
|---|---|
| **Descripción** | Operar en 902–928 MHz con 20 dBm puede exceder los límites de ENACOM |
| **Impacto** | **Alto** (legal, no técnico) |
| **Probabilidad** | Media |
| **Mitigación** | Verificar la normativa vigente antes de las pruebas en ruta y ajustar `tx_power_dbm` |

### R12 — Falso negativo en la clasificación

| | |
|---|---|
| **Descripción** | El conductor reporta un peligro real, pero el STT o el clasificador fallan y el código emitido es `DESCONOCIDO` o incorrecto |
| **Impacto** | **Alto** |
| **Probabilidad** | Media |
| **Mitigación** | El código `DESCONOCIDO` igual se transmite y produce una advertencia genérica. El conductor recibe una confirmación local y puede repetir. La confirmación local también permite detectar el fallo |

### R13 — Falsos positivos erosionan la confianza

| | |
|---|---|
| **Descripción** | Si el sistema advierte peligros que no existen, los conductores empiezan a ignorarlo. Ese es el peor estado posible para un sistema de seguridad |
| **Impacto** | **Alto** |
| **Probabilidad** | Media |
| **Mitigación** | Campo de confianza en el código, con frase atenuada ("Posible...") cuando es baja. Vocabulario de wake word distintivo para reducir disparos accidentales |

### R14 — Contención de CPU

| | |
|---|---|
| **Descripción** | Porcupine, Vosk y Piper compiten por los cuatro núcleos de la Pi 4 |
| **Impacto** | **Medio** |
| **Probabilidad** | Media |
| **Mitigación** | Reparto de hilos explícito ([02-arquitectura.md](02-arquitectura.md#modelo-de-concurrencia-y-prioridades)). Procesos separados con prioridades. Medir antes de agregar carga (por ejemplo, la futura cámara) |

### R15 — Licencia del motor de wake word

| | |
|---|---|
| **Descripción** | Porcupine es gratuito para uso personal, pero requiere licencia comercial |
| **Impacto** | **Medio** (legal, no técnico) |
| **Probabilidad** | Alta si el proyecto se comercializa |
| **Mitigación** | Definir el modelo de uso antes de comprometerse con Porcupine. Alternativa: entrenar una wake word propia con openWakeWord, asumiendo el costo de desarrollo |

### R16 — Cancelación de la energía borra el estado de alerta

| | |
|---|---|
| **Descripción** | Si un nodo se reinicia, pierde el registro de las alertas activas. Al reincorporarse no sabe qué peligros siguen vigentes |
| **Impacto** | **Medio** |
| **Probabilidad** | Media |
| **Mitigación** | Diferido. Futuro: reanunciación periódica mientras la alerta está activa, que resolvería esto y también el R10 |

### R17 — Alertas simultáneas de dos vehículos

| | |
|---|---|
| **Descripción** | Dos conductores alertan al mismo tiempo y las tramas colisionan |
| **Impacto** | **Medio** |
| **Probabilidad** | Baja |
| **Mitigación** | Backoff con jitter diferenciado y lógica de retransmisión. Los `alert_id` distintos sobreviven y ambos se anuncian. El LED muestra la urgencia mayor |

### R18 — El parlante no se escucha sobre el ruido de ruta

| | |
|---|---|
| **Descripción** | El anuncio por TTS puede quedar tapado por el ruido del vehículo o la radio |
| **Impacto** | **Medio** |
| **Probabilidad** | Media |
| **Mitigación** | El LED codifica el mismo estado y permanece encendido los 180 segundos completos. Es la razón de ser de D4 |

### R19 — Cancelación de eco inexistente

| | |
|---|---|
| **Descripción** | El micrófono siempre-encendido escucha la reproducción del propio TTS y puede auto-dispararse |
| **Impacto** | **Medio** |
| **Probabilidad** | Alta si no se mitiga |
| **Mitigación** | Half-duplex: el micrófono se silencia durante la reproducción. Simple y suficiente para el MVP |

---

## Resumen por severidad

| Severidad | Riesgos |
|---|---|
| **Crítico** | R1, R2, R4 |
| **Alto** | R3, R5, R6, R7, R8, R11, R12, R13 |
| **Medio** | R9, R10, R14, R15, R16, R17, R18, R19 |
| **Bajo** | — |

Los tres riesgos críticos tienen algo en común: **todos se validan en campo, no
en banco**. La wake word con ruido de ruta (R1, R2) y el alcance real con la
antena montada (R4) son las tres primeras cosas que hay que medir, antes de
invertir en el resto del sistema.

---

## Decisiones diferidas

Se acordaron explícitamente como fuera del MVP. Se listan acá para que no se
pierdan.

| Diferido | Motivo | Depende de |
|---|---|---|
| Botón físico de emergencia | Simplifica el MVP (D10) | — |
| Mensaje manual de "vía libre" | Simplifica el MVP (D7) | — |
| Reanunciación periódica de alertas activas | Simplifica el MVP | — |
| RTC de hardware | No es prioridad en desarrollo (D6) | — |
| Auditoría con cadena de hashes y firmas | No es prioridad en desarrollo (D6) | RTC |
| Detección de somnolencia | Fuera de alcance del MVP | Cámara IR, presupuesto de CPU |
| LLM para lenguaje flexible | Diferido al fallo elegante (D12); los embeddings cubren el lenguaje coloquial | Presupuesto de CPU |
| Liderazgo dinámico | Líder fijo por configuración (D11) | — |
| Configuración remota de nodos | No hay infraestructura | — |
| Rate adaptativo (ADR) | SF fijo es más simple | Mediciones de campo |

## Puntos que requieren medición en campo

Ninguno de estos se puede resolver en un escritorio. Son la agenda de la primera
prueba real.

| Medición | Define |
|---|---|
| Tasa de detección de la wake word a 80 y 100 km/h con ruido | Viabilidad de R1 y R2 |
| Tasa de acierto del STT en ruta con vocabulario de peligros | Calidad de R12 |
| RSSI, SNR y tasa de error de paquete a 1, 3 y 5 km | Spreading factor definitivo |
| Efecto de la antena montada en el techo versus dentro de la cabina | Viabilidad de R4 |
| Temperatura del SoC bajo carga, en verano y a pleno sol | Viabilidad de R7 |
| Consumo de CPU con Porcupine, Vosk y Piper corriendo juntos | Viabilidad de R14 |
