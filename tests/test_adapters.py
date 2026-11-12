import pandas as pd
import pytest

from cofas_twin.data import cofas_adapter, synthetic_adapter
from cofas_twin.scheme import SCHEMA


def test_synthetic_adapter_returns_the_six_tables(small_params, tmp_path):
    from cofas_twin.generation.export import OBSERVED_FOLDER
    from cofas_twin.generation.generate_history import generate_history

    tables = generate_history(small_params, output_dir=tmp_path)["observado"]
    loaded = synthetic_adapter.load_tables(tmp_path / OBSERVED_FOLDER)
    assert set(loaded) == set(SCHEMA)
    assert len(loaded["eventos_cubeta"]) == len(tables["eventos_cubeta"])


def test_cofas_adapter_without_data_explains_what_to_do(tmp_path):
    with pytest.raises(FileNotFoundError, match="COLUMN_MAP"):
        cofas_adapter.load_tables(tmp_path / "no_existe")


def test_cofas_adapter_maps_names_and_events(observed, tmp_path):
    """Si COFAS usa otros nombres de columna y de evento, los mapas los traducen al esquema."""
    renames = {
        "eventos_cubeta": {
            "cubeta_id": "id_cubeta",
            "tipo_evento": "evento",
            "timestamp": "fecha",
        }
    }
    events_to_cofas = {"RECOGIDA_VACIA": "RECOGIDA", "DISPONIBLE": "DISP"}
    for name, df in observed.items():
        out = df.rename(columns=renames.get(name, {})).copy()
        if name == "eventos_cubeta":
            out["evento"] = out["evento"].replace(events_to_cofas)
        out.to_csv(tmp_path / f"{name}.csv", index=False)

    back = cofas_adapter.load_tables(
        tmp_path,
        column_map={
            "eventos_cubeta": {v: k for k, v in renames["eventos_cubeta"].items()}
        },
        event_map={v: k for k, v in events_to_cofas.items()},
    )
    original = observed["eventos_cubeta"].reset_index(drop=True)
    restored = back["eventos_cubeta"].reset_index(drop=True)
    assert (
        original["tipo_evento"].astype(str) == restored["tipo_evento"].astype(str)
    ).all()
    assert (
        original["cubeta_id"].astype("Int64") == restored["cubeta_id"].astype("Int64")
    ).all()
    assert set(back) == set(SCHEMA)


def test_cofas_adapter_reports_missing_columns(observed, tmp_path):
    for name, df in observed.items():
        df.to_csv(tmp_path / f"{name}.csv", index=False)
    broken = pd.read_csv(tmp_path / "pedidos.csv").drop(columns=["n_cubetas"])
    broken.to_csv(tmp_path / "pedidos.csv", index=False)
    with pytest.raises(ValueError, match="n_cubetas"):
        cofas_adapter.load_tables(tmp_path)
