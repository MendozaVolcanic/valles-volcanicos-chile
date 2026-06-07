"""
14_usgs_sismos.py
-----------------
Descarga sismos USGS ComCat (FDSN GeoJSON) de los ultimos 7 dias para cada
volcan del catalogo (bbox ~55 km, M>=2).

POR QUE:
  El servicio FDSN de USGS (ComCat) es la fuente publica mas estable de
  catalogos sismicos globales. Para Chile remoto la cobertura tipica es
  M>=3.5 (red telesismica), y M>=2.5 cerca de zonas pobladas. Sirve como
  contexto sismico de fondo para cada volcan del dashboard, complementario
  a la sismicidad volcanica monitoreada por OVDAS.

PROCESO POR VOLCAN:
  1. Bbox = [lon-0.5, lat-0.5, lon+0.5, lat+0.5] (~55 km lado)
  2. Ventana = ahora - 7 dias .. ahora (UTC)
  3. Query FDSN GeoJSON, parsea features
  4. Guarda FeatureCollection en data/processed/sismos/{codigo}.geojson
     (vacio si no hay eventos)
  5. Acumula resumen: n_sismos, mag_max, mag_promedio, mas_reciente

Rate limit: 1.1 s entre volcanes (USGS recomienda <=1 req/s).

Salidas:
  - data/processed/sismos/{codigo}.geojson  (59 archivos)
  - data/processed/sismos_resumen.csv       (1 fila por volcan)
"""
from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

import yaml

ROOT     = Path(__file__).resolve().parent.parent
CONFIG   = ROOT / "config" / "volcanoes.yaml"
OUT_DIR  = ROOT / "data" / "processed" / "sismos"
RESUMEN  = ROOT / "data" / "processed" / "sismos_resumen.csv"

ENDPOINT = "https://earthquake.usgs.gov/fdsnws/event/1/query"
HALF_DEG = 0.5           # ~55 km a lat -30
MIN_MAG  = 2.0
DAYS     = 7
SLEEP_S  = 1.1
TIMEOUT  = 30
UA       = "valles-volcanicos-chile/1.0 (research; USGS FDSN client)"


def cargar_volcanes() -> list[dict]:
    with CONFIG.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data["volcanes"]


def consultar_usgs(lat: float, lon: float, t_ini: str, t_fin: str) -> dict:
    params = {
        "format": "geojson",
        "starttime": t_ini,
        "endtime":   t_fin,
        "minlatitude":  lat - HALF_DEG,
        "maxlatitude":  lat + HALF_DEG,
        "minlongitude": lon - HALF_DEG,
        "maxlongitude": lon + HALF_DEG,
        "minmagnitude": MIN_MAG,
    }
    url = f"{ENDPOINT}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/geo+json"})
    with urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def feature_compacto(feat: dict) -> dict:
    """Conserva solo campos clave: mag, place, time, depth, type, status, lon, lat."""
    props = feat.get("properties", {}) or {}
    geom  = feat.get("geometry", {}) or {}
    coords = geom.get("coordinates") or [None, None, None]
    lon, lat = coords[0], coords[1]
    depth    = coords[2] if len(coords) > 2 else None
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat, depth]},
        "properties": {
            "mag":    props.get("mag"),
            "place":  props.get("place"),
            "time":   props.get("time"),      # ms UTC
            "depth":  depth,                  # km
            "type":   props.get("type"),
            "status": props.get("status"),
            "lon":    lon,
            "lat":    lat,
        },
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    volcanes = cargar_volcanes()

    ahora  = datetime.now(timezone.utc).replace(microsecond=0)
    inicio = ahora - timedelta(days=DAYS)
    t_ini  = inicio.strftime("%Y-%m-%dT%H:%M:%S")
    t_fin  = ahora.strftime("%Y-%m-%dT%H:%M:%S")

    print(f"Ventana: {t_ini}Z .. {t_fin}Z (UTC), M>={MIN_MAG}")
    print(f"Volcanes: {len(volcanes)}\n")

    filas = []
    errores = []

    for i, v in enumerate(volcanes, 1):
        codigo = v["codigo"]
        nombre = v["nombre"]
        lat, lon = v["lat"], v["lon"]

        try:
            data = consultar_usgs(lat, lon, t_ini, t_fin)
            feats_raw = data.get("features", []) or []
        except (HTTPError, URLError, json.JSONDecodeError, TimeoutError) as e:
            print(f"  [{i:02d}/59] {codigo:<4} {nombre:<25} ERROR: {e}")
            errores.append((codigo, str(e)))
            # Igual genero shard vacio para que el dashboard no rompa
            feats_raw = []
            data = {}

        feats = [feature_compacto(f) for f in feats_raw]

        fc = {
            "type": "FeatureCollection",
            "metadata": {
                "volcan":     nombre,
                "codigo":     codigo,
                "lat":        lat,
                "lon":        lon,
                "bbox":       [lon - HALF_DEG, lat - HALF_DEG, lon + HALF_DEG, lat + HALF_DEG],
                "starttime":  f"{t_ini}Z",
                "endtime":    f"{t_fin}Z",
                "minmagnitude": MIN_MAG,
                "source":     "USGS FDSN ComCat",
                "generated":  ahora.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "count":      len(feats),
            },
            "features": feats,
        }

        shard_path = OUT_DIR / f"{codigo}.geojson"
        with shard_path.open("w", encoding="utf-8") as fh:
            json.dump(fc, fh, ensure_ascii=False)

        # Resumen
        if feats:
            mags  = [f["properties"]["mag"] for f in feats if f["properties"]["mag"] is not None]
            times = [f["properties"]["time"] for f in feats if f["properties"]["time"] is not None]
            mag_max = max(mags) if mags else None
            mag_avg = round(sum(mags) / len(mags), 2) if mags else None
            t_max   = max(times) if times else None
            mas_reciente = (
                datetime.fromtimestamp(t_max / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if t_max is not None else ""
            )
        else:
            mag_max = None
            mag_avg = None
            mas_reciente = ""

        filas.append({
            "codigo":        codigo,
            "nombre":        nombre,
            "lat":           lat,
            "lon":           lon,
            "n_sismos":      len(feats),
            "mag_max":       mag_max if mag_max is not None else "",
            "mag_promedio":  mag_avg if mag_avg is not None else "",
            "mas_reciente":  mas_reciente,
        })

        flag = "OK" if len(feats) > 0 else "..."
        print(f"  [{i:02d}/59] {codigo:<4} {nombre:<25} {flag} n={len(feats):>3}  "
              f"mag_max={mag_max if mag_max is not None else '-'}")

        time.sleep(SLEEP_S)

    # CSV resumen
    with RESUMEN.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "codigo", "nombre", "lat", "lon",
            "n_sismos", "mag_max", "mag_promedio", "mas_reciente",
        ])
        w.writeheader()
        w.writerows(filas)

    total = sum(r["n_sismos"] for r in filas)
    print()
    print(f"Total sismos (suma 59 bbox, con overlap posible): {total}")
    print(f"Resumen escrito: {RESUMEN}")
    print(f"Shards en:       {OUT_DIR}")
    if errores:
        print(f"\nErrores: {len(errores)}")
        for cod, msg in errores:
            print(f"  {cod}: {msg}")

    # Top 5
    top = sorted(filas, key=lambda r: r["n_sismos"], reverse=True)[:5]
    print("\nTop 5 volcanes por n_sismos:")
    for r in top:
        print(f"  {r['codigo']:<4} {r['nombre']:<25} n={r['n_sismos']:<3}  mag_max={r['mag_max']}")

    # Volcan con mag_max global
    con_mag = [r for r in filas if r["mag_max"] != ""]
    if con_mag:
        peor = max(con_mag, key=lambda r: r["mag_max"])
        print(f"\nVolcan con sismo de mayor magnitud:")
        print(f"  {peor['codigo']} {peor['nombre']}  M={peor['mag_max']}  ({peor['mas_reciente']})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
