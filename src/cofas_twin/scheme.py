"""Esquema de las seis tablas del proyecto.

Es el contrato entre el generador, los adaptadores y el modelo: cualquier
fuente de datos (sintetica o de COFAS) tiene que devolver tablas que
pasen validate_all().

Los nombres de tabla y de campo son una propuesta y se quedan en espanol
porque son datos. Cuando llegue el diagrama relacional de COFAS, se
renombran aqui y en el adaptador, y nada mas.
"""

import pandas as pd
from pandas.api import types as pdt

# Cada columna: (tipo, admite_nulos). Tipos: int, float, text, datetime
SCHEMA = {
    "farmacias": {
        "farmacia_id": ("int", False),
        "ruta_id": ("int", False),
        "zona": ("text", False),
        "tamano": ("text", False),
        "factor_demanda": ("float", False),
    },
    "rutas": {
        "ruta_id": ("int", False),
        "furgoneta_id": ("int", False),
        "hora_salida": ("int", False),
        "n_farmacias": ("int", False),
    },
    "cubetas": {
        "cubeta_id": ("int", False),
        "fecha_alta": ("datetime", False),
    },
    "pedidos": {
        "pedido_id": ("int", False),
        "farmacia_id": ("int", False),
        "fecha_hora": ("datetime", False),
        "oleada": ("int", False),
        "prioridad": ("text", False),
        "n_lineas": ("int", False),
        "n_cubetas": ("int", False),
    },
    "pedido_cubeta": {
        "pedido_id": ("int", False),
        "cubeta_id": ("int", False),
    },
    "eventos_cubeta": {
        "evento_id": ("int", False),
        # cubeta_id admite nulos para poder representar un registro por voz
        # sin ID (por ejemplo RECOGIDA_VACIA contada, no leida)
        "cubeta_id": ("int", True),
        "tipo_evento": ("text", False),
        "timestamp": ("datetime", False),
        "pedido_id": ("int", True),
        "ruta_id": ("int", True),
        # solo se rellena en FUSION: la cubeta a la que se pasa el contenido
        "cubeta_destino": ("int", True),
        "fuente_registro": ("text", False),
    },
}

KEYS = {
    "farmacias": ["farmacia_id"],
    "rutas": ["ruta_id"],
    "cubetas": ["cubeta_id"],
    "pedidos": ["pedido_id"],
    "pedido_cubeta": ["pedido_id", "cubeta_id"],
    "eventos_cubeta": ["evento_id"],
}

EVENT_TYPES = (
    "ENTRADA_ALMACEN",
    "ENTRADA_LAVADO",
    "SALIDA_LAVADO",
    "DISPONIBLE",
    "ASIGNADA_PEDIDO",
    "MUELLE",
    "SALIDA_REPARTO",
    "ENTREGA_FARMACIA",
    "RECOGIDA_VACIA",
    "CONSOLIDACION",
    "FUSION",
    "NO_LOCALIZADA",
)

RECORD_SOURCES = ("lectura", "voz", "sistema")

ALLOWED_VALUES = {
    ("eventos_cubeta", "tipo_evento"): EVENT_TYPES,
    ("eventos_cubeta", "fuente_registro"): RECORD_SOURCES,
}

_TYPE_CHECKS = {
    "int": pdt.is_integer_dtype,
    "float": pdt.is_float_dtype,
    "text": pdt.is_string_dtype,
    "datetime": pdt.is_datetime64_any_dtype,
}


def _dtype(kind, nullable):
    if kind == "int":
        return "Int64" if nullable else "int64"
    return {"float": "float64", "text": "string", "datetime": "datetime64[ns]"}[kind]


def columns(table):
    """Nombres de las columnas de una tabla, en orden."""
    return list(SCHEMA[table])


def empty_table(table):
    """DataFrame vacio con las columnas y tipos correctos."""
    return pd.DataFrame(
        {
            col: pd.Series(dtype=_dtype(kind, nullable))
            for col, (kind, nullable) in SCHEMA[table].items()
        }
    )


def validate_table(name, df):
    """Lanza ValueError si la tabla no cumple el esquema."""
    if name not in SCHEMA:
        raise KeyError(f"Tabla desconocida: {name}")
    expected = SCHEMA[name]

    missing = [c for c in expected if c not in df.columns]
    extra = [c for c in df.columns if c not in expected]
    if missing or extra:
        raise ValueError(f"Tabla '{name}': faltan columnas {missing}, sobran {extra}")

    for col, (kind, nullable) in expected.items():
        if not _TYPE_CHECKS[kind](df[col]):
            raise ValueError(
                f"Tabla '{name}', columna '{col}': tipo {df[col].dtype}, se esperaba {kind}"
            )
        if not nullable and df[col].isna().any():
            raise ValueError(
                f"Tabla '{name}', columna '{col}': tiene {int(df[col].isna().sum())} nulos y no los admite"
            )

    if df.duplicated(KEYS[name]).any():
        raise ValueError(f"Tabla '{name}': hay claves duplicadas en {KEYS[name]}")

    for (table, col), allowed in ALLOWED_VALUES.items():
        if table == name:
            unknown = set(df[col].dropna().unique()) - set(allowed)
            if unknown:
                raise ValueError(
                    f"Tabla '{name}', columna '{col}': valores no permitidos {sorted(unknown)}"
                )


def validate_all(tables):
    """Valida un diccionario {nombre: DataFrame} con las seis tablas."""
    missing = [t for t in SCHEMA if t not in tables]
    if missing:
        raise ValueError(f"Faltan tablas: {missing}")
    for name in SCHEMA:
        validate_table(name, tables[name])
