import copy

import pytest

from cofas_twin.config import (
    load_model_parameters,
    load_parameters,
    load_scenarios,
    load_validation_parameters,
    states_summary,
    value,
)
from cofas_twin.model.scenarios import complete


def test_all_yaml_files_load():
    assert load_parameters()
    assert load_model_parameters()
    assert load_validation_parameters()
    assert load_scenarios()


def test_value_returns_plain_value_or_value_field():
    params = load_parameters()
    assert value(params, "general", "semilla") == params["general"]["semilla"]
    assert (
        value(params, "maestros", "n_cubetas")
        == params["maestros"]["n_cubetas"]["valor"]
    )


def test_value_missing_parameter_raises():
    with pytest.raises(KeyError):
        value(load_parameters(), "general", "no_existe")


def test_invalid_state_is_rejected(tmp_path):
    import yaml

    params = copy.deepcopy(load_model_parameters())
    params["alerta"]["umbral_cubetas"]["estado"] = "inventado"
    path = tmp_path / "modelo.yaml"
    path.write_text(yaml.safe_dump(params), encoding="utf-8")
    with pytest.raises(ValueError):
        load_model_parameters(path)


def test_every_declared_state_is_valid():
    allowed = {"dato", "dato_derivado", "dato_con_rango", "supuesto", "desconocido"}
    for params in (load_parameters(), load_model_parameters()):
        assert {state for _, state, _ in states_summary(params)} <= allowed


def test_every_scenario_in_the_yaml_is_valid():
    for name, scenario in load_scenarios().items():
        complete(
            scenario["palancas"]
        )  # lanza si hay una palanca desconocida o fuera de rango
        assert scenario.get("descripcion"), f"el escenario {name} no tiene descripcion"
