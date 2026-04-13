"""
01_download_hydro.py
--------------------
Descarga hidrografia de Chile desde OpenStreetMap (Overpass API).
- Guarda por volcan individualmente (resume si se interrumpe)
- Reintento con backoff exponencial ante 429/504
- Compatible con encoding Windows

Salida: data/raw/hydro/{CODIGO}_hydro.gpkg  (uno por volcan)
        data/raw/hidrografia_osm.gpkg        (consolidado final)
"""

import geopandas as gpd
import requests
import pandas as pd
import yaml
import time
import sys
from pathlib import Path
from shapely.geometry import LineString
from tqdm import tqdm

RAW = Path("data/raw")
RAW_HYDRO = RAW / "hydro"
RAW_HYDRO.mkdir(parents=True, exist_ok=True)

CONFIG = yaml.safe_load(open("config/volcanoes.yaml"))
VOLCANES = CONFIG["volcanes"]

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
RADIO_KM = 50


def log(msg):
    """Print compatible con Windows (sin emojis ni caracteres especiales)."""
    print(msg, flush=True)


def bbox_volcan(lat, lon, radio_km=RADIO_KM):
    delta = radio_km / 111.0
    return lat - delta, lon - delta, lat + delta, lon + delta


def query_overpass(lat, lon, radio_km=RADIO_KM, max_intentos=5):
    """Consulta Overpass con reintento exponencial."""
    s, w, n, e = bbox_volcan(lat, lon, radio_km)
    query = f"""
    [out:json][timeout:90];
    (
      way["waterway"~"river|stream|canal|drain"]({s},{w},{n},{e});
    );
    out geom;
    """
    espera = 5
    for intento in range(1, max_intentos + 1):
        try:
            resp = requests.post(
                OVERPASS_URL,
                data={"data": query},
                timeout=120,
                headers={"User-Agent": "OVDAS-SERNAGEOMIN/valles-volcanicos"}
            )
            if resp.status_code == 429 or resp.status_code == 504:
                log(f"    [rate limit {resp.status_code}] espera {espera}s (intento {intento}/{max_intentos})")
                time.sleep(espera)
                espera = min(espera * 2, 120)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            log(f"    [timeout] espera {espera}s (intento {intento}/{max_intentos})")
            time.sleep(espera)
            espera = min(espera * 2, 120)
        except Exception as e:
            log(f"    [error] {e}")
            if intento < max_intentos:
                time.sleep(espera)
                espera = min(espera * 2, 120)
    return None


def overpass_to_geodataframe(data, codigo, nombre):
    features = []
    for element in data.get("elements", []):
        if element["type"] == "way" and "geometry" in element:
            coords = [(p["lon"], p["lat"]) for p in element["geometry"]]
            if len(coords) < 2:
                continue
            tags = element.get("tags", {})
            features.append({
                "geometry": LineString(coords),
                "osm_id": element["id"],
                "nombre": tags.get("name:es") or tags.get("name") or "Sin nombre",
                "tipo": tags.get("waterway", "stream"),
                "volcan_codigo": codigo,
                "volcan_nombre": nombre,
                "fuente": "OSM",
            })
    if not features:
        return None
    return gpd.GeoDataFrame(features, crs="EPSG:4326")


def descargar_volcan(v):
    """Descarga y guarda hidrografia de un volcan. Retorna GDF o None."""
    nombre = v["nombre"]
    codigo = v["codigo"]
    lat, lon = v["lat"], v["lon"]

    output = RAW_HYDRO / f"{codigo}_hydro.gpkg"
    if output.exists():
        try:
            gdf = gpd.read_file(output)
            log(f"  [skip] {nombre}: ya existe ({len(gdf)} tramos)")
            return gdf
        except Exception:
            pass  # archivo corrupto, re-descarga

    data = query_overpass(lat, lon)
    if data is None:
        log(f"  [fallo] {nombre}: sin respuesta de Overpass")
        return None

    gdf = overpass_to_geodataframe(data, codigo, nombre)
    if gdf is None or len(gdf) == 0:
        log(f"  {nombre}: sin datos en OSM (area despoblada o sin mapeo)")
        # Guardar GDF vacio para marcar como procesado
        empty = gpd.GeoDataFrame(columns=["geometry","osm_id","nombre","tipo","volcan_codigo","volcan_nombre","fuente"], crs="EPSG:4326")
        empty.to_file(output, driver="GPKG")
        return empty

    gdf.to_file(output, driver="GPKG")
    log(f"  {nombre}: {len(gdf)} tramos descargados")
    return gdf


def consolidar():
    """Une todos los .gpkg individuales en uno solo."""
    output = RAW / "hidrografia_osm.gpkg"
    archivos = sorted(RAW_HYDRO.glob("*_hydro.gpkg"))
    if not archivos:
        log("[!] No hay archivos individuales para consolidar")
        return

    gdfs = []
    for f in archivos:
        try:
            gdf = gpd.read_file(f)
            if len(gdf) > 0:
                gdfs.append(gdf)
        except Exception:
            pass

    if gdfs:
        result = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True), crs="EPSG:4326")
        result.to_file(output, driver="GPKG")
        log(f"\n[OK] Consolidado: {output}")
        log(f"     {len(result)} tramos totales de {len(gdfs)} volcanes")
    else:
        log("[!] No hay datos para consolidar")


def main():
    # Detectar cuales ya estan descargados
    ya_procesados = {f.stem.replace("_hydro", "") for f in RAW_HYDRO.glob("*_hydro.gpkg")}
    pendientes = [v for v in VOLCANES if v["codigo"] not in ya_procesados]
    ya = len(VOLCANES) - len(pendientes)

    log(f"Hidrografia OSM: {len(VOLCANES)} volcanes")
    log(f"  Ya descargados: {ya} | Pendientes: {len(pendientes)}\n")

    for v in tqdm(pendientes, desc="Descargando", file=sys.stdout):
        descargar_volcan(v)
        time.sleep(3)  # pausa entre requests

    log("\nConsolidando todos los archivos...")
    consolidar()


if __name__ == "__main__":
    main()
