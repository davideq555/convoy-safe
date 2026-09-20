
python3 medir_embeddings.py bge-m3r_embeddings.py bge-m3
modelo=bge-m3  prefijo=''
carga inicial (42 frases): 20518 ms

LATENCIA por frase (ms): min=297 mediana=385 max=545

CALIDAD Y SEPARACION
  ok              'se nos cruzo un bicho en el medio del camino' -> ANIMAL (0.798, margen +0.128)
  ok              'che, hay un monton de piedras en el medio' -> PIEDRAS (0.772, margen +0.098)
  ok              'esta todo mojado, resbala que da miedo' -> LLUVIA (0.806, margen +0.137)
  ok              'no se ve nada de la niebla' -> NIEBLA (0.904, margen +0.313)
  ok              'hay un loco manejando en contra' -> CONTRAMANO (0.834, margen +0.109)
  ok              'la ruta esta hecha un colador de pozos' -> BACHE (0.870, margen +0.092)
  ok              'hay gente caminando al costado' -> PEATON (0.819, margen +0.060)
  FALLA           'frena que hay un choque adelante' -> CONTRAMANO (0.719)  esperado ACCIDENTE
  ok              'esta todo blanco de escarcha' -> HIELO (0.791, margen +0.238)
  ok              'hay un camion parado en la ruta' -> VEHICULO_DETENIDO (0.894, margen +0.123)
  ok              'se viene una curva muy cerrada' -> CURVA (0.825, margen +0.121)
  ok              'estan arreglando la ruta mas adelante' -> OBRA (0.875, margen +0.127)
  ok              'nos van a parar en un control' -> CONTROL (0.811, margen +0.115)
  ok              'se vino la montana abajo' -> DERRUMBE (0.561, margen +0.005)
  FALSO POSITIVO  'paramos a cargar nafta' -> VEHICULO_DETENIDO (0.633)
  ok ruido        'me gusta el asado' -> DERRUMBE (0.586)
  ok ruido        'llegamos en dos horas' -> CONTRAMANO (0.595)
  FALSO POSITIVO  'ponete el cinturon' -> CONTRAMANO (0.624)

acierto=13/14 (93%)

--- SEPARACION: ¿existe umbral? ---
  ruido maximo : 0.633  'paramos a cargar nafta' -> VEHICULO_DETENIDO
  señal minima : 0.561  'se vino la montana abajo'
  brecha       : -0.072  NO HAY UMBRAL: se solapan

--- ERRORES CONFIADOS (peor que no entender) ---
  0.719  'frena que hay un choque adelante' -> CONTRAMANO   (era ACCIDENTE)
