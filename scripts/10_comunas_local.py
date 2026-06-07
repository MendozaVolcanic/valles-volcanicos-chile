"""
10_comunas_local.py
-------------------
Descarga limites comunales de Chile y los shardea por volcan.

CONTEXTO: el dashboard usaba WMS BCN (siit2.bcn.cl/mapas_geoserver) para los
limites comunales, pero el WMS esta caido en 2026. Este script genera una
capa local equivalente y la shardea por cuenca de volcan para carga lazy.

FUENTE: github.com/caracena/chile-geojson
  - 16 archivos GeoJSON, uno por region (1.geojson .. 16.geojson)
  - Schema: cod_comuna, Comuna, Provincia, Region, codregion
  - Geometrias Polygon/MultiPolygon en EPSG:4326
  - Origen primario: shapefiles BCN/INE (datos publicos oficiales),
    redistribuidos en GitHub. No requiere auth.

PROCESO:
  1. Descarga las 16 regiones a data/raw/comunas/
  2. Unifica, normaliza columnas, reproyecta a EPSG:4326, simplifica
  3. Guarda global a data/processed/comunas.geojson
  4. Sharding por interseccion con cuencas a data/processed/comunas/{codigo}.geojson

OUTPUT esperado: ~346 comunas, global <3 MB, shards pequenos.
"""
from pathlib import Path
import json
import shutil
import sys
import io
import time
import requests
import geopandas as gpd
import pandas as pd

# Forzar stdout UTF-8 en Windows (cp1252 default rompe tildes en logs)
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT       = Path(__file__).resolve().parent.parent
RAW_DIR    = ROOT / "data" / "raw" / "comunas"
PROC_DIR   = ROOT / "data" / "processed"
OUT_GLOBAL = PROC_DIR / "comunas.geojson"
OUT_SHARDS = PROC_DIR / "comunas"
CUENCAS    = PROC_DIR / "cuencas.geojson"

BASE_URL = "https://raw.githubusercontent.com/caracena/chile-geojson/master"
REGIONES = list(range(1, 17))  # 1..16

SIMPLIFY_DEG_GLOBAL = 0.001   # ~100 m: el GeoJSON global es para overview a zoom 4-8
SIMPLIFY_DEG_SHARD  = 0.0002  # ~20 m: shards a zoom 9-13 (mas detalle)
PRECISION_GLOBAL    = 4
PRECISION_SHARD     = 5
HEADERS = {"User-Agent": "valles-volcanicos-chile/1.0 (research)"}


def descargar_regiones():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for r in REGIONES:
        out = RAW_DIR / f"{r}.geojson"
        if out.exists() and out.stat().st_size > 1000:
            continue
        url = f"{BASE_URL}/{r}.geojson"
        print(f"  GET {url} ... ", end="", flush=True)
        resp = requests.get(url, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        out.write_bytes(resp.content)
        print(f"{len(resp.content)/1024:.0f} KB")
        time.sleep(0.3)


def unir_y_normalizar() -> gpd.GeoDataFrame:
    """Los GeoJSON de caracena estan codificados latin1 pero declarados utf-8.
    Hay que leerlos como bytes, decodificar latin1 y re-parsear como GeoJSON
    correcto antes de pasarlos a geopandas (sino se ven 'Puc?n', 'Regi?n')."""
    from shapely.geometry import shape

    rows = []
    geoms = []
    for r in REGIONES:
        raw = (RAW_DIR / f"{r}.geojson").read_bytes()
        # latin1 nunca falla y mapea cada byte a su codepoint Unicode equivalente
        data = json.loads(raw.decode("latin1"))
        for feat in data["features"]:
            p = feat["properties"]
            rows.append({
                "cod_comuna": str(p["cod_comuna"]).zfill(5),
                "nombre_comuna":    p.get("Comuna"),
                "nombre_provincia": p.get("Provincia"),
                "nombre_region":    p.get("Region"),
            })
            geoms.append(shape(feat["geometry"]))

    full = gpd.GeoDataFrame(rows, geometry=geoms, crs="EPSG:4326")
    return full


def _write_geojson_utf8(g: gpd.GeoDataFrame, path: Path, precision: int):
    """Escribir GeoJSON garantizando UTF-8 correcto y precision controlada.
    Evitamos pyogrio/fiona porque escriben los codepoints como bytes latin1."""
    from shapely.geometry import mapping
    feats = []
    for _, row in g.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        # Reducir precision via WKT round-trip seria caro: usamos json.dumps con
        # truncado manual en mapping.
        gj = mapping(geom)
        def trunc(coords):
            if isinstance(coords[0], (int, float)):
                return [round(coords[0], precision), round(coords[1], precision)]
            return [trunc(c) for c in coords]
        gj["coordinates"] = trunc(gj["coordinates"])
        props = {k: v for k, v in row.items() if k != "geometry"}
        feats.append({"type": "Feature", "properties": props, "geometry": gj})
    fc = {"type": "FeatureCollection",
          "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
          "features": feats}
    path.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")


def guardar_global(g: gpd.GeoDataFrame):
    PROC_DIR.mkdir(parents=True, exist_ok=True)
    g_global = g.copy()
    g_global["geometry"] = g_global["geometry"].simplify(
        SIMPLIFY_DEG_GLOBAL, preserve_topology=True
    )
    if OUT_GLOBAL.exists():
        OUT_GLOBAL.unlink()
    _write_geojson_utf8(g_global, OUT_GLOBAL, PRECISION_GLOBAL)
    size_mb = OUT_GLOBAL.stat().st_size / 1024 / 1024
    print(f"  global -> {OUT_GLOBAL.relative_to(ROOT)} ({size_mb:.2f} MB, {len(g_global)} comunas)")


def shardear_por_volcan(comunas: gpd.GeoDataFrame):
    if not CUENCAS.exists():
        print(f"[!] Falta {CUENCAS}. Correr 03_watershed.py / 06_watershed_pysheds.py primero.")
        return None
    cuencas = gpd.read_file(str(CUENCAS), engine="pyogrio").to_crs("EPSG:4326")

    if OUT_SHARDS.exists():
        shutil.rmtree(OUT_SHARDS)
    OUT_SHARDS.mkdir(parents=True)

    # Para los shards usamos simplificacion mas suave (zoom mayor)
    comunas = comunas.copy()
    comunas["geometry"] = comunas["geometry"].simplify(
        SIMPLIFY_DEG_SHARD, preserve_topology=True
    )

    # sjoin: para cada cuenca, comunas que intersectan
    joined = gpd.sjoin(
        comunas, cuencas[["volcan_codigo", "volcan_nombre", "geometry"]],
        how="inner", predicate="intersects",
    )

    resumen = {}
    total_bytes = 0
    for codigo, sub in joined.groupby("volcan_codigo"):
        sub_out = sub.drop(columns=["index_right", "volcan_codigo", "volcan_nombre"])
        sub_out = sub_out.drop_duplicates(subset=["cod_comuna"])
        out_f = OUT_SHARDS / f"{codigo}.geojson"
        _write_geojson_utf8(sub_out, out_f, PRECISION_SHARD)
        total_bytes += out_f.stat().st_size
        resumen[codigo] = sorted(sub_out["nombre_comuna"].tolist())

    print(f"  shards -> {OUT_SHARDS.relative_to(ROOT)}/  ({len(resumen)}/{len(cuencas)} volcanes, {total_bytes/1024:.0f} KB)")
    return resumen


def verificar(resumen: dict):
    print("\n=== Verificacion ===")
    if resumen is None:
        return
    for codigo in ["VIL", "CHA", "LAS"]:
        comunas_v = resumen.get(codigo, [])
        print(f"  {codigo}: {len(comunas_v)} comunas -> {comunas_v}")

    vil = set(c.lower() for c in resumen.get("VIL", []))
    esperadas = ["villarrica", "pucón", "curarrehue", "panguipulli"]
    print("\n  Check Villarrica (debe contener Villarrica/Pucon/Curarrehue/Panguipulli):")
    for e in esperadas:
        hit = any(e in v for v in vil)
        marca = "OK" if hit else "FALTA"
        print(f"    [{marca}] {e}")


def main():
    print("[1/4] Descargando 16 regiones desde caracena/chile-geojson...")
    descargar_regiones()

    print("[2/4] Unificando y normalizando...")
    comunas = unir_y_normalizar()
    print(f"  {len(comunas)} comunas en total")
    print(f"  Regiones: {comunas['nombre_region'].nunique()}")

    print("[3/4] Guardando GeoJSON global...")
    guardar_global(comunas)

    print("[4/4] Sharding por volcan...")
    resumen = shardear_por_volcan(comunas)

    verificar(resumen)
    print("\n[OK] Listo.")


if __name__ == "__main__":
    main()
