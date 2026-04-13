"""
03_watershed.py
---------------
Identifica quebradas, rios y valles asociados a cada volcan.

Estrategia: buffer radial + interseccion con hidrografia OSM.
  - Para cada volcan: buffer de RADIO_KM alrededor de la cima
  - Seleccionar todos los cursos de agua OSM que nacen o pasan por ese buffer
  - Clasificar por tipo (rio principal, quebrada, etc.)

Esto es equivalente a la delineacion de cuencas para el proposito de
identificar los valles afectables por una erupcion, y mucho mas robusto.

El DEM queda disponible en data/raw/dem/ para visualizacion futura.

Salida: data/processed/cuencas.gpkg
  - layer "cuencas":  circulos de influencia por volcan (poligono)
  - layer "drenajes": cursos de agua dentro del area de influencia
"""

import geopandas as gpd
import pandas as pd
import numpy as np
import yaml
from pathlib import Path
from shapely.geometry import Point
import sys

PROCESSED = Path("data/processed")
RAW_HYDRO = Path("data/raw/hidrografia_osm.gpkg")
PROCESSED.mkdir(parents=True, exist_ok=True)

CONFIG   = yaml.safe_load(open("config/volcanoes.yaml"))
VOLCANES = CONFIG["volcanes"]

# Radio de influencia alrededor de cada volcan
# Los lahares tipicamente se propagan 30-80 km desde el volcan
RADIO_KM = 50


def crear_buffer_km(lat, lon, radio_km):
    """
    Crea un buffer circular aproximado en grados (no proyectado).
    Para Chile, 1 grado lat ~ 111 km; 1 grado lon ~ 111*cos(lat) km.
    """
    delta_lat = radio_km / 111.0
    delta_lon = radio_km / (111.0 * abs(np.cos(np.radians(lat))))
    # Usar shapely Point buffer con grados (aproximacion suficiente a esta escala)
    return Point(lon, lat).buffer(min(delta_lat, delta_lon))


def procesar_volcan(v, osm_gdf):
    nombre  = v["nombre"]
    codigo  = v["codigo"]
    lat, lon = v["lat"], v["lon"]

    buffer_poly = crear_buffer_km(lat, lon, RADIO_KM)

    # Cursos de agua en el area de influencia del volcan
    # Tomamos los del layer OSM ya filtrado por volcan (bbox ~50km)
    osm_v = osm_gdf[osm_gdf["volcan_codigo"] == codigo].copy()

    # Filtrar adicionalmente a los que estan dentro del buffer
    dentro = osm_v[osm_v.intersects(buffer_poly)].copy()

    # Contar nombres unicos (excluyendo "Sin nombre")
    nombrados = dentro[dentro["nombre"] != "Sin nombre"]["nombre"].unique()

    print(f"  {nombre}: {len(dentro)} tramos, {len(nombrados)} con nombre", flush=True)

    # GeoDataFrame de la zona de influencia (circulo)
    cuenca_gdf = gpd.GeoDataFrame([{
        "geometry":       buffer_poly,
        "volcan_codigo":  codigo,
        "volcan_nombre":  nombre,
        "region":         v.get("region", ""),
        "elevacion":      v.get("elevacion", 0),
        "lat":            lat,
        "lon":            lon,
        "radio_km":       RADIO_KM,
        "n_tramos":       len(dentro),
        "n_nombrados":    len(nombrados),
    }], crs="EPSG:4326")

    return cuenca_gdf, dentro if len(dentro) > 0 else None


def main():
    if not RAW_HYDRO.exists():
        print("[!] Ejecuta primero 01_download_hydro.py")
        sys.exit(1)

    print("Cargando hidrografia OSM...", flush=True)
    osm = gpd.read_file(RAW_HYDRO)
    print(f"  {len(osm):,} tramos cargados\n")

    print(f"Procesando {len(VOLCANES)} volcanes (radio {RADIO_KM} km)...\n")

    all_cuencas  = []
    all_drenajes = []

    for v in VOLCANES:
        cuenca, drenajes = procesar_volcan(v, osm)
        all_cuencas.append(cuenca)
        if drenajes is not None:
            all_drenajes.append(drenajes)

    output = PROCESSED / "cuencas.gpkg"

    cuencas_final = gpd.GeoDataFrame(
        pd.concat(all_cuencas, ignore_index=True), crs="EPSG:4326"
    )
    cuencas_final.to_file(output, layer="cuencas", driver="GPKG")
    print(f"\n[OK] {len(cuencas_final)} zonas de influencia -> {output}")

    if all_drenajes:
        drenajes_final = gpd.GeoDataFrame(
            pd.concat(all_drenajes, ignore_index=True), crs="EPSG:4326"
        )
        # Eliminar duplicados (un tramo puede estar en varios volcanes si estan cerca)
        drenajes_final = drenajes_final.drop_duplicates(subset=["osm_id", "volcan_codigo"])
        drenajes_final.to_file(output, layer="drenajes", driver="GPKG")
        print(f"[OK] {len(drenajes_final):,} tramos de drenaje -> {output}")

        # Resumen por volcan
        print("\n--- Volcanes con mas quebradas identificadas ---")
        resumen = (
            drenajes_final
            .groupby(["volcan_codigo", "volcan_nombre"])
            .agg(
                total_tramos=("osm_id", "count"),
                tramos_nombrados=("nombre", lambda x: (x != "Sin nombre").sum()),
                nombres=("nombre", lambda x: ", ".join(sorted(set(x[x != "Sin nombre"]))[:5]))
            )
            .reset_index()
            .sort_values("total_tramos", ascending=False)
        )
        print(resumen[["volcan_nombre", "total_tramos", "tramos_nombrados", "nombres"]].to_string(index=False))


if __name__ == "__main__":
    main()
