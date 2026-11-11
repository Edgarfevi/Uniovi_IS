"""Adaptador de datos sinteticos: lee las seis tablas de data/synthetic/observado.

El modelo solo conoce esta forma de pedir datos: load_tables() devuelve un
diccionario con las seis tablas del esquema, ya validadas. Cuando lleguen los
datos de COFAS se escribira un adaptador con la misma funcion y el modelo no
cambia.

Este modulo no lee la carpeta `verdad` ni importa nada del generador.
"""

from pathlib import Path

import pandas as pd

from cofas_twin.scheme import SCHEMA, validate_all

# Raiz del proyecto / data / synthetic / observado
DEFAULT_FOLDER = (
    Path(__file__).resolve().parents[3] / "data" / "synthetic" / "observado"
)


def load_tables(folder=None):
    """Devuelve {nombre_tabla: DataFrame} con las seis tablas, validadas."""
    folder = Path(folder) if folder else DEFAULT_FOLDER
    if not folder.exists():
        raise FileNotFoundError(
            f"No existe {folder}. Genera el historico con: "
            "python -m cofas_twin.generation.generate_history"
        )
    tables = {}
    for name in SCHEMA:
        path = folder / f"{name}.parquet"
        if not path.exists():
            raise FileNotFoundError(f"Falta la tabla {name} en {folder}")
        tables[name] = pd.read_parquet(path)
    validate_all(tables)
    return tables
