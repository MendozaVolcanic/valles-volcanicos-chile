"""
01_download_hydro.py
--------------------
Descarga hidrografía de Chile desde fuentes públicas:
  - BCN (Biblioteca del Congreso Nacional): ríos y quebradas vectoriales
  - Fallback: OpenStreetMap via Overpass API

Salida: data/raw/hidrografia_chile.gpkg
"""

import geopandas as gpd
import requests
import json
import yaml
import time
from pathlib import Path
from tqdm import tqdm

RAW = Path("data/raw")
RAW.mkdir(parents=True, exist_ok=True)

CONFIG = yaml.safe_load(open("config/volcanoes.yaml"))
VOLCANES = CONFIG["volcanes"]


# ---------------------------------------------------------------------------
# Overpass API (OpenStreetMap) — descarga ríos/quebradas por bbox de volcán
# ---------------------------------------------------------------------------

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

def bbox_volcán(lat, lon, radio_km=50):
    """Calcula bounding box cuadrado alrededor de un punto."""
    delta = radio_km / 111.0  # ~111 km por grado
    return lat - delta, lon - delta, lat + delta, lon + delta


def query_overpass(lat, lon, radio_km=50):
    """Consulta Overpass para waterways dentro del radio del volcán."""
    s, w, n, e = bbox_volcán(lat, lon, radio_km)
    query = f"""
    [out:json][timeout:60];
    (
      way["waterway"~"river|stream|canal|drain"]({s},{w},{n},{e});
      relation["waterway"~"river|stream"]({s},{w},{n},{e});
    );
    out geom;
    """
    resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=90)
    resp.raise_for_status()
    return resp.json()


def overpass_to_geodataframe(data, volcán_codigo, volcán_nombre):
    """Convierte respuesta Overpass a GeoDataFrame."""
    from shapely.geometry import LineString
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
                "volcán_codigo": volcán_codigo,
                "volcán_nombre": volcán_nombre,
                "fuente": "OSM",
            })
    if not features:
        return None
    return gpd.GeoDataFrame(features, crs="EPSG:4326")


# ---------------------------------------------------------------------------
# Descarga principal
# ---------------------------------------------------------------------------

def descargar_hidrografia():
    output = RAW / "hidrografia_osm.gpkg"
    if output.exists():
        print(f"[✓] {output} ya existe. Borra el archivo para re-descargar.")
        return

    gdfs = []
    for v in tqdm(VOLCANES, desc="Descargando hidrografía OSM"):
        nombre = v["nombre"]
        codigo = v["codigo"]
        lat, lon = v["lat"], v["lon"]

        try:
            data = query_overpass(lat, lon, radio_km=50)
            gdf = overpass_to_geodataframe(data, codigo, nombre)
            if gdf is not None and len(gdf) > 0:
                gdfs.append(gdf)
                print(f"  {nombre}: {len(gdf)} tramos descargados")
            else:
                print(f"  {nombre}: sin datos OSM")
        except Exception as e:
            print(f"  [!] Error en {nombre}: {e}")

        time.sleep(2)  # respetar rate limit de Overpass

    if gdfs:
        import pandas as pd
        result = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True), crs="EPSG:4326")
        result.to_file(output, driver="GPKG")
        print(f"\n[✓] Guardado: {output} ({len(result)} tramos totales)")
    else:
        print("[!] No se descargaron datos.")


if __name__ == "__main__":
    descargar_hidrografia()
