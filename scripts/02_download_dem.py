"""
02_download_dem.py
------------------
Descarga DEM SRTM (30m) para cada volcán desde OpenTopography API pública.
SRTM GL1 (1 arc-second ~30m) es suficiente para delineación de cuencas.

Salida: data/raw/dem/{CODIGO}_dem.tif  (uno por volcán)

API pública de OpenTopography:
https://portal.opentopography.org/apidocs/#/Public/getGlobalDem
"""

import requests
import yaml
from pathlib import Path
from tqdm import tqdm
import time

RAW = Path("data/raw/dem")
RAW.mkdir(parents=True, exist_ok=True)

CONFIG = yaml.safe_load(open("config/volcanoes.yaml"))
VOLCANES = CONFIG["volcanes"]

# Radio de descarga alrededor del volcán (km)
RADIO_KM = 60

OPENTOPO_URL = "https://portal.opentopography.org/API/globaldem"


def bbox_volcán(lat, lon, radio_km):
    delta = radio_km / 111.0
    return {
        "south": lat - delta,
        "north": lat + delta,
        "west": lon - delta,
        "east": lon + delta,
    }


def descargar_dem(volcán, radio_km=RADIO_KM, dem_type="SRTMGL1"):
    nombre = volcán["nombre"]
    codigo = volcán["codigo"]
    lat, lon = volcán["lat"], volcán["lon"]

    output = RAW / f"{codigo}_dem.tif"
    if output.exists():
        return f"[skip] {nombre}: ya existe"

    bbox = bbox_volcán(lat, lon, radio_km)
    params = {
        "demtype": dem_type,
        "south": bbox["south"],
        "north": bbox["north"],
        "west": bbox["west"],
        "east": bbox["east"],
        "outputFormat": "GTiff",
    }

    try:
        resp = requests.get(OPENTOPO_URL, params=params, timeout=120, stream=True)
        resp.raise_for_status()
        with open(output, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        size_mb = output.stat().st_size / 1e6
        return f"[✓] {nombre}: {size_mb:.1f} MB"
    except Exception as e:
        return f"[!] {nombre}: {e}"


def main():
    print(f"Descargando DEM SRTM para {len(VOLCANES)} volcanes...")
    print(f"Radio: {RADIO_KM} km | Resolución: ~30m\n")

    for v in tqdm(VOLCANES):
        resultado = descargar_dem(v)
        print(f"  {resultado}")
        time.sleep(1)

    print(f"\n[✓] DEMs en: {RAW}")


if __name__ == "__main__":
    main()
