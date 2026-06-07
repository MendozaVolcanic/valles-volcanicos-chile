"""
06b_resumen_drenaje.py
----------------------
Resumen agregado de la clasificacion hidrologica producida por
06_watershed_pysheds.py. Genera data/processed/resumen_drenaje.csv
con: codigo, nombre, region, zona, tramos_total, tramos_drenan,
pct_drena, quebradas_nombradas_drenan.

Util para reportes OVDAS: que volcanes tienen mayor exposicion fluvial.
"""
from pathlib import Path
import yaml
import pandas as pd
import geopandas as gpd

ROOT      = Path(__file__).resolve().parent.parent
GPKG      = ROOT / "data" / "processed" / "cuencas.gpkg"
CONFIG    = ROOT / "config" / "volcanoes.yaml"
OUT       = ROOT / "data" / "processed" / "resumen_drenaje.csv"


def main():
    if not GPKG.exists():
        print(f"[!] Falta {GPKG} — correr 03_watershed.py + 06_watershed_pysheds.py")
        return

    vs = yaml.safe_load(open(CONFIG, encoding="utf-8"))["volcanes"]
    cat = {v["codigo"]: v for v in vs}

    d = gpd.read_file(str(GPKG), layer="drenajes", engine="pyogrio")
    if "drena_volcan" not in d.columns:
        print("[!] cuencas.gpkg sin columna 'drena_volcan' — correr 06_watershed_pysheds.py primero.")
        return

    df = d.assign(_nombrado=d["nombre"].fillna("Sin nombre") != "Sin nombre")
    agg = df.groupby("volcan_codigo").agg(
        tramos_total=("osm_id", "count"),
        tramos_drenan=("drena_volcan", "sum"),
        nombrados_total=("_nombrado", "sum"),
        nombrados_drenan=("_nombrado", lambda s: int((s & df.loc[s.index, "drena_volcan"]).sum())),
    ).reset_index()
    agg["pct_drena"] = (agg["tramos_drenan"] / agg["tramos_total"] * 100).round(2)

    # Enriquecer con metadatos del yaml
    agg["nombre"]    = agg["volcan_codigo"].map(lambda c: cat.get(c, {}).get("nombre", ""))
    agg["region"]    = agg["volcan_codigo"].map(lambda c: cat.get(c, {}).get("region", ""))
    agg["zona"]      = agg["volcan_codigo"].map(lambda c: cat.get(c, {}).get("zona", ""))
    agg["monitoreado_ovdas"] = agg["volcan_codigo"].map(
        lambda c: cat.get(c, {}).get("monitoreado_ovdas", True)
    )

    cols = ["volcan_codigo", "nombre", "region", "zona", "monitoreado_ovdas",
            "tramos_total", "tramos_drenan", "pct_drena",
            "nombrados_total", "nombrados_drenan"]
    out = agg[cols].sort_values("tramos_drenan", ascending=False).reset_index(drop=True)
    out.to_csv(OUT, index=False, encoding="utf-8")
    print(f"[OK] {OUT.relative_to(ROOT)} ({len(out)} volcanes)")
    print()
    print(out.head(15).to_string(index=False))


if __name__ == "__main__":
    main()
