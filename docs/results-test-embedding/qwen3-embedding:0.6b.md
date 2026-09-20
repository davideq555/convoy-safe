python3 medir_embeddings.py qwen3-embedding:0.6b
modelo=qwen3-embedding:0.6b  prefijo=''
carga inicial (42 frases): 20514 ms

LATENCIA por frase (ms): min=314 mediana=445 max=696

CALIDAD Y SEPARACION
  ok              'se nos cruzo un bicho en el medio del camino' -> ANIMAL (0.845, margen +0.055)
  ok              'che, hay un monton de piedras en el medio' -> PIEDRAS (0.693, margen +0.097)
  FALLA           'esta todo mojado, resbala que da miedo' -> CURVA (0.650)  esperado LLUVIA
  ok              'no se ve nada de la niebla' -> NIEBLA (0.954, margen +0.242)
  ok              'hay un loco manejando en contra' -> CONTRAMANO (0.736, margen +0.004)
  ok              'la ruta esta hecha un colador de pozos' -> BACHE (0.874, margen +0.106)
  ok              'hay gente caminando al costado' -> PEATON (0.762, margen +0.064)
  ok              'frena que hay un choque adelante' -> ACCIDENTE (0.744, margen +0.015)
  ok              'esta todo blanco de escarcha' -> HIELO (0.818, margen +0.144)
  ok              'hay un camion parado en la ruta' -> VEHICULO_DETENIDO (0.842, margen +0.103)
  ok              'se viene una curva muy cerrada' -> CURVA (0.853, margen +0.188)
  ok              'estan arreglando la ruta mas adelante' -> OBRA (0.735, margen +0.013)
  ok              'nos van a parar en un control' -> CONTROL (0.769, margen +0.118)
  ok              'se vino la montana abajo' -> DERRUMBE (0.820, margen +0.062)
  ok ruido        'paramos a cargar nafta' -> ACCIDENTE (0.556)
  FALSO POSITIVO  'me gusta el asado' -> DERRUMBE (0.617)
  FALSO POSITIVO  'llegamos en dos horas' -> ACCIDENTE (0.652)
  FALSO POSITIVO  'ponete el cinturon' -> CONTROL (0.680)

acierto=13/14 (93%)

--- SEPARACION: ¿existe umbral? ---
  ruido maximo : 0.680  'ponete el cinturon' -> CONTROL
  señal minima : 0.693  'che, hay un monton de piedras en el medio'
  brecha       : +0.013  HAY umbral (finisimo)

--- ERRORES CONFIADOS (peor que no entender) ---
  0.650  'esta todo mojado, resbala que da miedo' -> CURVA   (era LLUVIA)
