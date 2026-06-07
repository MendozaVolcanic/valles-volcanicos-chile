"""
run_pipeline.py
---------------
Ejecuta todo el pipeline de procesamiento en secuencia.
Uso: python scripts/run_pipeline.py
"""

import subprocess
import sys
from pathlib import Path

# El pipeline se ejecuta en este ORDEN — varios scripts dependen de
# data/processed/cuencas.gpkg (generado por 03) y cuencas.geojson (export).
SCRIPTS = [
    ("01 — Hidrografía OSM (Overpass, ~25 min)",          "scripts/01_download_hydro.py"),
    ("02 — DEM SRTM 30m AWS (~12 min)",                   "scripts/02_download_dem.py"),
    ("03 — Buffer 50 km + intersección OSM (UTM)",        "scripts/03_watershed.py"),
    ("05 — Contexto OSM (red vial, infra, centros pob.)", "scripts/05_osm_context.py"),
    ("06 — Watershed hidrológico real con pysheds (~45 min)", "scripts/06_watershed_pysheds.py"),
    ("06b — Resumen drenaje por volcán",                  "scripts/06b_resumen_drenaje.py"),
    ("07 — SNAP/SNASPE local (MBN SHP)",                  "scripts/07_snaspe_local.py"),
    ("08 — Descargar capas SENAPRED (ArcGIS Online)",     "scripts/08_descargar_senapred.py"),
    ("09 — Sharding capas SENAPRED por volcán",           "scripts/09_sharding_senapred.py"),
    ("export — Shards drenajes + índice + contexto",      "scripts/export_geojson.py"),
    ("04 — Censo / Población (manual)",                    "scripts/04_census.py"),
]

def run(label, script):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    result = subprocess.run([sys.executable, script], capture_output=False)
    if result.returncode != 0:
        print(f"\n[!] Error en {script}. Pipeline detenido.")
        sys.exit(1)

if __name__ == "__main__":
    print("Pipeline: Valles Volcánicos Chile")
    print(f"Scripts a ejecutar: {len(SCRIPTS)}\n")
    for label, script in SCRIPTS:
        run(label, script)
    print("\n[✓] Pipeline completo. Ejecuta el dashboard con:")
    print("    streamlit run app/dashboard.py")
