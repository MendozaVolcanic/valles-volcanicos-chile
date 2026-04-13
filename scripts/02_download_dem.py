"""
02_download_dem.py
------------------
Descarga DEM SRTM (30m, 1 arc-second) para cada volcan.
Fuente: AWS S3 elevation-tiles-prod (Mapzen/Tilezen) - publico, sin API key.

Formato de tiles: S{lat}W{lon}.hgt.gz  (1x1 grado)
Un volcan puede requerir multiples tiles si su radio cae en varios grados.

Salida: data/raw/dem/{CODIGO}_dem.tif  (mosaico recortado por volcan)
"""

import requests
import gzip
import struct
import numpy as np
import yaml
import sys
import time
from pathlib import Path
from tqdm import tqdm

try:
    import rasterio
    from rasterio.transform import from_bounds
    from rasterio.merge import merge
    from rasterio.mask import mask as rio_mask
    from shapely.geometry import box, mapping
except ImportError:
    raise ImportError("pip install rasterio shapely")

RAW     = Path("data/raw")
RAW_DEM = RAW / "dem"
RAW_HGT = RAW / "hgt_cache"  # cache de tiles crudos
RAW_DEM.mkdir(parents=True, exist_ok=True)
RAW_HGT.mkdir(parents=True, exist_ok=True)

CONFIG   = yaml.safe_load(open("config/volcanoes.yaml"))
VOLCANES = CONFIG["volcanes"]

RADIO_KM  = 60
AWS_BASE  = "https://s3.amazonaws.com/elevation-tiles-prod/skadi"


def tile_name(lat, lon):
    """
    Retorna el nombre del tile SRTM que contiene el punto (lat, lon).
    Ej: lat=-39.4, lon=-71.9 -> 'S40/S40W072'
    """
    lat_floor = int(np.floor(lat))
    lon_floor = int(np.floor(lon))

    ns = "N" if lat_floor >= 0 else "S"
    ew = "E" if lon_floor >= 0 else "W"

    lat_abs = abs(lat_floor) if lat_floor >= 0 else abs(lat_floor)
    lon_abs = abs(lon_floor) if lon_floor >= 0 else abs(lon_floor)

    folder = f"{ns}{lat_abs:02d}"
    name   = f"{ns}{lat_abs:02d}{ew}{lon_abs:03d}"
    return folder, name


def tiles_para_bbox(lat, lon, radio_km):
    """Retorna todos los tiles necesarios para cubrir el bbox del volcan."""
    delta = radio_km / 111.0
    lats = np.arange(int(np.floor(lat - delta)), int(np.floor(lat + delta)) + 1)
    lons = np.arange(int(np.floor(lon - delta)), int(np.floor(lon + delta)) + 1)
    tiles = set()
    for la in lats:
        for lo in lons:
            folder, name = tile_name(la + 0.5, lo + 0.5)  # centro del tile
            tiles.add((folder, name))
    return tiles


def descargar_tile(folder, name):
    """Descarga y descomprime un tile .hgt.gz desde AWS. Retorna path al .hgt."""
    hgt_path = RAW_HGT / f"{name}.hgt"
    if hgt_path.exists():
        return hgt_path

    url = f"{AWS_BASE}/{folder}/{name}.hgt.gz"
    try:
        resp = requests.get(url, timeout=60, stream=True)
        if resp.status_code == 404:
            return None  # tile sobre el oceano o sin datos
        resp.raise_for_status()

        gz_data = b"".join(resp.iter_content(chunk_size=65536))
        hgt_data = gzip.decompress(gz_data)

        with open(hgt_path, "wb") as f:
            f.write(hgt_data)
        return hgt_path

    except Exception as e:
        print(f"    [!] Error descargando {name}: {e}", flush=True)
        return None


def hgt_to_tif(hgt_path, tif_path):
    """
    Convierte un .hgt (SRTM 1-arc-second) a GeoTIFF con rasterio.
    Un tile SRTM GL1 = 3601x3601 muestras, 1 grado x 1 grado.
    """
    # Extraer lat/lon del nombre: S40W072 -> lat=-40, lon=-72
    name = hgt_path.stem  # ej "S40W072"
    ns = 1 if name[0] == "N" else -1
    ew = 1 if "E" in name else -1

    idx_ew = name.index("E") if "E" in name else name.index("W")
    lat_abs = int(name[1:idx_ew])
    lon_abs = int(name[idx_ew+1:])

    lat0 = ns * lat_abs
    lon0 = ew * lon_abs

    # Leer datos binarios HGT
    data = np.frombuffer(open(hgt_path, "rb").read(), dtype=">i2")
    size = int(np.sqrt(len(data)))  # 3601 para SRTM GL1
    NODATA = -9999.0
    data = data.reshape((size, size)).astype(np.float32)
    data[data == -32768] = NODATA

    transform = from_bounds(
        west=lon0, south=lat0,
        east=lon0 + 1, north=lat0 + 1,
        width=size, height=size
    )

    with rasterio.open(
        tif_path, "w",
        driver="GTiff",
        height=size, width=size,
        count=1, dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=NODATA,
        compress="lzw",
    ) as dst:
        dst.write(data, 1)


def construir_dem_volcan(v):
    """
    Descarga tiles SRTM necesarios y construye un mosaico recortado
    alrededor del volcan.
    """
    nombre = v["nombre"]
    codigo = v["codigo"]
    lat, lon = v["lat"], v["lon"]

    output = RAW_DEM / f"{codigo}_dem.tif"
    if output.exists():
        print(f"  [skip] {nombre}: ya existe", flush=True)
        return True

    print(f"  {nombre}...", end=" ", flush=True)

    tiles = tiles_para_bbox(lat, lon, RADIO_KM)
    tif_paths = []

    for folder, name in sorted(tiles):
        tif_cache = RAW_HGT / f"{name}.tif"
        if not tif_cache.exists():
            hgt = descargar_tile(folder, name)
            if hgt is None:
                continue
            hgt_to_tif(hgt, tif_cache)
        tif_paths.append(tif_cache)

    if not tif_paths:
        print("sin tiles disponibles")
        return False

    # Mosaico de tiles
    datasets = [rasterio.open(p) for p in tif_paths]
    mosaic, mosaic_transform = merge(datasets)
    for ds in datasets:
        ds.close()

    # Recortar al bbox del volcan
    delta = RADIO_KM / 111.0
    bbox_geom = box(lon - delta, lat - delta, lon + delta, lat + delta)

    meta = datasets[0].meta.copy()
    meta.update({
        "driver": "GTiff",
        "height": mosaic.shape[1],
        "width": mosaic.shape[2],
        "transform": mosaic_transform,
        "compress": "lzw",
    })

    # Guardar mosaico temporal y recortar
    tmp = RAW_DEM / f"{codigo}_mosaic_tmp.tif"
    with rasterio.open(tmp, "w", **meta) as dst:
        dst.write(mosaic)

    NODATA_OUT = -9999.0
    with rasterio.open(tmp) as src:
        out_img, out_transform = rio_mask(src, [mapping(bbox_geom)], crop=True, nodata=NODATA_OUT)
        out_meta = src.meta.copy()
        out_meta.update({
            "height": out_img.shape[1],
            "width": out_img.shape[2],
            "transform": out_transform,
            "nodata": NODATA_OUT,
        })

    with rasterio.open(output, "w", **out_meta) as dst:
        dst.write(out_img)

    tmp.unlink(missing_ok=True)

    size_mb = output.stat().st_size / 1e6
    print(f"{len(tif_paths)} tiles, {size_mb:.1f} MB", flush=True)
    return True


def main():
    ya = sum(1 for v in VOLCANES if (RAW_DEM / f"{v['codigo']}_dem.tif").exists())
    pendientes = [v for v in VOLCANES if not (RAW_DEM / f"{v['codigo']}_dem.tif").exists()]

    print(f"DEM SRTM (AWS S3, ~30m): {len(VOLCANES)} volcanes")
    print(f"  Ya descargados: {ya} | Pendientes: {len(pendientes)}\n")

    for v in tqdm(pendientes, desc="DEMs", file=sys.stdout):
        construir_dem_volcan(v)
        time.sleep(0.5)

    print(f"\n[OK] DEMs en: {RAW_DEM}")


if __name__ == "__main__":
    main()
