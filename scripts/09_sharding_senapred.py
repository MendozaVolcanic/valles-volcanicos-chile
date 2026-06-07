"""
09_sharding_senapred.py
-----------------------
Toma los GeoJSON globales descargados por 08_descargar_senapred.py y los
shardea por volcan (intersección con cuencas) para carga lazy en el dashboard.

Tambien aplica simplify + truncacion de precision para reducir tamaño.

Salida: data/processed/senapred/{capa}/{codigo}.geojson
"""
from pathlib import Path
import geopandas as gpd
import shutil

ROOT       = Path(__file__).resolve().parent.parent
SRC_DIR    = ROOT / "data" / "processed" / "senapred"
CUENCAS    = ROOT / "data" / "processed" / "cuencas.geojson"

# Capas a shardear (todas excepto las que ya son por-volcan o tienen 1-2 features)
CAPAS_SHARD = [
    "puntos_encuentro",
    "vias_evacuacion",
    "areas_peligro",          # 31 MB → critico shardear
    "servicios_salud",
    "servicios_bomberos",
    "servicios_educacion",    # 15k features
    "servicios_carabineros",
]

# Capas que se quedan globales (son chicas o ya van por volcan)
CAPAS_GLOBAL = [
    "volcanes_peligrosidad",
    "buffer_volcanes_poly",
    "buffer_volcanes_line",
    "perimetro_villarrica",
]

SIMPLIFY_DEG = 0.00005   # ~5 m, invisible al zoom <= 13
PRECISION    = 5


def shardear(capa: str, cuencas: gpd.GeoDataFrame):
    src = SRC_DIR / f"{capa}.geojson"
    if not src.exists():
        print(f"  [skip] {capa}.geojson no existe")
        return
    print(f"  {capa}...")
    g = gpd.read_file(str(src), engine="pyogrio")
    if g.crs is None:
        g = g.set_crs("EPSG:4326")
    # Simplify (solo para geometrias con simplify util)
    if g.geom_type.iloc[0] in ("LineString", "MultiLineString", "Polygon", "MultiPolygon"):
        g["geometry"] = g["geometry"].simplify(SIMPLIFY_DEG, preserve_topology=True)

    out_dir = SRC_DIR / capa
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    total = 0
    matches = 0
    for _, c in cuencas.iterrows():
        codigo = c["volcan_codigo"]
        sub = g[g.intersects(c.geometry)]
        if len(sub) == 0:
            continue
        out_f = out_dir / f"{codigo}.geojson"
        sub.to_file(str(out_f), driver="GeoJSON", COORDINATE_PRECISION=PRECISION)
        total   += out_f.stat().st_size
        matches += 1
    print(f"    {matches}/{len(cuencas)} volcanes, {total/1024:.0f} KB total ({total/1024/max(matches,1):.0f} KB/v)")

    # Borrar global pesado (areas_peligro 31 MB) si es shardeable; los chicos se mantienen
    src_size_kb = src.stat().st_size / 1024
    if src_size_kb > 2000:
        src.unlink()
        print(f"    eliminado {capa}.geojson global ({src_size_kb:.0f} KB)")


def main():
    if not CUENCAS.exists():
        print(f"[!] Falta {CUENCAS}. Correr 03_watershed.py primero.")
        return
    cuencas = gpd.read_file(str(CUENCAS), engine="pyogrio")
    print(f"Sharding sobre {len(cuencas)} cuencas...\n")

    for capa in CAPAS_SHARD:
        shardear(capa, cuencas)

    print("\n[OK] Sharding completo.")
    print(f"Capas globales preservadas: {', '.join(CAPAS_GLOBAL)}")


if __name__ == "__main__":
    main()
