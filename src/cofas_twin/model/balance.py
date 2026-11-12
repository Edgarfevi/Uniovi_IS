"""Balance de stock de cubetas: una realizacion de la proyeccion.

    D(t+1) = D(t) + R(t) - S(t)

- D(t): cubetas disponibles al final de la hora t. Puede ser negativo: un valor
  por debajo de 0 es quiebre (pedidos que no se pueden servir), no se recorta.
- S(t): cubetas que piden los pedidos de esa hora. Se remuestrea un dia entero
  del historico con el mismo dia de la semana, asi se conserva la forma del
  dia y los dias malos aparecen con su frecuencia real.
- R(t): cubetas que vuelven a quedar disponibles en esa hora. Salen de dos sitios:
  las que ya estan en circulacion al empezar (segun la fase en la que van) y las
  que salen durante el propio horizonte y alcanzan a volver.
- Las perdidas (P) no se restan a mano: una cubeta perdida simplemente no vuelve.

Cada duracion se remuestrea de las duraciones observadas, sin suponer una
distribucion. Las fases se tratan como independientes entre si.

Simplificacion conocida: si hay quiebre, los pedidos en espera no retrasan la
salida de sus cubetas en la proyeccion (en la realidad esperarian).
"""

import numpy as np
import pandas as pd

from cofas_twin.model.reconstruction import STATE_AFTER_EVENT, UNKNOWN
from cofas_twin.model.scenarios import complete, shape_day, shape_outflow

# Fases del recorrido, en orden. "recuperacion" = desde que entra al almacen hasta
# que queda disponible (con o sin lavado).
CHAIN = (
    "preparacion",
    "espera_muelle",
    "transporte_ida",
    "tiempo_en_farmacia",
    "transporte_vuelta",
    "recuperacion",
)
IN_LAVADO = 6  # ya esta en el lavado: solo falta lo que reste de lavado
DONE = 7  # acaba de salir del lavado: queda disponible ya
NO_PHASE = -1  # disponible, no localizada o sin informacion: no vuelve a la cola

# En que fase esta una cubeta segun su ultimo evento
PHASE_OF_EVENT = {
    "ASIGNADA_PEDIDO": 0,
    "MUELLE": 1,
    "SALIDA_REPARTO": 2,
    "ENTREGA_FARMACIA": 3,
    "CONSOLIDACION": 3,
    "FUSION": 3,
    "RECOGIDA_VACIA": 4,
    "ENTRADA_ALMACEN": 5,
    "ENTRADA_LAVADO": IN_LAVADO,
    "SALIDA_LAVADO": DONE,
}


def snapshot(events, bucket_ids, origin):
    """Que se sabe de cada cubeta en el instante `origin`, con los eventos hasta ese momento.

    Devuelve un DataFrame con una fila por cubeta: estado, fase y horas que lleva
    en ella (age_h). Para las que estan en farmacia, el tiempo se cuenta desde la entrega.
    """
    origin = pd.Timestamp(origin)
    known = events[events["timestamp"] <= origin]
    if not known["timestamp"].is_monotonic_increasing:
        known = known.sort_values("timestamp", kind="stable")
    last = known.drop_duplicates("cubeta_id", keep="last").set_index("cubeta_id")
    delivery = (
        known[known["tipo_evento"] == "ENTREGA_FARMACIA"]
        .drop_duplicates("cubeta_id", keep="last")
        .set_index("cubeta_id")["timestamp"]
    )

    table = pd.DataFrame(
        {"cubeta_id": np.asarray(bucket_ids, dtype="int64")}
    ).set_index("cubeta_id")
    table["last_event"] = last["tipo_evento"].reindex(table.index)
    table["last_time"] = last["timestamp"].reindex(table.index)
    table["state"] = table["last_event"].map(STATE_AFTER_EVENT).fillna(UNKNOWN)
    table["phase"] = (
        table["last_event"].map(PHASE_OF_EVENT).fillna(NO_PHASE).astype("int64")
    )
    since = table["last_time"].where(
        table["phase"] != 3, delivery.reindex(table.index).fillna(table["last_time"])
    )
    table["age_h"] = (
        ((origin - since).dt.total_seconds() / 3600).fillna(0.0).clip(lower=0.0)
    )
    return table.reset_index()


def prepare_samples(estimates, rng, recovery_size=200_000):
    """Deja las duraciones listas para remuestrear (ordenadas) y construye la fase 'recuperacion'."""
    d = estimates["duraciones"]
    wash_probability = estimates["tasas"]["probabilidad_lavado"]
    wait = d["espera_lavado"][rng.integers(0, len(d["espera_lavado"]), recovery_size)]
    wash = d["lavado"][rng.integers(0, len(d["lavado"]), recovery_size)]
    washed = rng.random(recovery_size) < wash_probability
    samples = {name: np.sort(d[name]) for name in CHAIN[:-1]}
    samples["recuperacion"] = np.sort(np.where(washed, wait + wash, 0.0))
    samples["lavado"] = np.sort(d["lavado"])
    return samples


def run_once(
    rng, current, samples, loss, outflow_days, origin, horizon_h, scenario=None
):
    """Una trayectoria. Devuelve (D, R, S): arrays de longitud horizon_h.

    current: salida de snapshot(). samples: salida de prepare_samples().
    loss: probabilidad de que una cubeta no vuelva en un ciclo.
    outflow_days: matriz dia x hora de cubetas pedidas (estimation.estimate_outflow_days).
    origin: instante donde empieza la proyeccion (un instante en punto).
    scenario: palancas que cambian el flujo de pedidos (ver scenarios.py). Las que
    cambian las duraciones ya vienen aplicadas en `samples`.
    """
    origin = pd.Timestamp(origin)
    returns = np.zeros(horizon_h)

    # 1) cubetas que ya estan en circulacion
    live = current[current["phase"] != NO_PHASE]
    ready = _remaining_time(
        rng, live["phase"].to_numpy(), live["age_h"].to_numpy(), samples
    )
    ready[(live["phase"].to_numpy() <= 3) & (rng.random(len(live)) < loss)] = np.inf
    _add_returns(returns, ready)

    # 2) cubetas que salen durante el horizonte
    scenario = complete(scenario)
    outflow = shape_outflow(
        _sample_outflow(rng, outflow_days, origin, horizon_h, scenario), scenario
    )
    outflow = np.rint(outflow).astype("int64")
    hour_of_leaving = np.repeat(np.arange(horizon_h), outflow)
    leaving_at = hour_of_leaving + rng.random(len(hour_of_leaving))
    trip = np.zeros(len(leaving_at))
    for name in CHAIN:
        trip += samples[name][rng.integers(0, len(samples[name]), len(trip))]
    trip[rng.random(len(trip)) < loss] = np.inf
    _add_returns(returns, leaving_at + trip)

    available_now = (
        int((current["state"] == "disponible").sum()) - scenario["retained_cubetas"]
    )
    stock = available_now + np.cumsum(returns - outflow)
    return stock, returns, outflow


def _remaining_time(rng, phase, age, samples):
    """Horas que faltan para quedar disponible, segun la fase actual y lo que lleva en ella."""
    total = np.zeros(len(phase))
    for code, name in enumerate(CHAIN):
        now = phase == code
        total[now] += _draw_remaining(
            rng, samples[name], age[now]
        )  # lo que resta de esta fase
        later = (phase >= 0) & (phase < code)
        total[later] += samples[name][
            rng.integers(0, len(samples[name]), later.sum())
        ]  # fases futuras
    washing = phase == IN_LAVADO
    total[washing] += _draw_remaining(rng, samples["lavado"], age[washing])
    return total


def _draw_remaining(rng, sorted_samples, age):
    """Lo que falta de una fase que ya dura `age`: se elige entre las muestras mas largas que `age`."""
    n = len(sorted_samples)
    first_longer = np.searchsorted(sorted_samples, age, side="right")
    remaining = np.zeros(len(age))
    has_more = first_longer < n
    pick = first_longer[has_more] + (
        rng.random(has_more.sum()) * (n - first_longer[has_more])
    ).astype("int64")
    remaining[has_more] = sorted_samples[pick] - age[has_more]
    return remaining  # si no hay ninguna muestra mas larga, la fase ya deberia haber acabado


def _add_returns(returns, ready_times):
    inside = (
        np.isfinite(ready_times) & (ready_times >= 0) & (ready_times < len(returns))
    )
    returns += np.bincount(
        np.floor(ready_times[inside]).astype("int64"), minlength=len(returns)
    )


def _sample_outflow(rng, outflow_days, origin, horizon_h, scenario):
    """Cubetas pedidas en cada hora del horizonte, remuestreando dias del historico con el mismo dia de la semana."""
    hours = origin + pd.to_timedelta(np.arange(horizon_h), unit="h")
    by_weekday = {w: np.flatnonzero(outflow_days.index.weekday == w) for w in range(7)}
    matrix = outflow_days.to_numpy()
    result = np.zeros(horizon_h)
    for day in pd.unique(hours.normalize()):
        rows = by_weekday[day.weekday()]
        chosen = shape_day(matrix[rng.choice(rows)], scenario)
        in_day = hours.normalize() == day
        result[in_day] = chosen[hours[in_day].hour]
    return result
