"""
06_watershed_pysheds.py
-----------------------
Identificacion HIDROLOGICA REAL de quebradas que drenan desde cada volcan.

A diferencia de 03_watershed.py (buffer geometrico de 50 km), este script
usa el DEM para determinar que tramos OSM realmente reciben flujo desde
el edificio volcanico — lo que importa para evaluar lahares.

Algoritmo por volcan:
  1. Cargar DEM (SRTM 30m).
  2. Condicionar: fill pits + resolve flats.
  3. Calcular direccion de flujo (D8, codificacion ESRI por defecto).
  4. Definir "mascara edificio" = celdas dentro de ~3 km del crater (en UTM).
  5. Trazar AGUAS ABAJO desde cada celda del edificio siguiendo fdir hasta
     salir del DEM o ciclar (downstream BFS).
  6. Por cada tramo OSM dentro del buffer 50 km del volcan, evaluar si su
     geometria intersecta la mascara downstream. Si si -> drena_volcan=True.

Salida:
  data/processed/cuencas.gpkg, layer "drenajes": columna nueva 'drena_volcan'.
  data/processed/drenajes/{codigo}.geojson: re-exportado con la columna.

NOTA: usa la misma geometria de tramos que 03_watershed.py, solo agrega
una clasificacion. No reemplaza el buffer geometrico — lo complementa.
"""
from pathlib import Path
import sys
import warnings
import numpy as np
import geopandas as gpd
import pandas as pd
import rasterio
import yaml
from pysheds.grid import Grid
from shapely.geometry import LineString, MultiLineString, Point
from tqdm import tqdm

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="pysheds")

ROOT      = Path(__file__).resolve().parent.parent
DEM_DIR   = ROOT / "data" / "raw" / "dem"
GPKG      = ROOT / "data" / "processed" / "cuencas.gpkg"
CONFIG    = ROOT / "config" / "volcanoes.yaml"

# Radio del "edificio volcanico" — celdas DEM dentro de este radio son
# semillas para el trazado aguas abajo. 3 km cubre el cono y parasitos
# sin extenderse a planicies bajas que ya no producen lahares.
RADIO_EDIFICIO_KM = 3.0

# Direcciones D8 ESRI: codigo -> (drow, dcol). drow positivo = abajo.
D8_ESRI = {
    64: (-1,  0),   # N
    128: (-1, 1),   # NE
    1:  (0,  1),    # E
    2:  (1,  1),    # SE
    4:  (1,  0),    # S
    8:  (1, -1),    # SW
    16: (0, -1),    # W
    32: (-1, -1),   # NW
}


def downstream_mask_from_seeds(fdir: np.ndarray, seed_mask: np.ndarray) -> np.ndarray:
    """Mascara booleana de celdas alcanzables aguas abajo desde seed_mask.
    Trazado iterativo siguiendo D8 fdir hasta salir del DEM o ciclar."""
    nrows, ncols = fdir.shape
    visited = np.zeros((nrows, ncols), dtype=bool)
    # Cola inicial con celdas del edificio
    seed_rc = np.argwhere(seed_mask)
    queue = [(int(r), int(c)) for r, c in seed_rc]
    while queue:
        r, c = queue.pop()
        if visited[r, c]:
            continue
        visited[r, c] = True
        d = int(fdir[r, c])
        if d not in D8_ESRI:
            continue
        dr, dc = D8_ESRI[d]
        nr, nc = r + dr, c + dc
        if 0 <= nr < nrows and 0 <= nc < ncols and not visited[nr, nc]:
            queue.append((nr, nc))
    return visited


def latlon_a_utm_epsg(lat: float, lon: float) -> int:
    """EPSG UTM/WGS84 segun zona y hemisferio."""
    zone = int((lon + 180) / 6) + 1
    return (32700 if lat < 0 else 32600) + zone


def edifice_mask(dem_shape, transform, lat_v: float, lon_v: float, radio_km: float) -> np.ndarray:
    """Mascara booleana de celdas dentro de radio_km del crater."""
    # Aproximacion: convertir radio_km a grados ajustado por latitud.
    delta_lat = radio_km / 111.0
    delta_lon = radio_km / (111.0 * abs(np.cos(np.radians(lat_v))))
    # rasterio transform: (lon_min, dx, 0, lat_max, 0, -dy)
    inv = ~transform
    rows, cols = dem_shape
    # Iterar solo el bbox del edificio para no recorrer todo el raster
    r_min, c_min = inv * (lon_v - delta_lon, lat_v + delta_lat)
    r_max, c_max = inv * (lon_v + delta_lon, lat_v - delta_lat)
    r_min, r_max = int(max(0, min(r_min, r_max))), int(min(rows, max(r_min, r_max) + 1))
    c_min, c_max = int(max(0, min(c_min, c_max))), int(min(cols, max(c_min, c_max) + 1))
    mask = np.zeros((rows, cols), dtype=bool)
    for r in range(r_min, r_max):
        for c in range(c_min, c_max):
            lon_rc, lat_rc = transform * (c + 0.5, r + 0.5)
            if (abs(lat_rc - lat_v) / delta_lat) ** 2 + (abs(lon_rc - lon_v) / delta_lon) ** 2 <= 1:
                mask[r, c] = True
    return mask


def tramo_toca_mascara(geom, transform_inv, mask: np.ndarray) -> bool:
    """True si algun nodo del LineString cae en una celda True del mask."""
    if geom is None or geom.is_empty:
        return False
    if isinstance(geom, MultiLineString):
        coords_iter = (list(g.coords) for g in geom.geoms)
    else:
        coords_iter = [list(geom.coords)]
    nrows, ncols = mask.shape
    for coords in coords_iter:
        for lon, lat in coords:
            c, r = transform_inv * (lon, lat)
            r, c = int(r), int(c)
            if 0 <= r < nrows and 0 <= c < ncols and mask[r, c]:
                return True
    return False


def procesar_volcan(v: dict, drenajes_v: gpd.GeoDataFrame) -> pd.Series:
    """Devuelve Serie booleana 'drena_volcan' indexada como drenajes_v."""
    codigo = v["codigo"]
    dem_path = DEM_DIR / f"{codigo}_dem.tif"
    if not dem_path.exists():
        return pd.Series(False, index=drenajes_v.index, name="drena_volcan")

    grid = Grid.from_raster(str(dem_path))
    dem  = grid.read_raster(str(dem_path))
    # Condicionar DEM: fill pits, resolve flats
    pit_filled = grid.fill_pits(dem)
    flooded    = grid.fill_depressions(pit_filled)
    inflated   = grid.resolve_flats(flooded)
    # Direccion D8 (codificacion ESRI por defecto)
    fdir = grid.flowdir(inflated)

    with rasterio.open(str(dem_path)) as src:
        transform = src.transform
        shape     = src.shape

    seeds = edifice_mask(shape, transform, v["lat"], v["lon"], RADIO_EDIFICIO_KM)
    if not seeds.any():
        return pd.Series(False, index=drenajes_v.index, name="drena_volcan")

    fdir_arr = np.asarray(fdir)
    mask_ds = downstream_mask_from_seeds(fdir_arr, seeds)
    inv = ~transform

    result = drenajes_v.geometry.apply(lambda g: tramo_toca_mascara(g, inv, mask_ds))
    result.name = "drena_volcan"
    return result


def main():
    if not GPKG.exists():
        print("[!] Falta data/processed/cuencas.gpkg — correr 03_watershed.py primero.")
        sys.exit(1)

    cfg = yaml.safe_load(open(CONFIG, encoding="utf-8"))
    volcanes = cfg["volcanes"]

    print("Cargando drenajes desde cuencas.gpkg...")
    drenajes = gpd.read_file(str(GPKG), layer="drenajes", engine="pyogrio")
    print(f"  {len(drenajes):,} tramos\n")

    drenajes["drena_volcan"] = False
    for v in tqdm(volcanes, desc="Volcanes"):
        sub_idx = drenajes.index[drenajes["volcan_codigo"] == v["codigo"]]
        if len(sub_idx) == 0:
            continue
        sub = drenajes.loc[sub_idx]
        try:
            flags = procesar_volcan(v, sub)
            drenajes.loc[sub_idx, "drena_volcan"] = flags.values
            n_drena = int(flags.sum())
            tqdm.write(f"  {v['codigo']:4s} {v['nombre']:24s}  {n_drena:5d}/{len(sub):5d} tramos drenan desde el edificio")
        except Exception as exc:
            tqdm.write(f"  [!] {v['codigo']} {v['nombre']}: {exc}")

    print(f"\nTotal tramos que drenan desde edificio: {int(drenajes['drena_volcan'].sum()):,} / {len(drenajes):,}")

    # Sobrescribir layer drenajes con la columna nueva
    drenajes.to_file(str(GPKG), layer="drenajes", driver="GPKG")
    print(f"[OK] {GPKG} actualizado con columna 'drena_volcan'")
    print("Ahora correr: python scripts/export_geojson.py")


if __name__ == "__main__":
    main()
