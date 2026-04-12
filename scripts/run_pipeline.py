"""
run_pipeline.py
---------------
Ejecuta todo el pipeline de procesamiento en secuencia.
Uso: python scripts/run_pipeline.py
"""

import subprocess
import sys
from pathlib import Path

SCRIPTS = [
    ("01 — Hidrografía OSM",  "scripts/01_download_hydro.py"),
    ("02 — DEM SRTM",         "scripts/02_download_dem.py"),
    ("03 — Cuencas",          "scripts/03_watershed.py"),
    ("04 — Censo / Población","scripts/04_census.py"),
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
