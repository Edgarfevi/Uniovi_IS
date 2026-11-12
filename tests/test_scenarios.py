import numpy as np
import pytest

from cofas_twin.model.scenarios import NEUTRAL, complete, shape_day, shape_outflow


def test_empty_scenario_is_neutral():
    assert complete({}) == NEUTRAL
    assert complete(None) == NEUTRAL


def test_neutral_scenario_changes_nothing():
    outflow = np.arange(24, dtype=float)
    assert np.array_equal(shape_outflow(outflow, {}), outflow)
    assert np.array_equal(shape_day(outflow, {}), outflow)


@pytest.mark.parametrize(
    "bad",
    [
        {"palanca_que_no_existe": 1},
        {"outflow_scale": -1},
        {"stay_scale": 0},
        {"alternative_fraction": 1.5},
        {"wave_fraction": -0.1},
        {"wave_window": (13, 11)},
        {"wave_window": (0, 25)},
        {"max_outflow_per_hour": -5},
        {"retained_cubetas": -1},
    ],
)
def test_invalid_levers_are_rejected(bad):
    with pytest.raises(ValueError):
        complete(bad)


def test_outflow_scale_and_alternative_multiply():
    out = shape_outflow(
        np.full(5, 100.0), {"outflow_scale": 2.0, "alternative_fraction": 0.25}
    )
    assert np.allclose(out, 150.0)


def test_cap_delays_demand_but_does_not_lose_it():
    demand = np.array([500.0, 500.0, 0.0, 0.0, 0.0, 0.0])
    served = shape_outflow(demand, {"max_outflow_per_hour": 250})
    assert served.max() <= 250
    assert served.sum() == pytest.approx(
        demand.sum()
    )  # lo que sobra pasa a las horas siguientes


def test_wave_keeps_the_daily_total_and_concentrates_in_the_window():
    day = np.full(24, 10.0)
    shaped = shape_day(day, {"wave_fraction": 0.6, "wave_window": (11, 13)})
    assert shaped.sum() == pytest.approx(day.sum())
    assert shaped[11] > day[11] and shaped[12] > day[12]
    assert shaped[5] < day[5]
