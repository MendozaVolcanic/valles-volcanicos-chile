"""
04_census.py
------------
Cruza datos censales con cuencas volcanicas para estimar poblacion en riesgo.

CENSO 2024 (INE):
  Las bases de manzanas con cartografia del Censo 2024 fueron publicadas
  en diciembre 2025 pero requieren descarga manual desde:
  https://www.ine.gob.cl/estadisticas-por-tema/demografia-y-poblacion/resultados-censo-2024
  -> Secciones de datos / Bases de datos a nivel de manzana y cartografia

  Alternativa Redatam online: https://redatam.ine.gob.cl

INSTRUCCIONES DE DESCARGA MANUAL:
  1. Ir a la URL anterior
  2. Descargar el shapefile de manzanas con poblacion
  3. Guardar en: data/raw/manzanas_censales.gpkg
     (o data/raw/manzanas_censales.shp si viene en shapefile)
  4. Ejecutar este script nuevamente

  Si tienes el Censo 2017, tambien funciona. Guarda como:
  data/raw/manzanas_censales_2017.gpkg

Salida: data/processed/resumen_poblacion.csv
        data/processed/poblacion_cuencas.gpkg
"""

import geopandas as gpd
import pandas as pd
from pathlib import Path
import yaml

PROCESSED = Path("data/processed")
RAW       = Path("data/raw")
PROCESSED.mkdir(parents=True, exist_ok=True)

CONFIG   = yaml.safe_load(open("config/volcanoes.yaml"))
VOLCANES = CONFIG["volcanes"]

# Columnas de poblacion segun version del censo
# El script detecta automaticamente cual usar
COLUMNAS_POBLACION_2024 = ["PERSONAS", "personas", "TOTAL_PERSONAS", "Total_personas", "P_TOTAL"]
COLUMNAS_POBLACION_2017 = ["PERSONAS", "personas", "TOTAL", "total", "P17", "TOT_PERSONAS"]


def detectar_col_poblacion(gdf, candidatas):
    for col in candidatas:
        if col in gdf.columns:
            return col
    return None


def cargar_manzanas():
    """Busca el archivo de manzanas en las ubicaciones esperadas."""
    candidatos = [
        RAW / "manzanas_censales.gpkg",
        RAW / "manzanas_censales.shp",
        RAW / "manzanas_censales_2024.gpkg",
        RAW / "manzanas_censales_2024.shp",
        RAW / "manzanas_censales_2017.gpkg",
        RAW / "manzanas_censales_2017.shp",
        RAW / "manzanas_2024" / "manzanas.shp",
        RAW / "manzanas_2017" / "manzanas.shp",
    ]

    for path in candidatos:
        if path.exists():
            print(f"  Cargando: {path}")
            gdf = gpd.read_file(path)
            print(f"  {len(gdf):,} manzanas | CRS: {gdf.crs}")
            print(f"  Columnas: {list(gdf.columns)}")
            return gdf

    return None


def calcular_poblacion_cuencas(manzanas_gdf):
    """Spatial join: manzanas dentro de cuencas volcanicas."""
    cuencas_path = PROCESSED / "cuencas.gpkg"
    if not cuencas_path.exists():
        print("[!] Ejecuta primero 03_watershed.py para generar cuencas.gpkg")
        return

    cuencas = gpd.read_file(cuencas_path, layer="cuencas")
    print(f"\n  Cuencas: {len(cuencas)} | Manzanas: {len(manzanas_gdf):,}")

    # Alinear CRS
    if manzanas_gdf.crs != cuencas.crs:
        manzanas_gdf = manzanas_gdf.to_crs(cuencas.crs)

    # Detectar columna de poblacion
    todas_candidatas = COLUMNAS_POBLACION_2024 + COLUMNAS_POBLACION_2017
    pop_col = detectar_col_poblacion(manzanas_gdf, todas_candidatas)

    if pop_col is None:
        print(f"\n[!] No se encontro columna de poblacion.")
        print(f"    Columnas disponibles: {list(manzanas_gdf.columns)}")
        print(f"    Edita COLUMNAS_POBLACION_2024 en este script.")
        return

    print(f"  Columna de poblacion: '{pop_col}'")

    # Asegurar que la columna de poblacion sea numerica
    manzanas_gdf[pop_col] = pd.to_numeric(manzanas_gdf[pop_col], errors="coerce").fillna(0)

    # Spatial join: manzanas que intersectan cuencas
    joined = gpd.sjoin(
        manzanas_gdf[[pop_col, "geometry"]],
        cuencas[["volcan_codigo", "volcan_nombre", "region", "geometry"]],
        how="inner",
        predicate="intersects"
    )

    # Resumen por volcan
    resumen = (
        joined
        .groupby(["volcan_codigo", "volcan_nombre", "region"])[pop_col]
        .sum()
        .reset_index()
        .rename(columns={pop_col: "poblacion_cuenca"})
        .sort_values("poblacion_cuenca", ascending=False)
    )

    # Agregar volcanes sin poblacion detectada
    codigos_con_pob = set(resumen["volcan_codigo"])
    sin_pob = [
        {"volcan_codigo": v["codigo"], "volcan_nombre": v["nombre"],
         "region": v.get("region",""), "poblacion_cuenca": 0}
        for v in VOLCANES if v["codigo"] not in codigos_con_pob
    ]
    if sin_pob:
        resumen = pd.concat([resumen, pd.DataFrame(sin_pob)], ignore_index=True)
        resumen = resumen.sort_values("poblacion_cuenca", ascending=False)

    # Guardar CSV resumen
    csv_out = PROCESSED / "resumen_poblacion.csv"
    resumen.to_csv(csv_out, index=False)
    print(f"\n[OK] Resumen guardado: {csv_out}")
    print(resumen.to_string(index=False))

    # Guardar GeoPackage con manzanas asignadas a volcanes
    gdf_out = gpd.GeoDataFrame(joined, crs=manzanas_gdf.crs)
    gpkg_out = PROCESSED / "poblacion_cuencas.gpkg"
    gdf_out.to_file(gpkg_out, driver="GPKG")
    print(f"[OK] GeoPackage: {gpkg_out}")


def main():
    print("Censo de Poblacion x Cuencas Volcanicas")
    print("=" * 45)

    manzanas = cargar_manzanas()

    if manzanas is None:
        print("\n[!] Archivo de manzanas censales no encontrado.")
        print("\n    DESCARGA MANUAL REQUERIDA:")
        print("    1. Ir a: https://www.ine.gob.cl/estadisticas-por-tema/demografia-y-poblacion/resultados-censo-2024")
        print("    2. Buscar 'Bases de datos a nivel de manzana y cartografia'")
        print("    3. Descargar el shapefile de manzanas con poblacion")
        print("    4. Guardar en: data/raw/manzanas_censales.gpkg")
        print("       (o data/raw/manzanas_censales.shp)")
        print("    5. Ejecutar nuevamente: python scripts/04_census.py")
        print("\n    Alternativa Censo 2017:")
        print("    https://www.ine.gob.cl/estadisticas/sociales/censos-de-poblacion-y-vivienda/censo-de-poblacion-y-vivienda")
        return

    calcular_poblacion_cuencas(manzanas)


if __name__ == "__main__":
    main()
