"""
export_geojson.py - Exporta cuencas.gpkg a GeoJSON planos para deploy en cloud.
Sin dependencias nativas en runtime (geopandas solo se necesita aqui, localmente).
"""
import geopandas as gpd
import json
from pathlib import Path

ROOT      = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
GPKG      = PROCESSED / "cuencas.gpkg"

if not GPKG.exists():
    print(f"[ERROR] No se encontro {GPKG}")
    raise SystemExit(1)

# --- Cuencas (zonas de influencia) ---
print("Exportando cuencas...")
cuencas = gpd.read_file(str(GPKG), layer="cuencas", engine="pyogrio")
cuencas = cuencas[["volcan_codigo", "volcan_nombre", "region", "elevacion", "geometry"]]
out_c = PROCESSED / "cuencas.geojson"
cuencas.to_file(str(out_c), driver="GeoJSON")
size_c = out_c.stat().st_size / 1024
print(f"  -> {out_c.name}  ({size_c:.0f} KB)")

# --- Drenajes (un GeoJSON por volcan) ---
print("Exportando drenajes por volcan...")
drenajes = gpd.read_file(str(GPKG), layer="drenajes", engine="pyogrio")
out_dir  = PROCESSED / "drenajes"
out_dir.mkdir(exist_ok=True)

cols = ["osm_id", "nombre", "tipo", "volcan_codigo", "volcan_nombre", "geometry"]
total = 0
for codigo, group in drenajes.groupby("volcan_codigo"):
    out_f = out_dir / f"{codigo}.geojson"
    group[cols].to_file(str(out_f), driver="GeoJSON")
    kb = out_f.stat().st_size / 1024
    total += out_f.stat().st_size
    print(f"  {codigo}: {len(group):5d} tramos  ({kb:.0f} KB)")

print(f"\nTotal drenajes: {total/1024:.0f} KB ({total/1024/1024:.1f} MB)")
print("Listo.")
