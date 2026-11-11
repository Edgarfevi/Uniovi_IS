"""Metricas de una proyeccion: que tan mal puede ponerse y cuando.

Trabajan sobre la matriz de trayectorias (simulaciones x horas) que devuelve
montecarlo.project.
"""

import numpy as np
import pandas as pd

from cofas_twin.config import value


def scenario_metrics(paths, origin, model_params):
    """Resumen de riesgo de una proyeccion.

    - prob_bajo_umbral: probabilidad de bajar del umbral en algun momento del horizonte.
    - prob_quiebre: probabilidad de que el stock llegue a ser negativo.
    - minimo_p10/p50/p90: el stock minimo de cada trayectoria, resumido.
    - primer_cruce_mediana: hora tipica a la que se baja del umbral
      (solo entre las trayectorias que bajan).
    - horas_bajo_umbral: media de horas que pasa por debajo del umbral.
    """
    threshold = value(model_params, "alerta", "umbral_cubetas")
    below = paths < threshold
    crosses = below.any(axis=1)
    minima = paths.min(axis=1)

    first_cross = None
    if crosses.any():
        first_hour = below[crosses].argmax(
            axis=1
        )  # primera hora (0 = primera del horizonte)
        first_cross = pd.Timestamp(origin) + pd.Timedelta(
            hours=int(np.median(first_hour)) + 1
        )

    return {
        "prob_bajo_umbral": float(crosses.mean()),
        "prob_quiebre": float((minima < 0).mean()),
        "minimo_p10": float(np.percentile(minima, 10)),
        "minimo_p50": float(np.percentile(minima, 50)),
        "minimo_p90": float(np.percentile(minima, 90)),
        "primer_cruce_mediana": first_cross,
        "horas_bajo_umbral": float(below.sum(axis=1).mean()),
    }


def compare(results):
    """Tabla con las metricas de varios escenarios, una fila por escenario.

    results: {nombre: salida de montecarlo.project}.
    """
    return pd.DataFrame({name: r["metricas"] for name, r in results.items()}).T
