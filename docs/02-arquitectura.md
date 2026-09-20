# 02 — Arquitectura

## Topología de despliegue

Cada vehículo ejecuta un **nodo idéntico**. No hay servidor, ni estación base, ni
hardware privilegiado. La única asimetría es la configuración: exactamente un
nodo está marcado como líder.

```
        ┌──────────┐        ┌──────────┐        ┌──────────┐
        │  NODO 1  │        │  NODO 2  │        │  NODO N  │
        │ (líder)  │        │(seguidor)│  ...   │(seguidor)│
        └────┬─────┘        └────┬─────┘        └────┬─────┘
             │                   │                   │
             └───────────┬───────┴───────────────────┘
                         │
              difusión LoRa 915 MHz
              (canal compartido, flooding)
```

N está entre 2 y 6. Los nodos son pares en el aire; la prioridad es un atributo
del protocolo, no de la red.

## Anatomía del nodo

```
 ┌───────────────────────────────────────────────────────────────┐
 │                      RASPBERRY PI 4 (8 GB)                    │
 │                                                               │
 │  ┌──────────────┐                                             │
 │  │ Capa de radio│  codec de tramas · caché de dedup · roster  │
 │  │   (SX1262)   │  flooding · prioridad · retransmisión       │
 │  └──────┬───────┘                                             │
 │         │ alerta / heartbeat decodificados                    │
 │         ▼                                                     │
 │  ┌──────────────┐                                             │
 │  │  FSM de      │  ACTIVA → EXPIRADA · dedup · caché local   │
 │  │  alertas     │                                             │
 │  └──┬────────┬──┘                                             │
 │     │        │                                                │
 │     │        ├────────────────▶ ┌──────────┐                  │
 │     │        │                  │   LED    │  indicador RGB   │
 │     │        │                  └──────────┘                  │
 │     │        └────────────────▶ ┌──────────┐                  │
 │     │                           │  Logger  │  texto plano     │
 │     │                           └──────────┘                  │
 │     │                                                         │
 │  ┌──▼───────────┐                                             │
 │  │ FSM de audio │  IDLE → CAPTURA → TRANSCRIBE → CLASIFICA    │
 │  │ (half-duplex)│  → TRANSMITE → REPRODUCE → IDLE             │
 │  └──┬───────┬───┘                                             │
 │     │       │                                                 │
 │     │       └────────▶ ┌──────────┐                           │
 │  ┌──▼────────┐         │   TTS    │───▶ parlante              │
 │  │ Wake word │         │ (Piper)  │                           │
 │  │(Porcupine)│         └──────────┘                           │
 │  └──▲────────┘                                                 │
 │     │                                                          │
 └─────┼──────────────────────────────────────────────────────────┘
       │
   micrófono
```

## Componentes

| Componente | Responsabilidad |
|---|---|
| **Capa de radio** | Codifica y decodifica tramas, ejecuta la máquina de flooding, mantiene la caché de deduplicación y el roster de nodos, y arbitra el canal. Expone una interfaz simple de "enviar alerta" / "alerta recibida" al resto del sistema |
| **Capa de transporte** | Abstrae el medio de envío: UDP sobre WiFi en el banco de pruebas, LoRa en producción. Entrega y recibe frames de 17 bytes sin que el resto del sistema sepa qué hay debajo — ver [Abstracción de transporte](#abstracción-de-transporte) |
| **FSM de alertas** | Lleva el registro de las alertas activas, aplica la expiración a los 180 segundos, deduplica alertas ya vistas, y distribuye hacia el LED y el logger |
| **FSM de audio** | Es dueña del micrófono y del parlante. Corre el detector de wake word de forma continua, captura enunciados, maneja STT y clasificación, y aplica el half-duplex en la reproducción |
| **Clasificador** | Convierte una transcripción en español en un código de peligro estructurado: **embeddings** para identificar el peligro y **reglas** para distancia, carril y urgencia, con una estimación de confianza |
| **TTS** | Convierte un código de peligro en una oración hablada en español |
| **Logger** | Agrega registros estructurados en texto plano a un archivo de log |
| **Controlador de LED** | Mapea el estado del sistema a un color y un patrón de parpadeo |

## Flujo de extremo a extremo

### Salida (un conductor reporta un peligro)

```
mic ──▶ wake word ──▶ VAD ──▶ STT ──▶ clasificador ──▶ código
                                                          │
                                          ┌───────────────┴───────────────┐
                                          ▼                               ▼
                                     difusión por LoRa              log local
                                          │
                                          ▼
                                LED local + confirmación por TTS local
```

El conductor que reporta recibe una confirmación local corta ("Alerta enviada")
para saber que el sistema lo entendió. Esto es importante: sin esa confirmación,
el conductor no puede distinguir entre "el comboy fue advertido" y "no pasó
nada".

### Entrada (llega la alerta de otro nodo)

```
LoRa ──▶ decodificar trama ──▶ ¿duplicado? ──▶ FSM de alertas ──▶ LED
                                                     │
                                                     ├──▶ anuncio por TTS
                                                     └──▶ log
                                                     │
                                                     └──▶ reemisión (flooding)
```

## Ciclo de vida de la alerta

```
                    ┌───────────────────────┐
                    │        (ninguna)      │
                    └───────────┬───────────┘
       alerta emitida o recibida│
                                ▼
                    ┌───────────────────────┐
                    │        ACTIVA         │◀── tramas duplicadas:
                    │  LED encendido ·      │    no refrescan nada,
                    │  anunciada una vez    │    no vuelven a anunciar
                    └───────────┬───────────┘
                                │
                  180 s desde la emisión
                                │
                                ▼
                    ┌───────────────────────┐
                    │       EXPIRADA        │
                    │  LED apagado · log    │
                    └───────────────────────┘
```

Reglas:

- Una alerta se anuncia por voz **una sola vez** por nodo. Los duplicados que
  llegan por flooding no producen habla repetida.
- El LED permanece encendido los 180 segundos completos, de modo que un
  conductor que no escuchó la advertencia igual tenga una señal visual
  persistente.
- El temporizador de expiración se ancla al **instante de emisión declarado en
  la trama**, no al momento de la recepción. Esto mantiene a los nodos
  aproximadamente alineados aunque no compartan un reloj (ver más abajo).
- Puede haber varios peligros distintos activos al mismo tiempo. Cada uno lleva
  su propio `alert_id` y su propio temporizador. El LED refleja la **urgencia
  más alta** entre las alertas activas.

### El tiempo sin reloj

No hay RTC, ni GPS, ni NTP, así que los nodos no tienen un reloj de pared
compartido. Por eso la trama lleva un **contador de milisegundos relativo al
emisor** en lugar de una hora absoluta. Los receptores tratan la trama como
"activa durante 180 s a partir de ahora", lo cual es suficientemente preciso
dado que la latencia de transmisión de LoRa es menor a un segundo.

Esta es la razón por la que el trabajo diferido de auditoría (D6) va a requerir
un RTC de hardware antes de tener sentido. Sin una fuente de tiempo real, los
timestamps son relativos a la sesión y no sirven como evidencia.

## Modelo de concurrencia y prioridades

La Pi 4 tiene cuatro núcleos. La carga se reparte así.

| Responsabilidad | Ubicación | Justificación |
|---|---|---|
| Detección de wake word | Hilo dedicado, continuo | No debe sufrir inanición; es el único camino de entrada (D10) |
| Captura de audio y VAD | Hilo dedicado | El ritmo lo marca el dispositivo de audio, en tiempo real |
| STT | Proceso o pool de hilos aparte | A ráfagas, pesado en CPU, latencia tolerada |
| TTS | Proceso aparte | A ráfagas, debe poder adelantarse limpiamente |
| TX/RX de transporte | Hilo dedicado | Sensible al tiempo; no debe bloquearse con E/S |
| FSM de alertas, logger, LED | Bucle de eventos | Baja frecuencia, sin presión de tiempo |

### Reglas de adelantamiento (preemption)

1. **Las alertas remotas siempre se adelantan a la captura local.** Si llega una
   alerta mientras el conductor está a mitad de un enunciado, la captura se
   detiene, se reproduce la alerta, y el sistema le pide al conductor que
   repita. La seguridad del grupo está por encima de la entrada local.
2. **La reproducción es half-duplex.** El micrófono se silencia durante toda
   reproducción de TTS. Esto evita que el pipeline siempre-escuchando se escuche
   a sí mismo. La operación full-duplex requeriría cancelación de eco acústico,
   que queda fuera del alcance del MVP.
3. **La prioridad del líder aplica solo en la capa de radio.** Influye en quién
   gana el canal, nunca en lo que se dice localmente.

## Modelo de fallas y degradación

El sistema está diseñado asumiendo que **la conectividad es intermitente**,
especialmente en terreno de montaña.

| Condición | Comportamiento |
|---|---|
| Un nodo queda temporalmente fuera de alcance | La alerta puede no llegarle; el flooding a través de un nodo intermedio puede entregarla igual |
| Un nodo está en silencio varios intervalos de heartbeat | Se lo marca como ausente en el roster y se registra. Es informativo, no una alarma |
| No se reconoce la wake word | No se produce alerta. No se registra nada más allá de la detección perdida en sí |
| El STT no produce transcripción usable | Se clasifica como peligro DESCONOCIDO; se envía una advertencia genérica y se le pide al conductor que repita |
| La confianza de la clasificación es baja | El código se envía con `confianza = BAJA`, y los receptores formulan la advertencia como incierta ("posible peligro") |
| Falla el hardware de radio | El nodo no puede recibir ni enviar nada; la falla se registra de forma visible al arranque |
| Se corta la energía | El nodo reinicia y se reincorpora por heartbeat. Ningún estado de alerta persiste tras el reinicio (limitación del MVP) |

## Lenguaje de implementación

**Decisión cerrada: Python (D13).**

Python es el lenguaje de todo el MVP. No es una concesión para prototipar rápido:
es la elección correcta para este sistema.

### El trabajo pesado no corre en Python

Todas las bibliotecas que consumen CPU son código nativo con bindings de Python.

| Tarea | Implementación | Dónde corre el bucle caliente |
|---|---|---|
| Wake word | Porcupine | C |
| Captura de audio | PortAudio vía `sounddevice` | C |
| STT | Vosk | C++ |
| TTS | Piper | C++ |
| Radio (al llegar el hardware) | SX1262 por SPI | Kernel y SPI |
| Protocolo, FSM, clasificador, logs | Nuestro código | Python |

Python no es el motor de cómputo del sistema: es el **orquestador**. Las
bibliotecas nativas liberan el GIL mientras trabajan, así que la concurrencia
funciona.

### El aporte de Python a la latencia es marginal

| Etapa | Tiempo nativo | Costo de Python |
|---|---|---|
| Detección de wake word | continua | ~µs por callback |
| Fin de captura (VAD) | — | < 1 ms |
| STT (Vosk, frase corta) | 500–1500 ms | ~5 ms |
| Clasificación (embeddings) | A medir | ~5 ms |
| Extracción de campos (reglas) | — | < 1 ms |
| Codificar trama y enviar | ~0,2 ms | ~0,1 ms |
| Decodificar trama | — | < 1 ms |
| TTS (Piper, una oración) | 300–1000 ms | ~5 ms |
| **Total** | 800–2500 ms, sin clasificación | **~17 ms** |

El costo de la clasificación por embeddings está sin medir: es una de las
incógnitas que resuelve la Fase 4. Ver
[04-audio-e-ia.md](04-audio-e-ia.md#presupuesto-de-cpu-y-latencia).

Python aporta entre el 0,5% y el 1% de la latencia del pipeline. El cuello de
botella es el STT, no el lenguaje, y el margen de reacción es de 40 segundos a
3 minutos. Ver el
[presupuesto de tiempo de reacción](01-vision-y-alcance.md#presupuesto-de-tiempo-de-reacción).

### El único punto frágil: los callbacks de audio

PortAudio invoca los callbacks desde un hilo nativo hacia Python. Si el GIL está
tomado o el GC se dispara, el callback se atrasa y se pierden muestras.

Mitigaciones obligatorias:

- **No hacer trabajo dentro del callback.** Solo encolar (`queue.Queue`) y
  procesar en otro hilo.
- Usar un `blocksize` generoso.
- `gc.freeze()` después del arranque, para que el GC no recorra los objetos del
  pipeline.
- Para la wake word, dejar que **Porcupine maneje su propio dispositivo de
  audio**: así se evitan los callbacks de Python por completo en ese camino.

### Ruta de escape si algún día hace falta

No reescribir el proyecto. Primero perfilar con `py-spy` o `cProfile`. Si
aparece una función caliente puntual, mover **esa función** a una extensión
nativa con `maturin` + `pyo3` (Rust) o `cffi` (C). El resto del sistema no se
entera.

### Por qué se descartó Rust

Rust se había recomendado antes de conocer las restricciones reales del
proyecto. Dos argumentos lo descartaron:

1. **Costo humano.** Un lenguaje que el responsable del proyecto no puede
   escribir no entrega nada. El mejor lenguaje es el que se puede mantener.
2. **El argumento técnico no se sostenía.** La recomendación se apoyaba en
   "eficiencia y tiempo real" sin mirar dónde vive el trabajo pesado. Como todo
   el cómputo está en bibliotecas nativas y el margen de latencia es amplio, la
   ventaja de Rust se reduce a unos pocos milisegundos que no cambian el
   resultado.

## Abstracción de transporte

La capa de radio no habla con el hardware directamente: habla con una interfaz
de transporte. Esto permite desarrollar y validar todo el protocolo sobre UDP
antes de tener el hardware LoRa (D14).

```python
class Transport(Protocol):
    def send_frame(self, frame: bytes) -> None: ...
    def recv_frames(self) -> Iterator[tuple[bytes, str]]: ...

class UdpTransport(Transport):    # banco de pruebas, sobre WiFi
class LoraTransport(Transport):   # producción, SX1262
class LossyTransport(Transport):  # decorador: agrega pérdida y latencia
class NullTransport(Transport):   # pruebas de un solo nodo
```

El frame de 17 bytes viaja **sin modificar** como payload del datagrama, así que
el camino de datos es idéntico en ambos transportes. Pasar de UDP a LoRa es
cambiar una línea de configuración.

`LossyTransport` envuelve a otro transporte y agrega latencia y pérdida
configurables, para simular condiciones de radio antes de tener radio. Los
detalles y los niveles de prueba están en
[09-banco-de-pruebas.md](09-banco-de-pruebas.md).

## Configuración

Cada nodo lee un único archivo de configuración al arrancar:

```yaml
node:
  id: 3                    # único dentro del comboy, 1..255
  role: follower           # leader | follower
  priority_order: 3        # posición en el comboy; menor significa más cerca del líder

transport:
  kind: udp                # udp | lora
  udp:
    bind: "0.0.0.0:45550"
    peers: ["192.168.1.42:45550"]

simulation:                # solo en el banco de pruebas
  enabled: false           # activa LossyTransport
  delay_ms: 340            # aproxima el ToA de una trama a SF10
  loss: 0.10               # aproxima un enlace marginal

radio:                     # solo se usa cuando transport.kind = lora
  frequency_hz: 915000000
  spreading_factor: 10
  bandwidth_khz: 125
  coding_rate: "4/5"
  sync_word: 0x12
  tx_power_dbm: 20

audio:
  wake_word: "atencion comboy"
  tts_voice: "es_AR"
  half_duplex: true

log:
  path: "/var/log/comboy-safe/events.log"
  level: info
```

El PC y la Raspberry Pi corren **el mismo programa** con distinta configuración.
La configuración es estática en el MVP: el liderazgo dinámico (D11) y la
configuración remota son trabajo futuro.
