"""Generacion de pedidos: convierte los conteos por hora de demand.py en
pedidos concretos (farmacia, instante, lineas, numero de cubetas).

Todavia no se asignan cubetas concretas a cada pedido. Eso depende de cuales
estan disponibles en cada momento, asi que se hace en cycle.py. Aqui solo se
decide cuantas cubetas necesita cada pedido (n_cubetas).
"""

import numpy as np
import pandas as pd

from cofas_twin.config import value
from cofas_twin.scheme import columns


def generate_orders(params, rng, demand, pharmacies):
    """Devuelve la tabla `pedidos` con las columnas del esquema, ordenada por fecha_hora.

    demand: salida de generate_demand (date, hour, n_orders, in_crisis).
    pharmacies: tabla `farmacias` (necesita farmacia_id y factor_demanda).
    """
    n_orders = int(demand["n_orders"].sum())

    # una fila de demanda se repite tantas veces como pedidos tenga esa hora
    rows = np.repeat(np.arange(len(demand)), demand["n_orders"].to_numpy())
    base = demand["date"].to_numpy()[rows] + demand["hour"].to_numpy()[rows].astype(
        "timedelta64[h]"
    )
    seconds = rng.integers(0, 3600, n_orders).astype("timedelta64[s]")
    timestamps = base + seconds

    order = np.argsort(timestamps, kind="stable")
    timestamps = timestamps[order]
    hours = demand["hour"].to_numpy()[rows][order]

    orders = pd.DataFrame(
        {
            "pedido_id": np.arange(1, n_orders + 1, dtype="int64"),
            "farmacia_id": _draw_pharmacies(rng, pharmacies, n_orders),
            "fecha_hora": timestamps,
            # provisional: la oleada es la hora de llegada, hasta saber como las define COFAS
            "oleada": hours.astype("int64"),
            "prioridad": _draw_priority(params, rng, n_orders),
            "n_lineas": _draw_lines(params, rng, n_orders),
            "n_cubetas": _draw_buckets_per_order(params, rng, n_orders),
        }
    )
    return orders[columns("pedidos")]


def _draw_pharmacies(rng, pharmacies, n):
    """Cada pedido cae en una farmacia con probabilidad proporcional a su factor_demanda."""
    weights = pharmacies["factor_demanda"].to_numpy(dtype=float)
    if (weights < 0).any() or weights.sum() <= 0:
        raise ValueError(
            "factor_demanda necesita valores no negativos y con suma mayor que 0"
        )
    ids = pharmacies["farmacia_id"].to_numpy()
    return rng.choice(ids, size=n, p=weights / weights.sum()).astype("int64")


def _draw_priority(params, rng, n):
    p_urgent = value(params, "pedidos", "prioridad", "probabilidad_urgente")
    return np.where(rng.random(n) < p_urgent, "urgente", "normal")


def _draw_buckets_per_order(params, rng, n):
    """1 + Poisson(lambda), con tope. Hoy es la unica distribucion soportada."""
    kind = value(params, "pedidos", "cubetas_por_pedido", "distribucion")
    if kind != "uno_mas_poisson":
        raise ValueError(f"Distribucion de cubetas_por_pedido no soportada: {kind}")
    lam = value(params, "pedidos", "cubetas_por_pedido", "lambda")
    maximum = value(params, "pedidos", "cubetas_por_pedido", "maximo")
    return np.minimum(1 + rng.poisson(lam, n), maximum).astype("int64")


def _draw_lines(params, rng, n):
    """Lognormal con mediana y sigma del YAML, redondeada y acotada entre 1 y el maximo."""
    kind = value(params, "pedidos", "lineas_por_pedido", "distribucion")
    if kind != "lognormal":
        raise ValueError(f"Distribucion de lineas_por_pedido no soportada: {kind}")
    median = value(params, "pedidos", "lineas_por_pedido", "mediana")
    sigma = value(params, "pedidos", "lineas_por_pedido", "sigma")
    maximum = value(params, "pedidos", "lineas_por_pedido", "maximo")
    raw = rng.lognormal(np.log(median), sigma, n)
    return np.clip(np.rint(raw), 1, maximum).astype("int64")
