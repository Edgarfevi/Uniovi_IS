"""Generacion de las tablas maestras: farmacias, rutas y cubetas.

Recibe los parametros y un generador aleatorio (el que se crea una sola
vez a partir de la semilla), y devuelve las tres tablas con el formato
de scheme.py.
"""

import numpy as np
import pandas as pd

from cofas_twin.config import value
from cofas_twin.scheme import columns


def generate_masters(params, rng):
    """Devuelve {"farmacias": df, "rutas": df, "cubetas": df}."""
    n_buckets = value(params, "maestros", "n_cubetas")
    n_pharmacies = value(params, "maestros", "n_farmacias")
    n_routes = value(params, "maestros", "n_rutas")
    if n_pharmacies < n_routes:
        raise ValueError(
            f"Hay menos farmacias ({n_pharmacies}) que rutas ({n_routes}): alguna ruta quedaria vacia"
        )

    # una zona por ruta, repartidas de forma ciclica
    zone_names = value(params, "maestros", "zonas", "nombres")
    route_ids = np.arange(1, n_routes + 1)
    route_zone = {int(r): zone_names[(int(r) - 1) % len(zone_names)] for r in route_ids}

    pharmacies = _build_pharmacies(params, rng, n_pharmacies, route_ids, route_zone)
    routes = _build_routes(params, rng, route_ids, pharmacies)
    buckets = _build_buckets(params, n_buckets)

    tables = {"farmacias": pharmacies, "rutas": routes, "cubetas": buckets}
    return {name: df[columns(name)] for name, df in tables.items()}


def _build_pharmacies(params, rng, n_pharmacies, route_ids, route_zone):
    proportions = value(params, "maestros", "tamano_farmacia", "proporciones")
    factors = value(params, "maestros", "tamano_farmacia", "factor_demanda")
    sizes = list(proportions)
    weights = np.array([proportions[s] for s in sizes], dtype=float)
    if not np.isclose(weights.sum(), 1.0):
        raise ValueError(
            f"Las proporciones de tamano de farmacia suman {weights.sum()}, deben sumar 1"
        )

    # cada ruta recibe al menos una farmacia, el resto se reparte al azar
    extra = rng.choice(route_ids, n_pharmacies - len(route_ids))
    assigned_routes = np.concatenate([route_ids, extra])
    rng.shuffle(assigned_routes)

    size_per_pharmacy = rng.choice(sizes, n_pharmacies, p=weights)
    demand = np.array([factors[s] for s in size_per_pharmacy], dtype=float)
    demand = demand / demand.mean()  # media 1: el total diario lo fija pedidos_por_dia

    return pd.DataFrame(
        {
            "farmacia_id": np.arange(1, n_pharmacies + 1, dtype="int64"),
            "ruta_id": assigned_routes.astype("int64"),
            "zona": pd.array(
                [route_zone[int(r)] for r in assigned_routes], dtype="string"
            ),
            "tamano": pd.array(size_per_pharmacy, dtype="string"),
            "factor_demanda": demand,
        }
    )


def _build_routes(params, rng, route_ids, pharmacies):
    first_hour = value(params, "maestros", "hora_salida_rutas", "minima")
    last_hour = value(params, "maestros", "hora_salida_rutas", "maxima")
    counts = pharmacies.groupby("ruta_id").size().reindex(route_ids, fill_value=0)

    return pd.DataFrame(
        {
            "ruta_id": route_ids.astype("int64"),
            "furgoneta_id": route_ids.astype(
                "int64"
            ),  # una furgoneta por ruta (supuesto)
            "hora_salida": rng.integers(
                first_hour, last_hour + 1, len(route_ids)
            ).astype("int64"),
            "n_farmacias": counts.to_numpy().astype("int64"),
        }
    )


def _build_buckets(params, n_buckets):
    # la flota existe desde el inicio de la simulacion (incluido el calentamiento)
    start = pd.Timestamp(value(params, "general", "fecha_inicio")) - pd.Timedelta(
        days=value(params, "general", "dias_calentamiento")
    )
    return pd.DataFrame(
        {
            "cubeta_id": np.arange(1, n_buckets + 1, dtype="int64"),
            "fecha_alta": pd.Series([start] * n_buckets),
        }
    )
