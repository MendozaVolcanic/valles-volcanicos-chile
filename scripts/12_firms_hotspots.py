"""
12_firms_hotspots.py
--------------------
Descarga hotspots térmicos NASA FIRMS (MODIS + VIIRS NRT) de los últimos 7
días para los 59 volcanes activos de Chile y los sharda por volcán.

Por qué FIRMS para este dashboard
---------------------------------
FIRMS publica detecciones de anomalías térmicas Near-Real-Time (NRT, latencia
~3 h) a partir de los radiómetros MODIS (Terra/Aqua) y VIIRS (S-NPP, NOAA-20,
NOAA-21). Cada hotspot es un pixel cuyo canal IR medio (MODIS B21/B22 a 4 μm,
VIIRS I4 a 3.74 μm) excede el background. Para un volcán activo, esos pixeles
suelen marcar emisión de lava, domos calientes o gases muy calientes en la
abertura — son el insumo crudo del producto VRP (Coppola et al., MIROVA).
Acá no calculamos VRP; sólo posicionamos las detecciones para que el geólogo
las cruce con drenajes, cuencas y comunidades en el dashboard.

Endpoint Area API
-----------------
    https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{SOURCE}/{AREA}/{DAY_RANGE}/{DATE}

- MAP_KEY: gratis, registrarse en https://firms.modaps.eosdis.nasa.gov/api/area/
- SOURCE: 4 fuentes NRT (MODIS_NRT, VIIRS_SNPP_NRT, VIIRS_NOAA20_NRT, VIIRS_NOAA21_NRT)
- AREA: "west,south,east,north" en grados decimales
- DAY_RANGE: 1..10 (acá 7)
- DATE: si se omite, defaultea a hoy → últimos 7 días desde hoy

Rate limit: 5000 transacciones / 10 min. 59 volcanes × 4 fuentes = 236 → OK.

Bbox por volcán: ±0.5° (~55 km lat, ~50 km lon a 30°S) cubre el campo
volcánico y un margen de drenaje proximal.

Uso
---
    set FIRMS_MAP_KEY=tu_key   (Windows)
    export FIRMS_MAP_KEY=tu_key (Linux/Mac)
    python scripts/12_firms_hotspots.py

Si no hay MAP_KEY válida, el script aborta con instrucciones.

Salida
------
- data/processed/firms/{codigo}.geojson  (59 archivos, FeatureCollection)
- Resumen por consola: total, top 5, FRP medio.
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests
import yaml

# ─────────────────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).resolve().parent.parent
CFG        = ROOT / "config" / "volcanoes.yaml"
OUT_DIR    = ROOT / "data" / "processed" / "firms"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# MAP_KEY: env var > placeholder. NUNCA hardcodear una key real acá.
MAP_KEY = os.environ.get("FIRMS_MAP_KEY", "YOUR_FIRMS_MAP_KEY").strip()

SOURCES   = ["MODIS_NRT", "VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT"]
DAY_RANGE = 7
BBOX_HALF = 0.5     # grados decimales (±0.5° ≈ 55 km en latitud)
TIMEOUT   = 60
SLEEP_S   = 0.15    # margen frente al rate limit 5000/10min

BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{src}/{area}/{days}"

# Columnas útiles del CSV FIRMS (varían leve entre MODIS y VIIRS)
KEEP_COLS = [
    "latitude", "longitude", "brightness", "bright_ti4", "bright_ti5",
    "scan", "track", "acq_date", "acq_time", "satellite", "instrument",
    "confidence", "version", "frp", "daynight",
]

# Cache en memoria: (source, bbox_redondeado) -> DataFrame
# Evita re-pedir bboxes solapados (Llaima/Lonquimay, Calbuco/Osorno, etc.)
_CACHE: dict[tuple[str, str], pd.DataFrame] = {}


def cargar_volcanes() -> list[dict]:
    with open(CFG, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["volcanes"]


def bbox_str(lon: float, lat: float) -> str:
    """west,south,east,north con 3 decimales (~110 m de granularidad)."""
    w = round(lon - BBOX_HALF, 3)
    s = round(lat - BBOX_HALF, 3)
    e = round(lon + BBOX_HALF, 3)
    n = round(lat + BBOX_HALF, 3)
    return f"{w},{s},{e},{n}"


def fetch_source(source: str, area: str) -> pd.DataFrame:
    """Devuelve DataFrame de hotspots para (source, bbox). Cachea por bbox."""
    cache_key = (source, area)
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    url = BASE_URL.format(key=MAP_KEY, src=source, area=area, days=DAY_RANGE)
    try:
        r = requests.get(url, timeout=TIMEOUT)
    except requests.RequestException as e:
        print(f"    [warn] {source} {area}: {e}")
        _CACHE[cache_key] = pd.DataFrame()
        return _CACHE[cache_key]

    # FIRMS devuelve 200 con cuerpo de texto incluso ante errores de key/cuota
    text = r.text.strip()
    if r.status_code != 200 or not text or text.lower().startswith("invalid"):
        if "invalid" in text.lower() or "error" in text.lower():
            print(f"    [warn] {source}: {text[:120]}")
        _CACHE[cache_key] = pd.DataFrame()
        return _CACHE[cache_key]

    # Si sólo viene el header (sin filas) → DF vacío con columnas
    try:
        df = pd.read_csv(io.StringIO(text))
    except Exception as e:
        print(f"    [warn] parse {source} {area}: {e}")
        df = pd.DataFrame()

    _CACHE[cache_key] = df
    time.sleep(SLEEP_S)
    return df


def normalizar(df: pd.DataFrame) -> pd.DataFrame:
    """Unifica columnas MODIS/VIIRS y se queda con KEEP_COLS disponibles."""
    if df.empty:
        return df
    cols = [c for c in KEEP_COLS if c in df.columns]
    out = df[cols].copy()
    # 'brightness' (MODIS) vs 'bright_ti4' (VIIRS) → expongo ambas y un alias
    if "brightness" not in out.columns and "bright_ti4" in out.columns:
        out["brightness"] = out["bright_ti4"]
    return out


def to_geojson(df: pd.DataFrame) -> dict:
    feats = []
    for _, r in df.iterrows():
        try:
            lon = float(r["longitude"])
            lat = float(r["latitude"])
        except (KeyError, ValueError, TypeError):
            continue
        props = {}
        for k in (
            "brightness", "frp", "confidence", "acq_date", "acq_time",
            "daynight", "satellite", "instrument",
        ):
            if k in df.columns:
                v = r.get(k)
                # serializar a tipos JSON nativos
                if pd.isna(v):
                    props[k] = None
                elif hasattr(v, "item"):
                    props[k] = v.item()
                else:
                    props[k] = v
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": props,
        })
    return {"type": "FeatureCollection", "features": feats}


def procesar_volcan(v: dict) -> tuple[int, float]:
    codigo = v["codigo"]
    area = bbox_str(v["lon"], v["lat"])

    dfs = []
    for src in SOURCES:
        df = fetch_source(src, area)
        df = normalizar(df)
        if not df.empty:
            dfs.append(df)

    if dfs:
        merged = pd.concat(dfs, ignore_index=True, sort=False)
        # de-dup por (lat, lon, acq_date, acq_time) — mismo pixel puede salir 2 sats
        dedup_keys = [c for c in ("latitude", "longitude", "acq_date", "acq_time")
                      if c in merged.columns]
        if dedup_keys:
            merged = merged.drop_duplicates(subset=dedup_keys, keep="first")
    else:
        merged = pd.DataFrame()

    gj = to_geojson(merged)
    out = OUT_DIR / f"{codigo}.geojson"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(gj, f, ensure_ascii=False, separators=(",", ":"))

    n = len(merged)
    frp_mean = float(merged["frp"].mean()) if (n and "frp" in merged.columns
                                               and merged["frp"].notna().any()) else 0.0
    return n, frp_mean


def main() -> int:
    if MAP_KEY == "YOUR_FIRMS_MAP_KEY" or len(MAP_KEY) < 20:
        print("ERROR: FIRMS_MAP_KEY no configurada.")
        print("  1) Registrate gratis: https://firms.modaps.eosdis.nasa.gov/api/area/")
        print("  2) Exporta la key:    set FIRMS_MAP_KEY=tu_key  (Windows)")
        print("                        export FIRMS_MAP_KEY=tu_key  (Linux/Mac)")
        print("  3) Re-ejecuta:        python scripts/12_firms_hotspots.py")
        return 1

    volcanes = cargar_volcanes()
    print(f"FIRMS hotspots últimos {DAY_RANGE} días — {len(volcanes)} volcanes, "
          f"{len(SOURCES)} sensores")
    print(f"  bbox ±{BBOX_HALF}° (~55 km) | salida: {OUT_DIR}")
    print()

    resumen: list[tuple[str, str, int, float]] = []  # (codigo, nombre, n, frp_mean)
    t0 = time.time()
    for i, v in enumerate(volcanes, 1):
        try:
            n, frp = procesar_volcan(v)
        except Exception as e:
            print(f"  [{i:>2}/{len(volcanes)}] {v['codigo']:5s} {v['nombre']:25s} "
                  f"ERROR: {e}")
            continue
        resumen.append((v["codigo"], v["nombre"], n, frp))
        marker = "🔥" if n else "  "
        print(f"  [{i:>2}/{len(volcanes)}] {v['codigo']:5s} {v['nombre']:25s} "
              f"{n:>5d} hotspots  FRP̄={frp:6.1f} MW  {marker}")

    elapsed = time.time() - t0
    total = sum(n for _, _, n, _ in resumen)

    print()
    print("─" * 70)
    print(f"TOTAL hotspots Chile (7d):  {total}")
    print(f"Tiempo:                     {elapsed:.1f} s")
    print(f"Requests al endpoint:       {len(_CACHE)} (cache hits ahorraron "
          f"{len(volcanes)*len(SOURCES) - len(_CACHE)})")

    if total:
        all_frp = [frp for _, _, n, frp in resumen if n]
        print(f"FRP medio global:           {sum(all_frp)/len(all_frp):.1f} MW")

    print()
    print("Top 5 volcanes con más hotspots:")
    top = sorted(resumen, key=lambda x: x[2], reverse=True)[:5]
    for codigo, nombre, n, frp in top:
        print(f"  {codigo:5s} {nombre:25s} {n:>5d} hotspots  FRP̄={frp:6.1f} MW")

    # Tamaño total de los shards
    total_kb = sum(p.stat().st_size for p in OUT_DIR.glob("*.geojson")) / 1024
    print()
    print(f"Tamaño total shards FIRMS: {total_kb:.1f} KB "
          f"({len(list(OUT_DIR.glob('*.geojson')))} archivos)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
