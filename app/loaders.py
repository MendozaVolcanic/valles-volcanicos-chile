"""
loaders.py — Funciones cacheadas de carga de datos.
Aisladas para mantenibilidad y para que tests/test_smoke.py pueda llamarlas
sin instanciar el resto del dashboard.
"""
from pathlib import Path
import json
import yaml
import pandas as pd
import streamlit as st


ROOT          = Path(__file__).resolve().parent.parent
PROCESSED     = ROOT / "data" / "processed"
CONFIG_PATH   = ROOT / "config" / "volcanoes.yaml"
CIUDADES_PATH = ROOT / "config" / "ciudades.yaml"

# Los GeoJSON se cachean con cache_resource, NO con cache_data, a proposito:
# cache_data serializa a pickle, y medimos que deserializar un shard grande
# cuesta 58 ms — casi lo mismo que leer el JSON del disco (65 ms) — y ademas
# mantiene una copia por sesion (~20 MB de RAM para un shard de 4 MB).
# cache_resource guarda el objeto tal cual y compartido: ~0 ms y una sola copia.
#
# CONTRATO: lo que devuelven estas funciones es READ-ONLY. Nunca mutar el dict
# ni sus features — se comparten entre sesiones. Para filtrar, armar lista nueva.
cache_geojson = st.cache_resource(show_spinner=False)


@st.cache_data
def cargar_config() -> dict:
    with open(str(CONFIG_PATH), encoding="utf-8") as f:
        return yaml.safe_load(f)


@cache_geojson
def cargar_cuencas() -> dict | None:
    p = PROCESSED / "cuencas.geojson"
    if not p.exists():
        return None
    with open(str(p), encoding="utf-8") as f:
        return json.load(f)


@cache_geojson
def cargar_drenajes(codigo: str) -> dict | None:
    p = PROCESSED / "drenajes" / f"{codigo}.geojson"
    if not p.exists():
        return None
    with open(str(p), encoding="utf-8") as f:
        return json.load(f)


@cache_geojson
def cargar_drenajes_nombrados(codigo: str) -> dict:
    """Solo los tramos CON nombre de un volcán.

    Se usa en la vista por encuadre (varios volcanes a la vez), donde cargar el
    shard completo sería prohibitivo: los tramos sin nombre son ~85% del total y
    a esa escala son ruido visual. Si existe un shard 'lite' pre-generado se usa
    ese; si no, se filtra el completo (queda cacheado igual).
    """
    lite = PROCESSED / "drenajes_lite" / f"{codigo}.geojson"
    if lite.exists():
        with open(str(lite), encoding="utf-8") as f:
            return json.load(f)
    gj = cargar_drenajes(codigo)
    if not gj:
        return {"type": "FeatureCollection", "features": []}
    feats = [
        f for f in gj.get("features", [])
        if (f.get("properties") or {}).get("nombre", "Sin nombre") != "Sin nombre"
    ]
    return {"type": "FeatureCollection", "features": feats}


@cache_geojson
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


_EMPTY_FC = {"type": "FeatureCollection", "features": []}


def _cargar_capa_sharded(capa: str, codigo: str | None) -> dict | None:
    """Carga lazy por volcán (~5-20 KB).

    Para la vista nacional (codigo=None) NO se carga la capa: red vial,
    infraestructura y centros poblados a escala país son inútiles y pesados
    (varios MB cada uno en RAM, problemático en Streamlit Cloud free tier).
    Devuelve FeatureCollection vacío para que el render simplemente no dibuje.
    """
    if not codigo:
        return _EMPTY_FC
    shard = PROCESSED / capa / f"{codigo}.geojson"
    if shard.exists():
        with open(str(shard), encoding="utf-8") as f:
            return json.load(f)
    return _EMPTY_FC


@cache_geojson
def cargar_vial(codigo: str | None = None) -> dict | None:
    return _cargar_capa_sharded("red_vial", codigo)


@cache_geojson
def cargar_infraestructura(codigo: str | None = None) -> dict | None:
    return _cargar_capa_sharded("infraestructura", codigo)


@cache_geojson
def cargar_centros_poblados(codigo: str | None = None) -> dict | None:
    return _cargar_capa_sharded("centros_poblados", codigo)


@st.cache_data
def cargar_ciudades() -> list[dict]:
    if not CIUDADES_PATH.exists():
        return []
    with open(str(CIUDADES_PATH), encoding="utf-8") as f:
        return yaml.safe_load(f).get("ciudades", [])


@st.cache_data
def cargar_indice_quebradas() -> pd.DataFrame:
    """Indice global precomputado por scripts/export_geojson.py (~177 KB)."""
    p = PROCESSED / "indice_quebradas.csv"
    if p.exists():
        return pd.read_csv(str(p))
    return pd.DataFrame(columns=["quebrada", "tipo", "volcan", "codigo", "tramos"])


# --- Comunas locales (reemplaza al WMS BCN roto en 2026) ---
@cache_geojson
def cargar_comunas(codigo: str | None = None) -> dict | None:
    """Limites comunales (345 comunas Chile). Shard por volcan o global."""
    if codigo:
        p = PROCESSED / "comunas" / f"{codigo}.geojson"
        if p.exists():
            with open(str(p), encoding="utf-8") as f:
                return json.load(f)
        return {"type": "FeatureCollection", "features": []}
    p = PROCESSED / "comunas.geojson"
    if not p.exists():
        return None
    with open(str(p), encoding="utf-8") as f:
        return json.load(f)


# --- SNASPE local (reemplaza al WMS SAG/CONAF roto en 2026) ---
@cache_geojson
def cargar_snaspe(codigo: str | None = None) -> dict | None:
    """Areas protegidas SNAP/SNASPE oficiales (MBN). Shard por volcan."""
    if codigo:
        p = PROCESSED / "snaspe" / f"{codigo}.geojson"
        if p.exists():
            with open(str(p), encoding="utf-8") as f:
                return json.load(f)
        return {"type": "FeatureCollection", "features": []}
    p = PROCESSED / "snaspe.geojson"
    if not p.exists():
        return None
    with open(str(p), encoding="utf-8") as f:
        return json.load(f)


# --- SENAPRED: capas oficiales del Visor Chile Preparado ---
SENAPRED = PROCESSED / "senapred"


def _cargar_senapred_shard(capa: str, codigo: str | None) -> dict | None:
    """Carga shard SENAPRED por volcan o devuelve FC vacio."""
    if codigo:
        p = SENAPRED / capa / f"{codigo}.geojson"
        if p.exists():
            with open(str(p), encoding="utf-8") as f:
                return json.load(f)
        return {"type": "FeatureCollection", "features": []}
    # Vista global: leer GeoJSON global si existe
    p = SENAPRED / f"{capa}.geojson"
    if not p.exists():
        return None
    with open(str(p), encoding="utf-8") as f:
        return json.load(f)


@cache_geojson
def cargar_puntos_encuentro(codigo: str | None = None) -> dict | None:
    return _cargar_senapred_shard("puntos_encuentro", codigo)


@cache_geojson
def cargar_vias_evacuacion(codigo: str | None = None) -> dict | None:
    return _cargar_senapred_shard("vias_evacuacion", codigo)


@cache_geojson
def cargar_servicios(tipo: str, codigo: str | None = None) -> dict | None:
    """tipo: salud | bomberos | educacion | carabineros"""
    return _cargar_senapred_shard(f"servicios_{tipo}", codigo)


@cache_geojson
def cargar_perimetro_villarrica() -> dict | None:
    p = SENAPRED / "perimetro_villarrica.geojson"
    if not p.exists():
        return None
    with open(str(p), encoding="utf-8") as f:
        return json.load(f)


# --- Sprint 1: capas NRT y referencias ---

# ttl para que una regeneracion del pipeline se refleje sin reiniciar el proceso
@st.cache_data(ttl=3600)
def cargar_estado_reav() -> pd.DataFrame:
    """Nivel REAV (Verde/Amarillo/Naranja/Rojo) por volcán. Scraping SERNAGEOMIN."""
    p = PROCESSED / "estado_reav.csv"
    if not p.exists():
        return pd.DataFrame(columns=["codigo","nombre","nivel","fecha_reav","url_reav","resumen","fecha_scrape"])
    return pd.read_csv(str(p))


@st.cache_resource(show_spinner=False, ttl=3600)
def cargar_firms(codigo: str) -> dict | None:
    """Hotspots NASA FIRMS últimos 7 días por volcán (cache 1h)."""
    p = PROCESSED / "firms" / f"{codigo}.geojson"
    if not p.exists():
        return None
    with open(str(p), encoding="utf-8") as f:
        return json.load(f)


@st.cache_resource(show_spinner=False, ttl=3600)
def cargar_sismos(codigo: str) -> dict | None:
    """Sismos USGS ComCat últimos 7 días por volcán (cache 1h)."""
    p = PROCESSED / "sismos" / f"{codigo}.geojson"
    if not p.exists():
        return None
    with open(str(p), encoding="utf-8") as f:
        return json.load(f)


@st.cache_data(ttl=3600)
def cargar_sismos_resumen() -> pd.DataFrame:
    p = PROCESSED / "sismos_resumen.csv"
    if not p.exists():
        return pd.DataFrame(columns=["codigo","nombre","n_sismos","mag_max","mag_promedio","mas_reciente"])
    return pd.read_csv(str(p))


@st.cache_data
def cargar_poblacion_expuesta() -> pd.DataFrame:
    """Censo 2024 INE — población por nivel de peligro Alto/Medio/Bajo."""
    p = PROCESSED / "poblacion_expuesta.csv"
    if not p.exists():
        return pd.DataFrame(columns=["volcan","peligro_nivel","n_manzanas","poblacion_estimada"])
    return pd.read_csv(str(p))


@st.cache_data
def cargar_gvp() -> pd.DataFrame:
    """Ficha Smithsonian GVP por volcán (VEI máx, última erupción, frecuencia)."""
    p = PROCESSED / "gvp.csv"
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(str(p))
