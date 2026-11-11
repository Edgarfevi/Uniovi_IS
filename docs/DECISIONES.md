# Registro de decisiones del proyecto

Este documento explica por qué el proyecto es como es. Cada decisión lleva su motivo y, cuando existe, lo que se descartó. Si algo del código te sorprende, probablemente esté aquí.

El README dice cómo se usa. Este documento dice por qué.

---

## 1. Qué estamos construyendo y qué no

**Decisión:** el gemelo digital es de procesos, no 3D y sin robots. Solo modela la trazabilidad de cubetas del almacén inteligente de COFAS.

**Qué hace:** proyecta hora a hora cuántas cubetas habrá disponibles, simula decisiones (regular el flujo de pedidos, acelerar el vaciado y la devolución, usar un contenedor alternativo) y estima la probabilidad de bajar del umbral de alerta (unas 1.500 cubetas).

**Por qué este alcance:** es el caso de uso del reto que se puede defender con datos de eventos por cubeta. Un gemelo 3D o de robots exigiría datos que no tenemos.

**Requisitos que condicionan todo lo demás:**
- El stock puede ser negativo. Por debajo de 0 hay quiebre (pedidos que no se pueden servir) y no se recorta.
- La proyección es una banda (p10 a p90), no un número.
- Todo tiene que poder cambiarse por datos reales de COFAS sin tocar el modelo.
- Hay que distinguir siempre entre dato, supuesto y desconocido.
- El equipo quería entender cada paso, así que el proyecto se construyó pieza a pieza.

---

## 2. Principios de trabajo

### 2.1 Todo en `.py` y YAML
Los parámetros viven en YAML y la lógica en Python. Así se puede cambiar un valor sin tocar código, y el código no esconde números mágicos.

### 2.2 Cada parámetro declara su estado
Cada valor lleva `estado` y `fuente`. Los estados posibles son:

| Estado           | Significa                             |
| ---------------- | ------------------------------------- |
| `dato`           | viene de COFAS o de una fuente fiable |
| `dato_derivado`  | calculado a partir de un dato         |
| `dato_con_rango` | solo se conoce un rango               |
| `supuesto`       | lo elegimos nosotros sin base         |
| `desconocido`    | no se sabe, hay un valor provisional  |

**Por qué:** casi todo lo que usamos es supuesto. Si no lo marcamos, es fácil olvidarlo y acabar defendiendo un número que nos inventamos. Todo lo que no sea `dato` se sustituye cuando COFAS aporte valores. `states_summary` lo lista y el dashboard lo muestra.

### 2.3 Convención de nombres
- Identificadores del código (funciones, variables, módulos) en inglés.
- Comentarios, docstrings y mensajes de error en español.
- Nombres de datos (claves de YAML, tablas, columnas, tipos de evento) en español.

**Por qué:** los nombres de datos son parte del contrato con COFAS y con el equipo (que habla español). El código en inglés es más fácil de leer para quien conozca Python.

### 2.4 Se avanza paso a paso
Primero se generó una versión que se descartó (ver sección 12) por saltarse la validación de fuentes. Desde entonces: cada módulo se prueba antes de entregarse y viene con su comando de prueba.

---

## 3. Arquitectura

### 3.1 Layout `src/` con `pyproject.toml`
El paquete se llama `cofas_twin` y se instala en modo editable (`pip install -e .`).

**Por qué:** con `src/` los imports siempre apuntan al paquete instalado y no a la carpeta de trabajo. Evita errores raros de rutas.

### 3.2 Un único generador aleatorio por ejecución
`generate_history` crea un `rng` con la semilla del YAML y lo pasa a cada módulo, en este orden: maestros, demanda, pedidos, ciclos, ruido.

**Por qué:** así todo es reproducible con una sola semilla. Cambiar el orden o añadir un sorteo cambia todos los datos generados después, aunque la semilla sea la misma. Es normal y no es un fallo.

### 3.3 Generador y modelo no se importan entre sí
El generador produce las seis tablas. El modelo las lee solo a través de un adaptador.

**Por qué:** si el modelo supiera cómo se generaron los datos, no podría usarse con datos reales.

### 3.4 Dos YAML separados: `parametros.yaml` y `modelo.yaml`
El primero lo lee el generador y el segundo el modelo. **El modelo no puede leer el del generador.**

**Por qué (la decisión más importante de la arquitectura):** si el modelo leyera los parámetros del generador, estaría "estimando" exactamente lo que se usó para crear los datos y la validación saldría perfecta sin demostrar nada. Es la circularidad. Con YAML separados, el modelo estima desde los datos, y la validación puede comprobar si recupera lo que se usó.

### 3.5 Adaptadores
`synthetic_adapter.load_tables()` y `cofas_adapter.load_tables()` devuelven lo mismo: las seis tablas, validadas contra el esquema.

**Por qué:** cambiar de datos sintéticos a reales es cambiar de adaptador. El adaptador de COFAS es un esqueleto con tres diccionarios vacíos (`FILES`, `COLUMN_MAP`, `EVENT_MAP`). No inventa nada: si falta una tabla o columna, falla con un mensaje que dice qué rellenar.

### 3.6 Carpeta `verdad` solo para validar
El generador guarda dos versiones: `observado` (con ruido de registro, sin calentamiento) y `verdad` (limpia, con calentamiento). **Solo la validación lee `verdad`.**

**Por qué:** en datos reales no existe la verdad. Si el modelo la usara, funcionaría en simulación y fallaría con COFAS.

---

## 4. Esquema de datos (`scheme.py`)

Seis tablas: `farmacias`, `rutas`, `cubetas`, `pedidos`, `pedido_cubeta`, `eventos_cubeta`.

| Decisión                                                                       | Motivo                                                                                                                |
| ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| No hay `estado_actual` en `cubetas`                                            | El estado se calcula a partir de los eventos. Guardarlo sería duplicar información y tendría que mantenerse coherente |
| `eventos_cubeta` tiene `cubeta_destino`                                        | Solo se rellena en FUSION: la cubeta a la que se pasa el contenido                                                    |
| `eventos_cubeta` tiene `fuente_registro`                                       | Lectura, voz o sistema. La calidad del registro depende de cómo se registra                                           |
| `cubeta_id`, `pedido_id`, `ruta_id`, `cubeta_destino` admiten nulos en eventos | Un registro por voz puede no llevar ID (por ejemplo una recogida contada, no leída)                                   |
| Los nombres de tabla y campo son una propuesta                                 | Cuando llegue el diagrama real de COFAS, se renombra en `scheme.py` y en el adaptador, y nada más                     |
| El esquema se valida en `validate_all`                                         | Es el contrato entre generador, adaptadores y modelo                                                                  |

Tipos de evento: ENTRADA_ALMACEN, ENTRADA_LAVADO, SALIDA_LAVADO, DISPONIBLE, ASIGNADA_PEDIDO, MUELLE, SALIDA_REPARTO, ENTREGA_FARMACIA, RECOGIDA_VACIA, CONSOLIDACION, FUSION, NO_LOCALIZADA.

**FUSION** se añadió porque en el planteamiento de la solución (voz) se puede registrar "paso la 4821 a la 4830".

---

## 5. Generador sintético

### 5.1 Por qué sintético y no un dataset público
No encontramos ningún dataset público de ciclos de contenedores retornables. Se barajaron un dataset de picking de calzado (Mendeley), uno de ventas farmacéuticas (Kaggle), recetas del Ministerio y SiVIRA. Ninguno se pudo validar ni descargar, y ninguno tiene la estructura de eventos por cubeta.

El documento de generación original suponía distribuciones que podían no ser las de COFAS. Por eso las distribuciones son parámetros marcados como supuesto y se sustituyen cuando haya datos.

La familia lognormal para el tiempo en farmacia se apoya en literatura (Li y Cobb 2022, tiempo de ciclo de ida lognormal). Los valores concretos son supuestos nuestros.

### 5.2 Maestros (`masters.py`)
- **n_cubetas = 17.500**, `dato_con_rango [15.000, 20.000]`. El rango lo dio un compañero y falta confirmarlo con COFAS.
- **n_farmacias = 650**. Supuesto basado en ">650 socios" de la presentación de COFAS. Se asume 1 socio = 1 farmacia, sin confirmar.
- **n_rutas = 40**, desconocido. No sabemos cuántas furgonetas hay.
- Cada ruta recibe al menos una farmacia y el resto se reparte al azar. Evita rutas vacías.
- Tamaño de farmacia (pequeña 50%, mediana 35%, grande 15%) con factor de demanda 0,6, 1,0 y 1,8. Todo supuesto sin base. El factor se normaliza a media 1, de modo que el total diario lo fija solo `pedidos_por_dia`.
- `hora_salida_rutas` entre 9 y 12h. Supuesto. Solo es informativo en la versión actual.
- Las zonas (Oviedo, Gijón, Avilés...) son nombres provisionales.

### 5.3 Demanda (`demand.py`)
Genera cuántos pedidos llegan cada día y cada hora. Es una tabla intermedia, no una de las seis.

Cadena de sorteos:
1. **Esperado del día** = base × factor día de la semana × factor mes × (1 + incremento si hay crisis).
2. **Ruido diario relativo** (10%, normal) y después **Poisson**, el azar propio de contar pedidos.
3. **Reparto por horas** con una multinomial según el perfil horario.

Decisiones:
- **Crisis como episodios** (2 a 3 al año, 3 a 5 días, +40%): sirven para que el histórico tenga picos que el modelo tenga que absorber.
- **Domingo con factor 0**: no hay pedidos. Consecuencia: si una proyección empieza en domingo, las palancas de demanda no se notan ese día.
- **Factores de mes** (ene, feb y dic 1,25; verano 0,9): vienen del documento de generación original. El resto a 1,0 es provisional.
- **Perfil horario** con picos a las 8, 11 y 15: provisional. **No reproduce la ola de mediodía del reto** (ver 9.3).
- **pedidos_por_dia = 2.500**: provisional. Con 2,3 cubetas por pedido salen unas 5.750 salidas por día, que cuadra con la estimación hecha a partir de compras (5.400 a 5.700 por día laborable). No cuadra con las 6.900 del documento original ni con el gráfico del reto.

### 5.4 Pedidos (`orders.py`)
- Cubetas por pedido: `1 + Poisson(1,3)` con tope 8, media 2,3 (del documento de generación).
- Cada pedido cae en una farmacia con probabilidad proporcional a su `factor_demanda`.
- Líneas por pedido: lognormal, mediana 15. **No afecta al balance de cubetas**, está para que los pedidos parezcan pedidos.
- Prioridad (5% urgente): solo una etiqueta, tampoco afecta al balance.
- `oleada` es provisional: la hora de llegada. Hasta saber cómo la define COFAS.

### 5.5 Ciclo de vida de la cubeta (`cycle.py`)
Es el corazón del generador. Cada cubeta recorre:

`DISPONIBLE → ASIGNADA_PEDIDO → MUELLE → SALIDA_REPARTO → ENTREGA_FARMACIA → (CONSOLIDACION) → RECOGIDA_VACIA → ENTRADA_ALMACEN → (ENTRADA_LAVADO → SALIDA_LAVADO) → DISPONIBLE`

Decisiones y motivos:

| Decisión                                                                                                                                                                                                                              | Motivo                                                                                                                                                                           |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Los pedidos se recorren en orden cronológico y cada uno toma las cubetas **FIFO** (las que más tiempo llevan libres)                                                                                                                  | Es la regla más simple y plausible. Supuesto: no sabemos cómo elige COFAS                                                                                                        |
| Las duraciones se **sortean de antemano** por hueco (cubeta en un pedido)                                                                                                                                                             | Hace el bucle principal rápido (unos 25 segundos para seis meses)                                                                                                                |
| Las fases usan distribuciones propias: preparación lognormal (mediana 45 min), espera en muelle uniforme (20 a 90 min), transporte normal truncada (media 105 min, 30 a 180), tiempo en farmacia lognormal (mediana 20 h, sigma 0,68) | Todo supuesto. Valores razonables dentro de lo que dice el documento original                                                                                                    |
| **La vuelta dura como la ida**                                                                                                                                                                                                        | Supuesto sin base                                                                                                                                                                |
| Si no hay cubetas libres, **el pedido espera**                                                                                                                                                                                        | Es la huella del quiebre en los datos: `ASIGNADA_PEDIDO` menos `fecha_hora` del pedido                                                                                           |
| **Lavado**: 40% de las cubetas, capacidad de 600 por hora, 1 hora                                                                                                                                                                     | Del documento de generación. El lavado es una cola con capacidad, no un retraso fijo                                                                                             |
| **CONSOLIDACION** (5%): la cubeta tarda entre 4 y 12 h más                                                                                                                                                                            | Del documento original                                                                                                                                                           |
| **FUSION** (3%): solo con otra cubeta del mismo pedido, registrada por voz                                                                                                                                                            | Evento nuevo de la fase de voz. Valor sin base                                                                                                                                   |
| **NO_LOCALIZADA**: la cubeta no aparece al recoger. Con probabilidad 0,5 reaparece (tras una exponencial de media 7 días) y si no, se pierde                                                                                          | La pérdida (0,05% por ciclo) viene de 900 compras entre 1,7 millones de salidas (por confirmar), e incluye roturas y crecimiento de flota. La fracción que reaparece es supuesto |
| **Margen de 2 segundos entre eventos de una misma cubeta** (`EPS_H`)                                                                                                                                                                  | Los eventos se redondean a segundos. Con 1 s salían empates e inversiones (ver sección 11)                                                                                       |
| **Calentamiento de 14 días**: todos los eventos se registran, luego se recorta                                                                                                                                                        | El histórico "observado" empieza con la flota ya en circulación, como pasaría con datos reales                                                                                   |
| Al empezar todas las cubetas están `DISPONIBLE`                                                                                                                                                                                       | Es el punto de partida del generador. En los datos observados esto no se ve (por el recorte)                                                                                     |

### 5.6 Ruido de registro (`noise.py`)
- **2% de eventos perdidos** y **1% de eventos duplicados** (con un retraso de 1 a 60 s). Del documento de generación.
- Se aplica solo a `observado`. `verdad` queda limpio.

**Por qué:** sin ruido el modelo no tendría que reconstruir nada. Con datos reales siempre hay lecturas perdidas y repetidas.

### 5.7 Exportación (`export.py`, `generate_history.py`)
Formato parquet (rápido, conserva tipos). Cada carpeta lleva `metadatos.json`. `verdad` incluye además `demanda.parquet` y `parametros_usados.yaml`, para poder reproducir.

---

## 6. Modelo

### 6.1 Reconstrucción de estados (`reconstruction.py`)
Siete estados más `sin_informacion`, deducidos del último evento de cada cubeta.

- **Eliminación de duplicados con ventana de 60 s**: dos eventos iguales (misma cubeta, tipo y pedido) en menos de 60 s cuentan como una lectura. Es un supuesto a revisar con datos reales.
- Una cubeta sin eventos se cuenta como `sin_informacion`, no como disponible.
- Los siete estados deben mapearse más adelante a los cuatro estados de "caja negra" del planteamiento (disponibles, en recuperación, en otra zona, no localizadas). **Pendiente.**

### 6.2 Estimación (`estimation.py`)
El modelo estima **solo desde los datos observados**: duraciones de cada fase, probabilidad de lavado, tasa de pérdida, de consolidación, fusiones y el flujo de pedidos.

- **Emparejado de eventos**: las duraciones se miden emparejando por (cubeta, pedido) cuando hay pedido, y por eventos consecutivos cuando no.
- **Recorte por censura (7 días)**: los últimos días del histórico se descartan al medir duraciones, porque los ciclos largos aún no han terminado y saldrían artificialmente cortos.
- **Reaparición de no localizadas (30 días)**: una cubeta que lleva más de 30 días sin eventos se da por perdida.
- **Flujo de salidas con los últimos 35 días**: ver sección 6.4, es la decisión que más peso tuvo.

Cuánto recupera lo que usó el generador (esa es la comprobación de que no hay circularidad): la pérdida por ciclo sale en 0,0005 a 0,0006 (real 0,0005), la fracción que reaparece en 0,46 a 0,52 (real 0,5), el lavado en 0,40 (real 0,40) y el tiempo en farmacia con mediana de 20,4 h (real 20).

### 6.3 Balance (`balance.py`)

> D(t+1) = D(t) + R(t) − S(t)

- D es el stock disponible. **Puede ser negativo.**
- S es lo que piden los pedidos de esa hora.
- R es lo que vuelve a quedar disponible: las cubetas que ya estaban en circulación al empezar (según su fase) y las que salen durante el horizonte y alcanzan a volver.
- **No se resta P(t) (pérdidas) a mano**: una cubeta perdida simplemente no vuelve. Es equivalente y evita contarla dos veces. El planteamiento original llevaba un término P.

Más decisiones:
- **Cada duración se remuestrea de las observadas**, sin suponer una distribución. Si lo real no es lognormal, el modelo no lo asume.
- **Se remuestrean días enteros del histórico con el mismo día de la semana.** Conserva la forma del día y hace que los días malos aparezcan con su frecuencia real.
- **Para una cubeta que ya lleva tiempo en una fase**, lo que le falta se elige entre las muestras más largas que lo que lleva. Es lo correcto estadísticamente (condicionar a que ya duró).
- **Las fases se tratan como independientes entre sí.** Simplificación conocida (ver sección 10).

### 6.4 Por qué solo los últimos 35 días
El primer backtest tuvo cobertura del 57% y un sesgo que crecía con el horizonte. La causa era la estacionalidad: remuestrear todo el histórico mezclaba meses distintos. Al usar solo los últimos 35 días, la cobertura subió y el error se redujo a la mitad. Es el parámetro `dias_recientes_salidas`. Con menos días la banda se queda demasiado corta.

### 6.5 Monte Carlo (`montecarlo.py`)
- 1.000 trayectorias por defecto, horizonte de 48 h, banda p10 a p90.
- **Cada trayectoria tiene su propio generador** derivado de la misma semilla (`SeedSequence.spawn`). Así, al comparar dos escenarios, las trayectorias están pareadas: la diferencia viene de la decisión y no de la suerte.
- Se puede reutilizar el estado inicial (`snapshot`) cuando se proyectan varios escenarios desde el mismo punto.

### 6.6 Métricas (`metrics.py`)
Probabilidad de bajar del umbral, probabilidad de quiebre (stock negativo), mínimo de cada trayectoria (p10, mediana, p90), hora del primer cruce y horas por debajo del umbral.

**Umbral de 1.500** (supuesto): viene del planteamiento del reto, por confirmar con COFAS.

---

## 7. Escenarios y palancas (`scenarios.py`)

Un escenario es un diccionario de palancas. Las que no se nombran quedan neutras. Se definen en `config/escenarios.yaml`.

| Palanca                        | Qué hace                                             | Cómo se aplica                                                    |
| ------------------------------ | ---------------------------------------------------- | ----------------------------------------------------------------- |
| `outflow_scale`                | Multiplica los pedidos                               | Primera operación                                                 |
| `alternative_fraction`         | Parte servida con otro contenedor                    | Tras escalar                                                      |
| `max_outflow_per_hour`         | Tope por hora                                        | Lo que sobra pasa a la hora siguiente, no se pierde               |
| `stay_scale`                   | Multiplica el tiempo en farmacia                     | Cambia las duraciones remuestreadas                               |
| `wave_fraction`, `wave_window` | Concentra parte de los pedidos del día en una franja | `(1-f)*día + f*total*uniforme(franja)`: conserva el total del día |
| `retained_cubetas`             | Cubetas que no vuelven                               | Se restan del stock inicial y no vuelven durante la proyección    |

**Por qué palancas y no efectos fijos:** no hay datos de COFAS sobre cuánto consigue cada medida. Son números que se pueden mover y comparar. Lo que defiende el modelo es la comparación entre decisiones y el orden de magnitud, no la cifra exacta.

**Decisiones de diseño:**
- Las palancas se validan: nombres desconocidos y valores fuera de rango lanzan error.
- Se aplican a **todo el horizonte** (48 h). Es una limitación: un "día de estrés" son realmente dos días de estrés.
- El tope por hora empeora el riesgo en algunos casos (visto en los datos). Tiene lógica: retrasa las salidas, y por tanto las vueltas, sin crear cubetas.

---

## 8. Validación

### 8.1 Coherencia (`conservation.py`)
Tres comprobaciones: la flota es constante, no hay transiciones imposibles entre eventos de una misma cubeta, y el balance coincide con el recuento directo.

- En `verdad` **todo da exactamente 0**. Si deja de dar 0, algo se rompió en el generador.
- En `observado` salen en torno a un 2% de transiciones imposibles, que es justo el 2% de eventos perdidos.
- **El balance se mide desde que se conoce el 99% de la flota.** Antes se medía desde el principio y daba una desviación de unas 7.000 cubetas. No era el ruido, era el stock inicial desconocido (al recortar el calentamiento no se sabe dónde está cada cubeta). Redefinirlo así mide lo que queremos medir.

### 8.2 Backtest (`backtest.py`)
Se estima con el 60% inicial del histórico, se eligen orígenes al azar en el resto (20), y se proyecta desde cada uno usando solo datos anteriores. Se compara con el stock real (verdad) y con una predicción ingenua ("el stock no cambia").

Resultados (los datos de cada persona difieren: 650 farmacias en el proyecto de Windows, 600 en el entorno de pruebas):

|                     | Cobertura p10 a p90 | Sesgo | Error del modelo | Error ingenuo |
| ------------------- | ------------------- | ----- | ---------------- | ------------- |
| Entorno de pruebas  | 74%                 | -203  | 344              | 2.057         |
| Proyecto de Windows | 57%                 | -51   | 299              | 1.813         |

- El modelo se equivoca entre seis y siete veces menos que "el stock no cambia".
- **La banda se queda estrecha** (el ideal es el 80%). Falta incluir la incertidumbre de los parámetros estimados.
- Hay un pequeño sesgo negativo: cuando se pierde un evento DISPONIBLE, la cubeta no cuenta como disponible. Está sin corregir.

### 8.3 Comparación con el reto (`anchors.py`)
Seis puntos leídos a ojo del gráfico del reto (hora, cubetas): 6h a 8.000, 8h a 6.400, 11h a 7.400, 13h a 800, 20h a −1.200, 22h a 100. Tolerancia de 500 cubetas.

**Qué se hizo:** una búsqueda en rejilla de combinaciones de palancas, ordenadas por error frente al reto.

**Resultado:** sin palancas el error es de unas 6.000 cubetas. La mejor combinación encontrada (2.000 cubetas retenidas, ola del 50% en 11h a 13h, 1,7 veces el volumen, estancias ×1,5) lo baja a unas 840. Acierta tres de los seis puntos (6h, 13h, 22h) y falla la forma de la mañana (la bajada y recuperación entre 6h y 11h) y el −1.200 de las 20h.

**Cómo leerlo:**
- El volumen llegó al borde de la rejilla, así que probablemente el reto pida aún más.
- Retenidas y estancia larga son intercambiables con seis puntos leídos a ojo.
- Los puntos están leídos a ojo y no prueban que el modelo sea correcto. Solo indican si es capaz de dar una curva parecida y qué palancas hacen falta.
- El gráfico se titula "Capacidad reducida por retenciones". Nuestra lectura es que es un **día de estrés, sin confirmar con COFAS**.

---

## 9. Calibración: lo que no cuadra todavía

### 9.1 Volumen
El reto implicaría más de 9.200 cubetas en el día del gráfico, con una caída de 6.600 en dos horas (11h a 13h). Un día normal del generador son entre 5.400 y 7.400 cubetas, con un pico de unas 900 por hora. **No puede ser un día normal.**

### 9.2 Operación normal sin riesgo
En operación normal el stock del generador nunca se acerca al umbral (media de unas 10.400, mínimo de unas 3.700). Por eso la probabilidad de bajar del umbral es 0 en las proyecciones base y hacen falta escenarios de estrés.

### 9.3 Perfil horario
El perfil provisional (picos a las 8, 11 y 15) no reproduce la concentración del reto, donde cerca del 72% de la caída neta del día ocurre entre las 11h y las 13h. Pendiente de calibrar con datos reales.

---

## 10. Simplificaciones conocidas del modelo

1. Las fases del ciclo son independientes entre sí.
2. Los pedidos que esperan por falta de cubetas no retrasan las salidas en la proyección (en la realidad esperarían).
3. Las no localizadas no reaparecen dentro del horizonte.
4. La recogida en farmacia es continua, no depende de la ruta de la furgoneta (ver sección 12).
5. La vuelta dura como la ida.
6. Las palancas se aplican a todo el horizonte.
7. El modelo se estima con todo el histórico, incluso al proyectar desde un día del pasado (en el dashboard se avisa).
8. Una cubeta con evento DISPONIBLE perdido no cuenta como disponible.

---

## 11. Problemas encontrados y cómo se resolvieron

| Problema                                                        | Causa                                                                    | Solución                                                                               |
| --------------------------------------------------------------- | ------------------------------------------------------------------------ | -------------------------------------------------------------------------------------- |
| 188.396 transiciones imposibles en los datos limpios            | Empates e inversiones al redondear a segundos cuando los pedidos esperan | `EPS_H` de 1 a 2 segundos y el inicio de la asignación pasa a `max(t, último + EPS_H)` |
| Cobertura del 57% y sesgo creciente en el primer backtest       | Estacionalidad al remuestrear todo el histórico                          | Remuestrear solo los últimos 35 días                                                   |
| Desviación del balance de 7.000 cubetas en los datos observados | Stock inicial desconocido, no el ruido                                   | Medir desde que se conoce el 99% de la flota                                           |
| Los escenarios no cambiaban nada en los tests                   | El origen caía en domingo, sin pedidos                                   | Los tests parten de un martes a las 5h. Pasa igual en el dashboard                     |
| Avisos de pandas por `.weekday`                                 | Deprecado en pandas 4                                                    | Cambiar a `.dayofweek` (no tocar `Timestamp.weekday()`)                                |
| Generador inicial con eventos del calentamiento sin registrar   | Se filtraba antes de simular                                             | Registrar todo y filtrar por fecha                                                     |
| `streamlit` no encuentra `app.py`                               | Ruta distinta de la indicada                                             | Lanzar con la ruta real (`src/cofas_twin/dashboard/app.py`)                            |
| La terminal queda bloqueada                                     | Streamlit corre en primer plano                                          | `Ctrl+C` o abrir otra terminal                                                         |
| `ConnectionResetError` al cerrar el navegador                   | Aviso de Windows al cortar la conexión                                   | Ignorarlo, es cosmético                                                                |

---

## 12. Alternativas descartadas

### 12.1 Primera versión del generador
Se había generado una primera versión con las seis tablas sin haber leído los documentos ni validado fuentes. **Se descartó entera** y se empezó de cero, de forma ordenada y modular.

### 12.2 Datasets públicos
Se descartaron los de Mendeley y Kaggle (sin descargar ni validar, y sin la estructura de eventos por cubeta). Siguen siendo candidatos para calibrar el perfil horario y la forma de la demanda si se validan.

### 12.3 Recogida en farmacia por ruta de furgoneta
**Se probó y se revirtió.**

Qué se hizo: que la cubeta vacía espere al siguiente paso de la furgoneta de su ruta (hora de salida más una parada fija por farmacia, entre 0 y 3 horas), en lugar de recogerse en cualquier momento. Es más realista.

Qué pasó:
- El generador funcionó: las entradas al almacén pasaron a concentrarse entre las 10h y las 17h, y la verdad siguió coherente (0 transiciones imposibles).
- La estancia total en farmacia pasó de una mediana de 20 h a unas 37 h, el stock medio bajó de unas 10.400 a unas 8.100 y por primera vez el generador rozó el umbral en operación normal.
- **El modelo empeoró mucho**: la cobertura cayó de 74% a 41% y el error medio subió de 344 a 775 cubetas, porque el modelo remuestrea cada fase por separado y no sabe que la recogida depende de la hora del día.
- Tampoco ayudó con el reto: con rutas que salen entre las 9h y las 12h, el stock sube por la tarde, no entre las 8h y las 11h como en el gráfico.

Decisión del equipo: **no aplicarlo**. Queda como mejora futura, y exigiría que el modelo aprenda la hora del día de las devoluciones. La hora de salida de las furgonetas es una pregunta para COFAS.

### 12.4 Recortar el stock a 0
Descartado desde el principio: el quiebre tiene que verse como valores negativos, es lo que pide el reto.

### 12.5 Que el modelo lea los parámetros del generador
Descartado por circularidad (sección 3.4).

---

## 13. Interfaz y herramientas

### 13.1 `run_twin.py`
Ejecuta todo de principio a fin y compara los escenarios del YAML. Admite `--fuente`, `--origen` y `--escenarios`. Sirve igual con datos sintéticos que con los de COFAS: solo cambia el adaptador.

### 13.2 Dashboard (`dashboard/app.py`)
Hecho con **Streamlit** y Altair (se instala con `pip install streamlit`, Altair viene incluido).

- **Por qué Streamlit**: es solo Python, cabe en un fichero y los controles (sliders, selectores) se