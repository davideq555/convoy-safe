# 09 — Banco de Pruebas

## Propósito

Permitir el desarrollo y la validación de **todo el pipeline y todo el
protocolo** con el hardware que ya existe, sin esperar a las placas LoRa.

## Hardware disponible hoy

| Equipo | Rol en el banco | Periféricos |
|---|---|---|
| Computadora local | **Emisor** (líder) | Micrófono |
| Raspberry Pi 4 (8 GB) | **Receptor** (seguidor) | Parlante |
| Red WiFi compartida | Medio de transporte | — |

LoRa todavía no está disponible. La cámara y el LED RGB tampoco.

### Entorno de la Raspberry Pi (confirmado)

La Pi no corre Raspberry Pi OS: corre **Ubuntu 24.04 aarch64**, kernel
`6.8.0-1064-raspi`. Python es **3.12.3** y el hostname es `eevee`. Por eso el
objetivo de `ruff` es `py312`: así ninguna sintaxis que no corra en el
intérprete real de despliegue llega al banco.

## Topología del banco

```
   ┌────────────────────────┐            ┌────────────────────────┐
   │   COMPUTADORA LOCAL    │            │   RASPBERRY PI 4       │
   │   rol: líder           │            │   rol: seguidor        │
   │                        │            │                        │
   │   micrófono ──▶ wake   │   WiFi     │   TTS ──▶ parlante     │
   │   STT ──▶ clasificador │◀──────────▶│   LED ──▶ ACT          │
   │   ▶ UdpTransport       │    UDP     │   ◀ UdpTransport       │
   └────────────────────────┘            └────────────────────────┘
```

## Un solo programa, dos roles

El PC y la Pi ejecutan **el mismo código**, diferenciados solo por su archivo de
configuración (`role: leader` / `role: follower`). Esto ya es un requisito del
diseño de producción (D11): todas las nodos son idénticos.

No escribir un "cliente de PC" y un "servidor de Pi" por separado. Si el código
se bifurca, la validación pierde valor, porque en producción cada vehículo tiene
que poder cumplir ambos roles.

## Configurar cada nodo sin editar archivos

Lo que cambia de una máquina a otra —id, rol, a qué dirección mandar— se pasa por
**variables de entorno**, que ganan sobre el YAML. Así un mismo archivo sirve en
las dos máquinas.

| Variable | Pisa a | Ejemplo |
|---|---|---|
| `COMBOY_NODE_ID` | `node.id` | `2` |
| `COMBOY_NODE_ROLE` | `node.role` | `follower` |
| `COMBOY_TRANSPORT` | `transport.kind` | `udp` |
| `COMBOY_UDP_BIND` | `transport.udp.bind` | `0.0.0.0:45550` |
| `COMBOY_UDP_PEERS` | `transport.udp.peers` | `eevee.local:45550` |
| `COMBOY_LOG_LEVEL` | `log.level` | `debug` |
| `COMBOY_EMBEDDING_KIND` | `embedding.kind` | `ollama` |
| `COMBOY_EMBEDDING_URL` | `embedding.url` | `http://localhost:11434` |
| `COMBOY_EMBEDDING_MODEL` | `embedding.model` | `qwen3-embedding:0.6b` |
| `COMBOY_EMBEDDING_TIMEOUT` | `embedding.timeout_s` | `60` |
| `COMBOY_EMBEDDING_CACHE` | `embedding.cache_path` | `.comboy-embeddings.json` |
| `COMBOY_ENV_FILE` | — (apunta a otro archivo de variables) | `config/node-pi.env` |

`COMBOY_UDP_PEERS` acepta varios pares separados por coma. Una variable presente
pero vacía se ignora: `COMBOY_UDP_PEERS=` no borra la lista del archivo. La
excepción es `COMBOY_EMBEDDING_CACHE=`, donde el vacío **deshabilita** el caché
en disco del índice.

Las rutas de datos no son overrides de la configuración: apuntan al archivo
**extra** que se fusiona sobre el corpus versionado, sin tocar `datos/`.
Opcionales: si no se definen, se usa solo la base.

| Variable | Qué define | Ejemplo |
|---|---|---|
| `COMBOY_CORPUS_PATH` | Corpus extra a fusionar con `datos/corpus.json` | `datos/extra-corpus.json` |
| `COMBOY_MEDICION_PATH` | Frases de medición extra a fusionar con `datos/medicion.json` | `datos/extra-medicion.json` |

### El archivo `.env`

Para no exportar variables a mano en cada terminal, cada máquina puede tener su
propio `.env`, que el nodo lee solo:

```bash
cp .env.example .env
```

`.env.example` está versionado y documenta todo lo configurable; `.env` no, así
que cada nodo tiene el suyo. **No hace falta `source`.**

Dos reglas deliberadas: solo se aceptan claves `COMBOY_*` —un `.env` no puede
inyectar `PATH` ni nada parecido— y el entorno real gana sobre el archivo. La
precedencia completa queda:

```
entorno real  >  .env  >  archivo YAML  >  valores por defecto
```

`COMBOY_ENV_FILE` permite apuntar a otro archivo, por si hacen falta varios
perfiles en la misma máquina.

### `peers` es la dirección del otro, no la propia

Conviene tenerlo claro porque es fácil confundirse: `bind` es dónde **yo**
escucho; `peers` es a dónde **yo mando**. Un nodo no puede deducir de sí mismo la
dirección de su par.

Para no averiguar direcciones a mano, cada nodo anuncia dónde escucha al arrancar:

```
INFO  boot  version=0.1.0 config=loaded local=192.168.25.155:45550
```

Ese `local=` es la IP real de la interfaz por la que sale el tráfico, no el
`0.0.0.0` del archivo. Es el dato que va del otro lado.

### Nombres mDNS en vez de IPs

La Pi tiene **una sola interfaz**, así que `eevee.local` resuelve siempre a su IP
de LAN y **sobrevive a que el DHCP se la cambie**. Por eso `config/node-pc.yaml`
lo usa como peer. No hace falta internet ni DNS: mDNS es local a la red.

La PC, en cambio, tiene varias interfaces (Docker, bridges) y su nombre mDNS
resuelve ambiguo: puede devolver una dirección inalcanzable. Del lado de la Pi va
una IP, y si el DHCP la cambia se pasa por `COMBOY_UDP_PEERS` sin tocar el YAML.

## Por qué UDP y no TCP

Aunque a primera vista TCP parece más cómodo, **es la elección equivocada para
este banco de pruebas**.

| Propiedad | TCP | UDP | LoRa | Se parece a LoRa |
|---|---|---|---|---|
| Límites de mensaje | Flujo continuo, requiere framing | Datagrama, preservado | Trama | **UDP** |
| Confiabilidad | Garantizada | Ninguna | Ninguna | **UDP** |
| Orden | Garantizado | Ninguno | Ninguno | **UDP** |
| Conexión | Requerida | Sin conexión | Ninguna | **UDP** |
| Broadcast | No | Sí | Sí | **UDP** |
| La pérdida es visible | No, la esconde | Sí | Sí | **UDP** |

El argumento central: **TCP esconde exactamente los modos de falla que el
protocolo existe para resolver.** Si se desarrolla sobre TCP:

- La caché de deduplicación nunca se ejercita, porque no hay duplicados.
- El flooding nunca se ejercita, porque no hace falta cubrir huecos.
- La lógica de retransmisión queda como código muerto.
- El manejo de tramas corruptas o incompletas nunca se prueba.

Todo eso aparece recién con el hardware real, en la ruta, que es el peor lugar
para descubrirlo. Con UDP se está obligado a resolverlo desde el día uno, y el
código que se escribe es el mismo que va a correr sobre LoRa.

## La abstracción de transporte

El resto del sistema nunca toca un socket. Habla con una interfaz.

```python
from typing import Protocol, Iterator


class Transport(Protocol):
    def send_frame(self, frame: bytes) -> None:
        """Envía una trama. Puede fallar silenciosamente: es best-effort."""
        ...

    def recv_frames(self) -> Iterator[tuple[bytes, str]]:
        """Genera (trama, origen). Bloqueante; corre en su propio hilo."""
        ...
```

Implementaciones:

| Clase | Uso | Comportamiento |
|---|---|---|
| `NullTransport` | Pruebas de un solo nodo | Descarta lo enviado, nunca recibe |
| `UdpTransport` | Banco de pruebas | Envía a la lista de pares configurada; recibe por `recvfrom` |
| `LossyTransport` | Banco de pruebas con estrés | Envuelve a otro transporte y agrega latencia y pérdida |
| `LoraTransport` | Producción | SX1262 sobre SPI. Se implementa cuando llegue el hardware |

**El frame de 17 bytes viaja sin modificar como payload del datagrama.** No hay
envoltorio, ni JSON, ni serialización extra. El camino de datos es byte a byte
idéntico al del LoRa, que es lo que hace que la migración sea trivial.

## Cómo simular LoRa sin tener LoRa

`LossyTransport` envuelve a otro transporte y le inyecta condiciones de radio
configurables:

```python
class LossyTransport(Transport):
    def __init__(self, inner: Transport, delay_ms: float, loss: float):
        self._inner = inner
        self._delay = delay_ms / 1000.0
        self._loss = loss

    def send_frame(self, frame: bytes) -> None:
        if random.random() < self._loss:
            return  # pérdida de paquete
        time.sleep(self._delay)  # tiempo de aire aproximado
        self._inner.send_frame(frame)
```

Valores iniciales sugeridos:

| Parámetro | Valor | Qué representa |
|---|---|---|
| `delay_ms` | 340 | El Time on Air de una trama de 17 bytes a SF10 |
| `loss` | 0.10 | Un enlace marginal con obstrucción parcial |

Con esto se puede verificar que el flooding, la deduplicación y los reintentos
efectivamente recuperan las alertas perdidas, **antes** de que exista una radio.

Se puede variar la pérdida de 0% a 40% y verificar dónde se rompe el protocolo.
Ese número es información valiosa: dice cuánto margen de radio hace falta.

### Alternativa en Linux: `tc netem`

Para condiciones más realistas se puede inyectar latencia y pérdida a nivel de
kernel:

```bash
sudo tc qdisc add dev wlan0 root netem delay 340ms loss 10%
# ...
sudo tc qdisc del dev wlan0 root
```

Es más realista porque afecta paquetes reales, pero tiene desventajas: requiere
root, afecta **todo** el tráfico de esa interfaz (puede cortar otras cosas) y no
es portable. El decorador en Python es más práctico para el día a día.

## Niveles de prueba

Cada nivel aísla un componente. Cuando algo falla, se sabe dónde mirar.

| Nivel | Qué se ejercita | Cómo se prueba | Criterio de aprobación |
|---|---|---|---|
| **L0** | Transporte + TTS | El PC envía una trama fija hardcodeada; la Pi la anuncia | La Pi pronuncia la frase correcta y ambos nodos lo registran en el log |
| **L1** | Clasificador + transporte + TTS | El PC toma una frase **escrita** por consola, la clasifica y la envía | La frase escrita produce el código correcto y la Pi lo anuncia |
| **L2** | Pipeline de audio completo | El PC: wake word → VAD → STT → clasificar → enviar | Hablando, el sistema produce el código correcto de punta a punta |
| **L3** | Protocolo bajo estrés | L2 con `LossyTransport` activo (10–40% de pérdida) | Las alertas llegan igual o el sistema informa quién no las recibió |
| **L4** | Radio real, alcance | Cambiar `UdpTransport` por `LoraTransport` | Ver Fase 5 de la [hoja de ruta](08-hoja-de-ruta.md) |

**Empezar por L0.** Valida el transporte y el audio de la Pi sin depender de
nada más, y es la base sobre la que se construye todo lo demás.

`NullTransport` permite además probar el pipeline completo de un solo nodo, sin
red: útil para depurar el clasificador o el TTS en aislamiento.

## Validar el pipeline sin micrófono

Además de los niveles, conviene tener una entrada por texto para depurar:

```bash
python -m comboy text "hay piedras en el carril derecho a dos kilometros"
```

Eso permite probar el clasificador y el protocolo sin depender de que el wake
word haya disparado, y sin hacer ruido. Es la herramienta que más se va a usar
durante el desarrollo, porque elimina la parte más frágil del sistema de la
ecuación mientras se trabaja en el resto.

## Advertencia: el PC no es la Pi

El PC es x86 y bastante más rápido que la Pi 4. Correr el STT en el PC **no
valida el desempeño en el hardware objetivo**.

La validación funcional sirve igual, pero hay que medir el desempeño aparte.

### Medir el real-time factor (RTF) del STT en la Pi

El RTF es segundos de cómputo dividido segundos de audio. Menor que 1 significa
más rápido que tiempo real.

```bash
# 1. Conseguir un WAV mono de 16 kHz con una frase de peligro típica
# 2. Medir
python -c "
import time, vosk, wave, json
w = wave.open('frase.wav')
dur = w.getnframes() / w.getframerate()
rec = vosk.KaldiRecognizer(vosk.Model('modelo-es'), w.getframerate())
t0 = time.perf_counter()
while True:
    data = w.readframes(4000)
    if not data: break
    rec.AcceptWaveform(data)
elapsed = time.perf_counter() - t0
print(f'RTF = {elapsed/dur:.2f}  ({dur:.2f}s de audio en {elapsed:.2f}s)')
"
```

Interpretación:

| RTF | Lectura |
|---|---|
| < 0,5 | Cómodo; hay margen para la cámara y otras cargas |
| 0,5 – 1,0 | Aceptable; entra dentro del presupuesto de reacción |
| > 1,0 | **Problema.** Hay que bajar de modelo, recortar audio o cambiar de motor |

Y lo mismo para Piper:

```bash
time piper -m es_AR.onnx -f salida.wav \
  <<< "Piedras en la calzada, carril derecho, a 2 kilómetros. Precaución."
```

Esta medición toma diez minutos y saca de encima la incógnita más grande del
proyecto. Vale la pena hacerla temprano.

## Medir la calidad del clasificador

La validación funcional (nivel L1) responde si **una** frase produce el código
correcto: `python -m comboy text "..."` pasa o falla. La **medición** responde
cuánto acierta el clasificador sobre **muchas** frases reservadas y devuelve un
porcentaje. Son preguntas distintas: la primera dice si el cableado funciona; la
segunda, si el juicio semántico alcanza para la ruta.

Las frases reservadas viven en `datos/medicion.json` y **no** se usan para
enseñar. Por eso miden de verdad.

```bash
python tools/medir_clasificador.py
```

El instrumento clasifica las 36 frases de peligro y las 28 de ruido, imprime el
detalle línea por línea y un resumen. Sale con código `0` si no hay errores
confiados ni falsos positivos, `1` si los hay, y `2` si no pudo medir (datos
ilegibles o servicio de embeddings caído). Un fallo del instrumento **nunca** se
cuenta como error del clasificador.

Flags útiles:

| Flag | Qué hace |
|---|---|
| `--url URL` | apunta a otro servicio de embeddings, p. ej. `http://eevee.local:11434` |
| `--model MODELO` | usa otro modelo |
| `--min-similarity FLOAT` | calibra el umbral de similitud sin tocar archivos |
| `--min-margin FLOAT` | calibra el margen de confianza sin tocar archivos |
| `--json` | imprime solo el resumen como JSON y suprime el detalle |
| `--sin-cache` | deshabilita el caché en disco y mide desde cero |

### Qué reporta

| Métrica | Definición | Umbral |
|---|---|---|
| **Aciertos** | `hazard == esperado` | ≥ 75% del MVP |
| **Abstenciones** | Dijo `DESCONOCIDO`. **No es un fallo**: es el respaldo seguro | — |
| **Fallos** | Código equivocado | — |
| **Errores confiados** | Fallo con confianza `ALTA` | **0** |
| **Falsos positivos** | Una frase de ruido anunciada como peligro con `ALTA` | **0** |
| **Calibración** | `min(similitud de los aciertos) - max(similitud del ruido)` | Dice si hay umbral limpio |

### Cómo leer los aciertos

| Acierto | Lectura |
|---|---|
| ≥ 90% | Listo para la ruta |
| 75–90% | Aceptable para el MVP; seguir agregando frases |
| < 75% | El corpus o el modelo no alcanzan |

**Los errores confiados son la métrica que manda.** La única cifra aceptable es
cero: un error confiado es un código equivocado con confianza `ALTA`, y el
sistema se lo diría al conductor con seguridad. Por eso la salida solo falla
cuando hay errores confiados o falsos positivos.

La calibración cierra el círculo: si es positiva, existe un `min_similarity` que
deja pasar todos los aciertos y rechaza todo el ruido; si es negativa, los dos
conjuntos se solapan y ningún umbral los separa.

### Cómo crece la medición

Cada frase que falle en la ruta se agrega a `datos/medicion.json`. La medición es
un banco vivo: más frases, mejor estimación. También se puede fusionar un archivo
extra con `COMBOY_MEDICION_PATH`, sin tocar el versionado.

Regla que no se rompe: **una frase no puede estar en el corpus y en la medición a
la vez.** Una frase del corpus se compara contra sí misma con similitud `1.0` y
no mide nada. Se enseña con una frase nueva en `datos/corpus.json` y se reserva
una **variante distinta** en `datos/medicion.json`.

## Tips físicos

**El LED de actividad de la Pi es gratis.** No hace falta comprar un LED para
validar la máquina de estados:

```bash
# Desactivar el trigger por defecto (requiere root)
echo none | sudo tee /sys/class/leds/ACT/trigger
# Encender y apagar
echo 1 | sudo tee /sys/class/leds/ACT/brightness
echo 0 | sudo tee /sys/class/leds/ACT/brightness
```

Es on/off, no RGB, así que no puede mostrar colores. Pero alcanza para validar
que la máquina de estados enciende y apaga el indicador cuando corresponde.

**Para el TTS, `espeak-ng` sirve para empezar.** Es instantáneo, no requiere
modelos ni descargas, y suena robótico. En Ubuntu se instala con
`sudo apt install espeak-ng`. Sirve para validar el transporte y el flujo sin
pelearse primero con Piper. Después se cambia.

## Checklist de migración a LoRa

Cuando lleguen las placas, el cambio debería ser acotado. Si no lo es, algo se
diseñó mal.

1. Implementar `LoraTransport` con la misma interfaz.
2. Cambiar `transport.kind` a `lora` en la configuración.
3. Desactivar `simulation.enabled` (la pérdida y la latencia ahora son reales).
4. Verificar que ninguna otra parte del sistema haya cambiado.
5. Correr los niveles L0 a L3 nuevamente, ahora sobre radio.
6. Recién entonces pasar a las mediciones de alcance de la Fase 5.

Si en el paso 4 aparece que hubo que tocar el protocolo, el clasificador o la FSM,
significa que alguna parte del sistema se había acoplado al transporte y hay que
corregirlo antes de seguir.

## Configuración del banco

```yaml
# Nodo PC (líder)
node:
  id: 1
  role: leader
  priority_order: 1

transport:
  kind: udp
  udp:
    bind: "0.0.0.0:45550"
    peers: ["192.168.1.42:45550"]

simulation:
  enabled: false
  delay_ms: 340
  loss: 0.10
```

```yaml
# Nodo Raspberry Pi (seguidor)
node:
  id: 2
  role: follower
  priority_order: 2

transport:
  kind: udp
  udp:
    bind: "0.0.0.0:45550"
    peers: ["192.168.1.10:45550"]

simulation:
  enabled: false
  delay_ms: 340
  loss: 0.10
```

La lista de pares (`peers`) alcanza para dos nodos. Si se agregan más, cada nodo
incluye a los demás, o se pasa a un `peers` descubierto por los heartbeats. La
segunda opción ya está prevista por el roster y se puede habilitar sin cambiar el
transporte.
