"""
dashboard.py - Valles Volcanicos OVDAS
Pantalla 43", modo oscuro, fondo satelital, etiquetas de quebradas.
"""

import streamlit as st
import geopandas as gpd
import pandas as pd
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from pyproj import Transformer
import yaml, json, os
from pathlib import Path
from shapely.geometry import MultiLineString

st.set_page_config(
    page_title="Valles Volcanicos - OVDAS",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .stApp { background-color: #0e1117; color: #e0e0e0; }
    section[data-testid="stSidebar"] { background-color: #161b22; }
    h1,h2,h3,h4 { color: #ff6b35; }
    div[data-testid="metric-container"] {
        background: #1e2530; border-radius: 8px; padding: 10px;
    }
    .stSelectbox label, .stCheckbox label, .stSlider label { color: #ccc !important; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Datos
# ---------------------------------------------------------------------------

PROCESSED   = Path("data/processed")
CONFIG_PATH = Path("config/volcanoes.yaml")

@st.cache_data
def cargar_config():
    return yaml.safe_load(open(CONFIG_PATH, encoding="utf-8"))

@st.cache_data
def cargar_cuencas():
    p = PROCESSED / "cuencas.gpkg"
    if not p.exists():
        return None, None
    cuencas  = gpd.read_file(p, layer="cuencas")
    try:
        drenajes = gpd.read_file(p, layer="drenajes")
    except Exception:
        drenajes = None
    return cuencas, drenajes

@st.cache_data
def cargar_poblacion():
    p = PROCESSED / "resumen_poblacion.csv"
    return pd.read_csv(p) if p.exists() else None

# Invalidar cache si el gpkg cambio
_gpkg = PROCESSED / "cuencas.gpkg"
_mtime = str(os.path.getmtime(_gpkg)) if _gpkg.exists() else "0"
if st.session_state.get("_mtime") != _mtime:
    st.cache_data.clear()
    st.session_state["_mtime"] = _mtime

config       = cargar_config()
VOLCANES     = config["volcanes"]
cuencas_gdf, drenajes_gdf = cargar_cuencas()
poblacion_df = cargar_poblacion()

def latlon_a_utm(lat, lon):
    zone = int((lon + 180) / 6) + 1
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    t = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    e, n = t.transform(lon, lat)
    return e, n, zone

def midpoint_linestring(geom):
    """Retorna el punto medio de una geometria lineal."""
    try:
        pt = geom.interpolate(0.5, normalized=True)
        return pt.y, pt.x
    except Exception:
        return None

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## Valles Volcanicos")
    st.markdown("**OVDAS - SERNAGEOMIN**")
    st.divider()

    nombres   = ["(Todos los volcanes)"] + [v["nombre"] for v in VOLCANES]
    seleccion = st.selectbox("Volcan", nombres, index=0)

    st.divider()
    st.markdown("**Capas**")
    mostrar_cuencas  = st.checkbox("Zona de influencia", value=True)
    mostrar_drenajes = st.checkbox("Quebradas / rios", value=True)
    mostrar_nombres  = st.checkbox("Nombres de quebradas", value=True)
    mostrar_volcanes = st.checkbox("Volcan", value=True)

    st.divider()
    opacidad = st.slider("Opacidad zona influencia", 0.05, 0.6, 0.2)

    st.divider()
    st.caption("Fuentes: SERNAGEOMIN · OSM · INE")

# ---------------------------------------------------------------------------
# Panel principal
# ---------------------------------------------------------------------------

volcan = None if seleccion == "(Todos los volcanes)" else next(
    (v for v in VOLCANES if v["nombre"] == seleccion), None
)

if volcan:
    lat, lon = volcan["lat"], volcan["lon"]
    e, n, zone = latlon_a_utm(lat, lon)
    hemi = "S" if lat < 0 else "N"

    st.markdown(f"### {volcan['nombre']}")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Region",      volcan.get("region", "-"))
    c2.metric("Elevacion",   f"{volcan.get('elevacion', 0):,} m")
    c3.metric("Este (UTM)",  f"{e:,.0f} m")
    c4.metric("Norte (UTM)", f"{n:,.0f} m")
    c5.metric("Zona UTM",    f"{zone}{hemi}")

    if drenajes_gdf is not None:
        dv = drenajes_gdf[drenajes_gdf["volcan_codigo"] == volcan["codigo"]]
        nombrados = dv[dv["nombre"] != "Sin nombre"]
        c6, c7 = st.columns(2)
        c6.metric("Tramos de drenaje", f"{len(dv):,}")
        c7.metric("Quebradas con nombre", f"{nombrados['nombre'].nunique():,}")
else:
    st.markdown("### Todos los volcanes monitoreados")
    c1, c2 = st.columns(2)
    c1.metric("Volcanes activos", len(VOLCANES))
    if cuencas_gdf is not None:
        c2.metric("Cuencas procesadas", len(cuencas_gdf))

# ---------------------------------------------------------------------------
# Mapa
# ---------------------------------------------------------------------------

REGION_COLORS = {
    "Arica y Parinacota": "#ff6b6b",
    "Tarapaca":           "#ffa36b",
    "Antofagasta":        "#ffd36b",
    "Atacama":            "#b8ff6b",
    "Biobio":             "#6bffb8",
    "La Araucania":       "#6bdbff",
    "Los Rios":           "#6b9fff",
    "Los Lagos":          "#c46bff",
    "Aysen":              "#ff6bdb",
}

center = [volcan["lat"], volcan["lon"]] if volcan else [-35.0, -70.5]
zoom   = 10 if volcan else 5

# Fondo satelital ESRI (publico, sin API key)
m = folium.Map(
    location=center,
    zoom_start=zoom,
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr="Esri World Imagery",
    name="Satelital",
    prefer_canvas=True,
)

# Capa adicional: rotulo de referencia sobre satelital
folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
    attr="Esri",
    name="Rotulos",
    overlay=True,
    control=True,
    opacity=0.7,
).add_to(m)

# Zona de influencia
if mostrar_cuencas and cuencas_gdf is not None:
    filtro_c = cuencas_gdf if not volcan else cuencas_gdf[
        cuencas_gdf["volcan_codigo"] == volcan["codigo"]
    ]
    if len(filtro_c) > 0:
        folium.GeoJson(
            json.loads(filtro_c.to_json()),
            name="Zona de influencia",
            style_function=lambda f, op=opacidad: {
                "fillColor": REGION_COLORS.get(f["properties"].get("region", ""), "#6bffb8"),
                "color": "#ffffff",
                "weight": 1.5,
                "fillOpacity": op,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["volcan_nombre", "region", "elevacion"],
                aliases=["Volcan", "Region", "Elevacion (m)"],
            ),
        ).add_to(m)

# Quebradas / rios
if mostrar_drenajes and drenajes_gdf is not None:
    filtro_d = drenajes_gdf if not volcan else drenajes_gdf[
        drenajes_gdf["volcan_codigo"] == volcan["codigo"]
    ]
    if len(filtro_d) > 0:
        folium.GeoJson(
            json.loads(filtro_d.to_json()),
            name="Quebradas y rios",
            style_function=lambda f: {
                "color":   "#00aaff" if f["properties"].get("tipo") == "river" else "#66ccff",
                "weight":  2.5      if f["properties"].get("tipo") == "river" else 1.2,
                "opacity": 0.9,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["nombre", "tipo"],
                aliases=["Nombre", "Tipo"],
            ),
        ).add_to(m)

    # Etiquetas de nombres (solo cuando hay un volcan seleccionado)
    if mostrar_nombres and volcan and len(filtro_d) > 0:
        nombrados_d = filtro_d[filtro_d["nombre"] != "Sin nombre"].copy()
        # Un marcador por nombre unico (en el punto medio del primer tramo)
        vistos = set()
        for _, row in nombrados_d.iterrows():
            nombre_q = row["nombre"]
            if nombre_q in vistos:
                continue
            vistos.add(nombre_q)
            mid = midpoint_linestring(row.geometry)
            if mid is None:
                continue
            es_rio = row.get("tipo") == "river"
            folium.Marker(
                location=mid,
                icon=folium.DivIcon(
                    html=f"""<div style="
                        font-size: {'11px' if es_rio else '9px'};
                        font-weight: {'bold' if es_rio else 'normal'};
                        color: {'#ffffff' if es_rio else '#aaddff'};
                        background: rgba(0,0,0,0.55);
                        padding: 1px 4px;
                        border-radius: 3px;
                        white-space: nowrap;
                        pointer-events: none;
                    ">{nombre_q}</div>""",
                    icon_size=(len(nombre_q)*7, 18),
                    icon_anchor=(len(nombre_q)*3, 9),
                ),
            ).add_to(m)

# Marcadores de volcanes
if mostrar_volcanes:
    vlist = [volcan] if volcan else VOLCANES
    for v in vlist:
        lat_v, lon_v = v["lat"], v["lon"]
        e_v, n_v, zone_v = latlon_a_utm(lat_v, lon_v)
        hemi_v = "S" if lat_v < 0 else "N"
        color = REGION_COLORS.get(v.get("region", ""), "#ff6b35")
        popup_html = (
            f"<div style='font-family:monospace;min-width:200px'>"
            f"<b style='color:#ff6b35;font-size:1.1em'>{v['nombre']}</b><br>"
            f"Region: {v.get('region','-')}<br>"
            f"Elevacion: {v.get('elevacion','-')} m<br>"
            f"Este: {e_v:,.0f} m &nbsp; Norte: {n_v:,.0f} m<br>"
            f"Zona: {zone_v}{hemi_v}<br>"
            f"Codigo: {v['codigo']}"
            f"</div>"
        )
        folium.CircleMarker(
            location=[lat_v, lon_v],
            radius=9,
            color="#ff6b35",
            fill=True,
            fill_color=color,
            fill_opacity=0.9,
            popup=folium.Popup(popup_html, max_width=240),
            tooltip=f"{v['nombre']} ({v.get('elevacion','?')} m)",
        ).add_to(m)

folium.LayerControl(collapsed=False).add_to(m)

st_folium(m, use_container_width=True, height=730, returned_objects=[], key="mapa")

# ---------------------------------------------------------------------------
# Tabla de quebradas
# ---------------------------------------------------------------------------

if volcan and drenajes_gdf is not None:
    st.divider()
    dv = drenajes_gdf[drenajes_gdf["volcan_codigo"] == volcan["codigo"]]
    nombrados = dv[dv["nombre"] != "Sin nombre"].copy()

    col_t, col_dl = st.columns([3, 1])
    col_t.markdown("#### Quebradas y rios identificados")

    if len(nombrados) > 0:
        resumen = (
            nombrados
            .groupby("nombre")
            .agg(tipo=("tipo", "first"), tramos=("osm_id", "count"))
            .reset_index()
            .sort_values(["tipo", "nombre"])
            .rename(columns={"nombre": "Nombre", "tipo": "Tipo", "tramos": "Tramos OSM"})
        )
        csv = resumen.to_csv(index=False).encode("utf-8")
        col_dl.download_button(
            label="Descargar CSV",
            data=csv,
            file_name=f"quebradas_{volcan['codigo']}.csv",
            mime="text/csv",
        )
        st.dataframe(resumen, use_container_width=True, hide_index=True, height=380)
    else:
        st.info("Sin quebradas nombradas en OSM para este volcan.")

elif not volcan and poblacion_df is not None:
    st.divider()
    st.markdown("#### Poblacion por cuenca volcanica")
    st.dataframe(
        poblacion_df.sort_values("poblacion_cuenca", ascending=False),
        use_container_width=True, hide_index=True,
    )
