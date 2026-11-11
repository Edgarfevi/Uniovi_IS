"""Comparacion con los anclajes del reto: valores de stock leidos del grafico de COFAS.

Los anclajes son pocos puntos leidos a ojo (hora del dia y cubetas disponibles).
Sirven para comprobar si el modelo es capaz de dar una curva parecida, y que
palancas hacen falta para ello. No son datos precisos ni prueban que el modelo
sea correcto.
"""

import itertools

import numpy as np
import pandas as pd

from cofas_twin.config import value
from cofas_twin.model.balance import snapshot
from cofas_twin.model.montecarlo import project


def compare_to_anchors(summary, day, validation_params):
    """Tabla hora a hora: valor del reto frente a la banda del modelo.

    summary: resumen de montecarlo.project. day: el dia (a las 00:00) al que se refieren
    los anclajes. El origen de la proyeccion tiene que ser anterior a la primera hora.
    """
    hours = value(validation_params, "anclajes_reto", "puntos", "horas")
    target = value(validation_params, "anclajes_reto", "puntos", "cubetas")
    tolerance = value(validation_params, "anclajes_reto", "tolerancia_cubetas")
    when = pd.Timestamp(day) + pd.to_timedelta(hours, unit="h")
    rows = summary.loc[when]
    table = pd.DataFrame(
        {
            "hora": hours,
            "reto": target,
            "modelo_p10": rows["p10"].to_numpy(),
            "modelo_mediana": rows["mediana"].to_numpy(),
            "modelo_p90": rows["p90"].to_numpy(),
        }
    )
    table["error"] = table["modelo_mediana"] - table["reto"]
    table["en_banda"] = (table["reto"] >= table["modelo_p10"]) & (
        table["reto"] <= table["modelo_p90"]
    )
    table["en_tolerancia"] = table["error"].abs() <= tolerance
    return table.set_index("hora")


def anchor_error(summary, day, validation_params):
    """Error cuadratico medio (en cubetas) entre la mediana del modelo y los anclajes."""
    table = compare_to_anchors(summary, day, validation_params)
    return float(np.sqrt((table["error"] ** 2).mean()))


def search_levers(
    events,
    bucket_ids,
    estimates,
    model_params,
    validation_params,
    day,
    grid,
    origin_hour=5,
):
    """Prueba todas las combinaciones de palancas de `grid` y ordena por error frente al reto.

    grid: {palanca: [valores]}. La proyeccion empieza a las `origin_hour` del dia indicado,
    de modo que la primera hora proyectada es la de la primera ancla.
    Devuelve un DataFrame con una fila por combinacion: las palancas y el error.
    """
    origin = pd.Timestamp(day) + pd.Timedelta(hours=origin_hour)
    current = snapshot(events, bucket_ids, origin)
    names = list(grid)
    rows = []
    for values in itertools.product(*grid.values()):
        scenario = dict(zip(names, values))
        result = project(
            events,
            bucket_ids,
            estimates,
            model_params,
            origin=origin,
            scenario=scenario,
            current=current,
        )
        rows.append(
            {
                **scenario,
                "error_cubetas": anchor_error(
                    result["resumen"], day, validation_params
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("error_cubetas").reset_index(drop=True)
