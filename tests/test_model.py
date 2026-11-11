import numpy as np
import pandas as pd
import pytest

from cofas_twin.config import value
from cofas_twin.model.estimation import estimate_all
from cofas_twin.model.montecarlo import project
from cofas_twin.model.reconstruction import remove_duplicates, state_counts


@pytest.fixture(scope="module")
def prepared(observed, model_params):
    events = remove_duplicates(
        observed["eventos_cubeta"],
        value(model_params, "limpieza", "ventana_duplicados_s"),
    )
    return {
        "events": events,
        "bucket_ids": observed["cubetas"]["cubeta_id"],
        "estimates": estimate_all(observed, model_params),
    }


def test_remove_duplicates_only_removes(observed, model_params):
    raw = observed["eventos_cubeta"]
    clean = remove_duplicates(
        raw, value(model_params, "limpieza", "ventana_duplicados_s")
    )
    assert len(clean) < len(raw)
    assert len(clean) > 0.95 * len(raw)


def test_state_counts_add_up_to_the_fleet(prepared):
    counts = state_counts(prepared["events"], prepared["bucket_ids"])
    states = [c for c in counts.columns if c != "total"]
    assert (counts[states].sum(axis=1) == len(prepared["bucket_ids"])).all()


def test_estimation_recovers_the_generator(prepared, small_params):
    """El modelo estima desde los datos, sin leer los parametros: tiene que acercarse a lo que se uso."""
    summary = prepared["estimates"]["resumen"]
    median_h = value(small_params, "ciclo", "tiempo_en_farmacia", "mediana_h")
    assert summary.loc["tiempo_en_farmacia", "mediana_h"] == pytest.approx(
        median_h, rel=0.15
    )
    wash = prepared["estimates"]["tasas"]["probabilidad_lavado"]
    assert wash == pytest.approx(
        value(small_params, "ciclo", "lavado", "probabilidad"), abs=0.05
    )


def _tuesday_morning(prepared):
    """Un martes a las 5h cerca del final del historico (los domingos no hay pedidos, y un origen ahi no distingue escenarios)."""
    last = prepared["events"]["timestamp"].max().floor("D") - pd.Timedelta(days=3)
    return last - pd.Timedelta(days=(last.weekday() - 1) % 7) + pd.Timedelta(hours=5)


def _project(prepared, model_params, scenario=None):
    return project(
        prepared["events"],
        prepared["bucket_ids"],
        prepared["estimates"],
        model_params,
        origin=_tuesday_morning(prepared),
        scenario=scenario,
    )


def test_projection_has_the_expected_shape(prepared, model_params):
    result = _project(prepared, model_params)
    n_sim = value(model_params, "proyeccion", "n_simulaciones")
    horizon = value(model_params, "proyeccion", "horizonte_h")
    assert result["trayectorias"].shape == (n_sim, horizon)
    assert len(result["resumen"]) == horizon
    assert (result["resumen"]["p10"] <= result["resumen"]["mediana"]).all()
    assert (result["resumen"]["mediana"] <= result["resumen"]["p90"]).all()


def test_projection_is_reproducible(prepared, model_params):
    a = _project(prepared, model_params)["trayectorias"]
    b = _project(prepared, model_params)["trayectorias"]
    assert np.array_equal(a, b)


def test_stock_is_not_clipped_at_zero(prepared, model_params):
    """Con muchisima demanda el stock tiene que poder ser negativo (quiebre)."""
    result = _project(
        prepared, model_params, {"outflow_scale": 3.0, "retained_cubetas": 2000}
    )
    assert result["trayectorias"].min() < 0
    assert result["metricas"]["prob_quiebre"] > 0


def test_more_demand_means_less_stock(prepared, model_params):
    base = _project(prepared, model_params)["resumen"]["mediana"]
    peak = _project(prepared, model_params, {"outflow_scale": 1.5})["resumen"][
        "mediana"
    ]
    assert peak.iloc[-1] < base.iloc[-1]


def test_alternative_container_helps(prepared, model_params):
    base = _project(prepared, model_params, {"outflow_scale": 2.0})["resumen"][
        "mediana"
    ]
    alt = _project(
        prepared, model_params, {"outflow_scale": 2.0, "alternative_fraction": 0.3}
    )["resumen"]["mediana"]
    assert alt.iloc[-1] > base.iloc[-1]


def test_retained_buckets_are_subtracted_from_the_start(prepared, model_params):
    base = _project(prepared, model_params)
    held = _project(prepared, model_params, {"retained_cubetas": 500})
    assert (
        held["stock_inicial"] == base["stock_inicial"]
    )  # el stock inicial que se muestra es el real
    assert held["resumen"]["mediana"].iloc[0] < base["resumen"]["mediana"].iloc[0] - 400
