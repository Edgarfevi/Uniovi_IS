"""Carga y validacion de los parametros del proyecto.

Es el unico modulo que abre los YAML de config/. El resto del codigo pide los
valores a traves de las funciones de aqui.

Hay dos ficheros separados a proposito:
- parametros.yaml: lo que usa el generador de datos sinteticos.
- modelo.yaml: lo que usa el modelo. No puede leer el anterior, porque entonces
  estimaria lo mismo que se uso para generar los datos (circularidad).
"""

from pathlib import Path

import yaml

# Claves del YAML: son datos, por eso se quedan en espanol
SECTIONS = ("general", "maestros", "demanda", "pedidos", "ciclo", "registro")
MODEL_SECTIONS = ("limpieza", "estimacion", "proyeccion", "alerta")
VALIDATION_SECTIONS = ("anclajes_reto", "backtest")
SCENARIO_SECTIONS = ("escenarios",)
STATES = {"dato", "dato_derivado", "dato_con_rango", "supuesto", "desconocido"}

# config.py esta en <raiz>/src/cofas_twin/, asi que la raiz queda 3 niveles arriba
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "parametros.yaml"
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[2] / "config" / "modelo.yaml"
DEFAULT_VALIDATION_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "validacion.yaml"
)
DEFAULT_SCENARIO_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "escenarios.yaml"
)


def load_parameters(path=None, sections=SECTIONS):
    """Lee el YAML, lo valida y devuelve el diccionario de parametros.

    Por defecto lee los parametros del generador. Para los del modelo,
    usa load_model_parameters().
    """
    path = Path(path) if path else DEFAULT_PATH
    if not path.exists():
        raise FileNotFoundError(f"No encuentro el fichero de parametros: {path}")
    with open(path, encoding="utf-8") as f:
        params = yaml.safe_load(f)
    _validate(params, sections)
    return params


def load_model_parameters(path=None):
    """Lee config/modelo.yaml (o el que se indique)."""
    return load_parameters(path or DEFAULT_MODEL_PATH, MODEL_SECTIONS)


def load_validation_parameters(path=None):
    """Lee config/validacion.yaml (o el que se indique)."""
    return load_parameters(path or DEFAULT_VALIDATION_PATH, VALIDATION_SECTIONS)


def load_scenarios(path=None):
    """Lee config/escenarios.yaml. Devuelve {nombre: {descripcion, estado, palancas}}."""
    return load_parameters(path or DEFAULT_SCENARIO_PATH, SCENARIO_SECTIONS)[
        "escenarios"
    ]


def value(params, *keys):
    """Devuelve un parametro a partir de su ruta, por ejemplo:

    value(p, "general", "semilla")                   -> 42
    value(p, "maestros", "n_cubetas")                -> 17500
    value(p, "ciclo", "tiempo_en_farmacia", "sigma") -> 0.68

    Si el parametro tiene la forma valor/estado/fuente, devuelve solo el valor.
    """
    node = params
    for key in keys:
        try:
            node = node[key]
        except (KeyError, TypeError):
            raise KeyError(f"No existe el parametro: {'.'.join(map(str, keys))}")
    if isinstance(node, dict) and "valor" in node:
        return node["valor"]
    return node


def states_summary(params):
    """Lista (parametro, estado, fuente) de todo lo que declara un estado.

    Sirve para ver de un vistazo que es dato y que es supuesto.
    """
    rows = []

    def walk(node, path):
        if "estado" in node:
            rows.append((".".join(path), node["estado"], node.get("fuente", "")))
        for key, child in node.items():
            if isinstance(child, dict):
                walk(child, path + (str(key),))

    walk(params, ())
    return rows


def _validate(params, sections):
    if not isinstance(params, dict):
        raise ValueError("El fichero de parametros esta vacio o mal formado")
    missing = [s for s in sections if s not in params]
    if missing:
        raise ValueError(f"Faltan secciones en el fichero de parametros: {missing}")
    _check_node(params, ())


def _check_node(node, path):
    if isinstance(node, dict):
        if "estado" in node and node["estado"] not in STATES:
            raise ValueError(
                f"Estado no valido en '{'.'.join(path)}': {node['estado']!r}. "
                f"Permitidos: {sorted(STATES)}"
            )
        for key, child in node.items():
            _check_node(child, path + (str(key),))
    elif node is None:
        raise ValueError(f"Parametro sin valor: {'.'.join(path)}")
