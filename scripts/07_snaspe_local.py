"""
07_snaspe_local.py
------------------
Procesa el shapefile oficial SNAP (ex-SNASPE) descargado desde MBN
(Ministerio de Bienes Nacionales) y lo shardea por volcan.

Reemplaza al WMS SNASPE de SAG/CONAF que esta roto en 2026.

Fuente: https://idembn.bienes.cl/catastro/catalog/download/ca3c267b-5270-39d0-97d2-6e4694a11877
        SNAP_Mayo 2026.zip (137 MB), datos a mayo 2026.

Salida:
  data/processed/snaspe.geojson         (global, simplificado)
  data/processed/snaspe/{codigo}.geojson (por volcan, interseccion con cuenca)
"""
from pathlib import Path
import geopandas as gpd

ROOT      = Path(__file__).resolve().parent.parent
SHP       = ROOT / "data" / "raw" / "snaspe" / "SNAP_.shp"
OUT_DIR   = ROOT / "data" / "processed" / "snaspe"
OUT_GLOB  = ROOT / "data" / "processed" / "snaspe.geojson"
CUENCAS   = ROOT / "data" / "processed" / "cuencas.geojson"

# Simplificacion: ~10 m (no perceptible al zoom <= 13). Reduce mucho el tamaño.
SIMPLIFY_DEG = 0.0001


def main():
    if not SHP.exists():
        print(f"[!] Falta {SHP}")
        print("    Descargar: https://idembn.bienes.cl/catastro/catalog/download/ca3c267b-5270-39d0-97d2-6e4694a11877")
        print("    Guardar en data/raw/snaspe/ y descomprimir.")
        return

    print("Cargando SNAP shapefile...")
    g = gpd.read_file(str(SHP), engine="pyogrio").to_crs("EPSG:4326")
    print(f"  {len(g)} areas protegidas, CRS WGS84")

    # Mantener solo columnas relevantes y renombrar
    cols_keep = {
        "NOMBRE_TOT": "nombre",
        "CATEGORIA":  "categoria",
        "REGION":     "region",
        "SUPERFICIE": "superficie_ha",
        "DECRETO":    "decreto",
        "geometry":   "geometry",
    }
    g = g[list(cols_keep)].rename(columns=cols_keep)
    g["geometry"] = g["geometry"].simplify(SIMPLIFY_DEG, preserve_topology=True)

    # Global
    g.to_file(str(OUT_GLOB), driver="GeoJSON", COORDINATE_PRECISION=5)
    print(f"  -> {OUT_GLOB.name}  ({OUT_GLOB.stat().st_size/1024:.0f} KB)")

    # Shards por volcan (interseccion con cuencas)
    if not CUENCAS.exists():
        print(f"  [!] {CUENCAS} no existe, salteando shards. Correr 03_watershed.py primero.")
        return
    cuencas = gpd.read_file(str(CUENCAS), engine="pyogrio")
    OUT_DIR.mkdir(exist_ok=True, parents=True)
    total = 0
    matches = 0
    for _, c in cuencas.iterrows():
        codigo = c["volcan_codigo"]
        poly   = c.geometry
        sub    = g[g.intersects(poly)]
        if len(sub) == 0:
            continue
        # Clip a la cuenca para mantener solo la porcion relevante
        clipped = gpd.clip(sub, poly)
        clipped = clipped[~clipped.is_empty]
        if len(clipped) == 0:
            continue
        out_f = OUT_DIR / f"{codigo}.geojson"
        clipped.to_file(str(out_f), driver="GeoJSON", COORDINATE_PRECISION=5)
        total += out_f.stat().st_size
        matches += 1

    print(f"  -> {matches}/{len(cuencas)} volcanes con SNASPE en buffer")
    print(f"  -> {total/1024:.0f} KB total ({total/1024/max(matches,1):.0f} KB/volcan avg)")


if __name__ == "__main__":
    main()
