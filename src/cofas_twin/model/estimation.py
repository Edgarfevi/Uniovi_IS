"""Estimacion, a partir del historico observado, de lo que necesita el balance.

Solo mira las tablas observadas y los parametros del modelo. No sabe como se
generaron los datos: si recupera los valores del generador, es porque estan en
los datos y no porque los haya leido.

Devuelve:
- duraciones de cada fase del ciclo (las muestras reales, para remuestrear
  despues, y un resumen),
- tasas del ciclo (perdida, reaparicion, lavado, consolidacion, fusion),
- cubetas pedidas por dia de la semana y hora.
"""

import numpy as np
import pandas as pd

from cofas_twin.config import value
from cofas_twin.model.reconstruction import remove_duplicates

# Fases que se miden uniendo dos eventos del mismo pedido y la misma cubeta
PHASES_BY_ORDER = {
    "preparacion": ("ASIGNADA_PEDIDO", "MUELLE"),
    "espera_muelle": ("MUELLE", "SALIDA_REPARTO"),
    "transporte_ida": ("SALIDA_REPARTO", "ENTREGA_FARMACIA"),
    "tiempo_en_farmacia": ("ENTREGA_FARMACIA", "RECOGIDA_VACIA"),
}
# Fases entre dos eventos seguidos de la misma cubeta (sin pedido de por medio)
PHASES_CONSECUTIVE = {
    "transporte_vuelta": ("RECOGIDA_VACIA", "ENTRADA_ALMACEN"),
    "espera_lavado": ("ENTRADA_ALMACEN", "ENTRADA_LAVADO"),
    "lavado": ("ENTRADA_LAVADO", "SALIDA_LAVADO"),
}


def estimate_all(tables, model_params):
    """Devuelve {"duraciones", "resumen", "tasas", "salidas", "salidas_dias"} a partir de las seis tablas."""
    events = remove_duplicates(
        tables["eventos_cubeta"],
        value(model_params, "limpieza", "ventana_duplicados_s"),
    )
    trim_days = value(model_params, "estimacion", "recorte_censura_dias")
    window_days = value(model_params, "estimacion", "ventana_reaparicion_dias")
    recent_days = value(model_params, "estimacion", "dias_recientes_salidas")

    durations = estimate_durations(events, trim_days)
    # los pedidos anteriores a la ventana solo estan a medias (los que aun tienen
    # eventos dentro), asi que para contar pedidos por hora se ignoran
    first_day = events["timestamp"].min().floor("D")
    orders = tables["pedidos"]
    orders = orders[orders["fecha_hora"] >= first_day]
    return {
        "duraciones": durations,
        "resumen": summarize_durations(durations),
        "tasas": estimate_rates(events, trim_days, window_days),
        "salidas": estimate_outflow(orders),
        # para proyectar solo se remuestrean los dias mas recientes: con todo el
        # historico, la estacionalidad (meses distintos) sesga la proyeccion
        "salidas_dias": estimate_outflow_days(orders).iloc[-recent_days:],
    }


def estimate_durations(events, trim_days):
    """Devuelve {fase: array de horas} con una muestra por cada ciclo observado.

    Se descartan las fases que empiezan en los ultimos `trim_days` dias, porque
    sus ciclos mas largos todavia no han terminado y sesgarian a la baja.
    """
    cut = events["timestamp"].max() - pd.Timedelta(days=trim_days)
    result = {}
    for phase, (first, second) in PHASES_BY_ORDER.items():
        result[phase] = _pair_by_order(events, first, second, cut)
    ordered = events.sort_values(["cubeta_id", "timestamp", "evento_id"], kind="stable")
    for phase, (first, second) in PHASES_CONSECUTIVE.items():
        result[phase] = _pair_consecutive(ordered, first, second, cut)
    return result


def summarize_durations(durations):
    """Tabla con n, mediana, media, p10, p90 y el ajuste lognormal de cada fase (en horas)."""
    rows = {}
    for phase, x in durations.items():
        positive = x[x > 0]
        logs = np.log(positive) if len(positive) else np.array([np.nan])
        rows[phase] = {
            "n": len(x),
            "mediana_h": np.median(x),
            "media_h": x.mean(),
            "p10_h": np.quantile(x, 0.10),
            "p90_h": np.quantile(x, 0.90),
            "mu_log": logs.mean(),
            "sigma_log": logs.std(),
        }
    return pd.DataFrame(rows).T


def estimate_rates(events, trim_days, window_days):
    """Tasas del ciclo a partir de recuentos de eventos."""
    end = events["timestamp"].max()
    counts = events["tipo_evento"].value_counts()
    n = lambda name: int(counts.get(name, 0))

    # perdida: de las cubetas que llegan al final de su estancia, cuantas no aparecen
    ends_of_stay = n("RECOGIDA_VACIA") + n("NO_LOCALIZADA")
    loss = n("NO_LOCALIZADA") / ends_of_stay

    # reaparicion: entre las no localizadas con tiempo de sobra, las que vuelven a tener eventos
    lost = events[events["tipo_evento"] == "NO_LOCALIZADA"][["cubeta_id", "timestamp"]]
    lost = lost[lost["timestamp"] <= end - pd.Timedelta(days=window_days)]
    after = _first_event_after(events, lost)
    reappeared = after.notna()
    delays_days = (
        after[reappeared] - lost["timestamp"][reappeared]
    ).dt.total_seconds() / 86400

    cut = end - pd.Timedelta(days=trim_days)
    delivered = _keys(events, "ENTREGA_FARMACIA", cut)
    consolidated = _keys(events, "CONSOLIDACION", None)
    n_delivered = len(delivered)

    return {
        "perdida_por_ciclo": loss,
        "fraccion_reaparece": float(reappeared.mean()) if len(lost) else np.nan,
        "dias_reaparicion_media": (
            float(delays_days.mean()) if reappeared.any() else np.nan
        ),
        "n_no_localizadas_evaluadas": int(len(lost)),
        "probabilidad_lavado": n("ENTRADA_LAVADO") / n("ENTRADA_ALMACEN"),
        "probabilidad_consolidacion": len(delivered & consolidated) / n_delivered,
        "fusiones_por_ciclo": n("FUSION") / n("ENTREGA_FARMACIA"),
    }


def estimate_outflow_days(orders):
    """Cubetas pedidas en cada hora de cada dia: una fila por dia, una columna por hora (0 a 23).

    Incluye los dias sin ningun pedido (domingos) con todo a 0.
    """
    when = orders["fecha_hora"]
    per_hour = (
        orders.assign(date=when.dt.normalize(), hour=when.dt.hour)
        .groupby(["date", "hour"])["n_cubetas"]
        .sum()
        .unstack("hour", fill_value=0)
    )
    all_days = pd.date_range(per_hour.index.min(), per_hour.index.max(), freq="D")
    per_hour = per_hour.reindex(index=all_days, columns=range(24), fill_value=0)
    per_hour.index.name = "date"
    return per_hour


def estimate_outflow(orders):
    """Cubetas pedidas por hora, para cada dia de la semana y hora del dia.

    Devuelve un DataFrame indexado por (dia_semana, hora) con la media, la
    desviacion y los percentiles 10, 50 y 90 de cubetas pedidas en esa hora,
    y el numero de dias que entran en la cuenta. dia_semana: 0 = lunes.
    """
    long = estimate_outflow_days(orders).stack().rename("cubetas").reset_index()
    long["dia_semana"] = long["date"].dt.weekday
    grouped = long.groupby(["dia_semana", "hour"])["cubetas"]
    out = grouped.agg(
        media="mean",
        desviacion="std",
        p10=lambda s: s.quantile(0.10),
        p50="median",
        p90=lambda s: s.quantile(0.90),
        dias="count",
    )
    out.index.names = ["dia_semana", "hora"]
    return out


def _pair_by_order(events, first, second, cut):
    a = events.loc[
        events["tipo_evento"] == first, ["cubeta_id", "pedido_id", "timestamp"]
    ]
    b = events.loc[
        events["tipo_evento"] == second, ["cubeta_id", "pedido_id", "timestamp"]
    ]
    merged = a.merge(b, on=["cubeta_id", "pedido_id"], suffixes=("_1", "_2"))
    merged = merged[merged["timestamp_1"] <= cut]
    return (
        (merged["timestamp_2"] - merged["timestamp_1"]).dt.total_seconds() / 3600
    ).to_numpy()


def _pair_consecutive(ordered, first, second, cut):
    bucket = ordered["cubeta_id"].to_numpy()
    kind = ordered["tipo_evento"].to_numpy()
    time = ordered["timestamp"]
    is_pair = (bucket[:-1] == bucket[1:]) & (kind[:-1] == first) & (kind[1:] == second)
    start = time.iloc[:-1][is_pair].reset_index(drop=True)
    stop = time.iloc[1:][is_pair].reset_index(drop=True)
    keep = start <= cut
    return ((stop[keep] - start[keep]).dt.total_seconds() / 3600).to_numpy()


def _first_event_after(events, marks):
    """Para cada fila de `marks` (cubeta_id, timestamp), el instante del siguiente evento de esa cubeta (NaT si no hay)."""
    ordered = events[["cubeta_id", "timestamp"]].sort_values(
        ["timestamp"], kind="stable"
    )
    left = marks.sort_values("timestamp")
    merged = pd.merge_asof(
        left.assign(after=left["timestamp"] + pd.Timedelta(seconds=1)),
        ordered.rename(columns={"timestamp": "next_event"}),
        left_on="after",
        right_on="next_event",
        by="cubeta_id",
        direction="forward",
    )
    merged.index = left.index
    return merged["next_event"].reindex(marks.index)


def _keys(events, kind, cut):
    rows = events[events["tipo_evento"] == kind]
    if cut is not None:
        rows = rows[rows["timestamp"] <= cut]
    return set(zip(rows["cubeta_id"].to_numpy(), rows["pedido_id"].to_numpy()))
