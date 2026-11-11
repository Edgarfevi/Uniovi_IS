"""Escenarios: situaciones o decisiones que se simulan sobre la proyeccion.

Un escenario es un diccionario de palancas. Las que no se nombran se quedan en
su valor neutro, asi que {} es el escenario base.

Todos los efectos son supuestos: no hay datos de COFAS sobre cuanto consigue
cada decision. Por eso las palancas son numeros que se pueden mover y comparar.
"""

import numpy as np

NEUTRAL = {
    # >1: mas pedidos de los normales (pico). <1: menos.
    "outflow_scale": 1.0,
    # Regular el flujo de pedidos: tope de cubetas servidas por hora. Lo que sobra
    # pasa a la hora siguiente. None = sin tope.
    "max_outflow_per_hour": None,
    # Multiplica el tiempo que las cubetas pasan en la farmacia. >1: retenciones.
    # <1: acelerar el vaciado y la devolucion.
    "stay_scale": 1.0,
    # Parte de las cubetas pedidas que se sirve con otro contenedor (0 a 1).
    "alternative_fraction": 0.0,
    # Ola de pedidos: parte de los pedidos de cada dia (0 a 1) que se concentra
    # repartida a partes iguales en las horas de wave_window = (desde, hasta),
    # con hasta no incluida. El resto del dia conserva su forma.
    "wave_fraction": 0.0,
    "wave_window": (11, 13),
    # Cubetas que el escenario da por retenidas: se restan del stock inicial y no
    # vuelven durante el horizonte.
    "retained_cubetas": 0,
}


def complete(scenario):
    """Devuelve el escenario con todas las palancas, validando nombres y rangos."""
    scenario = dict(scenario or {})
    unknown = set(scenario) - set(NEUTRAL)
    if unknown:
        raise ValueError(
            f"Palancas desconocidas: {sorted(unknown)}. Validas: {sorted(NEUTRAL)}"
        )
    full = {**NEUTRAL, **scenario}
    if full["outflow_scale"] < 0:
        raise ValueError("outflow_scale no puede ser negativo")
    if full["stay_scale"] <= 0:
        raise ValueError("stay_scale tiene que ser mayor que 0")
    if not 0 <= full["alternative_fraction"] <= 1:
        raise ValueError("alternative_fraction tiene que estar entre 0 y 1")
    if full["max_outflow_per_hour"] is not None and full["max_outflow_per_hour"] < 0:
        raise ValueError("max_outflow_per_hour no puede ser negativo")
    if not 0 <= full["wave_fraction"] <= 1:
        raise ValueError("wave_fraction tiene que estar entre 0 y 1")
    start, end = full["wave_window"]
    if not 0 <= start < end <= 24:
        raise ValueError(
            "wave_window tiene que ser (desde, hasta) con 0 <= desde < hasta <= 24"
        )
    if full["retained_cubetas"] < 0:
        raise ValueError("retained_cubetas no puede ser negativo")
    return full


def scale_samples(samples, scenario):
    """Copia de las duraciones con el tiempo en farmacia multiplicado por stay_scale."""
    scenario = complete(scenario)
    if scenario["stay_scale"] == 1.0:
        return samples
    scaled = dict(samples)
    scaled["tiempo_en_farmacia"] = (
        samples["tiempo_en_farmacia"] * scenario["stay_scale"]
    )
    return scaled


def shape_outflow(outflow, scenario):
    """Aplica al flujo de cubetas pedidas (una cifra por hora) lo que hace el escenario."""
    scenario = complete(scenario)
    result = np.asarray(outflow, dtype=float) * scenario["outflow_scale"]
    result = result * (1.0 - scenario["alternative_fraction"])
    cap = scenario["max_outflow_per_hour"]
    if cap is not None:
        served = np.empty_like(result)
        pending = 0.0
        for hour, demanded in enumerate(result):
            total = pending + demanded
            served[hour] = min(total, cap)
            pending = total - served[hour]
        result = served
    return result


def shape_day(day, scenario):
    """Aplica la ola de pedidos a un dia completo (24 cifras, una por hora)."""
    scenario = complete(scenario)
    fraction = scenario["wave_fraction"]
    if fraction == 0.0:
        return day
    start, end = scenario["wave_window"]
    row = np.asarray(day, dtype=float)
    wave = np.zeros(24)
    wave[start:end] = 1.0 / (end - start)
    return (1.0 - fraction) * row + fraction * row.sum() * wave
