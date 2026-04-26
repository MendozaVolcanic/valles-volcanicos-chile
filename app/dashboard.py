"""
dashboard.py - Valles Volcanicos OVDAS
Pantalla 43", modo oscuro, fondo satelital ESRI, etiquetas de quebradas.
Capas: comunas (WMS BCN Chile) + ciudades y pueblos (lista estatica OSM).
Sin dependencias nativas — funciona en cualquier Python.
"""

import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from collections import defaultdict
from pathlib import Path
import yaml, json, math, unicodedata, re


def _normalizar(s: str) -> str:
    """Normaliza texto para comparaciones robustas: minusculas, sin tildes,
    guiones/espacios colapsados a un solo separador."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    s = re.sub(r"[\s\-_]+", " ", s)
    return s

# ---------------------------------------------------------------------------
# Configuracion de pagina
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Valles Volcanicos - OVDAS",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .stApp { background-color: #0e1117; color: #e0e0e0; }
    section[data-testid="stSidebar"] { background-color: #161b22; }
    h1, h2, h3, h4 { color: #ff6b35; font-family: 'Segoe UI', sans-serif; }

    .stSelectbox label, .stCheckbox label, .stSlider label {
        color: #ccc !important;
        font-family: 'Segoe UI', sans-serif !important;
        font-size: 0.85rem !important;
    }
    div[data-testid="metric-container"] {
        background: #1e2530;
        border-radius: 8px;
        padding: 10px 14px;
        border-left: 3px solid #ff6b35;
    }
    div[data-testid="metric-container"] label {
        font-family: 'Segoe UI', sans-serif !important;
        font-size: 0.72rem !important;
        color: #999 !important;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    div[data-testid="metric-container"] [data-testid="stMetricValue"] {
        font-family: 'Courier New', monospace !important;
        font-size: 1.15rem !important;
        color: #f0f0f0 !important;
    }
    .stDataFrame { border-radius: 6px; }

    /* Badges OVDAS oficial / adicional */
    .badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 10px;
        font-size: 0.65rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        vertical-align: middle;
        margin-left: 8px;
    }
    .badge-ovdas { background: #ff6b35; color: #fff; }
    .badge-extra { background: #555; color: #ddd; }
    .badge-zona  { background: #1e2530; color: #6bdbff; border: 1px solid #6bdbff44; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Rutas absolutas (funciona local y en Streamlit Cloud)
# ---------------------------------------------------------------------------

ROOT        = Path(__file__).resolve().parent.parent
PROCESSED   = ROOT / "data" / "processed"
CONFIG_PATH = ROOT / "config" / "volcanoes.yaml"

# ---------------------------------------------------------------------------
# Datos estaticos: ciudades y pueblos de Chile (zonas volcanicas)
# Fuente: OpenStreetMap / INE. pop = poblacion aproximada.
# ---------------------------------------------------------------------------

CIUDADES = [
    # Arica y Parinacota
    {"nombre": "Arica",               "lat": -18.4783, "lon": -70.3126, "pop": 222000},
    {"nombre": "Putre",               "lat": -18.1969, "lon": -69.5644, "pop":   2500},
    # Tarapaca
    {"nombre": "Iquique",             "lat": -20.2307, "lon": -70.1357, "pop": 191000},
    {"nombre": "Colchane",            "lat": -19.2667, "lon": -68.6333, "pop":    800},
    # Antofagasta
    {"nombre": "Calama",              "lat": -22.4558, "lon": -68.9271, "pop": 165000},
    {"nombre": "San Pedro de Atacama","lat": -22.9087, "lon": -68.1997, "pop":  10000},
    {"nombre": "Antofagasta",         "lat": -23.6509, "lon": -70.3975, "pop": 402000},
    {"nombre": "Toconao",             "lat": -23.1833, "lon": -67.9833, "pop":    600},
    # Atacama
    {"nombre": "Copiapo",             "lat": -27.3668, "lon": -70.3323, "pop": 158000},
    {"nombre": "Tierra Amarilla",     "lat": -27.4931, "lon": -70.2703, "pop":  13000},
    {"nombre": "Fiambalá",            "lat": -27.7000, "lon": -67.6167, "pop":   2000},
    # Biobio
    {"nombre": "Los Angeles",         "lat": -37.4670, "lon": -72.3526, "pop": 211000},
    {"nombre": "Mulchen",             "lat": -37.7167, "lon": -72.2333, "pop":  25000},
    {"nombre": "Angol",               "lat": -37.7945, "lon": -72.7095, "pop":  54000},
    # La Araucania
    {"nombre": "Temuco",              "lat": -38.7396, "lon": -72.5900, "pop": 282000},
    {"nombre": "Curacautin",          "lat": -38.4231, "lon": -71.8832, "pop":  16000},
    {"nombre": "Lonquimay",           "lat": -38.4372, "lon": -71.5700, "pop":   7000},
    {"nombre": "Victoria",            "lat": -38.2352, "lon": -72.3394, "pop":  32000},
    {"nombre": "Villarrica",          "lat": -39.2812, "lon": -72.2232, "pop":  51000},
    {"nombre": "Pucon",               "lat": -39.2731, "lon": -71.9789, "pop":  22000},
    {"nombre": "Loncoche",            "lat": -39.3703, "lon": -72.6311, "pop":  20000},
    {"nombre": "Curarrehue",          "lat": -39.3833, "lon": -71.5500, "pop":   6000},
    {"nombre": "Licanray",            "lat": -39.4833, "lon": -72.1500, "pop":   4000},
    # Los Rios
    {"nombre": "Valdivia",            "lat": -39.8196, "lon": -73.2452, "pop": 154000},
    {"nombre": "Panguipulli",         "lat": -39.6375, "lon": -72.3356, "pop":  19000},
    {"nombre": "Conaripe",            "lat": -39.6136, "lon": -71.9875, "pop":   2000},
    {"nombre": "Futrono",             "lat": -40.1283, "lon": -72.3897, "pop":   9000},
    {"nombre": "La Union",            "lat": -40.2919, "lon": -73.0841, "pop":  40000},
    # Los Lagos
    {"nombre": "Osorno",              "lat": -40.5736, "lon": -73.1337, "pop": 145000},
    {"nombre": "Entre Lagos",         "lat": -40.6833, "lon": -72.6000, "pop":   5000},
    {"nombre": "Puerto Octay",        "lat": -40.9667, "lon": -72.9167, "pop":   5000},
    {"nombre": "Frutillar",           "lat": -41.1247, "lon": -73.0564, "pop":  16000},
    {"nombre": "Puerto Varas",        "lat": -41.3194, "lon": -72.9887, "pop":  41000},
    {"nombre": "Ensenada",            "lat": -41.2167, "lon": -72.6167, "pop":   2000},
    {"nombre": "Puerto Montt",        "lat": -41.4693, "lon": -72.9424, "pop": 245000},
    {"nombre": "Cochamo",             "lat": -41.4833, "lon": -72.3333, "pop":   1500},
    {"nombre": "Hornopiren",          "lat": -41.9167, "lon": -72.4333, "pop":   2500},
    {"nombre": "Chaiten",             "lat": -42.9167, "lon": -72.7000, "pop":   4000},
    {"nombre": "Futaleufu",           "lat": -43.1833, "lon": -71.8667, "pop":   2500},
    {"nombre": "Palena",              "lat": -43.6167, "lon": -71.8167, "pop":   2000},
    # Aysen
    {"nombre": "La Junta",            "lat": -43.9667, "lon": -72.4167, "pop":   1500},
    {"nombre": "Puyuhuapi",           "lat": -44.3333, "lon": -72.5667, "pop":    500},
    {"nombre": "Cisnes",              "lat": -44.7500, "lon": -72.6833, "pop":   1000},
    {"nombre": "Coyhaique",           "lat": -45.5752, "lon": -72.0662, "pop":  55000},
    {"nombre": "Puerto Aysen",        "lat": -45.4019, "lon": -72.6988, "pop":  16000},
    {"nombre": "Chile Chico",         "lat": -46.5333, "lon": -71.7333, "pop":   4500},
]

# ---------------------------------------------------------------------------
# Utilidades geograficas (puro Python, sin librerias nativas)
# ---------------------------------------------------------------------------

def latlon_a_utm(lat: float, lon: float) -> tuple[float, float, int]:
    """Convierte WGS84 a UTM. Formula directa Karney/USGS, precision metrica."""
    zone    = int((lon + 180) / 6) + 1
    lon_rad = math.radians(lon)
    lat_rad = math.radians(lat)
    a   = 6378137.0
    f   = 1 / 298.257223563
    e2  = 1 - (1 - f) ** 2
    lon0 = math.radians((zone - 1) * 6 - 180 + 3)
    N    = a / math.sqrt(1 - e2 * math.sin(lat_rad) ** 2)
    T    = math.tan(lat_rad) ** 2
    C    = e2 / (1 - e2) * math.cos(lat_rad) ** 2
    A    = math.cos(lat_rad) * (lon_rad - lon0)
    M    = a * (
        (1 - e2/4 - 3*e2**2/64 - 5*e2**3/256)  * lat_rad
        - (3*e2/8 + 3*e2**2/32 + 45*e2**3/1024) * math.sin(2*lat_rad)
        + (15*e2**2/256 + 45*e2**3/1024)         * math.sin(4*lat_rad)
        - (35*e2**3/3072)                         * math.sin(6*lat_rad)
    )
    easting = 500000.0 + 0.9996 * N * (
        A + (1 - T + C) * A**3 / 6
        + (5 - 18*T + T**2 + 72*C - 58*(e2/(1-e2))) * A**5 / 120
    )
    northing = (0.0 if lat >= 0 else 10_000_000.0) + 0.9996 * (
        M + N * math.tan(lat_rad) * (
            A**2 / 2
            + (5 - T + 9*C + 4*C**2) * A**4 / 24
            + (61 - 58*T + T**2 + 600*C - 330*(e2/(1-e2))) * A**6 / 720
        )
    )
    return easting, northing, zone


def midpoint_geojson(feature: dict) -> tuple[float, float] | None:
    """Coordenada media de LineString/MultiLineString para etiquetas."""
    try:
        geom   = feature["geometry"]
        coords = geom["coordinates"]
        if geom["type"] == "MultiLineString":
            coords = coords[0]
        mid = coords[len(coords) // 2]
        return mid[1], mid[0]
    except (KeyError, IndexError, TypeError):
        return None

# ---------------------------------------------------------------------------
# Carga de datos con cache
# ---------------------------------------------------------------------------

@st.cache_data
def cargar_config() -> dict:
    with open(str(CONFIG_PATH), encoding="utf-8") as f:
        return yaml.safe_load(f)


@st.cache_data
def cargar_cuencas() -> dict | None:
    p = PROCESSED / "cuencas.geojson"
    if not p.exists():
        return None
    with open(str(p), encoding="utf-8") as f:
        return json.load(f)


@st.cache_data
def cargar_drenajes(codigo: str) -> dict | None:
    """Carga lazy: solo el GeoJSON del volcan seleccionado (~200-400 KB)."""
    p = PROCESSED / "drenajes" / f"{codigo}.geojson"
    if not p.exists():
        return None
    with open(str(p), encoding="utf-8") as f:
        return json.load(f)


@st.cache_data
def cargar_peligros() -> dict | None:
    p = PROCESSED / "peligros_volcanicos.geojson"
    if not p.exists():
        return None
    with open(str(p), encoding="utf-8") as f:
        return json.load(f)


@st.cache_data
def cargar_poblacion() -> pd.DataFrame | None:
    p = PROCESSED / "resumen_poblacion.csv"
    return pd.read_csv(str(p)) if p.exists() else None


@st.cache_data
def cargar_vial() -> dict | None:
    p = PROCESSED / "red_vial.geojson"
    if not p.exists():
        return None
    with open(str(p), encoding="utf-8") as f:
        return json.load(f)


@st.cache_data
def cargar_infraestructura() -> dict | None:
    p = PROCESSED / "infraestructura.geojson"
    if not p.exists():
        return None
    with open(str(p), encoding="utf-8") as f:
        return json.load(f)


@st.cache_data
def cargar_centros_poblados() -> dict | None:
    p = PROCESSED / "centros_poblados.geojson"
    if not p.exists():
        return None
    with open(str(p), encoding="utf-8") as f:
        return json.load(f)


# Carga inicial
try:
    config   = cargar_config()
    VOLCANES = config["volcanes"]
except Exception as exc:
    st.error(f"Error cargando volcanoes.yaml: {exc}\nRuta: {CONFIG_PATH}")
    st.stop()

try:
    cuencas_gj = cargar_cuencas()
except Exception as exc:
    st.error(f"Error cargando cuencas.geojson: {exc}")
    st.stop()

peligros_gj      = cargar_peligros()
vial_gj          = cargar_vial()
infraestructura_gj = cargar_infraestructura()
centros_gj       = cargar_centros_poblados()
poblacion_df     = cargar_poblacion()

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

REGION_COLORS = {
    # Norte
    "Arica y Parinacota": "#ff6b6b",
    "Tarapaca":           "#ffa36b",
    "Antofagasta":        "#ffd36b",
    # Centro
    "Metropolitana":      "#e8ff6b",
    "O'Higgins":          "#c8ff6b",
    "Maule":              "#a8e86b",
    "Nuble":              "#aaff6b",
    # Sur
    "Biobio":             "#6bffb8",
    "La Araucania":       "#6bdbff",
    "Los Rios":           "#6b9fff",
    # Austral
    "Los Lagos":          "#c46bff",
    "Aysen":              "#ff6bdb",
}

# Zonas volcanicas OVDAS
ZONA_SHORT = {"Norte": "ZVN", "Centro": "ZVC", "Sur": "ZVS", "Austral": "ZVA"}
ZONA_LABELS = {
    "Norte":   "ZVN — Zona Norte",
    "Centro":  "ZVC — Zona Centro",
    "Sur":     "ZVS — Zona Sur",
    "Austral": "ZVA — Zona Austral",
}

def _zona_volcan(v: dict) -> str:
    """Devuelve zona desde el campo 'zona' del yaml, con fallback por latitud."""
    z = v.get("zona", "")
    if z in ZONA_SHORT:
        return z
    lat = v.get("lat", 0)
    if lat >= -28:  return "Norte"
    if lat >= -38:  return "Centro"
    if lat >= -43:  return "Sur"
    return "Austral"

def _es_ovdas(v: dict) -> bool:
    """True si el volcan es monitoreado oficialmente por OVDAS (default true)."""
    return v.get("monitoreado_ovdas", True)

# Lista ordenada N→S: zona primero, luego por latitud dentro de zona
_ZONAS_ORDEN = ["Norte", "Centro", "Sur", "Austral"]
VOLCANES_ORDENADOS = []
for _z in _ZONAS_ORDEN:
    VOLCANES_ORDENADOS.extend(
        sorted([v for v in VOLCANES if _zona_volcan(v) == _z],
               key=lambda v: v["lat"], reverse=True)
    )

# Filtros de zona y tipo (OVDAS oficial vs adicional)
ZONAS_FILTRO = ["Todas", "Norte (ZVN)", "Centro (ZVC)", "Sur (ZVS)", "Austral (ZVA)"]
_ZONA_FILTRO_MAP = {
    "Norte (ZVN)": "Norte", "Centro (ZVC)": "Centro",
    "Sur (ZVS)": "Sur", "Austral (ZVA)": "Austral",
}

# Indice global de quebradas nombradas (volcan_codigo, nombre, tipo)
@st.cache_data
def construir_indice_quebradas() -> pd.DataFrame:
    """Lista todas las quebradas nombradas de todos los volcanes (~10s primera carga)."""
    rows = []
    for v in VOLCANES:
        gj = cargar_drenajes(v["codigo"])
        if not gj:
            continue
        seen = set()
        for f in gj.get("features", []):
            n = f["properties"].get("nombre", "Sin nombre")
            if n == "Sin nombre" or n in seen:
                continue
            seen.add(n)
            rows.append({
                "quebrada": n,
                "tipo":     f["properties"].get("tipo", ""),
                "volcan":   v["nombre"],
                "codigo":   v["codigo"],
            })
    return pd.DataFrame(rows)

# ─── Permalinks: leer query params al cargar ───────────────────────────────
_qp = st.query_params
_qp_volcan    = _qp.get("volcan", "")
_qp_capas     = _qp.get("capas", "")
_qp_zona      = _qp.get("zona", "Todas")
_qp_solo_ovd  = _qp.get("ovdas", "false") == "true"
_qp_full      = _qp.get("full", "false") == "true"

with st.sidebar:
    st.markdown("## Valles Volcanicos")
    st.markdown("**OVDAS · SERNAGEOMIN**")
    st.divider()

    # Filtros de zona y tipo
    col_z1, col_z2 = st.columns([1, 1])
    zona_filtro = col_z1.selectbox(
        "Zona",
        ZONAS_FILTRO,
        index=ZONAS_FILTRO.index(_qp_zona) if _qp_zona in ZONAS_FILTRO else 0,
    )
    solo_ovdas = col_z2.toggle("Solo OVDAS", value=_qp_solo_ovd,
                                help="Mostrar solo los 43 volcanes monitoreados oficialmente por OVDAS")

    # Aplicar filtros
    _vols_filtrados = VOLCANES_ORDENADOS
    if zona_filtro != "Todas":
        _vols_filtrados = [v for v in _vols_filtrados
                           if _zona_volcan(v) == _ZONA_FILTRO_MAP[zona_filtro]]
    if solo_ovdas:
        _vols_filtrados = [v for v in _vols_filtrados if _es_ovdas(v)]

    _OPCION_TODOS = f"Todos los volcanes ({len(_vols_filtrados)})"
    _OPCIONES_VOLCAN = [_OPCION_TODOS] + [
        f"{ZONA_SHORT[_zona_volcan(v)]} · {v['nombre']}{'' if _es_ovdas(v) else ' *'}"
        for v in _vols_filtrados
    ]
    _LABEL_A_NOMBRE = {
        f"{ZONA_SHORT[_zona_volcan(v)]} · {v['nombre']}{'' if _es_ovdas(v) else ' *'}": v["nombre"]
        for v in _vols_filtrados
    }
    # Indice por defecto desde permalink
    _idx_default = 0
    if _qp_volcan:
        for i, lbl in enumerate(_OPCIONES_VOLCAN):
            if _LABEL_A_NOMBRE.get(lbl) == _qp_volcan:
                _idx_default = i
                break

    seleccion_label = st.selectbox("Volcan", _OPCIONES_VOLCAN, index=_idx_default,
                                    help="* = no monitoreado oficialmente por OVDAS")
    seleccion = (
        "(Todos los volcanes)"
        if seleccion_label == _OPCION_TODOS
        else _LABEL_A_NOMBRE.get(seleccion_label, seleccion_label)
    )

    st.divider()

    # Buscador global de quebradas (entre todos los volcanes)
    with st.expander("Buscar quebrada o rio", expanded=False):
        try:
            _idx_qb = construir_indice_quebradas()
            _q = st.text_input("Nombre o palabra clave", placeholder="ej: Pichillancahue")
            if _q and len(_q) >= 2:
                _q_norm = _normalizar(_q)
                _hits = _idx_qb[_idx_qb["quebrada"].apply(lambda x: _q_norm in _normalizar(x))]
                if len(_hits) > 0:
                    st.caption(f"{len(_hits)} coincidencias en {_hits['volcan'].nunique()} volcanes")
                    st.dataframe(_hits[["quebrada", "tipo", "volcan"]].head(30),
                                 use_container_width=True, hide_index=True, height=200)
                else:
                    st.caption("Sin coincidencias")
        except Exception as exc:
            st.caption(f"Indice no disponible: {exc}")

    st.divider()
    st.markdown("**Capas tematicas**")
    _capas_set = set(_qp_capas.split(",")) if _qp_capas else None
    def _capa_default(key, default):
        return key in _capas_set if _capas_set is not None else default
    mostrar_cuencas  = st.checkbox("Zona de influencia (50 km)", value=_capa_default("cuencas", True))
    mostrar_drenajes = st.checkbox("Quebradas y rios",           value=_capa_default("drenajes", True))
    mostrar_nombres  = st.checkbox("Nombres de quebradas",       value=_capa_default("nombres", True))
    mostrar_volcanes = st.checkbox("Marcadores de volcanes",     value=_capa_default("volcanes", True))

    st.divider()
    st.markdown("**Capas de contexto**")
    mostrar_comunas   = st.checkbox("Limites comunales",           value=_capa_default("comunas", False))
    mostrar_ciudades  = st.checkbox("Ciudades y pueblos",          value=_capa_default("ciudades", True))
    mostrar_centros   = st.checkbox("Centros poblados (poligonos)",value=_capa_default("centros", False))
    mostrar_vial      = st.checkbox("Red vial principal",          value=_capa_default("vial", False))
    mostrar_infra     = st.checkbox("Infraestructura critica",     value=_capa_default("infra", False))
    mostrar_peligros  = st.checkbox("Zonas de peligro volcanico",  value=_capa_default("peligros", False))
    mostrar_snaspe    = st.checkbox("Areas protegidas (SNASPE)",   value=_capa_default("snaspe", False),
                                     help="WMS oficial SAG/CONAF — Parques nacionales y reservas")

    st.divider()
    opacidad     = st.slider("Opacidad zona influencia", 0.05, 0.6, 0.2)
    modo_full    = st.toggle("Modo operacional (fullscreen)", value=_qp_full,
                              help="Oculta sidebar y maximiza el mapa para sala de monitoreo")

    st.divider()
    # Boton de permalink
    _capas_activas = ",".join(k for k, v in {
        "cuencas": mostrar_cuencas, "drenajes": mostrar_drenajes,
        "nombres": mostrar_nombres, "volcanes": mostrar_volcanes,
        "comunas": mostrar_comunas, "ciudades": mostrar_ciudades,
        "centros": mostrar_centros, "vial": mostrar_vial,
        "infra": mostrar_infra, "peligros": mostrar_peligros,
        "snaspe": mostrar_snaspe,
    }.items() if v)

    with st.expander("Compartir vista (permalink)"):
        _params = {
            "volcan": seleccion if seleccion != "(Todos los volcanes)" else "",
            "zona":   zona_filtro,
            "ovdas":  "true" if solo_ovdas else "false",
            "capas":  _capas_activas,
            "full":   "true" if modo_full else "false",
        }
        _qs = "&".join(f"{k}={v}" for k, v in _params.items() if v)
        st.code(f"?{_qs}", language=None)
        st.caption("Copia y pega tras la URL del dashboard")

    st.caption("Fuentes: SERNAGEOMIN · OSM · BCN · INE · CONAF/SAG")

# Aplicar permalink al state actual (escribir query params)
st.query_params.update({
    "volcan": seleccion if seleccion != "(Todos los volcanes)" else "",
    "zona":   zona_filtro,
    "ovdas":  "true" if solo_ovdas else "false",
    "capas":  _capas_activas,
    "full":   "true" if modo_full else "false",
})

# Modo operacional: ocultar sidebar via CSS
if modo_full:
    st.markdown("""
    <style>
        section[data-testid="stSidebar"] { display: none !important; }
        .main .block-container { padding-top: 1rem !important; max-width: 100% !important; }
        header[data-testid="stHeader"] { display: none !important; }
    </style>
    """, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Volcan seleccionado y datos derivados (calculados una sola vez)
# ---------------------------------------------------------------------------

volcan = None if seleccion == "(Todos los volcanes)" else next(
    (v for v in VOLCANES if v["nombre"] == seleccion), None
)

drenajes_gj    = cargar_drenajes(volcan["codigo"]) if volcan else None
feats          = drenajes_gj.get("features", []) if drenajes_gj else []
nombrados      = [f for f in feats
                  if f["properties"].get("nombre", "Sin nombre") != "Sin nombre"]
nombres_unicos = {f["properties"]["nombre"] for f in nombrados}

# ---------------------------------------------------------------------------
# Panel de metricas
# ---------------------------------------------------------------------------

if volcan:
    lat, lon   = volcan["lat"], volcan["lon"]
    e, n, zone = latlon_a_utm(lat, lon)
    hemi       = "S" if lat < 0 else "N"

    zona_volc = ZONA_LABELS.get(_zona_volcan(volcan), "-")
    badge_ovdas = (
        '<span class="badge badge-ovdas">OVDAS</span>'
        if _es_ovdas(volcan)
        else '<span class="badge badge-extra">Adicional</span>'
    )
    badge_zona = f'<span class="badge badge-zona">{ZONA_SHORT[_zona_volcan(volcan)]}</span>'
    st.markdown(
        f"### {volcan['nombre']} {badge_zona}{badge_ovdas} "
        f"&nbsp;<small style='color:#999;font-size:0.6em'>{zona_volc}</small>",
        unsafe_allow_html=True,
    )
    # Fila 1: identidad del volcan
    c1, c2, c3, c4, c5 = st.columns([1.6, 1.0, 1.6, 1.6, 0.8])
    c1.metric("Region",    volcan.get("region", "-"))
    c2.metric("Elevacion", f"{volcan.get('elevacion', 0):,} m")
    c3.metric("Este UTM",  f"{e:,.0f} m")
    c4.metric("Norte UTM", f"{n:,.0f} m")
    c5.metric("Zona",      f"{zone}{hemi}")
    # Fila 2: estadisticas de drenaje + mini-mapa Chile (contexto geografico)
    c6, c7, c_mini = st.columns([1.2, 1.6, 4.0])
    c6.metric("Tramos OSM",           f"{len(feats):,}")
    c7.metric("Quebradas con nombre", f"{len(nombres_unicos):,}")
    # Mini-mapa SVG inline: silueta de Chile con marca del volcan
    # Latitudes: -17 (norte) a -56 (austral); proyeccion lineal simple
    _lat_min, _lat_max = -56, -17
    _y = (volcan["lat"] - _lat_max) / (_lat_min - _lat_max) * 200  # 0-200 px
    _mini_svg = f"""
    <div style='background:#1e2530;border-radius:8px;padding:8px;
                border-left:3px solid #ff6b35;height:90px;display:flex;
                align-items:center;gap:12px;'>
      <svg width="22" height="220" viewBox="0 0 22 220" style='flex-shrink:0;margin:-65px 0;'>
        <rect x="9" y="0" width="4" height="220" fill="#444" rx="2"/>
        <circle cx="11" cy="{_y:.0f}" r="6" fill="#ff6b35" stroke="#fff" stroke-width="1.5"/>
        <text x="20" y="6"   fill="#666" font-size="9" font-family="monospace">17°S</text>
        <text x="20" y="220" fill="#666" font-size="9" font-family="monospace">56°S</text>
      </svg>
      <div style='font-family:monospace;font-size:0.75rem;color:#aaa;'>
        <div style='color:#ff6b35;font-weight:bold;'>{volcan['nombre']}</div>
        <div>Lat: {volcan['lat']:.2f}°S</div>
        <div>Lon: {abs(volcan['lon']):.2f}°W</div>
      </div>
    </div>
    """
    c_mini.markdown(_mini_svg, unsafe_allow_html=True)
else:
    st.markdown("### Todos los volcanes monitoreados")
    c1, c2, c3 = st.columns(3)
    _ovdas_count = sum(1 for v in VOLCANES if _es_ovdas(v))
    c1.metric("Volcanes monitoreados OVDAS", _ovdas_count)
    c2.metric("Volcanes adicionales",        len(VOLCANES) - _ovdas_count)
    c3.metric("Cuencas procesadas",          len(cuencas_gj.get("features", [])) if cuencas_gj else 0)

# ---------------------------------------------------------------------------
# Mapa Folium
# ---------------------------------------------------------------------------

center = [volcan["lat"], volcan["lon"]] if volcan else [-35.0, -70.5]
zoom   = 10 if volcan else 5

m = folium.Map(location=center, zoom_start=zoom, tiles=None, prefer_canvas=True)

# -- Base satelital ESRI --
folium.TileLayer(
    tiles=(
        "https://server.arcgisonline.com/ArcGIS/rest/services"
        "/World_Imagery/MapServer/tile/{z}/{y}/{x}"
    ),
    attr="Esri World Imagery",
    name="Satelital",
    control=True,
).add_to(m)

# -- Rotulos ESRI sobre satelital --
folium.TileLayer(
    tiles=(
        "https://server.arcgisonline.com/ArcGIS/rest/services"
        "/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}"
    ),
    attr="Esri",
    name="Rotulos",
    overlay=True,
    control=True,
    opacity=0.7,
).add_to(m)

# -- Limites comunales (WMS BCN Chile) --
# Servicio: Biblioteca del Congreso Nacional, SIIT
if mostrar_comunas:
    folium.WmsTileLayer(
        url="https://siit2.bcn.cl/mapas_geoserver/BCN/wms",
        layers="BCN:lim_comunal_2016_WGS84",
        fmt="image/png",
        transparent=True,
        name="Comunas (BCN)",
        overlay=True,
        control=True,
        opacity=0.85,
        show=True,
    ).add_to(m)

# -- SNASPE: Sistema Nacional de Areas Silvestres Protegidas (CONAF/SAG) --
if mostrar_snaspe:
    folium.WmsTileLayer(
        url="https://geoportal.sag.gob.cl/server/services/SNASPE/MapServer/WMSServer",
        layers="0",
        fmt="image/png",
        transparent=True,
        name="SNASPE (CONAF)",
        overlay=True,
        control=True,
        opacity=0.55,
        show=True,
    ).add_to(m)

# -- Zonas de peligro volcanico (SERNAGEOMIN shapefile) --
if mostrar_peligros and peligros_gj:
    PELIGRO_COLORS = {"Alto": "#cc0000", "Medio": "#ff8800", "Bajo": "#ffcc00"}
    feats_p = peligros_gj.get("features", [])
    if volcan:
        # Comparacion robusta: normalizar tildes/guiones/mayusculas
        # (peligros_volcanicos.geojson usa nombres con tildes y separadores
        # diferentes al yaml: ej. "Mocho - Choshuenco" vs "Mocho-Choshuenco")
        nv_norm = _normalizar(volcan["nombre"])
        # Tambien matchear nombre truncado: "Nevado de Longavi" → "Longavi"
        partes_v = nv_norm.split()
        feats_p = [
            f for f in feats_p
            if (lambda pn: nv_norm in pn or pn in nv_norm
                          or any(p in pn for p in partes_v if len(p) > 4))(
                _normalizar(f["properties"].get("volcan") or "")
            )
        ]
    if feats_p:
        folium.GeoJson(
            {"type": "FeatureCollection", "features": feats_p},
            name="Zonas de peligro",
            style_function=lambda f: {
                "fillColor":   PELIGRO_COLORS.get(
                                   f["properties"].get("peligro", "Bajo"), "#ffcc00"),
                "color":       PELIGRO_COLORS.get(
                                   f["properties"].get("peligro", "Bajo"), "#ffcc00"),
                "weight":      1.5,
                "fillOpacity": 0.40,
                "opacity":     0.85,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["volcan", "peligro"],
                aliases=["Volcan", "Nivel de peligro"],
            ),
        ).add_to(m)

# -- Centros poblados (poligonos OSM) --
if mostrar_centros and centros_gj:
    feats_cp = centros_gj.get("features", [])
    if volcan:
        # Filtrar por centroide del poligono (no por primer nodo)
        lat_v, lon_v = volcan["lat"], volcan["lon"]
        def _en_bbox_poly(feat, lat_c, lon_c, delta=0.6):
            if feat["geometry"]["type"] != "Polygon":
                return False
            ring = feat["geometry"]["coordinates"][0]
            if not ring:
                return False
            cx = sum(p[0] for p in ring) / len(ring)
            cy = sum(p[1] for p in ring) / len(ring)
            return abs(cy - lat_c) < delta and abs(cx - lon_c) < delta
        feats_cp = [f for f in feats_cp if _en_bbox_poly(f, lat_v, lon_v)]
    if feats_cp:
        folium.GeoJson(
            {"type": "FeatureCollection", "features": feats_cp},
            name="Centros poblados",
            style_function=lambda f: {
                "fillColor":   "#ffd166",
                "color":       "#f4a261",
                "weight":      1.2,
                "fillOpacity": 0.35,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["nombre", "tipo", "poblacion"],
                aliases=["Localidad", "Tipo", "Poblacion"],
            ),
        ).add_to(m)

# -- Red vial principal --
if mostrar_vial and vial_gj:
    VIAL_STYLE = {
        "motorway": {"color": "#e63946", "weight": 3.5, "opacity": 0.9},
        "trunk":    {"color": "#f4a261", "weight": 2.5, "opacity": 0.85},
        "primary":  {"color": "#f9c74f", "weight": 1.8, "opacity": 0.8},
    }
    feats_v = vial_gj.get("features", [])
    if volcan:
        lat_v, lon_v = volcan["lat"], volcan["lon"]
        delta = 0.6
        feats_v = [
            f for f in feats_v
            if any(
                abs(c[1] - lat_v) < delta and abs(c[0] - lon_v) < delta
                for c in f["geometry"]["coordinates"]
            )
        ]
    if feats_v:
        folium.GeoJson(
            {"type": "FeatureCollection", "features": feats_v},
            name="Red vial",
            style_function=lambda f: VIAL_STYLE.get(
                f["properties"].get("tipo", "primary"),
                {"color": "#f9c74f", "weight": 1.5, "opacity": 0.7},
            ),
            tooltip=folium.GeoJsonTooltip(
                fields=["tipo", "nombre", "ref"],
                aliases=["Tipo", "Nombre", "Ruta"],
            ),
        ).add_to(m)

# -- Infraestructura critica --
if mostrar_infra and infraestructura_gj:
    INFRA_COLORS = {
        "hospital":         "#e63946",
        "clinic":           "#ff8fa3",
        "helipuerto":       "#00b4d8",
        "represa":          "#0077b6",
        "planta_electrica": "#f9c74f",
    }
    INFRA_LABELS = {
        "hospital":         "Hospital",
        "clinic":           "Clinica",
        "helipuerto":       "Helipuerto",
        "represa":          "Represa",
        "planta_electrica": "Central electrica",
    }
    grupo_infra = folium.FeatureGroup(name="Infraestructura critica", show=True)
    feats_i = infraestructura_gj.get("features", [])
    if volcan:
        lat_v, lon_v = volcan["lat"], volcan["lon"]
        feats_i = [
            f for f in feats_i
            if abs(f["geometry"]["coordinates"][1] - lat_v) < 0.6 and
               abs(f["geometry"]["coordinates"][0] - lon_v) < 0.6
        ]
    for ft in feats_i:
        props = ft["properties"]
        tipo  = props.get("tipo", "")
        lon_i, lat_i = ft["geometry"]["coordinates"]
        color = INFRA_COLORS.get(tipo, "#aaa")
        label = INFRA_LABELS.get(tipo, tipo)
        icono = props.get("icono", "·")
        folium.CircleMarker(
            location=[lat_i, lon_i],
            radius=6,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.85,
            tooltip=f"{icono} {label}: {props.get('nombre', '')}",
            popup=folium.Popup(
                f"<b>{icono} {label}</b><br>{props.get('nombre', 'Sin nombre')}",
                max_width=200,
            ),
        ).add_to(grupo_infra)
    grupo_infra.add_to(m)

# -- Zona de influencia --
if mostrar_cuencas and cuencas_gj:
    features_c = (
        [f for f in cuencas_gj["features"]
         if f["properties"].get("volcan_codigo") == volcan["codigo"]]
        if volcan else cuencas_gj["features"]
    )
    if features_c:
        folium.GeoJson(
            {"type": "FeatureCollection", "features": features_c},
            name="Zona de influencia",
            style_function=lambda f, op=opacidad: {
                "fillColor":   REGION_COLORS.get(f["properties"].get("region", ""), "#6bffb8"),
                "color":       "#ffffff",
                "weight":      1.5,
                "fillOpacity": op,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["volcan_nombre", "region", "elevacion"],
                aliases=["Volcan", "Region", "Elevacion (m)"],
            ),
        ).add_to(m)

# -- Quebradas y rios --
if mostrar_drenajes and feats:
    folium.GeoJson(
        drenajes_gj,
        name="Quebradas y rios",
        style_function=lambda f: {
            "color":   "#00aaff" if f["properties"].get("tipo") == "river" else "#66ccff",
            "weight":  2.5       if f["properties"].get("tipo") == "river" else 1.2,
            "opacity": 0.9,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["nombre", "tipo"],
            aliases=["Nombre", "Tipo"],
        ),
    ).add_to(m)

    # Etiquetas — solo vista de un volcan
    if mostrar_nombres and volcan:
        vistos: set[str] = set()
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
                    html=(
                        f'<div style="'
                        f'font-size:{"11px" if es_rio else "9px"};'
                        f'font-weight:{"bold" if es_rio else "normal"};'
                        f'color:{"#ffffff" if es_rio else "#aaddff"};'
                        f'background:rgba(0,0,0,0.55);'
                        f'padding:1px 4px;border-radius:3px;'
                        f'white-space:nowrap;pointer-events:none;">'
                        f'{nombre_q}</div>'
                    ),
                    icon_size=(len(nombre_q) * 7, 18),
                    icon_anchor=(len(nombre_q) * 3, 9),
                ),
            ).add_to(m)

# -- Ciudades y pueblos --
if mostrar_ciudades:
    grupo_ciudades = folium.FeatureGroup(name="Ciudades y pueblos", show=True)
    for c in CIUDADES:
        # Tamaño y color segun poblacion
        if c["pop"] >= 100_000:
            radio, color_c, peso = 7, "#ffffff", 2
        elif c["pop"] >= 20_000:
            radio, color_c, peso = 5, "#eeeeee", 1.5
        else:
            radio, color_c, peso = 3, "#cccccc", 1

        folium.CircleMarker(
            location=[c["lat"], c["lon"]],
            radius=radio,
            color=color_c,
            weight=peso,
            fill=True,
            fill_color=color_c,
            fill_opacity=0.85,
            tooltip=f"{c['nombre']} ({c['pop']:,} hab.)",
            popup=folium.Popup(
                f"<b>{c['nombre']}</b><br>Poblacion: ~{c['pop']:,} hab.",
                max_width=180,
            ),
        ).add_to(grupo_ciudades)

        # Etiqueta de texto:
        # - Vista general (todos volcanes): solo ciudades >= 20k hab
        # - Vista de un volcan (zoom): todas las localidades
        mostrar_etiqueta = (volcan is not None) or (c["pop"] >= 20_000)
        if mostrar_etiqueta:
            if c["pop"] >= 100_000:
                fs, fw = "10px", "bold"
            elif c["pop"] >= 20_000:
                fs, fw = "9px", "normal"
            else:
                fs, fw = "8px", "normal"
            folium.Marker(
                location=[c["lat"], c["lon"]],
                icon=folium.DivIcon(
                    html=(
                        f'<div style="'
                        f'font-size:{fs};font-weight:{fw};'
                        f'color:#ffffff;'
                        f'text-shadow:1px 1px 2px #000,-1px -1px 2px #000;'
                        f'white-space:nowrap;pointer-events:none;'
                        f'margin-left:9px;margin-top:-4px;">'
                        f'{c["nombre"]}</div>'
                    ),
                    icon_size=(len(c["nombre"]) * 7, 16),
                    icon_anchor=(0, 8),
                ),
            ).add_to(grupo_ciudades)

    grupo_ciudades.add_to(m)

# -- Marcadores de volcanes --
if mostrar_volcanes:
    for v in ([volcan] if volcan else VOLCANES):
        lat_v, lon_v = v["lat"], v["lon"]
        e_v, n_v, zv = latlon_a_utm(lat_v, lon_v)
        hemi_v       = "S" if lat_v < 0 else "N"
        color_v      = REGION_COLORS.get(v.get("region", ""), "#ff6b35")
        popup_html   = (
            f"<div style='font-family:monospace;min-width:200px'>"
            f"<b style='color:#ff6b35;font-size:1.1em'>{v['nombre']}</b><br>"
            f"Region: {v.get('region', '-')}<br>"
            f"Elevacion: {v.get('elevacion', '-')} m<br>"
            f"Este: {e_v:,.0f} m &nbsp; Norte: {n_v:,.0f} m<br>"
            f"Zona: {zv}{hemi_v}<br>"
            f"Codigo: {v['codigo']}</div>"
        )
        folium.CircleMarker(
            location=[lat_v, lon_v],
            radius=9,
            color="#ff6b35",
            fill=True,
            fill_color=color_v,
            fill_opacity=0.9,
            popup=folium.Popup(popup_html, max_width=240),
            tooltip=f"{v['nombre']} ({v.get('elevacion', '?')} m)",
        ).add_to(m)

folium.LayerControl(collapsed=False).add_to(m)
st_folium(m, use_container_width=True, height=730, returned_objects=[], key="mapa")

# ---------------------------------------------------------------------------
# Tabla de quebradas
# ---------------------------------------------------------------------------

if volcan and drenajes_gj:
    st.divider()
    col_t, col_dl = st.columns([3, 1])
    col_t.markdown("#### Quebradas y rios identificados")

    if nombrados:
        grupos: dict[str, dict] = defaultdict(lambda: {"tipo": "", "tramos": 0})
        for f in nombrados:
            p = f["properties"]
            k = p.get("nombre", "")
            grupos[k]["tipo"]    = p.get("tipo", "")
            grupos[k]["tramos"] += 1

        resumen = pd.DataFrame([
            {"Nombre": k, "Tipo": v["tipo"], "Tramos OSM": v["tramos"]}
            for k, v in grupos.items()
        ]).sort_values(["Tipo", "Nombre"]).reset_index(drop=True)

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
        use_container_width=True,
        hide_index=True,
    )
