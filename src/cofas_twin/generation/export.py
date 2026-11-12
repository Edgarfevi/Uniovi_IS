"""Recorte de la ventana de historico y guardado de las tablas.

Dos salidas distintas:

- observado: lo que veria el modelo. Con ruido de registro y sin el periodo
  de calentamiento.
- verdad: lo que de verdad paso. Sin ruido, con calentamiento, y con una copia
  de los parametros usados. Solo la lee la validacion, nunca el modelo.
"""

import json
from pathlib import Path

import pandas as pd
import yaml

from cofas_twin.config import value
from cofas_twin.scheme import SCHEMA

# Raiz del proyecto / data / synthetic (este fichero esta en src/cofas_twin/generation/)
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[3] / "data" / "synthetic"

# Nombres de carpeta: son datos, se quedan en espanol
OBSERVED_FOLDER = "observado"
TRUTH_FOLDER = "verdad"


def cut_to_history(params, tables):
    """Quita el calentamiento: se queda con lo que ocurre desde `fecha_inicio`.

    - eventos_cubeta: solo los eventos desde `fecha_inicio`, con ids renumerados.
    - pedidos: los de la ventana, mas los anteriores que todavia tienen eventos
      dentro de ella (para que ningun evento apunte a un pedido que no existe).
    - pedido_cubeta: las filas de los pedidos que se quedan.
    Las demas tablas no dependen del tiempo y pasan tal cual.
    """
    start = pd.Timestamp(value(params, "general", "fecha_inicio"))

    events = tables["eventos_cubeta"]
    events = events[events["timestamp"] >= start].reset_index(drop=True)
    events["evento_id"] = pd.RangeIndex(1, len(events) + 1).to_numpy(dtype="int64")

    orders = tables["pedidos"]
    referenced = events["pedido_id"].dropna().unique()
    orders = orders[
        (orders["fecha_hora"] >= start) | orders["pedido_id"].isin(referenced)
    ]
    orders = orders.reset_index(drop=True)

    link = tables["pedido_cubeta"]
    link = link[link["pedido_id"].isin(orders["pedido_id"])].reset_index(drop=True)

    return {
        **tables,
        "eventos_cubeta": events,
        "pedidos": orders,
        "pedido_cubeta": link,
    }


def save_tables(tables, folder):
    """Guarda cada tabla como parquet en `folder` (se crea si no existe)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_parquet(folder / f"{name}.parquet", index=False)


def save_truth(params, tables, demand, folder):
    """Guarda la verdad: tablas limpias, demanda diaria y los parametros usados."""
    save_tables({**tables, "demanda": demand}, folder)
    with open(Path(folder) / "parametros_usados.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(params, f, allow_unicode=True, sort_keys=False)


def write_metadata(params, tables, folder):
    """Un resumen pequeno para saber de que ejecucion es cada carpeta."""
    summary = {
        "semilla": value(params, "general", "semilla"),
        "fecha_inicio": str(value(params, "general", "fecha_inicio")),
        "dias_historico": value(params, "general", "dias_historico"),
        "dias_calentamiento": value(params, "general", "dias_calentamiento"),
        "filas": {name: int(len(tables[name])) for name in SCHEMA if name in tables},
    }
    with open(Path(folder) / "metadatos.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
