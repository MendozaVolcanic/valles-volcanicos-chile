"""
export_geojson.py — Exporta cuencas.gpkg a GeoJSON planos + shardea capas de
contexto por volcan + precomputa indice global de quebradas.

Sin dependencias nativas en runtime (geopandas solo se necesita aqui).
Resultado:
  data/processed/cuencas.geojson                       (poligonos buffer)
  data/processed/drenajes/{codigo}.geojson             (1 por volcan)
  data/processed/red_vial/{codigo}.geojson             (1 por volcan)
  data/processed/centros_poblados/{codigo}.geojson     (1 por volcan)
  data/processed/infraestructura/{codigo}.geojson      (1 por volcan)
  data/processed/indice_quebradas.csv                  (busqueda global)
"""
import geopandas as gpd
import pandas as pd
import yaml
from pathlib import Path
from shapely.geometry import shape, mapping
import json


# Tolerancia de simplificacion en grados (~1m a estas latitudes) — invisible
# a zooms <= 14 pero reduce ~5x el tamaño de los GeoJSON.
SIMPLIFY_TOL = 0.00005
# Decimales de precision en GeoJSON output (5 = ~1m).
COORD_PRECISION = 5


def _write_geojson(gdf, path, simplify=True):
    """Escribe GeoJSON con simplificacion + precision controlada."""
    if simplify and len(gdf) > 0:
        gdf = gdf.copy()
        gdf["geometry"] = gdf["geometry"].simplify(SIMPLIFY_TOL, preserve_topology=True)
    gdf.to_file(str(path), driver="GeoJSON", COORDINATE_PRECISION=COORD_PRECISION)

ROOT      = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
GPKG      = PROCESSED / "cuencas.gpkg"
CONFIG    = ROOT / "config" / "volcanoes.yaml"

if not GPKG.exists():
    print(f"[ERROR] No se encontro {GPKG}")
    raise SystemExit(1)

VOLCANES = yaml.safe_load(open(CONFIG, encoding="utf-8"))["volcanes"]

# --- Cuencas (zonas de influencia) ---
print("Exportando cuencas...")
cuencas = gpd.read_file(str(GPKG), layer="cuencas", engine="pyogrio")
cuencas = cuencas[["volcan_codigo", "volcan_nombre", "region", "elevacion", "geometry"]]
out_c = PROCESSED / "cuencas.geojson"
_write_geojson(cuencas, out_c)
print(f"  -> {out_c.name}  ({out_c.stat().st_size/1024:.0f} KB)")

# --- Drenajes (un GeoJSON por volcan) ---
print("Exportando drenajes por volcan...")
drenajes = gpd.read_file(str(GPKG), layer="drenajes", engine="pyogrio")
out_dir  = PROCESSED / "drenajes"
out_dir.mkdir(exist_ok=True)

# Columnas core + drena_volcan si existe (lo agrega 06_watershed_pysheds.py)
cols = ["osm_id", "nombre", "tipo", "volcan_codigo", "volcan_nombre", "geometry"]
if "drena_volcan" in drenajes.columns:
    cols.insert(-1, "drena_volcan")
total = 0
indice_rows = []
for codigo, group in drenajes.groupby("volcan_codigo"):
    out_f = out_dir / f"{codigo}.geojson"
    _write_geojson(group[cols], out_f)
    total += out_f.stat().st_size
    # Indice de quebradas nombradas
    nombrados = group[group["nombre"] != "Sin nombre"]
    for nom, sub in nombrados.groupby("nombre"):
        indice_rows.append({
            "quebrada": nom,
            "tipo":     sub["tipo"].iloc[0],
            "volcan":   sub["volcan_nombre"].iloc[0],
            "codigo":   codigo,
            "tramos":   len(sub),
        })
print(f"  total drenajes: {total/1024/1024:.1f} MB")

# --- Indice global de quebradas (reemplaza construir_indice_quebradas en dashboard) ---
print("Precomputando indice global de quebradas...")
idx = pd.DataFrame(indice_rows).sort_values(["quebrada", "volcan"])
idx_path = PROCESSED / "indice_quebradas.csv"
idx.to_csv(idx_path, index=False, encoding="utf-8")
print(f"  -> {idx_path.name}  ({len(idx):,} entradas, {idx_path.stat().st_size/1024:.0f} KB)")

# --- Shardear capas de contexto por volcan via spatial join con cuencas ---
# Aprovecha los buffers ya generados como mascara espacial real (no bbox).
print("Sharding capas de contexto por volcan...")
cuencas_idx = cuencas.set_index("volcan_codigo")["geometry"]

CAPAS_CTX = {
    "red_vial":         "MultiLineString/LineString",
    "centros_poblados": "Polygon",
    "infraestructura":  "Point",
}

for capa in CAPAS_CTX:
    src = PROCESSED / f"{capa}.geojson"
    if not src.exists():
        print(f"  [skip] {capa}.geojson no existe")
        continue
    gdf = gpd.read_file(str(src), engine="pyogrio")
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    out_capa = PROCESSED / capa
    out_capa.mkdir(exist_ok=True)
    total_capa = 0
    for v in VOLCANES:
        codigo = v["codigo"]
        poly = cuencas_idx.get(codigo)
        if poly is None:
            continue
        # sjoin para preservar features que toquen el buffer
        sub = gdf[gdf.intersects(poly)]
        if len(sub) == 0:
            continue
        out_f = out_capa / f"{codigo}.geojson"
        _write_geojson(sub, out_f)
        total_capa += out_f.stat().st_size
    print(f"  {capa}: {total_capa/1024:.0f} KB total ({total_capa/1024/59:.0f} KB/volcan avg)")

print("\nListo.")
