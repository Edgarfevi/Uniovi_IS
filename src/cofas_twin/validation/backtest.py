"""Backtest: proyectar desde el pasado y comparar con lo que de verdad paso.

Se estima solo con la parte inicial del historico. Despues se eligen instantes de
partida en el resto, se proyecta desde cada uno usando unicamente los datos
hasta ese instante, y se compara con el stock real (la verdad del generador).

Mide tres cosas:
- cobertura: que fraccion de las veces lo real cae dentro de la banda p10 a p90
  (ideal: el 80%),
- sesgo: si la mediana se queda corta o larga de media,
- error: cuanto se equivoca, frente a una prediccion ingenua (que el stock no cambie).
"""

import copy

import numpy as np
import pandas as pd

from cofas_twin.config import value
from cofas_twin.model.estimation import estimate_all
from cofas_twin.model.montecarlo import project
from cofas_twin.model.reconstruction import remove_duplicates, state_counts


def run_backtest(tables, truth_events, model_params, validation_params):
    """Devuelve {"detalle": una fila por origen y hora, "resumen": tabla por tramo de horizonte}."""
    cfg = lambda key: value(validation_params, "backtest", key)
    events = remove_duplicates(
        tables["eventos_cubeta"],
        value(model_params, "limpieza", "ventana_duplicados_s"),
    )
    bucket_ids = tables["cubetas"]["cubeta_id"]
    horizon = value(model_params, "proyeccion", "horizonte_h")

    start = events["timestamp"].min().floor("h")
    end = events["timestamp"].max().floor("h")
    fit_end = (start + (end - start) * cfg("fraccion_ajuste")).floor("D")

    fit_tables = {
        **tables,
        "eventos_cubeta": tables["eventos_cubeta"][
            tables["eventos_cubeta"]["timestamp"] <= fit_end
        ],
        "pedidos": tables["pedidos"][tables["pedidos"]["fecha_hora"] <= fit_end],
    }
    estimates = estimate_all(fit_tables, model_params)

    params = copy.deepcopy(model_params)
    params["proyeccion"]["n_simulaciones"]["valor"] = cfg("n_simulaciones")

    first = fit_end + pd.Timedelta(days=1)
    last = end - pd.Timedelta(hours=horizon)
    n_hours = int((last - first) / pd.Timedelta(hours=1))
    rng = np.random.default_rng(cfg("semilla"))
    origins = first + pd.to_timedelta(
        rng.integers(0, n_hours + 1, cfg("n_origenes")), unit="h"
    )

    real = state_counts(truth_events, bucket_ids, start=start, end=end)["disponible"]

    rows = []
    for origin in origins:
        result = project(events, bucket_ids, estimates, params, origin=origin)
        summary = result["resumen"]
        rows.append(
            pd.DataFrame(
                {
                    "origen": origin,
                    "h": np.arange(1, horizon + 1),
                    "real": real.reindex(summary.index).to_numpy(),
                    "mediana": summary["mediana"].to_numpy(),
                    "p10": summary["p10"].to_numpy(),
                    "p90": summary["p90"].to_numpy(),
                    "ingenuo": result["stock_inicial"],
                }
            )
        )
    detail = pd.concat(rows, ignore_index=True)
    return {
        "detalle": detail,
        "resumen": _summarize(detail, horizon),
        "fin_ajuste": fit_end,
    }


def _summarize(detail, horizon):
    detail = detail.copy()
    detail["dentro"] = (detail["real"] >= detail["p10"]) & (
        detail["real"] <= detail["p90"]
    )
    detail["error"] = detail["mediana"] - detail["real"]
    detail["error_ingenuo"] = detail["ingenuo"] - detail["real"]
    detail["ancho"] = detail["p90"] - detail["p10"]
    edges = sorted({0, 6, 12, 24, horizon})
    detail["tramo"] = pd.cut(detail["h"], edges).astype(str)
    grouped = detail.groupby("tramo", sort=False)
    table = pd.DataFrame(
        {
            "cobertura": grouped["dentro"].mean(),
            "sesgo": grouped["error"].mean(),
            "error_modelo": grouped["error"].apply(lambda x: x.abs().mean()),
            "error_ingenuo": grouped["error_ingenuo"].apply(lambda x: x.abs().mean()),
            "ancho_banda": grouped["ancho"].mean(),
        }
    )
    table.loc["todo"] = [
        detail["dentro"].mean(),
        detail["error"].mean(),
        detail["error"].abs().mean(),
        detail["error_ingenuo"].abs().mean(),
        detail["ancho"].mean(),
    ]
    return table
