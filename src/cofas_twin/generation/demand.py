"""Generacion de la demanda: cuantos pedidos llegan cada dia y cada hora.

Devuelve una tabla intermedia (no es una de las seis tablas del esquema)
con una fila por dia y hora. Los pedidos concretos se crean despues,
en orders.py.
"""

import numpy as np
import pandas as pd

from cofas_twin.config import value

# Claves del YAML: son datos, por eso se quedan en espanol
WEEKDAYS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def generate_demand(params, rng):
    """Devuelve un DataFrame con columnas: date, hour, n_orders, in_crisis."""
    n_warmup = value(params, "general", "dias_calentamiento")
    n_history = value(params, "general", "dias_historico")
    start = pd.Timestamp(value(params, "general", "fecha_inicio")) - pd.Timedelta(
        days=n_warmup
    )
    dates = pd.date_range(start, periods=n_warmup + n_history, freq="D")

    hours, hour_probs = _hourly_profile(params)
    in_crisis = _crisis_calendar(params, rng, len(dates))
    expected = _expected_daily_orders(params, dates, in_crisis)

    # ruido de cada dia (relativo) y despues el azar propio de contar pedidos
    noise = np.maximum(
        0.0, rng.normal(1.0, value(params, "demanda", "ruido_diario"), len(dates))
    )
    daily_orders = rng.poisson(expected * noise)

    # reparto de los pedidos de cada dia entre las horas segun el perfil
    counts = np.vstack([rng.multinomial(n, hour_probs) for n in daily_orders])

    return pd.DataFrame(
        {
            "date": np.repeat(dates.values, len(hours)),
            "hour": np.tile(hours, len(dates)).astype("int64"),
            "n_orders": counts.ravel().astype("int64"),
            "in_crisis": np.repeat(in_crisis, len(hours)),
        }
    )


def _hourly_profile(params):
    weights = value(params, "demanda", "perfil_horario", "pesos")
    hours = np.array(sorted(weights), dtype="int64")
    raw = np.array([weights[h] for h in hours], dtype=float)
    if (raw < 0).any() or raw.sum() <= 0:
        raise ValueError(
            "El perfil horario necesita pesos no negativos y con suma mayor que 0"
        )
    return hours, raw / raw.sum()


def _crisis_calendar(params, rng, n_days):
    """Devuelve un array de bool: True en los dias de crisis."""
    min_episodes = value(params, "demanda", "crisis", "episodios_por_anio_min")
    max_episodes = value(params, "demanda", "crisis", "episodios_por_anio_max")
    min_length = value(params, "demanda", "crisis", "duracion_dias_min")
    max_length = value(params, "demanda", "crisis", "duracion_dias_max")

    # episodios esperados en el periodo simulado, a partir del ritmo anual
    per_year = rng.integers(min_episodes, max_episodes + 1)
    n_episodes = rng.poisson(per_year * n_days / 365)

    in_crisis = np.zeros(n_days, dtype=bool)
    for _ in range(n_episodes):
        first = rng.integers(0, n_days)
        length = rng.integers(min_length, max_length + 1)
        in_crisis[first : first + length] = True
    return in_crisis


def _expected_daily_orders(params, dates, in_crisis):
    base = value(params, "demanda", "pedidos_por_dia")
    weekday_factor = np.array(
        [value(params, "demanda", "factor_dia_semana", name) for name in WEEKDAYS],
        dtype=float,
    )
    month_factor = np.array(
        [value(params, "demanda", "factor_mes", name) for name in MONTHS], dtype=float
    )
    boost = value(params, "demanda", "crisis", "incremento")

    expected = (
        base
        * weekday_factor[np.asarray(dates.weekday)]
        * month_factor[np.asarray(dates.month) - 1]
    )
    return expected * np.where(in_crisis, 1.0 + boost, 1.0)
