"""Comprobaciones de coherencia: que las cubetas ni se creen ni se pierdan, y que el
balance D(t+1) = D(t) + R(t) - S(t) se cumpla sobre los datos.

En los datos limpios todo tiene que dar 0. En los observados (con ruido de
registro) los fallos que salgan miden cuanto estropea el ruido cada comprobacion.
"""

import numpy as np
import pandas as pd

from cofas_twin.model.reconstruction import state_counts

# Tras cada tipo de evento, que tipos pueden ser el siguiente de la misma cubeta
VALID_NEXT = {
    "DISPONIBLE": {"ASIGNADA_PEDIDO"},
    "ASIGNADA_PEDIDO": {"MUELLE"},
    "MUELLE": {"SALIDA_REPARTO"},
    "SALIDA_REPARTO": {"ENTREGA_FARMACIA"},
    "ENTREGA_FARMACIA": {"RECOGIDA_VACIA", "CONSOLIDACION", "FUSION", "NO_LOCALIZADA"},
    "FUSION": {"CONSOLIDACION", "RECOGIDA_VACIA", "NO_LOCALIZADA"},
    "CONSOLIDACION": {"RECOGIDA_VACIA", "NO_LOCALIZADA"},
    "RECOGIDA_VACIA": {"ENTRADA_ALMACEN"},
    "NO_LOCALIZADA": {"ENTRADA_ALMACEN"},
    "ENTRADA_ALMACEN": {"ENTRADA_LAVADO", "DISPONIBLE"},
    "ENTRADA_LAVADO": {"SALIDA_LAVADO"},
    "SALIDA_LAVADO": {"DISPONIBLE"},
}


def invalid_transitions(events):
    """Cuantos pares de eventos seguidos de una misma cubeta son imposibles."""
    ordered = events.sort_values(["cubeta_id", "timestamp", "evento_id"], kind="stable")
    bucket = ordered["cubeta_id"].to_numpy()
    kind = ordered["tipo_evento"].to_numpy()
    same = np.flatnonzero(bucket[1:] == bucket[:-1])
    bad = sum(1 for i in same if kind[i + 1] not in VALID_NEXT[kind[i]])
    return bad, len(same)


def balance_gap(events, bucket_ids, known_share=0.99):
    """Cuanto se desvia la ecuacion del balance de lo que se cuenta directamente.

    Stock directo: cubetas cuyo ultimo evento es DISPONIBLE. Stock por balance:
    cubetas puestas disponibles menos cubetas asignadas, acumulado. La ecuacion
    necesita un punto de partida, y al empezar el historico hay cubetas de las
    que aun no se sabe nada. Por eso se mide a partir de la primera hora en que
    ya se conoce al menos `known_share` de la flota, y la desviacion es la que
    se acumula desde ese momento.
    Con datos coherentes la desviacion es 0 siempre. Devuelve la serie hora a hora.
    """
    counts = state_counts(events, bucket_ids)
    counted = counts["disponible"]
    grid = counted.index
    arrived = np.sort(
        events[events["tipo_evento"] == "DISPONIBLE"]["timestamp"].to_numpy()
    )
    taken = np.sort(
        events[events["tipo_evento"] == "ASIGNADA_PEDIDO"]["timestamp"].to_numpy()
    )
    by_balance = np.searchsorted(
        arrived, grid.to_numpy(), side="right"
    ) - np.searchsorted(taken, grid.to_numpy(), side="right")
    gap = counted - pd.Series(by_balance, index=grid)

    settled = counts.index[
        counts["sin_informacion"] <= (1 - known_share) * len(bucket_ids)
    ][0]
    return (gap - gap[settled])[settled:]


def run_conservation(events, bucket_ids):
    """Resumen de las tres comprobaciones sobre un conjunto de eventos."""
    counts = state_counts(events, bucket_ids)
    states = [c for c in counts.columns if c != "total"]
    bad, pairs = invalid_transitions(events)
    gap = balance_gap(events, bucket_ids)
    return {
        "flota_constante": bool((counts[states].sum(axis=1) == len(bucket_ids)).all()),
        "transiciones_imposibles": bad,
        "transiciones_total": pairs,
        "balance_diferencia_max": int(gap.abs().max()),
        "balance_diferencia_media": float(gap.abs().mean()),
    }
