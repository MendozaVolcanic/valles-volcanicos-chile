"""
dashboard.py - Valles Volcanicos OVDAS
Pantalla 43", modo oscuro, fondo satelital ESRI, etiquetas de quebradas.
Capas: comunas (WMS BCN Chile) + ciudades y pueblos (lista estatica OSM).
Sin dependencias nativas — funciona en cualquier Python.
"""

import sys
from pathlib import Path

# Aseguramos que el directorio del propio script (app/) esté en sys.path antes
# de importar los módulos hermanos. Localmente Streamlit lo inyecta solo, pero
# en Streamlit Cloud el script puede ejecutarse con un CWD/sys.path distinto y
# entonces `from loaders import ...` lanza ImportError. Esto lo hace robusto en
# ambos entornos sin depender del working directory.
_APP_DIR = Path(__file__).resolve().parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from collections import defaultdict
from urllib.parse import urlencode

from loaders import (
    cargar_config, cargar_cuencas, cargar_drenajes, cargar_peligros,
    cargar_poblacion, cargar_vial, cargar_infraestructura,
    cargar_centros_poblados, cargar_ciudades, cargar_indice_quebradas,
    wms_disponible, cargar_comunas, cargar_snaspe,
    cargar_puntos_encuentro, cargar_vias_evacuacion,
    cargar_servicios, cargar_perimetro_villarrica,
    # Sprint 1: estado y NRT
    cargar_estado_reav, cargar_firms, cargar_sismos, cargar_sismos_resumen,
    cargar_poblacion_expuesta, cargar_gvp,
)
from geo_utils import normalizar as _normalizar, latlon_a_utm, midpoint_geojson

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

# Cargas y utilidades viven en app/loaders.py y app/geo_utils.py


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
poblacion_df     = cargar_poblacion()
CIUDADES         = cargar_ciudades()

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

# Indice de quebradas: precomputado en export_geojson.py — carga inmediata.

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

    # Buscador global: volcanes + ciudades + quebradas + comunas
    with st.expander("🔍 Buscar (volcán, ciudad, quebrada)", expanded=False):
        _q = st.text_input("Texto", placeholder="ej: Pichillancahue, Pucón, Villarrica",
                            label_visibility="collapsed")
        if _q and len(_q) >= 2:
            _q_norm = _normalizar(_q)
            hits_global = []

            # 1) Volcanes (match en nombre)
            for v in VOLCANES:
                if _q_norm in _normalizar(v["nombre"]):
                    hits_global.append({
                        "tipo": "🌋 Volcán", "nombre": v["nombre"],
                        "detalle": v.get("region", ""),
                        "lat": v["lat"], "lon": v["lon"],
                    })
            # 2) Ciudades
            for c in CIUDADES:
                if _q_norm in _normalizar(c["nombre"]):
                    hits_global.append({
                        "tipo": "🏙️ Ciudad", "nombre": c["nombre"],
                        "detalle": f"{c['pop']:,} hab.",
                        "lat": c["lat"], "lon": c["lon"],
                    })
            # 3) Quebradas (precomputado, instantaneo)
            try:
                _idx_qb = cargar_indice_quebradas()
                _hits_q = _idx_qb[_idx_qb["quebrada"].apply(lambda x: _q_norm in _normalizar(x))]
                for _, r in _hits_q.head(20).iterrows():
                    hits_global.append({
                        "tipo": f"💧 {r['tipo'].capitalize()}", "nombre": r["quebrada"],
                        "detalle": f"vía {r['volcan']}",
                        "lat": None, "lon": None,
                    })
            except Exception:
                pass

            if hits_global:
                st.caption(f"{len(hits_global)} coincidencias")
                _df = pd.DataFrame(hits_global)[["tipo", "nombre", "detalle"]]
                st.dataframe(_df.head(30), use_container_width=True, hide_index=True, height=200)
                # Tip de uso
                _con_coord = [h for h in hits_global if h["lat"] is not None]
                if _con_coord:
                    _pri = _con_coord[0]
                    st.caption(f"💡 Para centrar el mapa en **{_pri['nombre']}**, pegalo en el selector de volcán arriba.")
            else:
                st.caption("Sin coincidencias")

    st.divider()
    st.markdown("**Capas tematicas**")
    _capas_set = set(_qp_capas.split(",")) if _qp_capas else None
    def _capa_default(key, default):
        return key in _capas_set if _capas_set is not None else default
    mostrar_cuencas  = st.checkbox("Zona de influencia (50 km)", value=_capa_default("cuencas", True))
    mostrar_drenajes = st.checkbox("Quebradas y rios",           value=_capa_default("drenajes", True))
    mostrar_nombres  = st.checkbox("Nombres de quebradas",       value=_capa_default("nombres", True))
    mostrar_volcanes = st.checkbox("Marcadores de volcanes",     value=_capa_default("volcanes", True))
    solo_drena       = st.checkbox("Solo quebradas que drenan desde el edificio",
                                    value=_capa_default("drena", False),
                                    help="Filtra a las quebradas hidrologicamente conectadas al cono (pysheds, DEM SRTM 30m). "
                                         "Esconde tramos dentro del buffer 50 km que NO reciben flujo desde el volcan.")

    st.divider()
    st.markdown("**Capas de contexto**")
    mostrar_comunas   = st.checkbox("Limites comunales",           value=_capa_default("comunas", False))
    mostrar_ciudades  = st.checkbox("Ciudades y pueblos",          value=_capa_default("ciudades", True))
    mostrar_centros   = st.checkbox("Centros poblados (poligonos)",value=_capa_default("centros", False))
    mostrar_vial      = st.checkbox("Red vial principal",          value=_capa_default("vial", False))
    mostrar_infra     = st.checkbox("Infraestructura critica",     value=_capa_default("infra", False))
    mostrar_peligros  = st.checkbox("Zonas de peligro volcanico",  value=_capa_default("peligros", False))
    mostrar_snaspe    = st.checkbox("Areas protegidas (SNASPE)",   value=_capa_default("snaspe", False),
                                     help="SNAP (ex-SNASPE) oficial Bienes Nacionales, mayo 2026. Parques, reservas y monumentos.")

    st.divider()
    st.markdown("**Capas SENAPRED**  \n<small style='color:#888'>Visor Chile Preparado</small>", unsafe_allow_html=True)
    # Nota: las áreas de peligro ya están en "Zonas de peligro volcánico" arriba
    # (peligros_volcanicos.geojson, 142 features bien etiquetados por volcán).
    # No replicamos con SENAPRED areas_peligro (10k duplicados, campo 'volcan' vacío).
    mostrar_puntos_enc      = st.checkbox("Puntos de encuentro",   value=_capa_default("puntos", False),
                                          help="168 puntos de encuentro oficiales para evacuación")
    mostrar_vias_evac       = st.checkbox("Vías de evacuación",    value=_capa_default("vias", False),
                                          help="195 vías oficiales de evacuación")
    mostrar_perim_vil       = st.checkbox("Perímetro seguridad Villarrica", value=_capa_default("perimvil", False))
    c_serv1, c_serv2 = st.columns(2)
    mostrar_salud      = c_serv1.checkbox("Salud (S)",      value=_capa_default("salud", False))
    mostrar_bomberos   = c_serv2.checkbox("Bomberos (B)",   value=_capa_default("bomberos", False))
    mostrar_educacion  = c_serv1.checkbox("Educación (E)",  value=_capa_default("educ", False))
    mostrar_carab      = c_serv2.checkbox("Carabineros (C)", value=_capa_default("carab", False))

    st.divider()
    st.markdown("**Capas NRT** (7 días)  \n<small style='color:#888'>Sprint 1 · NASA/USGS</small>", unsafe_allow_html=True)
    mostrar_firms   = st.checkbox("🔥 Hotspots térmicos FIRMS", value=_capa_default("firms", False),
                                   help="MODIS+VIIRS últimos 7 días")
    mostrar_sismos  = st.checkbox("📡 Sismos USGS (M≥2)", value=_capa_default("sismos", False),
                                   help="USGS ComCat. Marcadores proporcionales a magnitud.")

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
        "snaspe": mostrar_snaspe, "drena": solo_drena,
        "puntos": mostrar_puntos_enc, "vias": mostrar_vias_evac,
        "perimvil": mostrar_perim_vil, "salud": mostrar_salud,
        "bomberos": mostrar_bomberos, "educ": mostrar_educacion,
        "carab": mostrar_carab,
        "firms": mostrar_firms, "sismos": mostrar_sismos,
    }.items() if v)

    with st.expander("Compartir vista (permalink)"):
        _params = {
            "volcan": seleccion if seleccion != "(Todos los volcanes)" else "",
            "zona":   zona_filtro,
            "ovdas":  "true" if solo_ovdas else "false",
            "capas":  _capas_activas,
            "full":   "true" if modo_full else "false",
        }
        _qs = urlencode({k: v for k, v in _params.items() if v})
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
# Filtro hidrologico opcional: solo tramos que drenan desde el edificio.
# Si el campo 'drena_volcan' no esta en los datos (pysheds no corrido aun),
# el toggle no hace efecto — feats queda sin cambios.
hay_drena_attr = any("drena_volcan" in f.get("properties", {}) for f in feats)
if solo_drena and hay_drena_attr:
    feats = [f for f in feats if f["properties"].get("drena_volcan")]
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
    # Semáforo REAV (Verde/Amarillo/Naranja/Rojo) — fuente SERNAGEOMIN
    _reav = cargar_estado_reav()
    _nivel_v = None
    if not _reav.empty:
        _row_v = _reav[_reav["codigo"] == volcan["codigo"]]
        if len(_row_v):
            _nivel_v = _row_v.iloc[0]["nivel"]
    _NIVEL_COLOR = {"Verde":"#2ecc40","Amarillo":"#ffdc00","Naranja":"#ff851b","Rojo":"#ff4136"}
    _NIVEL_EMOJI = {"Verde":"🟢","Amarillo":"🟡","Naranja":"🟠","Rojo":"🔴"}
    badge_reav = ""
    if _nivel_v and pd.notna(_nivel_v):
        _c = _NIVEL_COLOR.get(_nivel_v, "#888")
        badge_reav = (f'<span class="badge" style="background:{_c};color:#000;font-weight:700">'
                      f'{_NIVEL_EMOJI.get(_nivel_v,"")} REAV {_nivel_v.upper()}</span>')
    st.markdown(
        f"### {volcan['nombre']} {badge_zona}{badge_ovdas}{badge_reav} "
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
    n_drena = sum(1 for f in feats if f["properties"].get("drena_volcan"))
    c6, c7, c_drena, c_mini = st.columns([1.2, 1.4, 1.4, 4.0])
    c6.metric("Tramos OSM",           f"{len(feats):,}")
    c7.metric("Con nombre",           f"{len(nombres_unicos):,}")
    if hay_drena_attr and not solo_drena:
        pct = (n_drena / len(feats) * 100) if feats else 0
        c_drena.metric("Drenan del volcán", f"{n_drena:,}",
                       delta=f"{pct:.1f}% del total", delta_color="off",
                       help="Tramos OSM hidrológicamente conectados al edificio (D8 SRTM 30m)")
    elif hay_drena_attr and solo_drena:
        c_drena.metric("Drenan del volcán", f"{n_drena:,}", help="Filtro activo")
    else:
        c_drena.metric("Drenan del volcán", "—", help="Correr scripts/06_watershed_pysheds.py")
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

    # Fila 3: Sprint 1 — exposición + actividad NRT
    pob_df = cargar_poblacion_expuesta()
    pob_alto  = pob_df[(pob_df["volcan"] == volcan["nombre"]) & (pob_df["peligro_nivel"] == "Alto")]["poblacion_estimada"].sum() if not pob_df.empty else 0
    pob_total = pob_df[pob_df["volcan"] == volcan["nombre"]]["poblacion_estimada"].sum() if not pob_df.empty else 0
    sismos_df = cargar_sismos_resumen()
    sismos_v  = sismos_df[sismos_df["codigo"] == volcan["codigo"]] if not sismos_df.empty else pd.DataFrame()
    n_sismos  = int(sismos_v["n_sismos"].iloc[0]) if len(sismos_v) else 0
    mag_max   = float(sismos_v["mag_max"].iloc[0]) if len(sismos_v) and pd.notna(sismos_v["mag_max"].iloc[0]) else None
    firms_gj  = cargar_firms(volcan["codigo"])
    n_firms   = len(firms_gj.get("features", [])) if firms_gj else None
    gvp_df    = cargar_gvp()
    vei_max   = None
    if not gvp_df.empty:
        _gvp_r = gvp_df[gvp_df["codigo"] == volcan["codigo"]] if "codigo" in gvp_df.columns else pd.DataFrame()
        if len(_gvp_r):
            vei_max = _gvp_r.iloc[0].get("vei_maximo")

    cp1, cp2, cp3, cp4, cp5 = st.columns(5)
    cp1.metric("Pob. expuesta (Alto)", f"{int(pob_alto):,}" if pob_alto else "—",
               help="Censo 2024 INE — manzanas censales que caen en zona de peligro Alto.")
    cp2.metric("Pob. expuesta (total)", f"{int(pob_total):,}" if pob_total else "—",
               help="Suma Alto+Medio+Bajo.")
    cp3.metric("Sismos 7d (M≥2)", f"{n_sismos}" + (f" (máx {mag_max:.1f})" if mag_max else ""),
               help="USGS ComCat. Cobertura efectiva M≥3.5 en zonas remotas.")
    cp4.metric("Hotspots térmicos 7d", "—" if n_firms is None else str(n_firms),
               help="NASA FIRMS (MODIS+VIIRS). Requiere MAP_KEY — registrarse en firms.modaps.eosdis.nasa.gov.")
    cp5.metric("VEI máx histórico", str(int(vei_max)) if vei_max and pd.notna(vei_max) else "—",
               help="Smithsonian GVP — máximo VEI registrado en el Holoceno.")

    # Ficha GVP completa
    if not gvp_df.empty and "codigo" in gvp_df.columns:
        _gvp_r = gvp_df[gvp_df["codigo"] == volcan["codigo"]]
        if len(_gvp_r):
            _r = _gvp_r.iloc[0]
            with st.expander(f"📖 Ficha Smithsonian GVP — {_r.get('nombre_oficial_gvp', volcan['nombre'])}"):
                _gvp_url = _r.get("url_pagina_si_edu", "")
                _ult_anio = _r.get("ultima_erupcion_anio")
                _ult = (f"{int(_ult_anio)}" + (f" (VEI {int(_r['ultima_erupcion_vei'])})"
                                                if pd.notna(_r.get("ultima_erupcion_vei")) else "")
                        if pd.notna(_ult_anio) else "—")
                f1, f2, f3 = st.columns(3)
                f1.markdown(f"**Tipo morfológico**  \n{_r.get('tipo_morfologico','—')}")
                f1.markdown(f"**Composición**  \n{_r.get('composicion','—')}")
                f2.markdown(f"**Elevación GVP**  \n{int(_r['elevacion_gvp']):,} m" if pd.notna(_r.get("elevacion_gvp")) else "**Elevación GVP** —")
                f2.markdown(f"**Última erupción**  \n{_ult}")
                f3.markdown(f"**Erupciones Holoceno**  \n{int(_r.get('num_erupciones_holoceno', 0))}")
                f3.markdown(f"**Erupciones s. XX–XXI**  \n{int(_r.get('num_erupciones_siglo_xx_xxi', 0))}")
                if _gvp_url:
                    st.caption(f"Fuente: [Smithsonian GVP vn={int(_r['gvp_id'])}]({_gvp_url})")
else:
    st.markdown("### Estado nacional 🌋")
    # Tabla semáforo nacional estilo Vanuatu — vista panorámica
    _reav_nac = cargar_estado_reav()
    _sismos_nac = cargar_sismos_resumen()
    _pob_nac = cargar_poblacion_expuesta()

    c1, c2, c3, c4 = st.columns(4)
    _ovdas_count = sum(1 for v in VOLCANES if _es_ovdas(v))
    n_amarillo = (_reav_nac["nivel"] == "Amarillo").sum() if not _reav_nac.empty else 0
    n_naranja  = (_reav_nac["nivel"] == "Naranja").sum() if not _reav_nac.empty else 0
    n_rojo     = (_reav_nac["nivel"] == "Rojo").sum() if not _reav_nac.empty else 0
    n_sismos_total = int(_sismos_nac["n_sismos"].sum()) if not _sismos_nac.empty else 0
    pob_total_chile = int(_pob_nac["poblacion_estimada"].sum()) if not _pob_nac.empty else 0
    c1.metric("OVDAS monitorea", _ovdas_count)
    c2.metric("⚠️ Alerta ≥ amarilla", n_amarillo + n_naranja + n_rojo,
               help=f"Amarillo {n_amarillo} · Naranja {n_naranja} · Rojo {n_rojo}")
    c3.metric("📡 Sismos 7d (M≥2)", n_sismos_total, help="USGS ComCat — suma 59 bbox")
    c4.metric("👥 Pob. expuesta total", f"{pob_total_chile:,}",
               help="Censo 2024 INE — suma manzanas en polígonos peligro (Alto+Medio+Bajo)")

    st.divider()
    # Tabla semáforo ordenada por nivel descendente + magnitud
    if not _reav_nac.empty:
        _nivel_orden = {"Rojo": 0, "Naranja": 1, "Amarillo": 2, "Verde": 3}
        _tabla = _reav_nac.copy()
        _tabla["_ord"] = _tabla["nivel"].map(_nivel_orden).fillna(4)
        if not _sismos_nac.empty:
            _tabla = _tabla.merge(_sismos_nac[["codigo","n_sismos","mag_max"]], on="codigo", how="left")
        _tabla = _tabla.sort_values(["_ord","mag_max","n_sismos"], ascending=[True, False, False])
        _tabla["semáforo"] = _tabla["nivel"].map(
            {"Verde":"🟢","Amarillo":"🟡","Naranja":"🟠","Rojo":"🔴"}).fillna("⚪")
        st.markdown("#### Semáforo nacional por volcán")
        st.dataframe(
            _tabla[["semáforo","nivel","codigo","nombre","n_sismos","mag_max"]].rename(
                columns={"n_sismos":"sismos 7d","mag_max":"M máx"}),
            use_container_width=True, hide_index=True, height=420,
        )
        st.caption("Para zoom al volcán, seleccionalo en el menú lateral.")

# ---------------------------------------------------------------------------
# Mapa Folium
# ---------------------------------------------------------------------------

center = [volcan["lat"], volcan["lon"]] if volcan else [-35.0, -70.5]
zoom   = 10 if volcan else 5

m = folium.Map(location=center, zoom_start=zoom, tiles=None, prefer_canvas=True,
               control_scale=True)  # escala grafica en esquina (estilo visor SENAPRED)

# Coordenadas del mouse en la esquina inferior — estilo visor Chile Preparado
from folium.plugins import MousePosition, MeasureControl, MiniMap, Fullscreen
MousePosition(
    position="bottomleft", separator=" | ", empty_string="Mover el ratón para coordenadas",
    lng_first=False, num_digits=4, prefix="Lat/Lon",
).add_to(m)
# Herramienta de medicion (distancia/area)
MeasureControl(
    primary_length_unit="kilometers", secondary_length_unit="meters",
    primary_area_unit="hectares", position="topleft",
).add_to(m)
# Boton fullscreen
Fullscreen(position="topleft", title="Pantalla completa", title_cancel="Salir",
           force_separate_button=True).add_to(m)

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

# -- Limites comunales (local, 345 comunas — reemplaza WMS BCN roto) --
# Fuente: chile-geojson (BCN/INE upstream). Procesado por scripts/10_comunas_local.py
if mostrar_comunas:
    comunas_gj = cargar_comunas(volcan["codigo"] if volcan else None)
    if comunas_gj and comunas_gj.get("features"):
        folium.GeoJson(
            comunas_gj,
            name="Comunas",
            style_function=lambda f: {
                "fillColor":   "#ffffff",
                "color":       "#a0a0a0",
                "weight":      1.0,
                "fillOpacity": 0.05,
                "opacity":     0.7,
                "dashArray":   "3,3",
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["nombre_comuna", "nombre_provincia", "nombre_region"],
                aliases=["Comuna", "Provincia", "Región"],
            ),
        ).add_to(m)

# -- SNASPE / SNAP local (MBN, mayo 2026) — reemplaza al WMS SAG roto --
if mostrar_snaspe:
    snaspe_gj = cargar_snaspe(volcan["codigo"] if volcan else None)
    if snaspe_gj and snaspe_gj.get("features"):
        CAT_COLORS = {
            "Parque Nacional":          "#2a9d8f",
            "Reserva Nacional":         "#8ab17d",
            "Monumento Natural":        "#e9c46a",
            "Reserva de Region Virgen": "#264653",
            "Santuario de la Naturaleza":"#a4c2a8",
        }
        folium.GeoJson(
            snaspe_gj,
            name="SNAP / Áreas protegidas",
            style_function=lambda f: {
                "fillColor":   CAT_COLORS.get(f["properties"].get("categoria", ""), "#83c5be"),
                "color":       "#0a3a2a",
                "weight":      1.5,
                "fillOpacity": 0.40,
                "opacity":     0.85,
                "dashArray":   "4,3",
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["nombre", "categoria", "region"],
                aliases=["Área", "Categoría", "Región"],
            ),
        ).add_to(m)
    elif volcan:
        st.caption("Sin áreas SNAP en el buffer de este volcán.")

# === Capas oficiales SENAPRED (visor Chile Preparado) ============================

# -- Puntos de encuentro oficiales --
if mostrar_puntos_enc:
    pts = cargar_puntos_encuentro(volcan["codigo"] if volcan else None)
    if pts and pts.get("features"):
        grupo_pe = folium.FeatureGroup(name="Puntos de encuentro", show=True)
        for f in pts["features"]:
            lon_p, lat_p = f["geometry"]["coordinates"]
            props = f["properties"]
            nombre  = props.get("nombre", "Punto de encuentro")
            tipo_pe = props.get("tipo", "")
            volc_pe = props.get("volcan", "")
            folium.Marker(
                location=[lat_p, lon_p],
                icon=folium.DivIcon(html=(
                    '<div style="background:#06d6a0;color:#000;border:2px solid #fff;'
                    'border-radius:50%;width:18px;height:18px;font-weight:bold;font-size:11px;'
                    'text-align:center;line-height:14px;'
                    'box-shadow:0 1px 3px rgba(0,0,0,0.6);">★</div>'
                ), icon_size=(18,18), icon_anchor=(9,9)),
                tooltip=f"★ {nombre} ({tipo_pe})" if tipo_pe else f"★ {nombre}",
                popup=folium.Popup(
                    f"<b>★ Punto de encuentro</b><br>"
                    f"<b>{nombre}</b><br>"
                    f"Volcán: {volc_pe}<br>"
                    f"Tipo: {tipo_pe}",
                    max_width=240,
                ),
            ).add_to(grupo_pe)
        grupo_pe.add_to(m)

# -- Vías de evacuación --
if mostrar_vias_evac:
    vias = cargar_vias_evacuacion(volcan["codigo"] if volcan else None)
    if vias and vias.get("features"):
        folium.GeoJson(
            vias,
            name="Vías de evacuación",
            style_function=lambda f: {
                "color":   "#06d6a0",
                "weight":  4.5,
                "opacity": 0.85,
                "dashArray": "10,5",
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["volcan"], aliases=["Vía de evacuación — volcán"],
            ),
        ).add_to(m)

# -- Perímetro seguridad Villarrica --
if mostrar_perim_vil:
    pv = cargar_perimetro_villarrica()
    if pv and pv.get("features"):
        folium.GeoJson(
            pv,
            name="Perímetro seguridad Villarrica",
            style_function=lambda f: {
                "fillColor": "#ff006e", "color": "#ff006e",
                "weight": 2, "fillOpacity": 0.15, "opacity": 0.9,
                "dashArray": "6,3",
            },
        ).add_to(m)

# -- Servicios SENAPRED (salud, bomberos, educacion, carabineros) --
# Cada tipo tiene su propio esquema de propiedades, definido aqui:
SERV_SPEC = [
    ("salud",      mostrar_salud,     "🏥", "#e63946", "Salud",
       # nombre_ofi siempre vacio en SENAPRED — usamos simbologia (APS, urgencia, etc) como nombre
       lambda p: (p.get("simbologia") or p.get("nombre_dep") or "Centro de salud") + (f" — {p.get('comuna')}" if p.get("comuna") else ""),
       lambda p: [p.get("nombre_dep"), p.get("nivel_de_a"),
                  f"📞 {p.get('teléfono')}" if str(p.get("teléfono","0")) not in ("0","","None","null") else None,
                  p.get("dirección")]),
    ("bomberos",   mostrar_bomberos,  "🚒", "#d62828", "Bomberos",
       lambda p: p.get("nombre", "Bomberos"),
       lambda p: [p.get("tipo"), p.get("compa__ia"),
                  f"📞 {p.get('telefono')}" if p.get("telefono") else None,
                  p.get("direccion"), p.get("nom_com")]),
    ("educacion",  mostrar_educacion, "🏫", "#3a86ff", "Educación",
       lambda p: p.get("nombre_establecimiento", "Establecimiento"),
       lambda p: [p.get("dependencia"), p.get("urbano_rural"),
                  f"Matrícula: {p.get('matricula')}" if p.get("matricula") else None,
                  p.get("comuna")]),
    ("carabineros",mostrar_carab,     "🛡️", "#003049", "Carabineros",
       lambda p: p.get("nombre_uni", "Unidad"),
       lambda p: [p.get("tipo_de_un"), p.get("prefectura"),
                  p.get("comuna"), p.get("region")]),
]
for tipo, activo, icono, color, label, get_nombre, get_detalles in SERV_SPEC:
    if not activo:
        continue
    sv = cargar_servicios(tipo, volcan["codigo"] if volcan else None)
    if not sv or not sv.get("features"):
        continue
    grupo = folium.FeatureGroup(name=f"{label} (SENAPRED)", show=True)
    for f in sv["features"]:
        lon_s, lat_s = f["geometry"]["coordinates"]
        props = f["properties"]
        nombre = get_nombre(props)
        detalles = [d for d in get_detalles(props) if d not in (None, "", "null")]
        popup_html = f"<b>{icono} {label}</b><br><b>{nombre}</b>"
        if detalles:
            popup_html += "<br>" + "<br>".join(str(d) for d in detalles)
        folium.CircleMarker(
            location=[lat_s, lon_s],
            radius=5, color=color, fill=True, fill_color=color, fill_opacity=0.85,
            tooltip=f"{icono} {nombre}",
            popup=folium.Popup(popup_html, max_width=280),
        ).add_to(grupo)
    grupo.add_to(m)

# === Capas NRT — Sprint 1 ===

# -- Hotspots térmicos FIRMS (MODIS+VIIRS últimos 7 días) --
if mostrar_firms and volcan:
    firms_gj_v = cargar_firms(volcan["codigo"])
    if firms_gj_v and firms_gj_v.get("features"):
        grupo_f = folium.FeatureGroup(name="Hotspots FIRMS (7d)", show=True)
        for ft in firms_gj_v["features"]:
            lon_f, lat_f = ft["geometry"]["coordinates"]
            p = ft["properties"]
            frp = p.get("frp") or 0
            radio = 4 + min(float(frp) / 20, 10)  # 4-14 px
            popup = (f"<b>🔥 Hotspot</b><br>"
                     f"Satélite: {p.get('satellite','?')} ({p.get('instrument','')})<br>"
                     f"Fecha: {p.get('acq_date','?')} {p.get('acq_time','')}<br>"
                     f"FRP: {p.get('frp','?')} MW<br>"
                     f"Brightness: {p.get('brightness','?')} K<br>"
                     f"Confianza: {p.get('confidence','?')}")
            folium.CircleMarker(
                location=[lat_f, lon_f], radius=radio,
                color="#ff3300", weight=1, fill=True, fill_color="#ffaa00", fill_opacity=0.8,
                tooltip=f"🔥 {p.get('acq_date','?')} FRP={p.get('frp','?')}",
                popup=folium.Popup(popup, max_width=260),
            ).add_to(grupo_f)
        grupo_f.add_to(m)

# -- Sismos USGS ComCat últimos 7 días (M≥2) --
if mostrar_sismos and volcan:
    sismos_gj_v = cargar_sismos(volcan["codigo"])
    if sismos_gj_v and sismos_gj_v.get("features"):
        grupo_s = folium.FeatureGroup(name="Sismos USGS (7d)", show=True)
        for ft in sismos_gj_v["features"]:
            lon_s, lat_s = ft["geometry"]["coordinates"][:2]
            depth = ft["geometry"]["coordinates"][2] if len(ft["geometry"]["coordinates"]) > 2 else None
            p = ft["properties"]
            mag = p.get("mag") or 0
            radio = 4 + float(mag) * 2.5  # M2=9px, M4=14px, M5=16.5px
            color = "#003049" if mag < 3 else ("#d62828" if mag < 5 else "#9d0208")
            hora_str = pd.to_datetime(p.get("time"), unit="ms").strftime("%Y-%m-%d %H:%M UTC") if p.get("time") else "?"
            popup_parts = [f"<b>📡 Sismo M {mag:.1f}</b>", f"{p.get('place','')}"]
            if depth is not None:
                popup_parts.append(f"Profundidad: {depth:.1f} km")
            popup_parts.append(f"Hora: {hora_str}")
            popup = "<br>".join(popup_parts)
            folium.CircleMarker(
                location=[lat_s, lon_s], radius=radio,
                color=color, weight=1.5, fill=True, fill_color=color, fill_opacity=0.6,
                tooltip=f"📡 M{mag:.1f} {pd.to_datetime(p.get('time'), unit='ms').strftime('%m-%d %H:%M') if p.get('time') else ''}",
                popup=folium.Popup(popup, max_width=260),
            ).add_to(grupo_s)
        grupo_s.add_to(m)

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
# Carga lazy: si hay volcan, shard precomputado (~5 KB). Si no, global.
centros_gj = cargar_centros_poblados(volcan["codigo"] if volcan else None) if mostrar_centros else None
if mostrar_centros and centros_gj:
    feats_cp = centros_gj.get("features", [])
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
vial_gj = cargar_vial(volcan["codigo"] if volcan else None) if mostrar_vial else None
if mostrar_vial and vial_gj:
    VIAL_STYLE = {
        "motorway": {"color": "#e63946", "weight": 3.5, "opacity": 0.9},
        "trunk":    {"color": "#f4a261", "weight": 2.5, "opacity": 0.85},
        "primary":  {"color": "#f9c74f", "weight": 1.8, "opacity": 0.8},
    }
    feats_v = vial_gj.get("features", [])
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
infraestructura_gj = cargar_infraestructura(volcan["codigo"] if volcan else None) if mostrar_infra else None
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
# Tramos que drenan desde el edificio se ven en naranja (mismo color que el
# volcan en el resto del dashboard). Los que NO drenan se ven azules tenues.
# Si los datos no tienen drena_volcan, se usa el estilo legacy (azules).
def _estilo_drenaje(f):
    props  = f["properties"]
    es_rio = props.get("tipo") == "river"
    drena  = props.get("drena_volcan", False) if hay_drena_attr else None
    if hay_drena_attr and drena:
        return {
            "color":   "#ff6b35" if es_rio else "#ffaa66",
            "weight":  3.0       if es_rio else 1.8,
            "opacity": 0.95,
        }
    # Tramo dentro del buffer pero NO drena: azul tenue
    if hay_drena_attr and not drena:
        return {
            "color":   "#3a5a7a" if es_rio else "#446680",
            "weight":  1.5       if es_rio else 0.8,
            "opacity": 0.55,
        }
    # Legacy (sin drena_volcan): comportamiento previo
    return {
        "color":   "#00aaff" if es_rio else "#66ccff",
        "weight":  2.5       if es_rio else 1.2,
        "opacity": 0.9,
    }

if mostrar_drenajes and feats:
    folium.GeoJson(
        {"type": "FeatureCollection", "features": feats},
        name="Quebradas y rios",
        style_function=_estilo_drenaje,
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
        grupos: dict[str, dict] = defaultdict(lambda: {"tipo": "", "tramos": 0, "drena": 0})
        for f in nombrados:
            p = f["properties"]
            k = p.get("nombre", "")
            grupos[k]["tipo"]    = p.get("tipo", "")
            grupos[k]["tramos"] += 1
            if p.get("drena_volcan"):
                grupos[k]["drena"] += 1

        if hay_drena_attr:
            resumen = pd.DataFrame([
                {"Nombre": k, "Tipo": v["tipo"], "Tramos OSM": v["tramos"],
                 "Drena del volcán": "sí" if v["drena"] > 0 else "no",
                 "Tramos hidrol.": v["drena"]}
                for k, v in grupos.items()
            ]).sort_values(["Drena del volcán", "Tipo", "Nombre"],
                           ascending=[False, True, True]).reset_index(drop=True)
        else:
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
