"""Dashboard del gemelo digital de cubetas.

Uso (desde la raiz del proyecto, con el venv activo):

    streamlit run dashboard/app.py

Muestra la proyeccion del stock de cubetas disponibles (mediana y banda p10 a p90),
la probabilidad de bajar del umbral y la comparacion entre escenarios. Se pueden
elegir los escenarios de config/escenarios.yaml y probar uno propio con las palancas.

Los datos entran por el adaptador, igual que en run_twin.py: sintetico o COFAS.
"""

import copy
import json

import altair as alt
import pandas as pd
import streamlit as st

from cofas_twin.config import (
    load_model_parameters,
    load_scenarios,
    states_summary,
    value,
)
from cofas_twin.data import cofas_adapter, synthetic_adapter
from cofas_twin.model.estimation import estimate_all
from cofas_twin.model.montecarlo import project
from cofas_twin.model.reconstruction import remove_duplicates
from cofas_twin.model.scenarios import complete

ADAPTERS = {
    "sintetico": synthetic_adapter.load_tables,
    "cofas": cofas_adapter.load_tables,
}
CUSTOM = "escenario_propio"

st.set_page_config(page_title="Gemelo digital de cubetas", layout="wide")


@st.cache_resource(show_spinner="Cargando datos y estimando el modelo...")
def load_bundle(source):
    """Lee los datos y estima una sola vez por fuente."""
    model_params = load_model_parameters()
    tables = ADAPTERS[source]()
    events = remove_duplicates(
        tables["eventos_cubeta"],
        value(model_params, "limpieza", "ventana_duplicados_s"),
    )
    return {
        "model_params": model_params,
        "events": events,
        "bucket_ids": tables["cubetas"]["cubeta_id"],
        "estimates": estimate_all(tables, model_params),
    }


@st.cache_data(show_spinner=False)
def run_scenario(source, origin_iso, levers_json, n_sim):
    """Proyecta un escenario. Se guarda el resultado: repetir los mismos ajustes es instantaneo."""
    bundle = load_bundle(source)
    params = copy.deepcopy(bundle["model_params"])
    params["proyeccion"]["n_simulaciones"]["valor"] = n_sim
    result = project(
        bundle["events"],
        bundle["bucket_ids"],
        bundle["estimates"],
        params,
        origin=pd.Timestamp(origin_iso),
        scenario=complete(json.loads(levers_json)),
    )
    return {
        "resumen": result["resumen"],
        "metricas": result["metricas"],
        "stock_inicial": result["stock_inicial"],
    }


def sidebar_custom_scenario():
    """Controles de un escenario propio. Devuelve sus palancas (solo las que se tocan)."""
    st.sidebar.markdown("**Palancas del escenario propio**")
    levers = {}
    scale = st.sidebar.slider(
        "Volumen de pedidos (x)",
        0.5,
        2.5,
        1.0,
        0.05,
        help="Mas de 1 es un pico de pedidos",
    )
    stay = st.sidebar.slider(
        "Tiempo en farmacia (x)",
        0.5,
        2.0,
        1.0,
        0.05,
        help="Mas de 1 son retenciones, menos de 1 es acelerar el vaciado y la devolucion",
    )
    retained = st.sidebar.number_input(
        "Cubetas retenidas",
        0,
        8000,
        0,
        100,
        help="Se restan del stock inicial y no vuelven durante la proyeccion",
    )
    alternative = st.sidebar.slider("Pedidos con otro contenedor", 0.0, 1.0, 0.0, 0.05)
    wave = st.sidebar.slider("Parte de los pedidos en la ola", 0.0, 1.0, 0.0, 0.05)
    window = st.sidebar.slider("Horas de la ola", 0, 24, (11, 13))
    cap_on = st.sidebar.checkbox("Poner tope de cubetas por hora")
    cap = st.sidebar.number_input(
        "Tope por hora", 0, 5000, 900, 50, disabled=not cap_on
    )

    levers["outflow_scale"] = scale
    levers["stay_scale"] = stay
    levers["retained_cubetas"] = int(retained)
    levers["alternative_fraction"] = alternative
    levers["wave_fraction"] = wave
    levers["wave_window"] = list(window)
    if cap_on:
        levers["max_outflow_per_hour"] = cap
    return levers


def band_chart(frames, low, high, threshold):
    """Mediana y banda de cada escenario, con el umbral y el cero marcados."""
    data = pd.concat(frames, ignore_index=True)
    color = alt.Color(
        "escenario:N",
        scale=alt.Scale(scheme="tableau10"),
        legend=alt.Legend(title="Escenario", orient="bottom"),
    )
    x = alt.X(
        "hasta:T",
        title="Hora",
        axis=alt.Axis(format="%d/%m %Hh", labelAngle=0, tickCount=8),
    )
    y_title = "Cubetas disponibles"

    band = (
        alt.Chart(data)
        .mark_area(opacity=0.15)
        .encode(x=x, y=alt.Y(f"{low}:Q", title=y_title), y2=high, color=color)
    )
    line = (
        alt.Chart(data)
        .mark_line(point=alt.OverlayMarkDef(size=30, opacity=0))
        .encode(
            x=x,
            y="mediana:Q",
            color=color,
            tooltip=[
                alt.Tooltip("escenario:N"),
                alt.Tooltip("hasta:T", title="Hora", format="%d/%m %H:%M"),
                alt.Tooltip(f"{low}:Q", title="p10", format=",.0f"),
                alt.Tooltip("mediana:Q", title="Mediana", format=",.0f"),
                alt.Tooltip(f"{high}:Q", title="p90", format=",.0f"),
            ],
        )
    )
    alert = (
        alt.Chart(
            pd.DataFrame(
                {"y": [threshold], "texto": [f"Umbral de alerta ({threshold:,})"]}
            )
        )
        .mark_rule(strokeDash=[6, 4], color="#c0392b", strokeWidth=2)
        .encode(y="y:Q", tooltip=alt.Tooltip("texto:N", title=""))
    )
    zero = (
        alt.Chart(pd.DataFrame({"y": [0], "texto": ["Quiebre (0 cubetas)"]}))
        .mark_rule(strokeDash=[2, 3], color="#555555")
        .encode(y="y:Q", tooltip=alt.Tooltip("texto:N", title=""))
    )
    return (band + line + alert + zero).properties(height=420).interactive(bind_y=False)


# ---------------------------------------------------------------- barra lateral
st.sidebar.title("Gemelo de cubetas")
source = st.sidebar.radio(
    "Fuente de datos",
    list(ADAPTERS),
    help="sintetico: generado por nosotros. cofas: datos reales",
)
try:
    bundle = load_bundle(source)
except FileNotFoundError as error:
    st.error(str(error))
    st.stop()

model_params = bundle["model_params"]
events = bundle["events"]
scenarios = load_scenarios()
low, high = (f"p{p}" for p in value(model_params, "proyeccion", "percentiles"))
threshold = value(model_params, "alerta", "umbral_cubetas")
horizon = value(model_params, "proyeccion", "horizonte_h")

last = events["timestamp"].max().floor("h")
first = events["timestamp"].min().ceil("D") + pd.Timedelta(days=14)
day = st.sidebar.date_input(
    "Dia de partida", value=last.date(), min_value=first.date(), max_value=last.date()
)
hour = st.sidebar.slider("Hora de partida", 0, 23, int(last.hour))
origin = min(pd.Timestamp(day) + pd.Timedelta(hours=hour), last)
st.sidebar.caption(
    "Al elegir un dia del pasado, el modelo ya conoce lo que paso despues porque se estima con todo el historico."
)

chosen = st.sidebar.multiselect(
    "Escenarios",
    list(scenarios),
    default=[n for n in ("base", "dia_estres") if n in scenarios],
    format_func=lambda n: n.replace("_", " "),
)
use_custom = st.sidebar.checkbox("Anadir un escenario propio")
custom_levers = sidebar_custom_scenario() if use_custom else None
n_sim = st.sidebar.select_slider(
    "Simulaciones",
    [100, 200, 500, 1000],
    value=200,
    help="Mas simulaciones dan bandas mas estables y tardan mas",
)

# ---------------------------------------------------------------- calculo
to_run = {name: scenarios[name]["palancas"] for name in chosen}
if custom_levers is not None:
    to_run[CUSTOM] = custom_levers
if not to_run:
    st.info("Elige al menos un escenario en la barra lateral.")
    st.stop()

results = {}
try:
    with st.spinner(
        f"Proyectando {len(to_run)} escenario(s) con {n_sim} simulaciones..."
    ):
        for name, levers in to_run.items():
            results[name] = run_scenario(
                source, origin.isoformat(), json.dumps(levers, sort_keys=True), n_sim
            )
except ValueError as error:
    st.error(f"Palancas no validas: {error}")
    st.stop()

# ---------------------------------------------------------------- pantalla principal
st.title("Proyeccion del ciclo de cubetas")
st.caption(
    f"Datos {source}. Partida: {origin:%d/%m/%Y %H:%M}. Horizonte: {horizon} h. "
    "El efecto de cada decision es un supuesto, no esta medido con datos de COFAS."
)

focus = st.radio(
    "Escenario para el detalle",
    list(results),
    horizontal=True,
    format_func=lambda n: n.replace("_", " "),
)
m = results[focus]["metricas"]
cols = st.columns(5)
cols[0].metric("Cubetas disponibles ahora", f"{results[focus]['stock_inicial']:,}")
cols[1].metric(f"Prob. de bajar de {threshold:,}", f"{m['prob_bajo_umbral']:.0%}")
cols[2].metric(
    "Prob. de quiebre",
    f"{m['prob_quiebre']:.0%}",
    help="Probabilidad de que el stock llegue a ser negativo: pedidos que no se pueden servir",
)
cols[3].metric(
    "Minimo esperado (mediana)",
    f"{m['minimo_p50']:,.0f}",
    help=f"Stock minimo de cada trayectoria. Rango p10 a p90: {m['minimo_p10']:,.0f} a {m['minimo_p90']:,.0f}",
)
cols[4].metric(
    "Primer cruce del umbral",
    (
        "no cruza"
        if m["primer_cruce_mediana"] is None
        else f"{m['primer_cruce_mediana']:%d/%m %H:%M}"
    ),
    help="Hora mediana a la que bajan del umbral las trayectorias que lo hacen",
)

frames = []
for name, result in results.items():
    frame = result["resumen"][[low, "mediana", high]].reset_index()
    start = pd.DataFrame(
        {
            "hasta": [origin],
            low: [result["stock_inicial"]],
            "mediana": [result["stock_inicial"]],
            high: [result["stock_inicial"]],
        }
    )
    frames.append(
        pd.concat([start, frame], ignore_index=True).assign(
            escenario=name.replace("_", " ")
        )
    )
st.altair_chart(band_chart(frames, low, high, threshold), width="stretch")
st.caption(
    "Linea: mediana. Zona sombreada: banda p10 a p90. Linea roja: umbral de alerta. Por debajo de 0 hay quiebre, no se recorta."
)

tab_compare, tab_levers, tab_states = st.tabs(
    ["Comparativa", "Palancas de cada escenario", "Dato o supuesto"]
)

with tab_compare:
    table = pd.DataFrame({name: r["metricas"] for name, r in results.items()}).T
    table["primer_cruce_mediana"] = table["primer_cruce_mediana"].map(
        lambda t: "no cruza" if t is None or pd.isna(t) else f"{t:%d/%m %H:%M}"
    )
    table = table.rename(
        columns={
            "prob_bajo_umbral": "Prob. bajo umbral",
            "prob_quiebre": "Prob. quiebre",
            "minimo_p10": "Minimo p10",
            "minimo_p50": "Minimo mediana",
            "minimo_p90": "Minimo p90",
            "primer_cruce_mediana": "Primer cruce",
            "horas_bajo_umbral": "Horas bajo umbral",
        }
    )
    st.dataframe(
        table.style.format(
            {
                "Prob. bajo umbral": "{:.0%}",
                "Prob. quiebre": "{:.0%}",
                "Minimo p10": "{:,.0f}",
                "Minimo mediana": "{:,.0f}",
                "Minimo p90": "{:,.0f}",
                "Horas bajo umbral": "{:.1f}",
            }
        ),
        width="stretch",
    )

with tab_levers:
    rows = []
    for name, levers in to_run.items():
        full = complete(levers)
        description = (
            scenarios[name]["descripcion"] if name in scenarios else "escenario propio"
        )
        rows.append(
            {
                "escenario": name,
                "descripcion": description,
                **{k: str(v) for k, v in full.items()},
            }
        )
    st.dataframe(pd.DataFrame(rows).set_index("escenario"), width="stretch")

with tab_states:
    st.write(
        "Cada parametro del modelo declara si es dato, supuesto o desconocido. "
        "Lo que no es dato se sustituye cuando COFAS aporte valores reales."
    )
    states = pd.DataFrame(
        states_summary(model_params), columns=["parametro", "estado", "fuente"]
    )
    st.dataframe(states.set_index("parametro"), width="stretch")
    scenario_states = pd.DataFrame(
        [(n, s.get("estado", ""), s.get("fuente", "")) for n, s in scenarios.items()],
        columns=["escenario", "estado", "fuente"],
    )
    st.write("Escenarios")
    st.dataframe(scenario_states.set_index("escenario"), width="stretch")
