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
        │ (continuo)  (fin de  (Vosk)  (embeddings)                │
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
| Motor | **Vosk con gramática restringida** |
| Alternativas evaluadas | Porcupine (Picovoice), openWakeWord |
| Ejecución | Hilo dedicado, continuo, independiente del resto del pipeline |

### Por qué Vosk y no Porcupine

Porcupine es técnicamente superior para escucha continua: consume una fracción
pequeña de un núcleo y tiene consola para entrenar wake words en español. Pero
exige crear una cuenta, entrenar la frase y **resolver una licencia comercial**
antes de poder usar el sistema en producción.

Vosk gana por otra razón: **ya es el motor de STT del proyecto.** Usarlo también
para la wake word deja **un solo motor de audio** en vez de dos, sin licencias,
sin cuentas y sin entrenamiento — y el modelo en español ya está descargado.

El costo es de CPU: escuchar continuo con Vosk pesa más que Porcupine. Eso es
parte de lo que mide la Fase 4, y es el argumento principal para reconsiderarlo
si la medición no cierra.

### La trampa de "comboy"

La frase que dice el conductor es `atencion comboy`, pero **la gramática lleva
`convoy`**. No es un error de tipeo:

- `comboy` **no existe** en el vocabulario del modelo. Vosk descarta en silencio
  las palabras que no conoce —solo deja un aviso por `stderr`—, así que una
  gramática con `comboy` no daría match nunca.
- En español, **`b` y `v` se pronuncian igual** (betacismo): "atención comboy" y
  "atención convoy" son fonéticamente idénticas.

El conductor dice "comboy", el modelo transcribe "convoy" y la detección
funciona. La equivalencia está explícita en el código, con un test que la
protege para que nadie la "arregle" creyendo que es un typo.

### Recuperación del audio posterior a la wake word (buffer rodante)

Vosk no reporta nada hasta que detecta **silencio**: el resultado final de una
frase recién llega cuando el conductor calla. Eso es un problema para la wake
word cuando el conductor **encadena** la activación con la frase de peligro:

1. Dice "atención comboy" → Vosk ya lo tiene, pero no lo reporta (no hubo pausa).
2. Sigue hablando ("hay piedras...") → esos chunks entran al detector, que
   todavía espera el final, y **se descartan**.
3. Calla → recién ahí dispara.
4. La transcripción arranca en el chunk siguiente: todo lo del paso 2 se perdió.

El síntoma en uso real es que la frase se corta al principio ("demora un poco y
me da cortado").

#### Por qué la detección temprana no alcanzó

El primer intento fue leer también `PartialResult()`, el texto provisorio que Vosk
emite sin esperar silencio, y disparar con él (`early=True`). **No funcionó**: Vosk
emite el parcial con retraso, una vez que ya procesó audio que incluye el arranque
de la frase. El disparo sigue llegando tarde y ese arranque se pierde igual.
Además, disparar sobre un parcial arriesga falsos positivos, porque el texto
provisorio es inestable.

El flag `early` sigue existiendo con default `False`, pero `talk` **ya no lo usa**:
`listen` conserva el comportamiento clásico.

#### El mecanismo: guardar y recuperar

En vez de depender de *cuándo* dispara la detección, se guarda el audio y se lo
recupera:

1. El detector mantiene un **buffer rodante de PCM** de 30 segundos (~960 KB a
   16 kHz mono s16). Cada chunk se agrega al buffer **antes** de pasarlo a Vosk,
   así el audio en vuelo ya está disponible cuando la detección dispara.
2. El recognizer del wake word se construye con `SetWords(True)`. Así `Result()`
   devuelve, además del texto, un array `result` con los tiempos por palabra **en
   segundos**: el `end` de la última palabra es dónde terminó "atención comboy".
3. Ese `end` se traduce a un **sample absoluto** (`end * rate`) dentro del buffer.
   El detector expone `audio_since_wake()`, que devuelve el PCM desde ese punto
   hasta el final del buffer.
4. `talk` inyecta ese recorte al transcriber de una sola vez y después sigue
   alimentando en vivo desde el chunk siguiente.

Como el recorte termina exactamente donde termina el buffer, y el vivo continúa
desde ahí, **no hay solapamiento ni audio duplicado**. Y ninguna muestra hablada
después de la activación se pierde, sin importar cuántos chunks haya tardado la
detección.

#### El invariante: un solo origen temporal

Los timestamps de Vosk y el contador de samples del buffer tienen que arrancar
del **mismo origen**: el inicio del stream del recognizer. Por eso el buffer vive
**dentro** de `comboy/wakeword.py`: el detector es el único que conoce ambos.

La parte no obvia —y la razón de ser de la corrección que sigue— es que **ese
origen nunca se reinicia**:

- `Reset()` de Vosk limpia el estado de decodificación, pero **no reinicia su
  contador de frames**: los `end` de los resultados posteriores siguen siendo
  absolutos desde el inicio del stream.
- Por eso `reset()` del detector **no** debe vaciar el buffer ni volver
  `total_samples_fed` a cero. Ambos tienen que ser **monotónicos durante toda la
  vida del detector**, igual que el contador de Vosk.

A primera vista "reset debería limpiar todo" parece lo correcto, y de hecho fue
lo que se implementó primero. **Era el bug**: a partir de la **segunda**
detección, `wake_end` (absoluto, grande) quedaba por delante de
`total_samples_fed` (reiniciado, chico), el recorte caía fuera del buffer y
`audio_since_wake()` devolvía `None` para siempre. La primera detección andaba
perfecto; todas las siguientes daban `recovered_samples=0`. El buffer no crece
sin control por no vaciarse: está acotado a 30 s y descarta lo más viejo.

`reset()` sí limpia el latch, `last_text` y `_wake_end_sample`, y sigue llamando
a `Reset()` del recognizer: lo que no toca es el buffer ni el contador.

#### Guard: el invariante roto no es un fallback

Si `wake_end_sample > total_samples_fed`, los dos orígenes se separaron: es
imposible que el fin de la wake word esté más allá de todo lo alimentado. Ese
caso **no** es un fallback normal (falta de dato): es un **bug de sincronía**.
El detector registra un evento propio, `wakeword.invariant_broken`, con los dos
valores como evidencia, y devuelve `None`. Con este guard, el bug de arriba
habría sido obvio en la primera corrida en vez de costar dos hipótesis falsas.
Ver [06-codigos-y-logs.md](06-codigos-y-logs.md).

#### Riesgo residual: `flush()` y `FinalResult()`

`talk` **no** llama `detector.flush()`, así que `FinalResult()` no se invoca en
ese camino. Queda anotado como riesgo conocido que si en el futuro algo invocara
`flush()`/`FinalResult()` sobre el detector de wake word, habría que **verificar**
si eso sí reinicia el contador de frames de Vosk —no está medido—. Si lo hiciera,
el mismo desfase reaparecería por otra puerta.

#### Margen de seguridad

`audio_since_wake()` recorta **50 ms antes** del `end` de la wake word. Los
tiempos de Vosk vienen del alineamiento acústico y pueden errar unas decenas de
milisegundos: incluir un poco de silencio o la cola de "convoy" no le molesta al
clasificador, pero cortar el arranque de una sílaba de la frase sí. El margen es
configurable; el default es 50 ms.

#### Fallback: nunca lanza

Si el resultado que disparó no traía array `result` (sin timestamp), o si la wake
word quedó más atrás que los 30 segundos del buffer, `audio_since_wake()` devuelve
`None` y registra `wakeword.replay_fallback` con el motivo. El llamador cae al
comportamiento de siempre: empezar en el chunk siguiente. **No es un error**, es
la degradación segura cuando el dato no está.

#### Instrumentación

`talk` registra el evento `wake_word` con `recovered_samples` (las muestras que
se recuperaron del buffer, o sea las que antes se perdían) y `detect_to_send_ms`
(el tiempo total desde la detección hasta el envío). `recovered_samples` decide el
diagnóstico del "cortado": si es grande, el problema era **pérdida de audio** y
este replay lo ataca; si es ~0, era **latencia percibida** y el replay no la
cambia. Ver [06-codigos-y-logs.md](06-codigos-y-logs.md).


### Riesgos propios del wake word

- **El ruido de cabina degrada la detección.** Es lo primero a validar en un
  vehículo real en movimiento, antes de construir cualquier otra cosa.
- **Falsos disparos.** La frase de dos palabras con fonética distintiva reduce el
  riesgo, pero es un parámetro a medir en campo.
- **La licencia de Porcupine sigue abierta**, por si la Fase 4 recomienda volver
  a él. Ver [07-riesgos.md](07-riesgos.md).

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
estructurado. Usa **dos motores complementarios**, cada uno donde es mejor:

| Etapa | Motor | Por qué |
|---|---|---|
| **Identificar el peligro** | Embeddings (similitud semántica) | El conductor habla coloquial y variado; enumerar sinónimos a mano no alcanza |
| **Extraer distancia, carril y urgencia** | Reglas | Son datos estructurados (números, direcciones): las reglas son exactas y auditables |
| **Confianza** | Combinación de ambos | Ver abajo |

### Identificación del peligro por embeddings

Un modelo de embeddings convierte la frase en un vector y lo compara contra
frases de ejemplo, una por concepto:

```
"se nos cruzó un bicho"  ──▶  vector  ──▶  más parecido a
                                            "hay un animal en la ruta"
                                            = ANIMAL
```

Las propiedades que importan acá:

- **El conductor no memoriza nada.** Habla como habla. El modelo entiende
  paráfrasis, no palabras exactas.
- **No puede alucinar.** Solo puede elegir entre los códigos que le dimos. Es
  estructuralmente imposible que invente un peligro fuera de la lista.
- **Enseñarle es agregar frases de ejemplo**, no entrenar nada. La cobertura
  crece escribiendo casos, no con machine learning.
- **Es liviano y rápido.** Un modelo de decenas de millones de parámetros corre
  en CPU en decenas o cientos de milisegundos. Ver el presupuesto más abajo.

> **El vector NO se transmite.** El embedding corre entero en el nodo que
> escucha; lo único que sale al aire son los **17 bytes de la trama**. Mandar el
> vector sería unas 90 veces más grande (384 dimensiones son ~400 bytes en
> `int8`) y no aportaría nada: el significado ya viaja destilado en el código, y
> el receptor no tiene el audio para aprovecharlo.

Hay que usar un modelo **multilingüe**: los modelos de embeddings más difundidos
son solo en inglés.

### Modelo elegido

El modelo es **`qwen3-embedding:0.6b`**, servido por **Ollama** en
`http://localhost:11434`. Se eligió con mediciones sobre el conjunto de frases
reales, no por intuición:

| Modelo | Acierto | ¿El error cae bajo el umbral? |
|---|---|---|
| `qwen3-embedding:0.6b` | 93 % (13/14) | **Sí** — el único error queda bajo el umbral y se vuelve `DESCONOCIDO` |
| `bge-m3` | 93 % (13/14) | No — su error cae por encima del umbral (código incorrecto con confianza alta) |
| `nomic-embed-text` | 64 % (9/14) | No — varios errores confiados |
| `granite-embedding:278m` | 79 % (11/14) | No — se solapa con el ruido |

Los resultados crudos están en `docs/results-test-embedding/`. Lo decisivo no fue
el acierto —`qwen3-embedding:0.6b` y `bge-m3` empatan— sino que el único error de
`qwen3-embedding:0.6b` cae **por debajo** del umbral: ante la duda, el sistema
responde `DESCONOCIDO` con confianza baja en vez de un código incorrecto con
confianza alta. Eso es exactamente el invariante que no se negocia.

El cliente de embeddings vive en `comboy/embedding.py`. Hay un cliente
`kind: null` determinista para depurar sin red, y el comando
`python -m comboy text "..."` permite probar el clasificador sin micrófono.

### Extracción de campos por reglas

Distancia, carril y urgencia son datos estructurados, no lenguaje libre:

- **Distancia**: "a dos kilómetros", "un kilómetro y medio", "a 200 metros",
  "acá nomás", "aquí mismo".
- **Carril**: "carril derecho", "mano izquierda", "toda la ruta", "la banquina".
- **Urgencia**: por defecto `PRECAUCION`; sube a `DETENERSE` solo con señal
  explícita ("frená", "pará", "detenete").

Acá las reglas son la herramienta correcta: son exactas, auditables y su costo
es despreciable.

#### La urgencia no se infiere del peligro

El sistema **nunca** deriva la urgencia del tipo de peligro. Una crecida de río no
es `DETENERSE` por ser una crecida: lo es solo si el conductor dijo "frená" o
"detenete".

La razón es que **la decisión es del conductor, no del sistema**. El comboy tiene
un líder humano; el sistema transporta y anuncia la advertencia, pero no la
gradúa. Un mapa de peligro a urgencia codificaría el criterio de un ingeniero
sobre una situación que solo quien va adelante puede juzgar: el mismo derrumbe
puede ser un obstáculo menor o la ruta cortada, y eso no se sabe desde la frase.

Por eso el conductor tiene que decir explícitamente que hay que detenerse. Si el
líder dice que hay que parar, se para.

### Frases de ejemplo por código

La cobertura del clasificador vive en las **frases completas** de ejemplo, no en
un léxico de palabras sueltas: el motor es semántico y compara oraciones enteras.
Agregar una frase es agregar cobertura, sin reentrenar nada.

Los datos no son código: el corpus completo (4 a 6 frases por código) está en
`datos/corpus.json` y las frases reservadas para medir están en
`datos/medicion.json`, incluido el conjunto de control de frases que **no** son
peligro. Para no tocar el archivo versionado, `COMBOY_CORPUS_PATH` y
`COMBOY_MEDICION_PATH` apuntan a un archivo extra cuyas frases se fusionan sobre
la base. Las frases se normalizan antes de embeber, así que las tildes o los
números en dígitos no cambian el resultado.

Esta tabla muestra una muestra representativa de cada código:

| Código | Frases de ejemplo |
|---|---|
| `ACCIDENTE` | "hubo un accidente en la ruta", "frena que hay un choque adelante" |
| `PIEDRAS` | "hay piedras en la calzada", "se desprendieron rocas de la montaña" |
| `ANIMAL` | "se nos cruzó un bicho en el camino", "hay una vaca suelta en la calzada" |
| `PEATON` | "hay gente caminando al costado", "hay un peatón en la banquina" |
| `VEHICULO_DETENIDO` | "hay un camión parado en la ruta", "hay un auto detenido en la calzada" |
| `BACHE` | "la ruta está hecha un colador de pozos", "hay un pozo profundo en la ruta" |
| `OBRA` | "están arreglando la ruta más adelante", "hay maquinaria trabajando en la calzada" |
| `CONTROL` | "nos van a parar en un control", "hay gendarmería en la ruta" |
| `NIEBLA` | "hay mucha niebla en la ruta", "la visibilidad es muy baja por la neblina" |
| `LLUVIA` | "está lloviendo muy fuerte", "la ruta está mojada y resbaladiza" |
| `HIELO` | "está todo blanco de escarcha", "hay hielo sobre la calzada" |
| `DERRUMBE` | "se vino la montaña abajo", "hubo un deslizamiento de tierra" |
| `CURVA` | "se viene una curva muy cerrada", "hay una curva peligrosa adelante" |
| `CONTRAMANO` | "hay un loco manejando en contra", "viene un auto en contramano" |
| `CRECIDA` | "el río creció y tapó la ruta", "hay un badén inundado" |
| `POLVO` | "hay mucho polvo en suspensión", "levantó tierra y no se ve nada" |

### Cálculo de confianza

La confianza `ALTA` exige **dos** condiciones a la vez:

| Confianza | Cuándo |
|---|---|
| `ALTA` | La similitud supera `min_similarity` **y** el margen contra el segundo peligro supera `min_margin` |
| `BAJA` | La similitud no alcanza el umbral, o el margen es chico, o el cliente de embeddings falló |

El **margen** es la diferencia contra el **segundo peligro distinto**, no contra la
segunda frase de ejemplo: con varias frases por código, comparar frases del mismo
peligro daría un margen cercano a cero y `ALTA` sería inalcanzable.

El margen es la señal que atrapa los aciertos por casualidad. En las mediciones,
un acierto correcto llegó a tener un margen de `0.004`: el código era el correcto,
pero por una moneda al aire. Ese caso debe salir `BAJA`, y por eso el margen es
una condición independiente de la similitud.

**Sin coincidencia clara** se emite `DESCONOCIDO` con confianza baja, y se le
pide al conductor que repita.

### El invariante que no se negocia

> Ante la duda, `DESCONOCIDO` con confianza baja — **nunca** un código
> incorrecto con confianza alta.

Un falso negativo con confianza baja se mitiga: se transmite igual, con la frase
atenuada ("Posible..."). Un falso positivo **con confianza alta** es el peor
estado posible, porque erosiona la confianza en el sistema (R13).

### Por qué no un LLM en el camino crítico

Se evaluó usar un LLM chico para interpretar lenguaje libre, y se midió en el
hardware objetivo antes de descartarlo.

| Modelo en Raspberry Pi 4 (8 GB) | Cuantización | Generación |
|---|---|---|
| Gemma 4 E2B | Q4_K_M | **1,7 tok/s** |
| Gemma 4 E4B | Q4_0 | *timeout* |

Una salida estructurada son unos 30 tokens: **18 segundos**. Incluso una salida
mínima de 10 tokens son 6 segundos, contra un presupuesto de **2 a 4 segundos**
de punta a punta. La RAM no es el problema —8 GB alcanzan de sobra—; el cómputo
sí: el SoC no tiene NPU y su ancho de banda de memoria es mínimo. Aun en una
Pi 5 (~6,5 tok/s medidos) una salida así ronda los 5 segundos.

A la latencia se suman tres razones más:

- **Puede alucinar un peligro.** Un modelo generativo puede emitir un código
  válido pero falso. La decodificación restringida limita la *forma* de la
  salida, no su *significado*. Un falso positivo con confianza alta es R13, el
  peor riesgo del sistema.
- **CPU compartida**: la misma CPU ya corre la wake word, Vosk y Piper.
- **No es auditable**: en un camino relevante para la seguridad, un clasificador
  determinista se revisa caso por caso; un LLM, no.
- **Sin internet** no hay forma de traer modelos mejores de los que entran en
  una Pi 4.

**El LLM queda diferido, no descartado.** Su lugar natural es el **fallo
elegante**: cuando la confianza del clasificador es baja, reformularle la duda al
conductor ("¿quisiste decir que hay algo en la ruta?"). Eso corre **fuera del
camino crítico**, donde su latencia deja de importar. Ver
[08-hoja-de-ruta.md](08-hoja-de-ruta.md).

Los embeddings cubren el objetivo de lenguaje flexible sin ninguno de estos
problemas, que es la razón por la que son el motor principal y no un LLM.

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
| Wake word (Vosk, continuo) | A medir | — |
| Captura + VAD | ~2% de un núcleo | 0,6–0,8 s de espera de silencio |
| STT (Vosk, frase corta) | ~30–60% de un núcleo durante la transcripción | 0,5–1,5 s |
| Clasificación (embeddings) | A medir | A medir |
| Extracción por reglas | Despreciable | < 10 ms |
| TTS (Piper, una oración) | ~40–80% de un núcleo durante la síntesis | 0,3–1,0 s |

Las dos filas marcadas **a medir** son las incógnitas que resuelve la Fase 4. La
wake word pesa más que antes: al usar Vosk en vez de Porcupine hay un motor más
corriendo, y eso es exactamente lo que hay que cuantificar antes de dar por
bueno el presupuesto de CPU.

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
