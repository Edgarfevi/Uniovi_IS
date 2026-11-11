"""Adaptador de datos reales de COFAS.

Misma funcion que el sintetico (load_tables) y mismo resultado: las seis tablas
del esquema, validadas. El modelo no sabe de donde vienen.

Esto es un esqueleto. Cuando lleguen los datos reales hay que rellenar tres cosas
y no tocar nada mas:
  1. FILES: en que fichero esta cada tabla (se admite .csv o .parquet).
  2. COLUMN_MAP: como se llama cada columna de COFAS en nuestro esquema.
  3. EVENT_MAP: como se llama cada tipo de evento de COFAS en nuestro esquema.
Si COFAS ya usara nuestros nombres, los tres pueden quedarse vacios.

Todo lo que COFAS no tenga (por ejemplo la tabla `rutas`) hay que decidirlo aqui:
construirlo a partir de otra cosa o avisar al equipo. Aqui no se inventa nada.
"""

from pathlib import Path

import pandas as pd

from cofas_twin.scheme import SCHEMA, empty_table, validate_all

# Raiz del proyecto / data / cofas
DEFAULT_FOLDER = Path(__file__).resolve().parents[3] / "data" / "cofas"

# {tabla_nuestra: nombre del fichero sin extension}. Por defecto, el mismo nombre.
FILES = {}

# {tabla_nuestra: {columna_de_cofas: columna_nuestra}}
COLUMN_MAP = {}

# {tipo_de_evento_de_cofas: tipo_nuestro}
EVENT_MAP = {}


def load_tables(folder=None, files=None, column_map=None, event_map=None):
    """Devuelve {nombre_tabla: DataFrame} con las seis tablas, validadas.

    Los tres diccionarios se pueden pasar a mano (para probar). Si no, se usan los
    de este modulo.
    """
    folder = Path(folder) if folder else DEFAULT_FOLDER
    files = FILES if files is None else files
    column_map = COLUMN_MAP if column_map is None else column_map
    event_map = EVENT_MAP if event_map is None else event_map

    if not folder.exists():
        raise FileNotFoundError(
            f"No existe {folder}. Deja ahi los ficheros de COFAS (uno por tabla, .csv o .parquet) "
            "y rellena FILES, COLUMN_MAP y EVENT_MAP en data/cofas_adapter.py"
        )

    tables = {}
    for name in SCHEMA:
        raw = _read(folder, files.get(name, name))
        raw = raw.rename(columns=column_map.get(name, {}))
        if name == "eventos_cubeta" and event_map:
            raw["tipo_evento"] = (
                raw["tipo_evento"].map(event_map).fillna(raw["tipo_evento"])
            )
        tables[name] = _coerce(name, raw)
    validate_all(tables)
    return tables


def _read(folder, stem):
    for suffix, reader in ((".parquet", pd.read_parquet), (".csv", pd.read_csv)):
        path = folder / f"{stem}{suffix}"
        if path.exists():
            return reader(path)
    raise FileNotFoundError(
        f"Falta el fichero de la tabla ({stem}.parquet o {stem}.csv) en {folder}"
    )


def _coerce(name, df):
    """Deja la tabla con las columnas, el orden y los tipos del esquema."""
    missing = [c for c in SCHEMA[name] if c not in df.columns]
    if missing:
        raise ValueError(
            f"Tabla '{name}': faltan las columnas {missing}. Revisa COLUMN_MAP en data/cofas_adapter.py"
        )
    df = df[list(SCHEMA[name])].copy()
    for col, (kind, _) in SCHEMA[name].items():
        if kind == "datetime":
            df[col] = pd.to_datetime(df[col])
    return df.astype(empty_table(name).dtypes.to_dict())
