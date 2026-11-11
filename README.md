# Uniovi_IS
An repository for working in the solution for COFAS

# Gemelo digital de procesos COFAS: trazabilidad de cubetas

Gemelo digital de un almacén inteligente para el caso de uso de trazabilidad de cubetas (reto COFAS, Uniovi Innovation Skills). Proyecta hora a hora cuántas cubetas habrá disponibles, simula decisiones (regular el flujo de pedidos, acelerar el vaciado y la devolución, usar un contenedor alternativo) y estima la probabilidad de caer por debajo del umbral de alerta.

Todo funciona hoy con datos sintéticos. Cuando lleguen los datos reales de COFAS, solo hay que rellenar un adaptador: el modelo no cambia.

## Qué hace

- Genera un histórico sintético de seis meses (cubetas, farmacias, rutas, pedidos y eventos de cada cubeta), con ruido de registro realista (eventos perdidos y duplicados).
- Reconstruye el estado de cada cubeta (siete estados más "sin información") a partir de los eventos.
- Estima desde los datos observados, sin leer los parámetros del generador, las duraciones de cada fase, las tasas de pérdida, lavado y consolidación y el flujo de pedidos.
- Proyecta el stock disponible con un balance `D(t+1) = D(t) + R(t) - S(t)` y Monte Carlo (banda p10 a p90).
- El stock puede ser negativo: por debajo de 0 hay quiebre (pedidos que no se pueden servir) y no se recorta.
- Compara escenarios con las mismas trayectorias aleatorias, para que la diferencia venga de la decisión y no de la suerte.
- Valida el modelo (coherencia, backtest y comparación con el gráfico del reto).
- Muestra todo en un dashboard.

## Instalación

Requiere Python 3.11 o superior.

```
python -m venv .venv
.venv\Scripts\activate
pip install pandas numpy scipy pyyaml pyarrow streamlit pytest
pip install -e .
```

El último comando instala el paquete `cofas_twin` en modo editable (hace falta que exista el `pyproject.toml` del proyecto).

## Cómo se usa

Desde la raíz del proyecto y con el venv activo.

**1. Generar el histórico sintético** (unos 25 segundos). Crea `data/synthetic/observado` (con ruido) y `data/synthetic/verdad` (limpio, solo para validar):

```
python -m cofas_twin.generation.generate_history
```

**2. Proyectar y comparar escenarios:**

```
python -m cofas_twin.run_twin
python -m cofas_twin.run_twin --origen "2026-06-23 05:00" --escenarios base dia_estres
python -m cofas_twin.run_twin --fuente cofas
```

**3. Dashboard:**

```
streamlit run src/cofas_twin/dashboard/app.py
```

Se abre en `http://localhost:8501`. Hay que lanzarlo siempre con `streamlit run`, no con el botón de ejecutar de VS Code. Para cerrarlo, `Ctrl+C` en la terminal.

**4. Tests** (unos 10 segundos):

```
pytest tests -q
```

**5. Validación.** Coherencia de los datos (con la verdad tiene que dar todo 0):

```
python -c "from cofas_twin.data.synthetic_adapter import load_tables; from cofas_twin.validation.truth import load_truth; from cofas_twin.validation.conservation import run_conservation; t=load_tables(); print(run_conservation(load_truth()['eventos_cubeta'], t['cubetas']['cubeta_id']))"
```

Backtest (proyectar desde el pasado y comparar con lo que pasó):

```
python -c "import pandas as pd; from cofas_twin.config import load_model_parameters, load_validation_parameters; from cofas_twin.data.synthetic_adapter import load_tables; from cofas_twin.validation.truth import load_truth; from cofas_twin.validation.backtest import run_backtest; r=run_backtest(load_tables(), load_truth()['eventos_cubeta'], load_model_parameters(), load_validation_parameters()); pd.set_option('display.width',200); print(r['resumen'].round(2))"
```

## Estructura

```
config/
  parametros.yaml     parámetros del generador de datos sintéticos
  modelo.yaml         parámetros del modelo (separado a propósito, ver abajo)
  escenarios.yaml     escenarios que se comparan (palancas de decisión)
  validacion.yaml     anclajes del reto y ajustes del backtest
src/cofas_twin/
  config.py           lectura y validación de los YAML
  scheme.py           esquema de las seis tablas (contrato entre generador, adaptadores y modelo)
  generation/         generador sintético: maestros, demanda, pedidos, ciclo, ruido, exportación
  data/               adaptadores: synthetic_adapter.py y cofas_adapter.py (esqueleto)
  model/              reconstrucción de estados, estimación, balance, Monte Carlo, escenarios, métricas
  validation/         coherencia, backtest y comparación con los anclajes del reto
  dashboard/app.py    dashboard
  run_twin.py         ejecución de principio a fin
tests/                pruebas automáticas
```

## Cómo está pensado

**El modelo no puede ver cómo se generaron los datos.** Por eso hay dos YAML separados. El modelo lee los datos solo a través de un adaptador y estima todo desde ellos. Si leyera `parametros.yaml` estaría estimando lo mismo que se usó para generar los datos, y la validación no valdría nada. La carpeta `verdad` solo la lee la validación.

**Cambiar de datos sintéticos a reales es cambiar de adaptador.** `cofas_adapter.py` tiene tres diccionarios vacíos que rellenar (`FILES`, `COLUMN_MAP`, `EVENT_MAP`). Si COFAS no tiene alguna de las seis tablas, hay que decidir cómo construirla y avisar al equipo. No se inventa nada.

**Cada parámetro declara su estado.** En los YAML, cada valor lleva `estado` y `fuente`:

| Estado           | Significa                             |
| ---------------- | ------------------------------------- |
| `dato`           | viene de COFAS o de una fuente fiable |
| `dato_derivado`  | calculado a partir de un dato         |
| `dato_con_rango` | solo se conoce un rango               |
| `supuesto`       | lo hemos elegido nosotros, sin base   |
| `desconocido`    | no se sabe, hay un valor provisional  |

La pestaña "Dato o supuesto" del dashboard lo muestra. Todo lo que no sea `dato` se sustituye cuando lleguen los valores reales de COFAS.

**Nombres.** Los identificadores del código van en inglés. Los comentarios, mensajes de error y los datos (claves de YAML, tablas, columnas, tipos de evento) van en español.

## Escenarios

Un escenario es un conjunto de palancas (ver `model/scenarios.py`). Las que no se nombran quedan neutras.

| Palanca                        | Qué hace                                                                                     |
| ------------------------------ | -------------------------------------------------------------------------------------------- |
| `outflow_scale`                | Multiplica los pedidos. Más de 1 es un pico                                                  |
| `stay_scale`                   | Multiplica el tiempo en farmacia. Más de 1 son retenciones, menos de 1 acelera la devolución |
| `max_outflow_per_hour`         | Tope de cubetas servidas por hora. Lo que sobra pasa a la hora siguiente                     |
| `alternative_fraction`         | Parte de los pedidos servida con otro contenedor                                             |
| `wave_fraction`, `wave_window` | Parte de los pedidos del día concentrada en una franja horaria                               |
| `retained_cubetas`             | Cubetas retenidas: se restan del stock inicial y no vuelven durante la proyección            |

Se editan en `config/escenarios.yaml` sin tocar código. También se pueden probar en el dashboard con el "escenario propio".

## Qué hay que tener en cuenta

- **El efecto de cada decisión es un supuesto.** No hay datos de COFAS sobre cuánto consigue cada medida. Lo que defiende el modelo es la comparación entre decisiones y el orden de magnitud, no la cifra exacta.
- **Los anclajes del reto están leídos a ojo** de un gráfico, y se sospecha que corresponde a un día de estrés (por confirmar con COFAS). Con las palancas el modelo reproduce solo parte de la curva.
- **La banda es algo estrecha.** En el backtest la banda p10 a p90 cubre entre el 57% y el 74% de las veces, y debería cubrir el 80%. Todavía no se incluye la incertidumbre de los parámetros estimados.
- **Las palancas se aplican a todo el horizonte** (48 horas). Un "día de estrés" son, hoy, dos días de estrés.
- **Los domingos no hay pedidos en el generador.** Si el origen de la proyección cae en domingo, las palancas de demanda no se notan ese día.
- **Las fases del ciclo se tratan como independientes**, y los pedidos que esperan por falta de cubetas no retrasan las salidas en la proyección.
- **La recogida en farmacia es continua en el generador** (no depende de la ruta de la furgoneta). Se probó hacerla por ruta y el modelo, tal como está, no la aprende: es una mejora pendiente.
- **Con las cubetas no localizadas** el modelo no las hace reaparecer dentro del horizonte.

## Pendiente de COFAS

Hay que confirmar con ellos, y en cuanto lleguen se cambian en los YAML:

- Si el gráfico del reto corresponde a un día de estrés o a un día normal.
- El perfil horario real de salidas, en un día normal y en uno de pico.
- Pedidos por día y cubetas por pedido.
- Unidades por cubeta, precio de la cubeta y cuántas cubetas hay (el 17.500 es un rango dado por un compañero).
- Número y horarios de las furgonetas.
- Si el lavado y la cámara registran el ID de la cubeta.
- Si una farmacia equivale a un socio.