"""
15_poblacion_expuesta.py
------------------------
Calcula la poblacion expuesta a cada nivel de peligro volcanico usando
manzanas del Censo 2024 INE (publicado dic 2025).

Fuente: bucket publico INE
  https://storage.googleapis.com/bktdescargascenso2024/Cartografia/GEOPARQUET/Cartografia_censo2024_Pais.zip
  Schema: Cartografia_censo2024_Pais_Manzanas.parquet (216.341 manzanas, CRS EPSG:4674 SIRGAS2000)

Algoritmo:
  Para cada poligono de peligros_volcanicos.geojson:
    - Detectar manzanas que intersectan el poligono
    - Calcular fraccion de area de manzana dentro del poligono
    - Sumar poblacion ponderada por fraccion de area
    - Agregar por (volcan, nivel Alto/Medio/Bajo)

Salida:
  data/processed/poblacion_expuesta.csv
    columnas: volcan, peligro_nivel, n_manzanas, poblacion_estimada
"""
from pathlib import Path
import json
import pandas as pd
import geopandas as gpd
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
MANZANAS = ROOT / "data" / "raw" / "censo2024" / "Cartografia_censo2024_Pais_Manzanas.parquet"
PELIGROS = ROOT / "data" / "processed" / "peligros_volcanicos.geojson"
OUT      = ROOT / "data" / "processed" / "poblacion_expuesta.csv"


def main():
    if not MANZANAS.exists():
        print(f"[!] Falta {MANZANAS}")
        print("    Descargar de https://storage.googleapis.com/bktdescargascenso2024/Cartografia/GEOPARQUET/Cartografia_censo2024_Pais.zip")
        print("    Descomprimir en data/raw/censo2024/")
        return

    print("Cargando manzanas censales (216 mil features)...")
    g = gpd.read_parquet(str(MANZANAS))
    # La columna geometria de INE se llama "SHAPE" (no "geometry"); renombrar
    if "SHAPE" in g.columns and g.geometry.name == "SHAPE":
        g = g.rename_geometry("geometry")
    g["poblacion"] = g["n_hombres"].fillna(0) + g["n_mujeres"].fillna(0)
    g = g[["CUT", "COMUNA", "REGION", "poblacion", "geometry"]]
    g = g.to_crs("EPSG:4326")
    print(f"  cargadas. Poblacion total Chile: {int(g['poblacion'].sum()):,}")

    print("Cargando poligonos de peligro...")
    peligros = gpd.read_file(str(PELIGROS), engine="pyogrio")
    if peligros.crs is None:
        peligros = peligros.set_crs("EPSG:4326")
    print(f"  {len(peligros)} poligonos, volcanes unicos: {peligros['volcan'].nunique()}")

    # Spatial join para encontrar manzanas que intersectan cada poligono
    print("Spatial join manzanas vs poligonos peligro...")
    # Indice espacial para acelerar
    sjoin = gpd.sjoin(g[["poblacion", "geometry"]], peligros[["volcan", "peligro", "geometry"]],
                       how="inner", predicate="intersects")
    print(f"  {len(sjoin):,} intersecciones encontradas")

    # Calcular fraccion de area: por cada pareja (manzana, peligro) intersectar y dividir
    # por area total de manzana. Esto requiere overlay, no solo sjoin.
    # Para ahorrar tiempo: si la manzana cae ENTERA dentro del poligono usamos pop full.
    # Si la manzana cae parcialmente, hacemos overlay solo de esas.
    print("Calculando poblacion expuesta ponderada por area...")
    rows = []
    for (volcan, peligro), grupo in sjoin.groupby(["volcan", "peligro"]):
        # Polygon del peligro
        poly = peligros[(peligros["volcan"] == volcan) & (peligros["peligro"] == peligro)].iloc[0].geometry

        # Manzanas candidatas
        manz = g.loc[grupo.index]

        # Intersectar geometrias
        inter = manz.copy()
        inter["geom_inter"] = manz.geometry.intersection(poly)
        inter["area_manz"] = manz.geometry.area
        inter["area_inter"] = inter["geom_inter"].area
        inter["fraccion"] = np.where(inter["area_manz"] > 0,
                                       inter["area_inter"] / inter["area_manz"], 0)
        inter["pob_expuesta"] = inter["poblacion"] * inter["fraccion"]
        rows.append({
            "volcan": volcan,
            "peligro_nivel": peligro,
            "n_manzanas": len(manz),
            "poblacion_estimada": int(round(inter["pob_expuesta"].sum())),
        })

    out = pd.DataFrame(rows).sort_values(["volcan", "peligro_nivel"]).reset_index(drop=True)
    out.to_csv(OUT, index=False, encoding="utf-8")
    print(f"\n[OK] {OUT.relative_to(ROOT)} ({len(out)} filas)")

    # Resumen
    print("\n--- TOP-10 (volcan, nivel) por poblacion expuesta ---")
    print(out.sort_values("poblacion_estimada", ascending=False).head(10).to_string(index=False))
    print("\n--- TOTAL por nivel ---")
    print(out.groupby("peligro_nivel")["poblacion_estimada"].sum().to_string())


if __name__ == "__main__":
    main()
