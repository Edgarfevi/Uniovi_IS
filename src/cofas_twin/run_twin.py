"""Ejecuta el gemelo de principio a fin y compara escenarios.

Uso (desde la raiz del proyecto, con el venv activo):

    python -m cofas_twin.run_twin
    python -m cofas_twin.run_twin --fuente cofas
    python -m cofas_twin.run_twin --origen "2026-06-23 05:00" --escenarios base dia_estres

Pasos: carga de datos (adaptador), limpieza, estimacion, proyeccion de cada
escenario del YAML y tabla comparativa. Sirve igual con datos sinteticos que con
los de COFAS: solo cambia el adaptador.
"""

import argparse
import sys

import pandas as pd

from cofas_twin.config import load_model_parameters, load_scenarios, value
from cofas_twin.data import cofas_adapter, synthetic_adapter
from cofas_twin.model.balance import snapshot
from cofas_twin.model.estimation import estimate_all
from cofas_twin.model.metrics import compare
from cofas_twin.model.montecarlo import project
from cofas_twin.model.reconstruction import remove_duplicates
from cofas_twin.model.scenarios import complete

ADAPTERS = {
    "sintetico": synthetic_adapter.load_tables,
    "cofas": cofas_adapter.load_tables,
}


def run(source="sintetico", origin=None, names=None, model_params=None):
    """Devuelve {"origen", "resultados": {nombre: project(...)}, "comparacion": DataFrame}."""
    model_params = model_params or load_model_parameters()
    scenarios = load_scenarios()
    names = list(names) if names else list(scenarios)
    unknown = [n for n in names if n not in scenarios]
    if unknown:
        raise ValueError(
            f"Escenarios desconocidos: {unknown}. Disponibles: {list(scenarios)}"
        )

    tables = ADAPTERS[source]()
    events = remove_duplicates(
        tables["eventos_cubeta"],
        value(model_params, "limpieza", "ventana_duplicados_s"),
    )
    bucket_ids = tables["cubetas"]["cubeta_id"]
    estimates = estimate_all(tables, model_params)

    origin = pd.Timestamp(origin) if origin else events["timestamp"].max().floor("h")
    current = snapshot(
        events, bucket_ids, origin
    )  # una vez, sirve para todos los escenarios

    results = {}
    for name in names:
        levers = complete(scenarios[name]["palancas"])  # valida nombres y rangos
        results[name] = project(
            events,
            bucket_ids,
            estimates,
            model_params,
            origin=origin,
            scenario=levers,
            current=current,
        )
    return {
        "origen": origin,
        "resultados": results,
        "comparacion": compare(results),
        "descripciones": {n: scenarios[n]["descripcion"] for n in names},
    }


def print_report(out, model_params):
    """Muestra por pantalla la banda de cada escenario y la comparativa."""
    threshold = value(model_params, "alerta", "umbral_cubetas")
    first = next(iter(out["resultados"]))
    first_result = out["resultados"][first]
    print(
        f"\nOrigen de la proyeccion: {out['origen']}   stock disponible ahora: {first_result['stock_inicial']:,}"
    )
    print(f"Umbral de alerta: {threshold:,} cubetas\n")

    for name, result in out["resultados"].items():
        print(f"[{name}] {out['descripciones'][name]}")
        table = result["resumen"].iloc[5::6][
            ["p10", "mediana", "p90", "prob_bajo_umbral"]
        ]
        print(
            table.round(
                {"p10": 0, "mediana": 0, "p90": 0, "prob_bajo_umbral": 2}
            ).to_string()
        )
        print()

    pd.set_option("display.width", 200)
    print("Comparativa de riesgo en el horizonte:")
    print(out["comparacion"].round(2).to_string())


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Gemelo digital de cubetas: proyeccion y escenarios"
    )
    parser.add_argument("--fuente", choices=sorted(ADAPTERS), default="sintetico")
    parser.add_argument(
        "--origen",
        help='instante de partida, por ejemplo "2026-06-23 05:00" (por defecto, el final del historico)',
    )
    parser.add_argument(
        "--escenarios",
        nargs="+",
        help="nombres de config/escenarios.yaml (por defecto, todos)",
    )
    args = parser.parse_args(argv)

    model_params = load_model_parameters()
    out = run(args.fuente, args.origen, args.escenarios, model_params)
    print_report(out, model_params)


if __name__ == "__main__":
    sys.exit(main())
