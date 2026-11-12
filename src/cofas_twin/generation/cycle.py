"""Simulacion del ciclo de vida de las cubetas.

Recorre los pedidos en orden cronologico. Cada pedido coge las cubetas que
lleva mas tiempo libres (FIFO) y, a partir de ahi, el recorrido de cada
cubeta se calcula con duraciones sorteadas de antemano:

    DISPONIBLE -> ASIGNADA_PEDIDO -> MUELLE -> SALIDA_REPARTO -> ENTREGA_FARMACIA
    -> (CONSOLIDACION) -> RECOGIDA_VACIA -> ENTRADA_ALMACEN
    -> (ENTRADA_LAVADO -> SALIDA_LAVADO) -> DISPONIBLE

Casos aparte: FUSION (se registra dentro de la estancia en farmacia) y
NO_LOCALIZADA (la cubeta no aparece al recogerla; puede reaparecer o perderse).

Si en el momento de un pedido no hay cubetas libres, el pedido espera a que
vuelvan. Ese retraso (ASIGNADA_PEDIDO menos fecha_hora del pedido) es la
huella del quiebre en los datos.

Devuelve todos los eventos, incluidos los del periodo de calentamiento.
Quitarlos es trabajo de la exportacion, no de este modulo.
"""

import heapq

import numpy as np
import pandas as pd
from scipy import stats

from cofas_twin.config import value
from cofas_twin.scheme import EVENT_TYPES, columns, empty_table

EPS_H = (
    2.0 / 3600.0
)  # dos segundos: margen entre eventos consecutivos de una misma cubeta
# (con 2 s el redondeo a segundos nunca invierte ni empata dos eventos seguidos)

# Supuesto: quien registra cada evento. El resto se registra por lectura.
SOURCE_BY_EVENT = {"ASIGNADA_PEDIDO": "sistema", "FUSION": "voz"}
DEFAULT_SOURCE = "lectura"


def generate_cycles(params, rng, orders, pharmacies, buckets):
    """Devuelve {"eventos_cubeta": DataFrame, "pedido_cubeta": DataFrame}."""
    t0 = pd.Timestamp(value(params, "general", "fecha_inicio")) - pd.Timedelta(
        days=value(params, "general", "dias_calentamiento")
    )
    n_days = value(params, "general", "dias_calentamiento") + value(
        params, "general", "dias_historico"
    )
    end_h = 24.0 * n_days  # los eventos posteriores al ultimo dia no existen todavia

    n_orders = len(orders)
    per_order = orders["n_cubetas"].to_numpy()
    n_slots = int(per_order.sum())
    first_slot = np.cumsum(per_order) - per_order  # primer hueco de cada pedido
    order_of_slot = np.repeat(np.arange(n_orders), per_order)
    is_first = np.zeros(n_slots, dtype=bool)
    is_first[first_slot] = True

    trip = _draw_trip(params, rng, n_slots)
    bucket_ids = buckets["cubeta_id"].to_numpy(dtype="int64")
    order_hours = ((orders["fecha_hora"] - t0) / pd.Timedelta(hours=1)).to_numpy()

    wash = {
        "gap": 1.0 / value(params, "ciclo", "lavado", "capacidad_por_hora"),
        "duration": value(params, "ciclo", "lavado", "duracion_h"),
    }
    bucket_of_slot, assigned_at, wash_start, available_at = _simulate(
        rng, bucket_ids, order_hours, per_order, trip, wash
    )

    events = _build_events(
        bucket_of_slot,
        assigned_at,
        wash_start,
        available_at,
        trip,
        wash,
        is_first,
        first_slot,
        order_of_slot,
        orders,
        pharmacies,
        bucket_ids,
        t0,
        end_h,
    )
    link = pd.DataFrame(
        {
            "pedido_id": orders["pedido_id"].to_numpy()[order_of_slot],
            "cubeta_id": bucket_of_slot,
        }
    )
    return {
        "eventos_cubeta": _cast(events, "eventos_cubeta"),
        "pedido_cubeta": _cast(link, "pedido_cubeta"),
    }


def _draw_trip(params, rng, n):
    """Sortea de antemano todo lo que le pasa a cada hueco (una cubeta en un pedido).

    Los desplazamientos (offset_*) son horas desde que se asigna la cubeta.
    """
    c = lambda *keys: value(params, "ciclo", *keys)
    _check_kind(c("preparacion", "distribucion"), "lognormal", "preparacion")
    _check_kind(c("espera_muelle", "distribucion"), "uniforme", "espera_muelle")
    _check_kind(c("transporte", "distribucion"), "normal_truncada", "transporte")
    _check_kind(
        c("tiempo_en_farmacia", "distribucion"), "lognormal", "tiempo_en_farmacia"
    )

    prep = rng.lognormal(
        np.log(c("preparacion", "mediana_min") / 60), c("preparacion", "sigma"), n
    )
    wait = (
        rng.uniform(
            c("espera_muelle", "minimo_min"), c("espera_muelle", "maximo_min"), n
        )
        / 60
    )
    go = _truncated_normal(rng, n, c("transporte"))
    back = _truncated_normal(
        rng, n, c("transporte")
    )  # supuesto: la vuelta dura como la ida
    stay = rng.lognormal(
        np.log(c("tiempo_en_farmacia", "mediana_h")),
        c("tiempo_en_farmacia", "sigma"),
        n,
    )

    consolidated = rng.random(n) < c("consolidacion", "probabilidad")
    extra = rng.uniform(
        c("consolidacion", "horas_extra_min"), c("consolidacion", "horas_extra_max"), n
    )
    extra = np.where(consolidated, extra, 0.0)

    fusion_flag = rng.random(n) < c("fusion", "probabilidad")
    fusion_frac = rng.uniform(0.1, 0.9, n)

    lost = rng.random(n) < c("perdida_por_ciclo", "valor")
    reappears = rng.random(n) < c("perdida_por_ciclo", "fraccion_reaparece")
    # supuesto: la reaparicion tarda una exponencial con media dias_reaparicion
    delay = rng.exponential(24.0 * c("perdida_por_ciclo", "dias_reaparicion"), n)

    washed = rng.random(n) < c("lavado", "probabilidad")

    offset_muelle = prep
    offset_departure = offset_muelle + wait
    offset_delivery = offset_departure + go
    offset_consolidation = offset_delivery + stay
    offset_pickup = offset_consolidation + extra
    offset_arrival = offset_pickup + np.where(
        lost, np.where(reappears, delay, np.inf), back
    )
    return {
        "muelle": offset_muelle,
        "departure": offset_departure,
        "delivery": offset_delivery,
        "consolidation": offset_consolidation,
        "pickup": offset_pickup,
        "fusion": offset_delivery + fusion_frac * stay,
        "arrival": offset_arrival,
        "consolidated": consolidated,
        "fusion_flag": fusion_flag,
        "lost": lost,
        "washed": washed,
    }


def _truncated_normal(rng, n, node):
    mean, sd = node["media_min"], node["desviacion_min"]
    low, high = node["minimo_min"], node["maximo_min"]
    a, b = (low - mean) / sd, (high - mean) / sd
    return stats.truncnorm.rvs(a, b, loc=mean, scale=sd, size=n, random_state=rng) / 60


def _check_kind(found, expected, name):
    if found != expected:
        raise ValueError(
            f"Distribucion de {name} no soportada: {found} (solo {expected})"
        )


def _simulate(rng, bucket_ids, order_hours, per_order, trip, wash):
    """Bucle principal: asigna cubetas a pedidos y gestiona vueltas y lavado.

    Usa dos montones (heaps): `available` (cubetas libres, ordenadas por el
    instante en que quedan libres) y `returning` (cubetas en ruta, ordenadas
    por su llegada al almacen).
    """
    n_slots = int(per_order.sum())
    arrival_offset = trip["arrival"].tolist()
    washed = trip["washed"].tolist()
    bucket_of_slot = [0] * n_slots
    assigned_at = [0.0] * n_slots
    wash_start = [np.nan] * n_slots
    available_at = [np.nan] * n_slots

    # al empezar todas estan libres; el orden inicial se baraja
    jitter = rng.permutation(len(bucket_ids)) * (EPS_H / len(bucket_ids))
    available = [(float(j), int(b)) for j, b in zip(jitter, bucket_ids)]
    heapq.heapify(available)
    returning = []
    state = {"wash_free": 0.0}

    def finish_return(arrival, s):
        """La cubeta llega al almacen: pasa por lavado si toca y queda libre."""
        if washed[s]:
            # el lavado procesa a lo sumo `capacidad_por_hora` cubetas por hora
            start = max(arrival + EPS_H, state["wash_free"])
            state["wash_free"] = start + wash["gap"]
            wash_start[s] = start
            free_at = start + wash["duration"] + EPS_H
        else:
            free_at = arrival + EPS_H
        available_at[s] = free_at
        heapq.heappush(available, (free_at, bucket_of_slot[s]))

    slot = 0
    for i, need in enumerate(per_order.tolist()):
        t = order_hours[i]
        while returning and returning[0][0] <= t:
            finish_return(*heapq.heappop(returning))
        while True:
            if len(available) >= need:
                chosen = [heapq.heappop(available) for _ in range(need)]
                latest = chosen[-1][0]
                # no hay nada por llegar que pudiera quedar libre antes: la eleccion vale
                if not returning or returning[0][0] >= latest:
                    break
                for item in chosen:
                    heapq.heappush(available, item)
            if not returning:
                raise RuntimeError(
                    "La flota no alcanza para cubrir los pedidos. "
                    "Baja demanda.pedidos_por_dia o sube maestros.n_cubetas."
                )
            finish_return(*heapq.heappop(returning))

        start = max(t, latest + EPS_H)  # si hubo espera, la asignacion se retrasa
        for k, (_, bucket) in enumerate(chosen):
            s = slot + k
            bucket_of_slot[s] = bucket
            assigned_at[s] = start
            if arrival_offset[s] != np.inf:
                heapq.heappush(returning, (start + arrival_offset[s], s))
        slot += need

    while returning:  # lo que sigue en ruta al acabar los pedidos
        finish_return(*heapq.heappop(returning))

    return (
        np.array(bucket_of_slot, dtype="int64"),
        np.array(assigned_at),
        np.array(wash_start),
        np.array(available_at),
    )


def _build_events(
    bucket_of_slot,
    assigned_at,
    wash_start,
    available_at,
    trip,
    wash,
    is_first,
    first_slot,
    order_of_slot,
    orders,
    pharmacies,
    bucket_ids,
    t0,
    end_h,
):
    """Convierte el resultado de la simulacion en la tabla de eventos (vectorizado)."""
    route_of_pharmacy = pharmacies.set_index("farmacia_id")["ruta_id"]
    order_ids = orders["pedido_id"].to_numpy()[order_of_slot]
    route_ids = route_of_pharmacy.loc[orders["farmacia_id"].to_numpy()].to_numpy()[
        order_of_slot
    ]
    first_bucket_of_order = bucket_of_slot[first_slot][order_of_slot]

    lost = trip["lost"]
    parts = []

    def add(kind, times, mask, with_order=True, destination=None):
        parts.append(
            {
                "kind": np.full(mask.sum(), EVENT_TYPES.index(kind), dtype="int8"),
                "time": times[mask],
                "bucket": bucket_of_slot[mask],
                "order": (
                    order_ids[mask]
                    if with_order
                    else np.full(mask.sum(), -1, dtype="int64")
                ),
                "route": (
                    route_ids[mask]
                    if with_order
                    else np.full(mask.sum(), -1, dtype="int64")
                ),
                "destination": (
                    destination[mask]
                    if destination is not None
                    else np.full(mask.sum(), -1, dtype="int64")
                ),
            }
        )

    everyone = np.ones(len(bucket_of_slot), dtype=bool)
    arrives = np.isfinite(trip["arrival"])
    fuses = (
        trip["fusion_flag"] & ~is_first
    )  # solo se fusiona con otra cubeta del mismo pedido

    add("ASIGNADA_PEDIDO", assigned_at, everyone)
    add("MUELLE", assigned_at + trip["muelle"], everyone)
    add("SALIDA_REPARTO", assigned_at + trip["departure"], everyone)
    add("ENTREGA_FARMACIA", assigned_at + trip["delivery"], everyone)
    add("CONSOLIDACION", assigned_at + trip["consolidation"], trip["consolidated"])
    add(
        "FUSION", assigned_at + trip["fusion"], fuses, destination=first_bucket_of_order
    )
    add("RECOGIDA_VACIA", assigned_at + trip["pickup"], ~lost)
    add("NO_LOCALIZADA", assigned_at + trip["pickup"], lost)
    add("ENTRADA_ALMACEN", assigned_at + trip["arrival"], arrives, with_order=False)
    washed = ~np.isnan(wash_start)
    add("ENTRADA_LAVADO", wash_start, washed, with_order=False)
    add("SALIDA_LAVADO", wash_start + wash["duration"], washed, with_order=False)
    add("DISPONIBLE", available_at, ~np.isnan(available_at), with_order=False)

    # estado inicial: todas las cubetas libres al empezar
    n_buckets = len(bucket_ids)
    parts.append(
        {
            "kind": np.full(n_buckets, EVENT_TYPES.index("DISPONIBLE"), dtype="int8"),
            "time": np.zeros(n_buckets),
            "bucket": bucket_ids,
            "order": np.full(n_buckets, -1, dtype="int64"),
            "route": np.full(n_buckets, -1, dtype="int64"),
            "destination": np.full(n_buckets, -1, dtype="int64"),
        }
    )

    cols = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
    keep = cols["time"] < end_h
    cols = {k: v[keep] for k, v in cols.items()}

    seconds = np.rint(cols["time"] * 3600).astype("int64")
    # orden por instante y, a igualdad, por cubeta (lexsort es estable)
    order = np.lexsort((cols["bucket"], seconds))
    seconds, cols = seconds[order], {k: v[order] for k, v in cols.items()}

    kind_names = np.array(EVENT_TYPES)[cols["kind"]]
    source_by_code = np.array(
        [SOURCE_BY_EVENT.get(k, DEFAULT_SOURCE) for k in EVENT_TYPES]
    )
    return pd.DataFrame(
        {
            "evento_id": np.arange(1, len(seconds) + 1, dtype="int64"),
            "cubeta_id": cols["bucket"],
            "tipo_evento": kind_names,
            "timestamp": t0 + pd.to_timedelta(seconds, unit="s"),
            "pedido_id": _nullable(cols["order"]),
            "ruta_id": _nullable(cols["route"]),
            "cubeta_destino": _nullable(cols["destination"]),
            "fuente_registro": source_by_code[cols["kind"]],
        }
    )


def _nullable(values):
    """Enteros con -1 como 'sin valor' pasan a Int64 con nulos."""
    return (
        pd.array(np.where(values < 0, pd.NA, values), dtype="Int64")
        if (values < 0).any()
        else pd.array(values, dtype="Int64")
    )


def _cast(df, table):
    """Deja el DataFrame con las columnas y tipos exactos del esquema."""
    dtypes = empty_table(table).dtypes.to_dict()
    return df[columns(table)].astype(dtypes)
