# 04 — Audio e IA

> **Restricción global:** no hay internet. Todo modelo, toda inferencia y toda
> síntesis corre embarcado en la Raspberry Pi 4. No existe ninguna dependencia
> de nube, ni siquiera opcional.

## Visión general del pipeline

```
        ┌──────────────────────────────────────────────────────────┐
        │                    PIPELINE DE ENTRADA                   │
        │                                                          │
 mic ──▶│  Wake word ──▶ VAD ──▶ STT ──▶ Clasificador ──▶ código    │
        │ (continuo)  (fin de  (Vosk)   (reglas)                   │
        │             frase)                                       │
        └──────────────────────────────────────────────────────────┘
                                              │
                                              ▼
                                      capa de radio (LoRa)
                                              │
        ┌─────────────────────────────────────┼────────────────────┐
        │                    PIPELINE DE SALIDA                     │
        │                                                          │
        │  código ──▶ Plantilla ──▶ TTS (Piper) ──▶ parlante        │
        │                          + LED                           │
        └──────────────────────────────────────────────────────────┘
```

## Máquina de estados de audio

```
        ┌──────────────────────────────────────────────┐
        │                   IDLE                        │
        │   Wake word escuchando · LED según alertas    │
        └───────────────────────┬──────────────────────┘
                                │ wake word detectada
                                ▼
        ┌──────────────────────────────────────────────┐
        │                 CAPTURA                       │
        │   Grabando · VAD esperando fin de frase       │
        └───────────────────────┬──────────────────────┘
                                │ fin de frase o timeout
                                ▼
        ┌──────────────────────────────────────────────┐
        │              TRANSCRIPCIÓN                    │
        │   STT sobre el audio capturado                │
        └───────────────────────┬──────────────────────┘
                                │ transcripción lista
                                ▼
        ┌──────────────────────────────────────────────┐
        │              CLASIFICACIÓN                    │
        │   Transcripción → código de peligro           │
        └───────────────────────┬──────────────────────┘
                                │ código listo
                                ▼
        ┌──────────────────────────────────────────────┐
        │               TRANSMISIÓN                     │
        │   Difusión por LoRa · espera de asentamiento  │
        └───────────────────────┬──────────────────────┘
                                │ canal asentado
                                ▼
        ┌──────────────────────────────────────────────┐
        │               REPRODUCCIÓN                    │
        │   Confirmación por TTS · micrófono silenciado │
        └───────────────────────┬──────────────────────┘
                                │ reproducción terminada
                                ▼
                            (volver a IDLE)
```

### Reglas de la máquina de estados

- **El micrófono está silenciado en REPRODUCCIÓN.** Half-duplex (regla 2 de
  preemption, ver [02-arquitectura.md](02-arquitectura.md#reglas-de-adelantamiento-preemption)).
- **Una alerta remota fuerza la transición a REPRODUCCIÓN desde cualquier
  estado.** Si el sistema estaba en CAPTURA, la captura se descarta y, al
  terminar la reproducción, se le pide al conductor que repita.
- **CAPTURA tiene un timeout duro** (por ejemplo, 8 segundos). Si el VAD nunca
  detecta el fin de frase, la captura se corta igual y el audio se transcribe
  como está.
- **TRANSCRIPCIÓN y CLASIFICACIÓN tienen timeout.** Si superan su presupuesto,
  el sistema envía el código genérico de peligro desconocido con confianza baja
  en lugar de no enviar nada.

## Wake word

| Aspecto | Decisión |
|---|---|
| Frase | "atención comboy" |
| Motor recomendado | **Porcupine** (Picovoice) |
| Alternativa | openWakeWord |
| Ejecución | Hilo dedicado, continuo, independiente del resto del pipeline |

### Por qué Porcupine

- Soporta wake words personalizadas en español a través de su consola.
- Es muy liviano en CPU: consume una fracción pequeña de un núcleo, lo que lo
  hace viable para operación continua durante horas.
- Tiene bindings para varios lenguajes y una API estable.

### Riesgos propios del wake word

- **openWakeWord está fuertemente orientado al inglés.** Sus modelos preentrenados
  son mayoritariamente en inglés, y entrenar una wake word en español propia es
  trabajo adicional con resultados inciertos.
- **El ruido de cabina degrada la detección.** Esta es la primera cosa a validar
  en un vehículo real en movimiento, antes de construir cualquier otra cosa.
- **La licencia importa.** Porcupine es gratuito para uso personal, pero requiere
  licencia para uso comercial. Si el proyecto se comercializa, esto hay que
  resolverlo (ver [07-riesgos.md](07-riesgos.md)).

La frase elegida es buena: dos palabras, fonética distintiva, poco probable de
aparecer en una conversación normal.

## VAD (detección de actividad de voz)

Se usa para detectar cuándo el conductor terminó de hablar, en lugar de esperar
un tiempo fijo.

- Criterio: aproximadamente 600–800 ms de silencio sostenido cierran la captura.
- Esto agrega latencia a propósito, y está contemplado en el presupuesto de
  tiempo de reacción.
- Se puede apoyar en el propio VAD de Vosk, que ya trabaja en streaming, o en una
  implementación simple de energía más cruce por cero.

## STT (reconocimiento de habla)

| Aspecto | Decisión |
|---|---|
| Motor recomendado | **Vosk** (`vosk-model-small-es-*`) |
| Alternativa | whisper.cpp (tiny o base) |
| Ejecución | Proceso aparte, disparado por la FSM de audio |

### Por qué Vosk y no Whisper como opción principal

En la primera ronda de diseño habíamos asumido Whisper, y conviene corregirlo:

| Criterio | Vosk | whisper.cpp |
|---|---|---|
| Modo | Streaming, va devolviendo texto | Por lotes, espera el audio completo |
| Tamaño del modelo | ~40 MB (small es) | ~75 MB (tiny) a ~142 MB (base) |
| Latencia en Pi 4 | Baja, incremental | Segundos por enunciado |
| Precisión en lenguaje libre | Menor | Mayor |
| Precisión en vocabulario acotado | Muy buena | Muy buena |
| Costo de CPU | Bajo | Alto |

El dominio de este sistema es un **vocabulario acotado de peligros de ruta**, no
lenguaje libre. Para ese caso, Vosk ofrece baja latencia y bajo consumo con
precisión más que suficiente. Whisper queda como alternativa de mayor precisión
si en las pruebas de campo Vosk resulta insuficiente.

## Clasificación

El clasificador convierte una transcripción en español en un código de peligro
estructurado. **Es puramente por reglas en el MVP (D12).**

### Estrategia

1. **Normalización**: minúsculas, sin tildes, sin puntuación, números escritos
   como palabras unificados.
2. **Coincidencia por léxico**: cada tipo de peligro tiene un conjunto de
   términos y frases asociados.
3. **Extracción de campos**: distancia ("a dos kilómetros", "un kilómetro y
   medio"), carril ("carril derecho", "mano izquierda", "toda la ruta"), y
   urgencia ("cuidado", "frená", "pará").
4. **Cálculo de confianza**: según la fuerza y la cantidad de coincidencias, más
   la confianza que reporta el propio STT.
5. **Sin coincidencia**: se emite el código `DESCONOCIDO` con confianza baja, y
   se le pide al conductor que repita.

### Ejemplos de léxico

| Código | Términos de ejemplo |
|---|---|
| `ACCIDENTE` | accidente, choque, colisión, vuelco |
| `PIEDRAS` | piedra, piedras, roca, rocas, derrumbe, desprendimiento |
| `ANIMAL` | animal, vaca, caballo, perro, oveja, lana |
| `PEATON` | persona, peatón, gente, caminando |
| `VEHICULO_DETENIDO` | auto parado, camión detenido, vehículo parado |
| `BACHE` | bache, pozo, hoyo |
| `OBRA` | obra, trabajo, arreglo, máquina |
| `CONTROL` | control, policía, gendarmería, retén |
| `NIEBLA` | niebla, neblina, humo, baja visibilidad |
| `LLUVIA` | lluvia, lloviendo, mojado, resbaladizo |
| `HIELO` | hielo, escarcha, congelado, nieve |
| `DERRUMBE` | derrumbe, deslizamiento, alud |
| `CURVA` | curva, curva peligrosa, contracurva |

### Por qué no un LLM

- **Latencia**: un modelo de 1B en la Pi 4 agrega 1–3 segundos por enunciado.
- **CPU compartida**: la misma CPU ya corre Porcupine, Vosk y Piper.
- **Determinismo**: en un camino relevante para la seguridad, un clasificador por
  reglas es auditable y predecible; un LLM puede alucinar.
- **Sin internet** no hay forma de descargar modelos mejores de los que entran en
  una Pi 4.

Si algún día se quiere lenguaje más flexible, el camino correcto es un modelo
chico (0.5B–1.5B) con **gramática restringida** de modo que solo pueda emitir
códigos válidos, corriendo como proceso de baja prioridad y opcional. Ver
[08-hoja-de-ruta.md](08-hoja-de-ruta.md).

## TTS (síntesis de habla)

| Aspecto | Decisión |
|---|---|
| Motor recomendado | **Piper** |
| Alternativa liviana | espeak-ng |
| Idioma | Español (variante argentina si hay voz disponible) |
| Ejecución | Proceso aparte, disparado por la FSM de audio |

Piper ofrece voces neuronales offline que corren cerca de tiempo real en la Pi 4
para frases cortas, que es exactamente el caso de uso: una oración por alerta.
espeak-ng queda como respaldo instantáneo aunque más robótico, útil si la
latencia de Piper resulta problemática.

### Plantillas de anuncio

El código recibido se renderiza con una plantilla. La frase arranca directamente
con el peligro: "atención comboy" es la wake word que dice el conductor, no un
prefijo que pronuncie el receptor. Los textos del catálogo van en minúscula y la
primera letra de la frase final se capitaliza al ensamblar.

| Urgencia | Plantilla | Ejemplo generado |
|---|---|---|
| INFO | `{peligro} {carril}, a {dist} kilómetros. Solo informativo.` | "Derrumbe sobre la ruta, toda la ruta, aquí mismo. Solo informativo." |
| PRECAUCIÓN | `{peligro} {carril}, a {dist} kilómetros. Precaución.` | "Piedras en la calzada, carril derecho, a 2 kilómetros. Precaución." |
| DETENERSE | `{peligro} {carril}, a {dist} kilómetros. Deténgase.` | "Accidente en la calzada, toda la ruta, a 1 kilómetro. Deténgase." |
| Confianza baja | `Posible {peligro} {carril}, a {dist} kilómetros. Precaución.` | "Posible animal sobre la calzada, a 3 kilómetros. Precaución." |

Cuando el carril es `SIN_ESPECIFICAR`, la plantilla omite el carril. Cuando la
urgencia es desconocida, se cae a `PRECAUCION` (el nivel medio).

Cuando el código es `DESCONOCIDO`, la plantilla es genérica:

> "Peligro no identificado. Precaución."

El catálogo completo de códigos y sus textos está en
[06-codigos-y-logs.md](06-codigos-y-logs.md).

## Indicador LED

La salida sonora nunca es suficiente por sí sola: el ruido de cabina, una
ventanilla abierta o una conversación pueden tapar el anuncio. Por eso el LED es
obligatorio (D4).

| Estado | Color y patrón | Significado |
|---|---|---|
| Sin alertas, roster completo | Verde fijo | Todo normal |
| Alerta activa, urgencia INFO | Ámbar fijo | Peligro informado, sin urgencia inmediata |
| Alerta activa, urgencia PRECAUCIÓN | Ámbar, parpadeo lento | Prestar atención |
| Alerta activa, urgencia DETENERSE | Rojo, parpadeo rápido | Detenerse |
| Nodo del comboy ausente | Azul, parpadeo lento | Un vehículo dejó de responder |
| Falla del sistema | Blanco o magenta fijo | Problema de radio, micrófono o audio |

> **Propuesta a validar:** el mapeo de patrones para `INFO` y `PRECAUCIÓN`
> (ámbar fijo vs. ámbar con parpadeo lento) queda por confirmar en pruebas de
> campo; la distinción es útil pero puede no ser perceptible a pleno sol.

Si hay varias alertas activas simultáneas, el LED muestra la de **mayor
urgencia**.

## Presupuesto de CPU y latencia

Estimaciones para una Raspberry Pi 4 de 8 GB, a validar con mediciones reales.

| Etapa | CPU | Latencia típica |
|---|---|---|
| Wake word (continuo) | ~5–15% de un núcleo | — |
| Captura + VAD | ~2% de un núcleo | 0,6–0,8 s de espera de silencio |
| STT (Vosk, frase corta) | ~30–60% de un núcleo durante la transcripción | 0,5–1,5 s |
| Clasificación (reglas) | Despreciable | < 10 ms |
| TTS (Piper, una oración) | ~40–80% de un núcleo durante la síntesis | 0,3–1,0 s |

En el peor caso, desde que el conductor termina de hablar hasta que el último
vehículo escucha la advertencia: **2 a 4 segundos**. Comparado con el margen de
40 segundos a 3 minutos calculado en
[01-vision-y-alcance.md](01-vision-y-alcance.md#presupuesto-de-tiempo-de-reacción),
es una fracción cómoda.

## Lo que este diseño deliberadamente no hace

- No transmite audio.
- No persiste audio.
- No usa internet.
- No usa un LLM.
- No intenta operación full-duplex.
- No intenta detección visual de peligros.
- No intenta diarización ni identificación del hablante.
