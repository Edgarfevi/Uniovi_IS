"""Genera el historico sintetico completo y lo guarda en data/synthetic.

Uso (desde la raiz del proyecto, con el venv activo):

    python -m cofas_twin.generation.generate_history

Orden de generacion (un unico rng con la semilla del YAML, asi todo es
reproducible): maestros, demanda, pedidos, ciclo de cubetas, ruido de registro.
"""

import sys
from pathlib import Path

import numpy as np

from cofas_twin.config import load_parameters, value
from cofas_twin.generation.cycle import generate_cycles
from cofas_twin.generation.demand import generate_demand
from cofas_twin.generation.export import (
    DEFAULT_OUTPUT_DIR,
    OBSERVED_FOLDER,
    TRUTH_FOLDER,
    cut_to_history,
    save_tables,
    save_truth,
    write_metadata,
)
from cofas_twin.generation.masters import generate_masters
from cofas_twin.generation.noise import add_record_noise
from cofas_twin.generation.orders import generate_orders
from cofas_twin.scheme import validate_all


def generate_history(params=None, output_dir=None):
    """Genera y guarda el historico. Devuelve {"observado": tablas, "verdad": tablas}."""
    params = params if params is not None else load_parameters()
    output_dir = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_DIR
    rng = np.random.default_rng(value(params, "general", "semilla"))

    masters = generate_masters(params, rng)
    demand = generate_demand(params, rng)
    orders = generate_orders(params, rng, demand, masters["farmacias"])
    cycles = generate_cycles(
        params, rng, orders, masters["farmacias"], masters["cubetas"]
    )
    truth = {**masters, "pedidos": orders, **cycles}

    noisy_events = add_record_noise(params, rng, truth["eventos_cubeta"])
    observed = cut_to_history(params, {**truth, "eventos_cubeta": noisy_events})
    del noisy_events

    validate_all(truth)
    validate_all(observed)

    save_tables(observed, output_dir / OBSERVED_FOLDER)
    write_metadata(params, observed, output_dir / OBSERVED_FOLDER)
    save_truth(params, truth, demand, output_dir / TRUTH_FOLDER)
    write_metadata(params, truth, output_dir / TRUTH_FOLDER)
    return {"observado": observed, "verdad": truth}


def main():
    result = generate_history()
    print("Historico generado en", DEFAULT_OUTPUT_DIR)
    for kind, tables in result.items():
        print(f"\n{kind}:")
        for name, df in tables.items():
            print(f"  {name}: {len(df):,} filas")


if __name__ == "__main__":
    sys.exit(main())
