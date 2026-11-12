"""Monte Carlo sobre el balance de stock: muchas trayectorias, una banda.

Cada trayectoria tiene su propio generador aleatorio, derivado de la misma
semilla. Asi, al comparar dos escenarios, las trayectorias son pareadas: la
diferencia viene de la decision y no de la suerte.
"""

import numpy as np
import pandas as pd

from cofas_twin.config import value
from cofas_twin.model.balance import prepare_samples, run_once, snapshot
from cofas_twin.model.metrics import scenario_metrics
from cofas_twin.model.scenarios import complete, scale_samples


def project(
    tables_events,
    bucket_ids,
    estimates,
    model_params,
    origin=None,
    scenario=None,
    current=None,
):
    """Proyecta el stock de cubetas disponibles desde `origin`.

    tables_events: eventos observados y limpios (sin duplicados).
    estimates: salida de estimation.estimate_all.
    origin: por defecto, el ultimo instante en punto del historico.
    scenario: diccionario de palancas (ver scenarios.py). None = escenario base.
    current: snapshot ya calculado para ese origen (si se proyectan muchos escenarios
    desde el mismo instante, se calcula una vez y se reutiliza).
    Devuelve un diccionario con el origen, las trayectorias, el resumen por hora y las metricas.
    """
    n_sim = value(model_params, "proyeccion", "n_simulaciones")
    horizon = value(model_params, "proyeccion", "horizonte_h")
    seeds = np.random.SeedSequence(value(model_params, "proyeccion", "semilla")).spawn(
        n_sim + 1
    )
    scenario = complete(scenario)

    if origin is None:
        origin = tables_events["timestamp"].max().floor("h")
    origin = pd.Timestamp(origin)

    if current is None:
        current = snapshot(tables_events, bucket_ids, origin)
    samples = scale_samples(
        prepare_samples(estimates, np.random.default_rng(seeds[0])), scenario
    )
    loss = estimates["tasas"]["perdida_por_ciclo"]
    days = estimates["salidas_dias"]

    paths = np.empty((n_sim, horizon))
    for i in range(n_sim):
        rng = np.random.default_rng(seeds[i + 1])
        paths[i] = run_once(
            rng, current, samples, loss, days, origin, horizon, scenario
        )[0]

    return {
        "origen": origin,
        "escenario": scenario,
        "stock_inicial": int((current["state"] == "disponible").sum()),
        "trayectorias": paths,
        "resumen": summarize(paths, origin, model_params),
        "metricas": scenario_metrics(paths, origin, model_params),
    }


def summarize(paths, origin, model_params):
    """Media, mediana, banda y probabilidad de estar por debajo del umbral, hora a hora."""
    low, high = value(model_params, "proyeccion", "percentiles")
    threshold = value(model_params, "alerta", "umbral_cubetas")
    index = pd.Index(
        origin + pd.to_timedelta(np.arange(1, paths.shape[1] + 1), unit="h"),
        name="hasta",
    )
    return pd.DataFrame(
        {
            "media": paths.mean(axis=0),
            f"p{low}": np.percentile(paths, low, axis=0),
            "mediana": np.median(paths, axis=0),
            f"p{high}": np.percentile(paths, high, axis=0),
            "prob_bajo_umbral": (paths < threshold).mean(axis=0),
        },
        index=index,
    )
