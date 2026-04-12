"""
04_census.py
------------
Descarga y procesa datos del Censo 2024 (INE Chile).
Cruza manzanas censales con cuencas volcánicas para estimar
población por quebrada/valle.

Fuentes públicas INE:
  - Redatam / IDE del INE: manzanas con población total

Salida: data/processed/poblacion_cuencas.gpkg
        data/processed/resumen_poblacion.csv
"""

import geopandas as gpd
import pandas as pd
import requests
import zipfile
import io
from pathlib import Path
import yaml

RAW = Path("data/raw")
PROCESSED = Path("data/processed")
PROCESSED.mkdir(parents=True, exist_ok=True)

CONFIG = yaml.safe_load(open("config/volcanoes.yaml"))

# ---------------------------------------------------------------------------
# Fuentes de datos INE (URLs públicas)
# ---------------------------------------------------------------------------

# IDE IGM / BCN shapefile de manzanas censales con población
# INE publica resultados del censo por manzana en su IDE
INE_URLS = {
    # URL del shapefile de manzanas del Censo 2024 - INE IDE
    # Alternativa: descarga manual desde https://ide.ine.cl
    "manzanas": "https://www.ine.gob.cl/docs/default-source/censo-de-poblacion-y-vivienda/cartografia/2024/manzanas_2024.zip",
}

# Fallback: usar censo 2017 si 2024 no está disponible públicamente aún
INE_URLS_2017 = {
    "manzanas": "https://www.ine.gob.cl/docs/default-source/censo-de-poblacion-y-vivienda/cartografia/2017/manzanas_2017.zip",
}


def descargar_manzanas():
    """Descarga el shapefile de manzanas censales de INE."""
    output = RAW / "manzanas_censales.gpkg"
    if output.exists():
        print(f"[✓] Manzanas ya descargadas: {output}")
        return gpd.read_file(output)

    print("Intentando descargar manzanas del Censo 2024 (INE)...")

    for año, urls in [("2024", INE_URLS), ("2017", INE_URLS_2017)]:
        try:
            url = urls["manzanas"]
            print(f"  → {url}")
            resp = requests.get(url, timeout=120, stream=True)
            resp.raise_for_status()

            z = zipfile.ZipFile(io.BytesIO(resp.content))
            shp_files = [f for f in z.namelist() if f.endswith(".shp")]
            if not shp_files:
                print(f"  [!] No se encontró .shp en el zip del censo {año}")
                continue

            z.extractall(RAW / f"manzanas_{año}_raw")
            shp = RAW / f"manzanas_{año}_raw" / shp_files[0]
            gdf = gpd.read_file(shp)

            # Normalizar columnas de población
            pop_cols = [c for c in gdf.columns if "pobl" in c.lower() or "personas" in c.lower() or "total" in c.lower()]
            print(f"  [i] Columnas de población encontradas: {pop_cols}")

            gdf.to_file(output, driver="GPKG")
            print(f"  [✓] Censo {año}: {len(gdf)} manzanas guardadas → {output}")
            return gdf

        except Exception as e:
            print(f"  [!] Censo {año} no disponible: {e}")
            continue

    print("\n[!] No se pudo descargar manzanas automáticamente.")
    print("    Descarga manual desde: https://ide.ine.cl")
    print("    y guarda el .gpkg en data/raw/manzanas_censales.gpkg")
    return None


def calcular_poblacion_cuencas(manzanas_gdf):
    """Cruza manzanas censales con cuencas volcánicas."""
    cuencas_path = PROCESSED / "cuencas.gpkg"
    if not cuencas_path.exists():
        print("[!] Ejecuta primero 03_watershed.py")
        return

    cuencas = gpd.read_file(cuencas_path, layer="cuencas")
    print(f"[i] Cuencas: {len(cuencas)} | Manzanas: {len(manzanas_gdf)}")

    # Asegurar mismo CRS
    if manzanas_gdf.crs != cuencas.crs:
        manzanas_gdf = manzanas_gdf.to_crs(cuencas.crs)

    # Detectar columna de población
    pop_col = None
    for candidate in ["PERSONAS", "personas", "TOTAL_PERS", "P_TOTAL", "pobl_total", "POBL_TOTAL"]:
        if candidate in manzanas_gdf.columns:
            pop_col = candidate
            break

    if pop_col is None:
        print(f"[!] Columna de población no encontrada. Columnas disponibles: {list(manzanas_gdf.columns)}")
        print("    Ajusta la variable pop_col manualmente.")
        return

    print(f"[i] Usando columna de población: '{pop_col}'")

    # Spatial join: manzanas dentro de cada cuenca
    joined = gpd.sjoin(manzanas_gdf[[pop_col, "geometry"]], cuencas, how="inner", predicate="intersects")

    # Agregar población por volcán
    resumen = joined.groupby(["volcán_codigo", "volcán_nombre", "region"])[pop_col].sum().reset_index()
    resumen.columns = ["volcán_codigo", "volcán_nombre", "region", "poblacion_cuenca"]
    resumen = resumen.sort_values("poblacion_cuenca", ascending=False)

    # Guardar
    resumen.to_csv(PROCESSED / "resumen_poblacion.csv", index=False)
    print(f"\n[✓] Resumen guardado: {PROCESSED}/resumen_poblacion.csv")
    print(resumen.to_string(index=False))

    # Guardar manzanas con volcán asignado
    joined_out = joined.merge(resumen[["volcán_codigo", "poblacion_cuenca"]], on="volcán_codigo")
    gdf_out = gpd.GeoDataFrame(joined_out, crs=manzanas_gdf.crs)
    gdf_out.to_file(PROCESSED / "poblacion_cuencas.gpkg", driver="GPKG")
    print(f"[✓] GeoPackage: {PROCESSED}/poblacion_cuencas.gpkg")


def main():
    manzanas = descargar_manzanas()
    if manzanas is not None:
        calcular_poblacion_cuencas(manzanas)


if __name__ == "__main__":
    main()
