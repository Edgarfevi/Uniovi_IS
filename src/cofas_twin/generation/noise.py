"""Ruido de registro: lo que le pasa a los eventos al anotarlos.

Parte de los eventos limpios (los que de verdad ocurrieron) y devuelve una
copia con los fallos tipicos de un sistema real:

- eventos faltantes: una lectura que no se registro (se borra la fila)
- eventos duplicados: la misma lectura anotada dos veces, unos segundos despues

No toca el original: el generador conserva la version limpia para poder
validar despues si el modelo se acerca a la verdad.
"""

import numpy as np
import pandas as pd

from cofas_twin.config import value


def add_record_noise(params, rng, events):
    """Devuelve una copia ruidosa de `events` (tabla eventos_cubeta)."""
    p_missing = value(params, "registro", "eventos_faltantes")
    p_duplicate = value(params, "registro", "eventos_duplicados")
    min_delay = value(params, "registro", "eventos_duplicados", "retraso_s_min")
    max_delay = value(params, "registro", "eventos_duplicados", "retraso_s_max")
    for name, p in (
        ("eventos_faltantes", p_missing),
        ("eventos_duplicados", p_duplicate),
    ):
        if not 0 <= p <= 1:
            raise ValueError(f"registro.{name} tiene que estar entre 0 y 1, no {p}")

    n = len(events)
    kept = events[rng.random(n) >= p_missing]
    # el duplicado se sortea sobre lo que si se registro
    duplicated = kept[rng.random(len(kept)) < p_duplicate].copy()
    delay = rng.integers(min_delay, max_delay + 1, len(duplicated))
    duplicated["timestamp"] = duplicated["timestamp"] + pd.to_timedelta(delay, unit="s")

    noisy = pd.concat([kept, duplicated], ignore_index=True)
    # orden por instante (estable: a igualdad se respeta el orden original) y ids nuevos
    noisy = noisy.sort_values("timestamp", kind="stable", ignore_index=True)
    noisy["evento_id"] = np.arange(1, len(noisy) + 1, dtype="int64")
    return noisy
