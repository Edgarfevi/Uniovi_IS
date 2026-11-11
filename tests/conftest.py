"""Datos pequenos compartidos por todas las pruebas.

Se genera un historico sintetico reducido (rapido) una sola vez por sesion de pytest
y en una carpeta temporal: no toca data/synthetic.
"""

import copy

import pytest

from cofas_twin.config import load_model_parameters, load_parameters
from cofas_twin.generation.generate_history import generate_history


@pytest.fixture(scope="session")
def small_params():
    """Parametros del generador reducidos: pocas farmacias, pocas cubetas, pocos dias."""
    params = copy.deepcopy(load_parameters())
    params["general"]["dias_historico"] = 45
    params["general"]["dias_calentamiento"] = 7
    params["maestros"]["n_cubetas"]["valor"] = 3000
    params["maestros"]["n_farmacias"]["valor"] = 80
    params["maestros"]["n_rutas"]["valor"] = 8
    params["demanda"]["pedidos_por_dia"]["valor"] = 250
    return params


@pytest.fixture(scope="session")
def generated(small_params, tmp_path_factory):
    """{"observado": tablas, "verdad": tablas} del historico reducido."""
    folder = tmp_path_factory.mktemp("synthetic")
    return generate_history(small_params, output_dir=folder)


@pytest.fixture(scope="session")
def observed(generated):
    return generated["observado"]


@pytest.fixture(scope="session")
def truth(generated):
    return generated["verdad"]


@pytest.fixture(scope="session")
def model_params():
    """Parametros del modelo, con pocas simulaciones y horizonte corto para que sea rapido."""
    params = copy.deepcopy(load_model_parameters())
    params["proyeccion"]["n_simulaciones"]["valor"] = 60
    params["proyeccion"]["horizonte_h"]["valor"] = 24
    return params
