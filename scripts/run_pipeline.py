"""
run_pipeline.py
---------------
Ejecuta todo el pipeline de procesamiento en secuencia.
Uso: python scripts/run_pipeline.py
"""

import subprocess
import sys
from pathlib import Path

# ORDEN OBLIGATORIO. La dependencia que manda es data/processed/cuencas.geojson:
# lo produce `export_geojson.py` y lo consumen 07 (SNASPE), 09 (SENAPRED),
# 10 (comunas) para recortar por volcan. Antes export corria DESPUES de 09, asi
# que en un clone limpio 09 no encontraba el archivo, imprimia el aviso y salia
# con codigo 0 → el pipeline terminaba "verde" sin haber generado ni un shard.
SCRIPTS = [
    # --- Base: hidrografia, relieve y cuencas ---
    ("01 — Hidrografía OSM (Overpass, ~25 min)",              "scripts/01_download_hydro.py"),
    ("02 — DEM SRTM 30m AWS (~12 min)",                       "scripts/02_download_dem.py"),
    ("03 — Buffer 50 km + intersección OSM (UTM)",            "scripts/03_watershed.py"),
    ("06 — Watershed hidrológico real con pysheds (~45 min)", "scripts/06_watershed_pysheds.py"),
    ("06b — Resumen drenaje por volcán",                      "scripts/06b_resumen_drenaje.py"),
    # --- export ANTES de las capas que recortan contra cuencas.geojson ---
    ("export — Shards drenajes + índice + cuencas.geojson",   "scripts/export_geojson.py"),
    ("16 — Shards lite (cauces nombrados, vista por zoom)",   "scripts/16_drenajes_lite.py"),
    # --- Capas de contexto (todas dependen de cuencas.geojson) ---
    ("05 — Contexto OSM (red vial, infra, centros pob.)",     "scripts/05_osm_context.py"),
    ("07 — SNAP/SNASPE local (MBN SHP)",                      "scripts/07_snaspe_local.py"),
    ("08 — Descargar capas SENAPRED (ArcGIS Online)",         "scripts/08_descargar_senapred.py"),
    ("09 — Sharding capas SENAPRED por volcán",               "scripts/09_sharding_senapred.py"),
    ("10 — Comunas Chile (reemplaza WMS BCN)",                "scripts/10_comunas_local.py"),
    # --- Estado y NRT (Sprint 1): refrescan el semaforo y las capas vivas ---
    ("11 — Estado REAV SERNAGEOMIN",                          "scripts/11_estado_reav.py"),
    ("13 — Fichas Smithsonian GVP",                           "scripts/13_gvp_smithsonian.py"),
    ("14 — Sismicidad USGS ComCat",                           "scripts/14_usgs_sismos.py"),
    ("15 — Población expuesta (Censo 2024)",                  "scripts/15_poblacion_expuesta.py"),
    # --- Manual / requiere credencial ---
    ("04 — Censo / Población (manual)",                       "scripts/04_census.py"),
]

# Requieren intervencion humana (API key o descarga manual): no los corre el
# pipeline, pero conviene recordarlos al final.
OPCIONALES = [
    ("12 — Hotspots NASA FIRMS", "scripts/12_firms_hotspots.py",
     "necesita la variable de entorno FIRMS_MAP_KEY"),
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
    print("\n[✓] Pipeline completo.")
    if OPCIONALES:
        print("\nPendientes que requieren intervención manual:")
        for label, script, motivo in OPCIONALES:
            print(f"  - {label}: {motivo}")
            print(f"      python {script}")
    print("\nEjecuta el dashboard con:")
    print("    streamlit run app/dashboard.py")
