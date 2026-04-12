"""
03_watershed.py
---------------
Delinea cuencas hidrográficas que nacen de cada volcán usando pysheds.

Proceso por volcán:
  1. Leer DEM .tif
  2. Rellenar depresiones (fill pits)
  3. Calcular dirección de flujo (flow direction)
  4. Calcular acumulación de flujo (flow accumulation)
  5. Definir punto de partida = cima del volcán
  6. Delinear cuenca que drena desde ese punto
  7. Extraer red de drenaje (umbral de acumulación)
  8. Guardar polígono de cuenca + líneas de drenaje

Salida: data/processed/cuencas.gpkg
         - layer "cuencas":  polígonos de cuenca por volcán
         - layer "drenajes": red de drenaje con nombres OSM cruzados
"""

import numpy as np
import geopandas as gpd
import pandas as pd
from pathlib import Path
from shapely.geometry import shape, LineString, mapping
import yaml
import rasterio
from rasterio.transform import from_bounds
import warnings
warnings.filterwarnings("ignore")

try:
    from pysheds.grid import Grid
except ImportError:
    raise ImportError("Instala pysheds: pip install pysheds")

RAW_DEM = Path("data/raw/dem")
RAW_HYDRO = Path("data/raw/hidrografia_osm.gpkg")
PROCESSED = Path("data/processed")
PROCESSED.mkdir(parents=True, exist_ok=True)

CONFIG = yaml.safe_load(open("config/volcanoes.yaml"))
VOLCANES = CONFIG["volcanes"]

# Umbral de acumulación para definir red de drenaje
# Valores menores → más quebradas pequeñas
ACUM_THRESHOLD = 500  # celdas (~4.5 km² en SRTM 30m)


def delinear_cuenca(dem_path, lat_cima, lon_cima):
    """
    Delinea la cuenca que drena desde la cima del volcán.
    Retorna (polígono_cuenca, GeoDataFrame_drenajes) o (None, None) si falla.
    """
    grid = Grid.from_raster(str(dem_path))
    dem = grid.read_raster(str(dem_path))

    # Preprocesamiento
    pit_filled = grid.fill_pits(dem)
    flooded = grid.fill_depressions(pit_filled)
    inflated = grid.resolve_flats(flooded)

    # Dirección y acumulación de flujo
    fdir = grid.flowdir(inflated)
    acc = grid.accumulation(fdir)

    # Punto de inicio = cima del volcán (coordenadas → celda del grid)
    col, row = grid.nearest_cell(lon_cima, lat_cima)

    # Delinear cuenca desde la cima
    try:
        catch = grid.catchment(fdir, x=col, y=row, xytype='index')
    except Exception:
        return None, None

    # Recortar grid a la cuenca
    grid.clip_to(catch)
    catch_view = grid.view(catch)

    # Extraer polígono de cuenca
    shapes = list(grid.polygonize(catch_view))
    if not shapes:
        return None, None

    # El polígono más grande es la cuenca
    polys = [(shape(s), v) for s, v in shapes if v == 1]
    if not polys:
        return None, None
    cuenca_poly = max(polys, key=lambda x: x[0].area)[0]

    # Extraer red de drenaje (celdas con acumulación > umbral)
    acc_view = grid.view(acc)
    mask = acc_view > ACUM_THRESHOLD

    # Convertir celdas de drenaje a líneas (simplificado)
    drenaje_lines = []
    rows_idx, cols_idx = np.where(mask)
    if len(rows_idx) > 0:
        # Extraer coordenadas de los puntos de drenaje
        xs, ys = grid.affine * (cols_idx, rows_idx)
        # Agrupar en segmentos de línea simples (aproximación)
        if len(xs) > 1:
            coords = list(zip(xs.tolist(), ys.tolist()))
            # Crear líneas por segmentos de 10 puntos
            for i in range(0, len(coords) - 1, 10):
                seg = coords[i:i+12]
                if len(seg) >= 2:
                    drenaje_lines.append(LineString(seg))

    return cuenca_poly, drenaje_lines


def cruzar_con_osm(drenajes_gdf, cuenca_poly, volcán_codigo):
    """Cruza drenajes calculados con nombres OSM para asignar nombres."""
    if not RAW_HYDRO.exists():
        return drenajes_gdf

    try:
        osm = gpd.read_file(RAW_HYDRO)
        osm_v = osm[osm["volcán_codigo"] == volcán_codigo].copy()
        if osm_v.empty:
            return drenajes_gdf

        # Filtrar OSM a los que están dentro de la cuenca
        osm_en_cuenca = osm_v[osm_v.intersects(cuenca_poly)]
        return osm_en_cuenca[["geometry", "nombre", "tipo", "volcán_codigo", "volcán_nombre"]]
    except Exception:
        return drenajes_gdf


def procesar_volcán(v):
    nombre = v["nombre"]
    codigo = v["codigo"]
    lat, lon = v["lat"], v["lon"]

    dem_path = RAW_DEM / f"{codigo}_dem.tif"
    if not dem_path.exists():
        print(f"  [!] {nombre}: sin DEM, omitido")
        return None, None

    print(f"  Procesando {nombre}...")
    try:
        cuenca_poly, drenaje_lines = delinear_cuenca(dem_path, lat, lon)
    except Exception as e:
        print(f"  [!] {nombre}: error en delineación — {e}")
        return None, None

    if cuenca_poly is None:
        print(f"  [!] {nombre}: no se pudo delinear cuenca")
        return None, None

    # GeoDataFrame de cuenca
    cuenca_gdf = gpd.GeoDataFrame([{
        "geometry": cuenca_poly,
        "volcán_codigo": codigo,
        "volcán_nombre": nombre,
        "lat": lat,
        "lon": lon,
        "region": v.get("region", ""),
        "elevacion": v.get("elevacion", 0),
        "area_km2": cuenca_poly.area * (111**2),  # aprox
    }], crs="EPSG:4326")

    # GeoDataFrame de drenajes (desde OSM principalmente)
    drenajes_gdf = cruzar_con_osm(None, cuenca_poly, codigo)

    area = cuenca_poly.area * (111**2)
    n_drenajes = len(drenajes_gdf) if drenajes_gdf is not None else 0
    print(f"  [✓] {nombre}: cuenca ~{area:.0f} km², {n_drenajes} tramos de drenaje")

    return cuenca_gdf, drenajes_gdf


def main():
    print(f"Delineando cuencas para {len(VOLCANES)} volcanes...\n")

    all_cuencas = []
    all_drenajes = []

    for v in VOLCANES:
        cuenca, drenajes = procesar_volcán(v)
        if cuenca is not None:
            all_cuencas.append(cuenca)
        if drenajes is not None and len(drenajes) > 0:
            all_drenajes.append(drenajes)

    output = PROCESSED / "cuencas.gpkg"

    if all_cuencas:
        cuencas_final = gpd.GeoDataFrame(
            pd.concat(all_cuencas, ignore_index=True), crs="EPSG:4326"
        )
        cuencas_final.to_file(output, layer="cuencas", driver="GPKG")
        print(f"\n[✓] {len(cuencas_final)} cuencas guardadas → {output}")

    if all_drenajes:
        drenajes_final = gpd.GeoDataFrame(
            pd.concat(all_drenajes, ignore_index=True), crs="EPSG:4326"
        )
        drenajes_final.to_file(output, layer="drenajes", driver="GPKG")
        print(f"[✓] {len(drenajes_final)} tramos de drenaje guardados → {output}")


if __name__ == "__main__":
    main()
