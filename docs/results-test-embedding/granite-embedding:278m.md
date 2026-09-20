python3 medir_embeddings.py ibm/granite-embedding:278m
modelo=ibm/granite-embedding:278m  prefijo=''
carga inicial (42 frases): 10266 ms

LATENCIA por frase (ms): min=100 mediana=129 max=174

CALIDAD Y SEPARACION
  ok              'se nos cruzo un bicho en el medio del camino' -> ANIMAL (0.759, margen +0.005)
  ok              'che, hay un monton de piedras en el medio' -> PIEDRAS (0.771, margen +0.066)
  ok              'esta todo mojado, resbala que da miedo' -> LLUVIA (0.742, margen +0.069)
  ok              'no se ve nada de la niebla' -> NIEBLA (0.931, margen +0.248)
  ok              'hay un loco manejando en contra' -> CONTRAMANO (0.774, margen +0.010)
  FALLA           'la ruta esta hecha un colador de pozos' -> PIEDRAS (0.832)  esperado BACHE
  ok              'hay gente caminando al costado' -> PEATON (0.768, margen +0.064)
  FALLA           'frena que hay un choque adelante' -> CURVA (0.772)  esperado ACCIDENTE
  FALLA           'esta todo blanco de escarcha' -> PIEDRAS (0.739)  esperado HIELO
  ok              'hay un camion parado en la ruta' -> VEHICULO_DETENIDO (0.882, margen +0.017)
  ok              'se viene una curva muy cerrada' -> CURVA (0.860, margen +0.136)
  ok              'estan arreglando la ruta mas adelante' -> OBRA (0.817, margen +0.070)
  ok              'nos van a parar en un control' -> CONTROL (0.734, margen +0.020)
  ok              'se vino la montana abajo' -> DERRUMBE (0.806, margen +0.038)
  FALSO POSITIVO  'paramos a cargar nafta' -> VEHICULO_DETENIDO (0.718)
  FALSO POSITIVO  'me gusta el asado' -> ANIMAL (0.692)
  FALSO POSITIVO  'llegamos en dos horas' -> CONTRAMANO (0.643)
  FALSO POSITIVO  'ponete el cinturon' -> DERRUMBE (0.779)

acierto=11/14 (79%)

--- SEPARACION: ¿existe umbral? ---
  ruido maximo : 0.779  'ponete el cinturon' -> DERRUMBE
  señal minima : 0.734  'nos van a parar en un control'
  brecha       : -0.045  NO HAY UMBRAL: se solapan

--- ERRORES CONFIADOS (peor que no entender) ---
  0.832  'la ruta esta hecha un colador de pozos' -> PIEDRAS   (era BACHE)
  0.772  'frena que hay un choque adelante' -> CURVA   (era ACCIDENTE)
  0.739  'esta todo blanco de escarcha' -> PIEDRAS   (era HIELO)
