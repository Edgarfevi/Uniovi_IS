"""Lectura de la verdad del generador (carpeta data/synthetic/verdad).

Solo la usa la validacion. El modelo no la importa nunca.
"""

from pathlib import Path

import pandas as pd

from cofas_twin.scheme import SCHEMA

# Raiz del proyecto / data / synthetic / verdad
DEFAULT_FOLDER = Path(__file__).resolve().parents[3] / "data" / "synthetic" / "verdad"


def load_truth(folder=None):
    """Devuelve {nombre_tabla: DataFrame} con las tablas limpias y completas (con calentamiento)."""
    folder = Path(folder) if folder else DEFAULT_FOLDER
    if not folder.exists():
        raise FileNotFoundError(
            f"No existe {folder}. Genera el historico con: python -m cofas_twin.generation.generate_history"
        )
    return {name: pd.read_parquet(folder / f"{name}.parquet") for name in SCHEMA}
