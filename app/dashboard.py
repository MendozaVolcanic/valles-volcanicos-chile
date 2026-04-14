"""
dashboard.py - Valles Volcanicos OVDAS
Pantalla 43", modo oscuro, fondo satelital, etiquetas de quebradas.
Sin dependencias nativas (no geopandas/pyogrio/shapely/pyproj).
"""

import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import yaml, json, math
from pathlib import Path

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
# Rutas — absolutas para funcionar local y en Streamlit Cloud
# ---------------------------------------------------------------------------

ROOT      = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
CONFIG_PATH = ROOT / "config" / "volcanoes.yaml"

# ---------------------------------------------------------------------------
# Funciones puras (sin librerias nativas)
# ---------------------------------------------------------------------------

def latlon_a_utm(lat, lon):
    """Convierte lat/lon WGS84 a coordenadas UTM. Implementacion pura Python."""
    zone = int((lon + 180) / 6) + 1
    lon_rad = math.radians(lon)
    lat_rad = math.radians(lat)
    a  = 6378137.0
    f  = 1 / 298.257223563
    b  = a * (1 - f)
    e2 = 1 - (b / a) ** 2
    e  = math.sqrt(e2)
    lon0 = math.radians((zone - 1) * 6 - 180 + 3)
    N = a / math.sqrt(1 - e2 * math.sin(lat_rad) ** 2)
    T = math.tan(lat_rad) ** 2
    C = e2 / (1 - e2) * math.cos(lat_rad) ** 2
    A = math.cos(lat_rad) * (lon_rad - lon0)
    M = a * (
        (1 - e2/4 - 3*e2**2/64 - 5*e2**3/256) * lat_rad
        - (3*e2/8 + 3*e2**2/32 + 45*e2**3/1024) * math.sin(2*lat_rad)
        + (15*e2**2/256 + 45*e2**3/1024) * math.sin(4*lat_rad)
        - (35*e2**3/3072) * math.sin(6*lat_rad)
    )
    easting = 500000 + 0.9996 * N * (
        A + (1-T+C)*A**3/6
        + (5-18*T+T**2+72*C-58*(e2/(1-e2)))*A**5/120
    )
    northing = (0 if lat >= 0 else 10000000) + 0.9996 * (
        M + N * math.tan(lat_rad) * (
            A**2/2
            + (5-T+9*C+4*C**2)*A**4/24
            + (61-58*T+T**2+600*C-330*(e2/(1-e2)))*A**6/720
        )
    )
    return easting, northing, zone

def midpoint_geojson(feature):
    """Punto medio aproximado de un feature LineString/MultiLineString."""
    try:
        geom = feature["geometry"]
        coords = geom["coordinates"]
        if geom["type"] == "MultiLineString":
            coords = coords[0]
        mid = coords[len(coords) // 2]
        return mid[1], mid[0]   # lat, lon
    except (KeyError, IndexError, TypeError):
        return None

# ---------------------------------------------------------------------------
# Carga de datos (JSON puro, sin geopandas)
# ---------------------------------------------------------------------------

@st.cache_data
def cargar_config():
    with open(str(CONFIG_PATH), encoding="utf-8") as f:
        return yaml.safe_load(f)

@st.cache_data
def cargar_cuencas():
    p = PROCESSED / "cuencas.geojson"
    if not p.exists():
        return None
    with open(str(p), encoding="utf-8") as f:
        return json.load(f)

@st.cache_data
def cargar_drenajes(codigo):
    p = PROCESSED / "drenajes" / f"{codigo}.geojson"
    if not p.exists():
        return None
    with open(str(p), encoding="utf-8") as f:
        return json.load(f)

@st.cache_data
def cargar_poblacion():
    p = PROCESSED / "resumen_poblacion.csv"
    return pd.read_csv(str(p)) if p.exists() else None

try:
    config   = cargar_config()
    VOLCANES = config["volcanes"]
except Exception as e:
    st.error(f"Error cargando volcanoes.yaml: {e}  |  Ruta: {CONFIG_PATH}")
    st.stop()

try:
    cuencas_gj = cargar_cuencas()
except Exception as e:
    st.error(f"Error cargando cuencas.geojson: {e}")
    st.stop()

poblacion_df = cargar_poblacion()

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

    drenajes_gj = cargar_drenajes(volcan["codigo"])
    if drenajes_gj:
        feats    = drenajes_gj.get("features", [])
        nombrados = [f for f in feats if f["properties"].get("nombre", "Sin nombre") != "Sin nombre"]
        n_nombres = len({f["properties"]["nombre"] for f in nombrados})
        c6, c7 = st.columns(2)
        c6.metric("Tramos de drenaje",     f"{len(feats):,}")
        c7.metric("Quebradas con nombre",  f"{n_nombres:,}")
    else:
        drenajes_gj = None
else:
    st.markdown("### Todos los volcanes monitoreados")
    c1, c2 = st.columns(2)
    c1.metric("Volcanes activos", len(VOLCANES))
    if cuencas_gj:
        c2.metric("Cuencas procesadas", len(cuencas_gj.get("features", [])))
    drenajes_gj = None

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

m = folium.Map(
    location=center,
    zoom_start=zoom,
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr="Esri World Imagery",
    name="Satelital",
    prefer_canvas=True,
)

folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
    attr="Esri",
    name="Rotulos",
    overlay=True,
    control=True,
    opacity=0.7,
).add_to(m)

# Zona de influencia
if mostrar_cuencas and cuencas_gj:
    if volcan:
        filtro_c = {
            "type": "FeatureCollection",
            "features": [
                f for f in cuencas_gj["features"]
                if f["properties"].get("volcan_codigo") == volcan["codigo"]
            ],
        }
    else:
        filtro_c = cuencas_gj

    if filtro_c["features"]:
        folium.GeoJson(
            filtro_c,
            name="Zona de influencia",
            style_function=lambda f, op=opacidad: {
                "fillColor": REGION_COLORS.get(f["properties"].get("region", ""), "#6bffb8"),
                "color":       "#ffffff",
                "weight":      1.5,
                "fillOpacity": op,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["volcan_nombre", "region", "elevacion"],
                aliases=["Volcan", "Region", "Elevacion (m)"],
            ),
        ).add_to(m)

# Quebradas / rios
if mostrar_drenajes and drenajes_gj and drenajes_gj.get("features"):
    folium.GeoJson(
        drenajes_gj,
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

    # Etiquetas (solo vista por volcan)
    if mostrar_nombres and volcan:
        feats = drenajes_gj.get("features", [])
        nombrados = [f for f in feats if f["properties"].get("nombre", "Sin nombre") != "Sin nombre"]
        vistos = set()
        for feat in nombrados:
            nombre_q = feat["properties"]["nombre"]
            if nombre_q in vistos:
                continue
            vistos.add(nombre_q)
            mid = midpoint_geojson(feat)
            if mid is None:
                continue
            es_rio = feat["properties"].get("tipo") == "river"
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

if volcan and drenajes_gj:
    st.divider()
    feats     = drenajes_gj.get("features", [])
    nombrados = [f for f in feats if f["properties"].get("nombre", "Sin nombre") != "Sin nombre"]

    col_t, col_dl = st.columns([3, 1])
    col_t.markdown("#### Quebradas y rios identificados")

    if nombrados:
        from collections import defaultdict
        grupos = defaultdict(lambda: {"tipo": "", "tramos": 0})
        for f in nombrados:
            p = f["properties"]
            nombre = p.get("nombre", "")
            grupos[nombre]["tipo"]   = p.get("tipo", "")
            grupos[nombre]["tramos"] += 1

        resumen = pd.DataFrame([
            {"Nombre": k, "Tipo": v["tipo"], "Tramos OSM": v["tramos"]}
            for k, v in grupos.items()
        ]).sort_values(["Tipo", "Nombre"])

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
