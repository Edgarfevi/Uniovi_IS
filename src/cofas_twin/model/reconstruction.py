"""Reconstruccion de lo que se sabe de las cubetas a partir de los eventos.

Dos pasos:
1. remove_duplicates: quita lecturas repetidas (ruido de registro).
2. state_counts: para cada hora, cuantas cubetas hay en cada estado, segun el
   ultimo evento conocido de cada una.

Solo usa la tabla eventos_cubeta y la lista de cubetas. No sabe nada de como
se generaron los datos.
"""

import numpy as np
import pandas as pd

# Estado en el que queda una cubeta justo despues de cada evento
STATE_AFTER_EVENT = {
    "DISPONIBLE": "disponible",
    "ASIGNADA_PEDIDO": "en_preparacion",
    "MUELLE": "en_preparacion",
    "SALIDA_REPARTO": "en_ruta",
    "ENTREGA_FARMACIA": "en_farmacia",
    "CONSOLIDACION": "en_farmacia",
    "FUSION": "en_farmacia",
    "RECOGIDA_VACIA": "en_retorno",
    "ENTRADA_ALMACEN": "en_recuperacion",
    "ENTRADA_LAVADO": "en_recuperacion",
    "SALIDA_LAVADO": "en_recuperacion",
    "NO_LOCALIZADA": "no_localizada",
}
STATES = (
    "disponible",
    "en_preparacion",
    "en_ruta",
    "en_farmacia",
    "en_retorno",
    "en_recuperacion",
    "no_localizada",
)
UNKNOWN = "sin_informacion"  # cubetas de las que aun no se ha visto ningun evento


def remove_duplicates(events, window_s):
    """Quita los eventos que repiten a otro igual ocurrido hace `window_s` segundos o menos.

    Igual significa misma cubeta, mismo tipo, mismo pedido y mismo destino.
    Se conserva la primera lectura. Devuelve los eventos en su orden original.
    """
    n = len(events)
    if n == 0:
        return events
    keys = [
        events["cubeta_id"].to_numpy(dtype="int64"),
        pd.factorize(events["tipo_evento"])[0],
        events["pedido_id"].fillna(-1).to_numpy(dtype="int64"),
        events["cubeta_destino"].fillna(-1).to_numpy(dtype="int64"),
    ]
    seconds = events["timestamp"].astype("int64").to_numpy() // 1_000_000_000
    order = np.lexsort((seconds, *keys[::-1]))  # por clave y, dentro, por instante

    same_key = np.ones(n - 1, dtype=bool)
    for k in keys:
        same_key &= k[order][1:] == k[order][:-1]
    close = np.diff(seconds[order]) <= window_s

    drop = np.zeros(n, dtype=bool)
    drop[order[1:][same_key & close]] = True
    return events[~drop]


def state_counts(events, bucket_ids, start=None, end=None, freq="1h"):
    """Cuantas cubetas hay en cada estado en cada instante de una rejilla.

    En cada instante t, el estado de una cubeta es el que dejo su ultimo evento
    con timestamp <= t. Si aun no tiene ninguno, cuenta como `sin_informacion`.

    Devuelve un DataFrame indexado por instante, con una columna por estado
    (mas sin_informacion) y `total`, que siempre suma el numero de cubetas.
    start y end por defecto salen de los propios eventos (redondeados a la hora).
    """
    events = events.sort_values("timestamp", kind="stable")
    start = (
        pd.Timestamp(start)
        if start is not None
        else events["timestamp"].min().floor(freq)
    )
    end = (
        pd.Timestamp(end) if end is not None else events["timestamp"].max().floor(freq)
    )
    grid = pd.date_range(start, end, freq=freq)

    names = STATES + (UNKNOWN,)
    unknown_code = len(STATES)
    code_of_event = pd.Series(
        {event: STATES.index(state) for event, state in STATE_AFTER_EVENT.items()}
    )
    ids = np.sort(np.asarray(bucket_ids, dtype="int64"))
    position = np.searchsorted(ids, events["cubeta_id"].to_numpy(dtype="int64"))
    if (
        ids[np.minimum(position, len(ids) - 1)]
        != events["cubeta_id"].to_numpy(dtype="int64")
    ).any():
        raise ValueError("Hay eventos de cubetas que no estan en la tabla cubetas")
    codes = code_of_event.reindex(events["tipo_evento"]).to_numpy()
    if np.isnan(codes.astype(float)).any():
        raise ValueError("Hay tipos de evento sin estado asociado")
    codes = codes.astype("int64")

    times = events["timestamp"].to_numpy()
    state = np.full(len(ids), unknown_code, dtype="int64")
    counts = np.empty((len(grid), len(names)), dtype="int64")
    done = 0
    for row, t in enumerate(grid.to_numpy()):
        upto = np.searchsorted(times, t, side="right")  # eventos con timestamp <= t
        if upto > done:
            chunk_pos, chunk_codes = position[done:upto], codes[done:upto]
            # varios eventos de una misma cubeta en el tramo: vale el ultimo
            last = len(chunk_pos) - 1 - np.unique(chunk_pos[::-1], return_index=True)[1]
            state[chunk_pos[last]] = chunk_codes[last]
            done = upto
        counts[row] = np.bincount(state, minlength=len(names))

    result = pd.DataFrame(
        counts, index=pd.Index(grid, name="timestamp"), columns=list(names)
    )
    result["total"] = len(ids)
    return result
