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


def _cargar_capa_sharded(capa: str, codigo: str | None) -> dict | None:
    """Carga lazy: shard por volcan (~5-20 KB) o GeoJSON global (legacy)."""
    if codigo:
        shard = PROCESSED / capa / f"{codigo}.geojson"
        if shard.exists():
            with open(str(shard), encoding="utf-8") as f:
                return json.load(f)
        return {"type": "FeatureCollection", "features": []}
    p = PROCESSED / f"{capa}.geojson"
    if not p.exists():
        return None
    with open(str(p), encoding="utf-8") as f:
        return json.load(f)


@st.cache_data
def cargar_vial(codigo: str | None = None) -> dict | None:
    return _cargar_capa_sharded("red_vial", codigo)


@st.cache_data
def cargar_infraestructura(codigo: str | None = None) -> dict | None:
    return _cargar_capa_sharded("infraestructura", codigo)


@st.cache_data
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
@st.cache_data
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
@st.cache_data
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


@st.cache_data
def cargar_puntos_encuentro(codigo: str | None = None) -> dict | None:
    return _cargar_senapred_shard("puntos_encuentro", codigo)


@st.cache_data
def cargar_vias_evacuacion(codigo: str | None = None) -> dict | None:
    return _cargar_senapred_shard("vias_evacuacion", codigo)


@st.cache_data
def cargar_servicios(tipo: str, codigo: str | None = None) -> dict | None:
    """tipo: salud | bomberos | educacion | carabineros"""
    return _cargar_senapred_shard(f"servicios_{tipo}", codigo)


@st.cache_data
def cargar_perimetro_villarrica() -> dict | None:
    p = SENAPRED / "perimetro_villarrica.geojson"
    if not p.exists():
        return None
    with open(str(p), encoding="utf-8") as f:
        return json.load(f)


@st.cache_data(ttl=300)
def wms_disponible(url: str, timeout: float = 3.0) -> bool:
    """Verifica que el endpoint WMS responda. Cache 5 min."""
    import requests
    try:
        r = requests.get(url, params={"service": "WMS", "request": "GetCapabilities"},
                         timeout=timeout)
        return r.status_code == 200 and b"WMS" in r.content[:2048].upper()
    except Exception:
        return False
