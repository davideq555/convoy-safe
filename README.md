# convoy-safe

Sistema de alerta temprana de peligros en ruta para convoys de vehículos que
circulan por caminos de montaña, sin cobertura celular, sin GPS y sin acceso a
internet.

Cada vehículo lleva una Raspberry Pi 4 que escucha al conductor, interpreta una
advertencia hablada, y transmite por LoRa un código estructurado y compacto al
resto del convoy. Cada vehículo receptor sintetiza la advertencia localmente con
texto-a-voz y enciende una señal visual.

> **Estado:** fase de diseño. No hay implementación iniciada.

---

## La decisión arquitectónica central

**LoRa no puede transportar audio, así que transporta significado.**

En una configuración realista (SF10, ancho de banda de 125 kHz, tasa de
codificación 4/5) la tasa nominal de LoRa es de unos 980 bps, y la tasa efectiva
después del framing es todavía menor. Transmitir voz —incluso con un vocoder
pesado— obligaría a elegir entre alcance e inteligibilidad, y el proyecto no
puede pagar ese precio.

En lugar de eso, el sistema transmite un **código estructurado de ~17 bytes** que
describe el peligro (tipo, carril, distancia aproximada, urgencia, confianza).
Cada nodo receptor convierte ese código nuevamente en habla localmente, con un
motor de texto-a-voz embarcado.

Consecuencias de esta decisión:

- Micrófono y parlante son **dispositivos estrictamente locales**: ningún dato de
  audio cruza el enlace de radio.
- El presupuesto de radio se mantiene holgado: una alerta que llega a todo el
  convoy cuesta entre 2 y 5 segundos de tiempo de canal.
- El sistema funciona completamente offline, sin ninguna dependencia de nube.
- No hay ningún LLM en el camino de la alerta (ver
  [docs/04-audio-e-ia.md](docs/04-audio-e-ia.md)).

---

## Decisiones cerradas

Se acordaron durante la conversación de diseño y se consideran firmes hasta que
se revisen explícitamente.

| # | Decisión | Consecuencia |
|---|---|---|
| D1 | El convoy ocupa **hasta ~5 km en total**; la separación entre vehículos es variable | Se asumen enlaces LoRa directos, pero el protocolo debe tolerar la pérdida intermitente de línea de vista |
| D2 | **Cualquier vehículo puede alertar**; el líder tiene prioridad de transmisión | Requiere arbitraje de canal con prioridad para el líder |
| D3 | Las alertas son **de un solo disparo con retransmisiones** si no se recibieron correctamente | Requiere broadcast confiable con acuse de recibo implícito |
| D4 | La salida es **síntesis de voz local más un LED** para situaciones de mucho ruido | Doble canal de salida: TTS + indicador visual codificado |
| D5 | **Sin GPS y sin internet.** Caminos de montaña y zonas alejadas | Toda la inferencia corre embarcada; la ubicación del peligro la declara el conductor |
| D6 | **Solo logs en texto plano**, para desarrollo. Sin auditoría, hashes ni hora confiable | La auditoría de nivel evidencial queda explícitamente diferida, no cancelada |
| D7 | **La alerta se cierra por timeout a los 180 segundos** | No hay mensaje manual de "vía libre" en el MVP |
| D8 | **Solo se almacena la transcripción**, nunca el audio | Privacidad por diseño y menor uso de almacenamiento |
| D9 | **La ubicación es solo una distancia estimada** | Sin puntos de referencia, sin kilometraje, sin coordenadas en el payload |
| D10 | **Sin botones físicos** en el MVP | La voz es el único camino de entrada — ver riesgo R1 |
| D11 | **El líder se asigna por orden configurado** | Configuración estática por ahora; el liderazgo dinámico es trabajo futuro |
| D12 | **Sin LLM en el camino crítico** | Embeddings + reglas para clasificar; el LLM queda diferido para el fallo elegante |
| D13 | **Python para todo el MVP** | El cómputo pesado corre en bibliotecas nativas (Porcupine, Vosk, Piper); Python orquesta y aporta ~1% de la latencia total |
| D14 | **El transporte se abstrae tras una interfaz** | El banco de pruebas usa UDP, no TCP, para no ocultar los modos de falla que el protocolo existe para resolver |

---

## Índice de documentos

| Documento | Contenido |
|---|---|
| [docs/01-vision-y-alcance.md](docs/01-vision-y-alcance.md) | Problema, escenario, objetivos, no-objetivos, límite de alcance |
| [docs/02-arquitectura.md](docs/02-arquitectura.md) | Arquitectura del sistema, anatomía del nodo, flujos, ciclo de vida de la alerta |
| [docs/03-protocolo-de-radio.md](docs/03-protocolo-de-radio.md) | Parámetros LoRa, formato de trama, flooding, prioridad, roster |
| [docs/04-audio-e-ia.md](docs/04-audio-e-ia.md) | Wake word, VAD, STT, clasificación, TTS, máquina de estados de audio |
| [docs/05-hardware.md](docs/05-hardware.md) | Lista de materiales, energía, antenas, térmica, instalación, regulación |
| [docs/06-codigos-y-logs.md](docs/06-codigos-y-logs.md) | Catálogo de códigos de peligro, codificación del payload, formato de logs |
| [docs/07-riesgos.md](docs/07-riesgos.md) | Registro de riesgos, decisiones diferidas, puntos a medir en campo |
| [docs/08-hoja-de-ruta.md](docs/08-hoja-de-ruta.md) | Plan de implementación por fases y estrategia de validación |
| [docs/09-banco-de-pruebas.md](docs/09-banco-de-pruebas.md) | Banco de pruebas PC + Raspberry Pi sobre UDP, niveles L0–L4, simulación de LoRa |

---

## Decisiones abiertas

| Punto | Estado | Notas |
|---|---|---|
| Spreading factor de producción | Provisional SF10 | Debe validarse con mediciones en los caminos reales |
| Licenciamiento del motor de wake word | Abierto | Porcupine es gratuito para uso personal, pero tiene licencia para uso comercial |
| Micrófono | Abierto | El factor decisivo es su desempeño en cabina con ruido |
| Desempeño del STT en la Pi 4 | A medir | Hay que medir el *real-time factor* en el hardware objetivo — ver [docs/09-banco-de-pruebas.md](docs/09-banco-de-pruebas.md) |

---

## Glosario

| Término | Significado |
|---|---|
| **Convoy** | El grupo de 2 a 6 vehículos que cooperan |
| **Nodo** | El sistema instalado en un vehículo: Raspberry Pi 4 + radio + micrófono + parlante + LED |
| **Líder** | El nodo configurado como cabeza del convoy, con prioridad de transmisión |
| **Seguidor** | Cualquier nodo que no es el líder |
| **Código de peligro** | La descripción estructurada y compacta del peligro en ruta que viaja por LoRa |
| **Alerta** | Un código de peligro que fue transmitido y está actualmente activo |
| **Roster** | El conjunto de nodos que se cree presentes en el convoy, derivado de los heartbeats |
| **Wake word** | La frase hablada ("atención comboy") que activa la captura de voz |
| **Flooding** | El esquema de reemisión que le da redundancia y alcance a la capa de radio |
| **ToA** | Time on Air — cuánto tiempo ocupa una trama el canal LoRa |
| **SF** | Spreading Factor — el parámetro de LoRa que intercambia tasa de datos por alcance |
| **CAD** | Channel Activity Detection — la primitiva de "escuchar antes de hablar" de la radio |
| **VAD** | Voice Activity Detection — detección de actividad de voz |
| **STT** | Speech-to-Text — reconocimiento de habla |
| **TTS** | Text-to-Speech — síntesis de habla |
| **Transporte** | La interfaz que abstrae el medio de envío. Hoy UDP sobre WiFi; mañana LoRa |
| **RTF** | Real-Time Factor — segundos de cómputo por segundo de audio. Menor que 1 significa más rápido que tiempo real |
| **Banco de pruebas** | El entorno de desarrollo con el PC como emisor y la Raspberry Pi como receptor, conectados por WiFi |
