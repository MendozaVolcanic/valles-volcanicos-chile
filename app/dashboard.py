"""
dashboard.py
------------
Dashboard Streamlit para visualización de valles volcánicos.
Optimizado para pantalla de monitoreo 43" (1920x1080+), modo oscuro.

Capas:
  - Volcanes (marcadores con ícono)
  - Cuencas hidrográficas (polígonos translúcidos por volcán)
  - Red de drenaje / quebradas (líneas con nombre)
  - Población (manzanas censales coloreadas por densidad)
"""

import streamlit as st
import geopandas as gpd
import pandas as pd
import folium
from streamlit_folium import st_folium
import yaml
from pathlib import Path
import json

# ---------------------------------------------------------------------------
# Configuración de página (modo oscuro, full width)
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Valles Volcánicos — OVDAS",
    page_icon="🌋",
    layout="wide",
    initial_sidebar_state="expanded",
)

# CSS: fondo oscuro optimizado para sala de monitoreo
st.markdown("""
<style>
    .stApp { background-color: #0e1117; color: #e0e0e0; }
    .stSidebar { background-color: #161b22; }
    h1, h2, h3 { color: #ff6b35; }
    .metric-card {
        background: #1e2530;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 12px;
        margin: 4px 0;
    }
    .volcano-name { font-size: 1.4em; font-weight: bold; color: #ff6b35; }
    .stSelectbox label { color: #e0e0e0; font-size: 1.1em; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Carga de datos
# ---------------------------------------------------------------------------

PROCESSED = Path("data/processed")
CONFIG_PATH = Path("config/volcanoes.yaml")


@st.cache_data
def cargar_config():
    return yaml.safe_load(open(CONFIG_PATH))


@st.cache_data
def cargar_cuencas():
    p = PROCESSED / "cuencas.gpkg"
    if not p.exists():
        return None, None
    cuencas = gpd.read_file(p, layer="cuencas")
    try:
        drenajes = gpd.read_file(p, layer="drenajes")
    except Exception:
        drenajes = None
    return cuencas, drenajes


@st.cache_data
def cargar_poblacion():
    p = PROCESSED / "resumen_poblacion.csv"
    if p.exists():
        return pd.read_csv(p)
    return None


@st.cache_data
def cargar_manzanas():
    p = PROCESSED / "poblacion_cuencas.gpkg"
    if p.exists():
        return gpd.read_file(p)
    return None


config = cargar_config()
VOLCANES = config["volcanes"]
cuencas_gdf, drenajes_gdf = cargar_cuencas()
poblacion_df = cargar_poblacion()


# ---------------------------------------------------------------------------
# Sidebar: controles
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## 🌋 Valles Volcánicos")
    st.markdown("**OVDAS — SERNAGEOMIN**")
    st.divider()

    # Selector de volcán
    nombres = ["(Todos los volcanes)"] + [v["nombre"] for v in VOLCANES]
    seleccion = st.selectbox("Volcán", nombres, index=0)

    st.divider()

    # Capas visibles
    st.markdown("**Capas**")
    mostrar_cuencas = st.checkbox("Cuencas hidrográficas", value=True)
    mostrar_drenajes = st.checkbox("Red de drenaje / quebradas", value=True)
    mostrar_poblacion = st.checkbox("Población (manzanas censales)", value=False)
    mostrar_volcanes = st.checkbox("Volcanes", value=True)

    st.divider()

    # Opacidad
    opacidad_cuenca = st.slider("Opacidad cuencas", 0.1, 0.8, 0.3)

    st.divider()
    st.caption("Fuentes: SERNAGEOMIN · OSM · INE Censo 2024")


# ---------------------------------------------------------------------------
# Panel principal
# ---------------------------------------------------------------------------

# Título
volcán_activo = None if seleccion == "(Todos los volcanes)" else next(
    (v for v in VOLCANES if v["nombre"] == seleccion), None
)

if volcán_activo:
    st.markdown(f"### 🌋 {volcán_activo['nombre']}")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Región", volcán_activo.get("region", "—"))
    col2.metric("Elevación", f"{volcán_activo.get('elevacion', 0):,} m")
    col3.metric("Latitud", f"{volcán_activo['lat']:.4f}°")
    col4.metric("Longitud", f"{volcán_activo['lon']:.4f}°")

    # Población en cuenca si disponible
    if poblacion_df is not None and "volcan_codigo" in poblacion_df.columns:
        row = poblacion_df[poblacion_df["volcan_codigo"] == volcán_activo["codigo"]]
        if not row.empty:
            pob = row.iloc[0]["poblacion_cuenca"]
            st.metric("Población en cuenca", f"{int(pob):,} hab.", help="Censo 2024, manzanas dentro de la cuenca")
else:
    st.markdown("### 🌋 Todos los volcanes monitoreados")
    col1, col2 = st.columns(2)
    col1.metric("Volcanes activos", len(VOLCANES))
    if cuencas_gdf is not None:
        col2.metric("Cuencas procesadas", len(cuencas_gdf))

# ---------------------------------------------------------------------------
# Mapa
# ---------------------------------------------------------------------------

# Centro del mapa
if volcán_activo:
    center = [volcán_activo["lat"], volcán_activo["lon"]]
    zoom = 10
else:
    center = [-35.0, -70.5]  # centro de Chile
    zoom = 5

# Fondo oscuro para sala de monitoreo
m = folium.Map(
    location=center,
    zoom_start=zoom,
    tiles="CartoDB dark_matter",
    prefer_canvas=True,
)

# Colores por región (para distinguir volcanes)
REGION_COLORS = {
    "Arica y Parinacota": "#ff6b6b",
    "Tarapacá": "#ffa36b",
    "Antofagasta": "#ffd36b",
    "Atacama": "#b8ff6b",
    "Biobío": "#6bffb8",
    "La Araucanía": "#6bdbff",
    "Los Ríos": "#6b9fff",
    "Los Lagos": "#c46bff",
    "Aysén": "#ff6bdb",
}

# Capa: cuencas
if mostrar_cuencas and cuencas_gdf is not None:
    filtro = cuencas_gdf if not volcán_activo else cuencas_gdf[
        cuencas_gdf["volcan_codigo"] == volcán_activo["codigo"]
    ]
    for _, row in filtro.iterrows():
        color = REGION_COLORS.get(row.get("region", ""), "#6bffb8")
        folium.GeoJson(
            row.geometry.__geo_interface__,
            style_function=lambda f, c=color, op=opacidad_cuenca: {
                "fillColor": c,
                "color": c,
                "weight": 1.5,
                "fillOpacity": op,
            },
            tooltip=f"<b>{row['volcan_nombre']}</b><br>Cuenca hidrográfica",
        ).add_to(m)

# Capa: drenajes / quebradas
if mostrar_drenajes and drenajes_gdf is not None:
    filtro_d = drenajes_gdf if not volcán_activo else drenajes_gdf[
        drenajes_gdf["volcan_codigo"] == volcán_activo["codigo"]
    ]
    for _, row in filtro_d.iterrows():
        nombre_q = row.get("nombre", "Sin nombre")
        tipo = row.get("tipo", "stream")
        color_d = "#4fc3f7" if tipo == "river" else "#81d4fa"
        weight = 2.5 if tipo == "river" else 1.5
        folium.GeoJson(
            row.geometry.__geo_interface__,
            style_function=lambda f, c=color_d, w=weight: {
                "color": c,
                "weight": w,
                "opacity": 0.9,
            },
            tooltip=f"<b>{nombre_q}</b><br>{tipo}",
        ).add_to(m)

# Capa: volcanes
if mostrar_volcanes:
    volcanes_a_mostrar = [volcán_activo] if volcán_activo else VOLCANES
    for v in volcanes_a_mostrar:
        color = REGION_COLORS.get(v.get("region", ""), "#ff6b35")
        popup_html = f"""
        <div style='font-family: monospace; min-width: 180px;'>
        <b style='color: #ff6b35; font-size: 1.1em;'>{v['nombre']}</b><br>
        Región: {v.get('region', '—')}<br>
        Elevación: {v.get('elevacion', '—')} m<br>
        Coord: {v['lat']:.4f}, {v['lon']:.4f}<br>
        Código: {v['codigo']}
        </div>
        """
        folium.CircleMarker(
            location=[v["lat"], v["lon"]],
            radius=10,
            color="#ff6b35",
            fill=True,
            fill_color=color,
            fill_opacity=0.9,
            popup=folium.Popup(popup_html, max_width=220),
            tooltip=f"🌋 {v['nombre']} ({v.get('elevacion', '?')} m)",
        ).add_to(m)

# Render del mapa
map_height = 750  # px — para pantalla 43"
st_folium(m, width=None, height=map_height, returned_objects=[])

# ---------------------------------------------------------------------------
# Tabla resumen (bajo el mapa)
# ---------------------------------------------------------------------------

if volcán_activo and drenajes_gdf is not None:
    st.divider()
    st.markdown("#### Quebradas / Valles identificados")
    drenajes_v = drenajes_gdf[drenajes_gdf["volcan_codigo"] == volcán_activo["codigo"]]
    if len(drenajes_v) > 0:
        nombres_unicos = drenajes_v[drenajes_v["nombre"] != "Sin nombre"]["nombre"].unique()
        if len(nombres_unicos) > 0:
            df_show = pd.DataFrame({
                "Nombre": nombres_unicos,
                "Tipo": [drenajes_v[drenajes_v["nombre"] == n]["tipo"].iloc[0] for n in nombres_unicos],
            })
            st.dataframe(df_show, use_container_width=True, hide_index=True)
        else:
            st.info("No se encontraron nombres de quebradas en esta área (fuente: OSM). Considera agregar nombres manualmente.")
    else:
        st.info("Sin datos de drenaje procesados para este volcán. Ejecuta los scripts de procesamiento.")

elif not volcán_activo and poblacion_df is not None:
    st.divider()
    st.markdown("#### Población por cuenca volcánica")
    st.dataframe(
        poblacion_df.sort_values("poblacion_cuenca", ascending=False),
        use_container_width=True,
        hide_index=True,
    )
