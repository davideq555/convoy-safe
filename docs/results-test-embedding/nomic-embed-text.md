python3 medir_embeddings.py nomic-embed-text
modelo=nomic-embed-text  prefijo=''
carga inicial (42 frases): 6889 ms

LATENCIA por frase (ms): min=125 mediana=164 max=210

CALIDAD Y SEPARACION
  FALLA           'se nos cruzo un bicho en el medio del camino' -> PEATON (0.675)  esperado ANIMAL
  ok              'che, hay un monton de piedras en el medio' -> PIEDRAS (0.749, margen +0.087)
  ok              'esta todo mojado, resbala que da miedo' -> LLUVIA (0.681, margen +0.083)
  ok              'no se ve nada de la niebla' -> NIEBLA (0.847, margen +0.244)
  FALLA           'hay un loco manejando en contra' -> CURVA (0.757)  esperado CONTRAMANO
  ok              'la ruta esta hecha un colador de pozos' -> BACHE (0.872, margen +0.120)
  ok              'hay gente caminando al costado' -> PEATON (0.795, margen +0.083)
  FALLA           'frena que hay un choque adelante' -> CONTRAMANO (0.723)  esperado ACCIDENTE
  ok              'esta todo blanco de escarcha' -> HIELO (0.755, margen +0.144)
  ok              'hay un camion parado en la ruta' -> VEHICULO_DETENIDO (0.864, margen +0.034)
  ok              'se viene una curva muy cerrada' -> CURVA (0.890, margen +0.224)
  FALLA           'estan arreglando la ruta mas adelante' -> HIELO (0.804)  esperado OBRA
  ok              'nos van a parar en un control' -> CONTROL (0.785, margen +0.179)
  FALLA           'se vino la montana abajo' -> ANIMAL (0.666)  esperado DERRUMBE
  FALSO POSITIVO  'paramos a cargar nafta' -> VEHICULO_DETENIDO (0.663)
  FALSO POSITIVO  'me gusta el asado' -> DERRUMBE (0.641)
  FALSO POSITIVO  'llegamos en dos horas' -> LLUVIA (0.627)
  FALSO POSITIVO  'ponete el cinturon' -> BACHE (0.608)

acierto=9/14 (64%)

--- SEPARACION: ¿existe umbral? ---
  ruido maximo : 0.663  'paramos a cargar nafta' -> VEHICULO_DETENIDO
  señal minima : 0.681  'esta todo mojado, resbala que da miedo'
  brecha       : +0.017  HAY umbral (finisimo)

--- ERRORES CONFIADOS (peor que no entender) ---
  0.804  'estan arreglando la ruta mas adelante' -> HIELO   (era OBRA)
  0.757  'hay un loco manejando en contra' -> CURVA   (era CONTRAMANO)
  0.723  'frena que hay un choque adelante' -> CONTRAMANO   (era ACCIDENTE)
  0.675  'se nos cruzo un bicho en el medio del camino' -> PEATON   (era ANIMAL)
  0.666  'se vino la montana abajo' -> ANIMAL   (era DERRUMBE)
