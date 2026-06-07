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
