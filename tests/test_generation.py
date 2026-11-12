import copy

import numpy as np
import pandas as pd

from cofas_twin.generation.generate_history import generate_history
from cofas_twin.scheme import SCHEMA, validate_all
from cofas_twin.validation.conservation import invalid_transitions, run_conservation


def test_tables_follow_the_schema(observed, truth):
    validate_all(observed)
    validate_all(truth)
    assert set(observed) == set(SCHEMA)


def test_truth_is_perfectly_coherent(truth):
    """En los datos limpios la flota es constante, no hay transiciones imposibles y el balance cuadra."""
    result = run_conservation(truth["eventos_cubeta"], truth["cubetas"]["cubeta_id"])
    assert result["flota_constante"]
    assert result["transiciones_imposibles"] == 0
    assert result["balance_diferencia_max"] == 0


def test_observed_has_noise_but_keeps_the_fleet(observed):
    events = observed["eventos_cubeta"]
    bad, pairs = invalid_transitions(events)
    assert (
        0 < bad / pairs < 0.05
    )  # el ruido de registro rompe algunas transiciones, pero pocas


def test_observed_starts_after_the_warmup(observed, truth, small_params):
    start = pd.Timestamp(small_params["general"]["fecha_inicio"])
    assert observed["eventos_cubeta"]["timestamp"].min() >= start
    assert truth["eventos_cubeta"]["timestamp"].min() < start


def test_same_seed_gives_same_data(small_params, tmp_path):
    a = generate_history(small_params, output_dir=tmp_path / "a")["verdad"][
        "eventos_cubeta"
    ]
    b = generate_history(small_params, output_dir=tmp_path / "b")["verdad"][
        "eventos_cubeta"
    ]
    assert a.equals(b)


def test_different_seed_gives_different_data(small_params, tmp_path):
    other = copy.deepcopy(small_params)
    other["general"]["semilla"] = small_params["general"]["semilla"] + 1
    a = generate_history(small_params, output_dir=tmp_path / "a")["verdad"]["pedidos"]
    b = generate_history(other, output_dir=tmp_path / "b")["verdad"]["pedidos"]
    assert not np.array_equal(
        a["fecha_hora"].to_numpy()[:200], b["fecha_hora"].to_numpy()[:200]
    )


def test_no_sunday_orders(truth):
    orders = truth["pedidos"]
    assert (orders["fecha_hora"].dt.weekday != 6).all()  # el domingo tiene factor 0
