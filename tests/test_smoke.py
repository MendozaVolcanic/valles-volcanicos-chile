"""
test_smoke.py — Validaciones rapidas de integridad de datos y arranque del
dashboard. Diseñado para correr en CI (GitHub Actions) y localmente.

Ejecutar: pytest tests/ -v
"""
from pathlib import Path
import json
import yaml
import subprocess
import time
import sys

import pandas as pd
import pytest
import requests


ROOT      = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
CONFIG    = ROOT / "config" / "volcanoes.yaml"
CIUDADES  = ROOT / "config" / "ciudades.yaml"


def _load_yaml(p):
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------

def test_volcanoes_yaml_estructura():
    cfg = _load_yaml(CONFIG)
    assert "volcanes" in cfg
    assert len(cfg["volcanes"]) == 59, f"Esperados 59 volcanes, hay {len(cfg['volcanes'])}"
    for v in cfg["volcanes"]:
        assert {"nombre", "lat", "lon", "codigo", "zona"} <= v.keys(), f"campos faltantes en {v}"
        assert -56 < v["lat"] < -17, f"lat fuera de Chile: {v['nombre']}"
        assert -76 < v["lon"] < -66, f"lon fuera de Chile: {v['nombre']}"
        assert v["zona"] in {"Norte", "Centro", "Sur", "Austral"}


def test_ciudades_yaml():
    c = _load_yaml(CIUDADES)
    assert "ciudades" in c and len(c["ciudades"]) >= 40
    for x in c["ciudades"]:
        assert {"nombre", "lat", "lon", "pop"} <= x.keys()


def test_codigos_unicos():
    vs = _load_yaml(CONFIG)["volcanes"]
    codigos = [v["codigo"] for v in vs]
    assert len(codigos) == len(set(codigos)), "codigos duplicados"


# ---------------------------------------------------------------------------
# Datos procesados
# ---------------------------------------------------------------------------

def test_cuencas_geojson_existe_y_match_yaml():
    p = PROCESSED / "cuencas.geojson"
    assert p.exists(), "cuencas.geojson no existe — correr scripts/03_watershed.py + export_geojson.py"
    gj = json.load(open(p, encoding="utf-8"))
    yaml_codigos = {v["codigo"] for v in _load_yaml(CONFIG)["volcanes"]}
    geo_codigos  = {f["properties"]["volcan_codigo"] for f in gj["features"]}
    faltantes = yaml_codigos - geo_codigos
    assert not faltantes, f"volcanes sin cuenca: {sorted(faltantes)}"


def test_drenajes_shards():
    d = PROCESSED / "drenajes"
    assert d.exists()
    yaml_codigos = {v["codigo"] for v in _load_yaml(CONFIG)["volcanes"]}
    shards = {p.stem for p in d.glob("*.geojson")}
    assert shards == yaml_codigos, f"shards != yaml: faltan {yaml_codigos - shards}, sobran {shards - yaml_codigos}"


def test_indice_quebradas():
    p = PROCESSED / "indice_quebradas.csv"
    assert p.exists(), "indice_quebradas.csv falta — correr scripts/export_geojson.py"
    df = pd.read_csv(p)
    assert {"quebrada", "tipo", "volcan", "codigo", "tramos"} <= set(df.columns)
    assert len(df) > 1000, f"indice sospechosamente chico: {len(df)}"


def test_senapred_capas_existen():
    """Capas oficiales del Visor Chile Preparado descargadas (08_descargar_senapred.py)."""
    senapred = PROCESSED / "senapred"
    if not senapred.exists():
        pytest.skip("SENAPRED no descargado")
    # Globales chicos
    for f in ["volcanes_peligrosidad.geojson", "buffer_volcanes_poly.geojson",
              "buffer_volcanes_line.geojson", "perimetro_villarrica.geojson"]:
        assert (senapred / f).exists(), f"{f} falta — correr scripts/08_descargar_senapred.py"
    # Shards SENAPRED por volcan. Nota: areas_peligro se quito del pipeline
    # porque ya tenemos peligros_volcanicos.geojson (SERNAGEOMIN, mejor metadata).
    for capa in ["puntos_encuentro", "vias_evacuacion",
                 "servicios_salud", "servicios_bomberos", "servicios_educacion",
                 "servicios_carabineros"]:
        d = senapred / capa
        assert d.exists() and any(d.glob("*.geojson")), \
            f"shards de {capa} faltan — correr scripts/09_sharding_senapred.py"


def test_snaspe_local():
    """SNAP/SNASPE oficial MBN, reemplazo del WMS SAG roto."""
    d = PROCESSED / "snaspe"
    if not d.exists():
        pytest.skip("SNASPE no procesado")
    shards = list(d.glob("*.geojson"))
    assert len(shards) >= 20, f"muy pocos shards SNASPE: {len(shards)}"


def test_drenajes_tienen_clasificacion_hidrologica():
    """Verifica que los shards llevan la columna drena_volcan (06_watershed_pysheds.py).
    Sin esto el toggle hidrologico del dashboard queda inerte."""
    sample = PROCESSED / "drenajes" / "VIL.geojson"
    if not sample.exists():
        pytest.skip("shard de muestra no disponible")
    gj = json.load(open(sample, encoding="utf-8"))
    if not gj["features"]:
        pytest.skip("shard vacio")
    props = gj["features"][0]["properties"]
    assert "drena_volcan" in props, \
        "falta 'drena_volcan' — correr scripts/06_watershed_pysheds.py + export_geojson.py"


@pytest.mark.parametrize("capa", ["red_vial", "centros_poblados", "infraestructura"])
def test_capas_contexto_sharded(capa):
    d = PROCESSED / capa
    assert d.exists(), f"capa {capa} no shardeada — correr scripts/export_geojson.py"
    shards = list(d.glob("*.geojson"))
    assert len(shards) > 0, f"sin shards para {capa}"
    # Verificar que al menos un shard es GeoJSON valido
    sample = json.load(open(shards[0], encoding="utf-8"))
    assert sample["type"] == "FeatureCollection"


# ---------------------------------------------------------------------------
# Dashboard arranca
# ---------------------------------------------------------------------------

def test_dashboard_arranca_headless():
    """Levanta streamlit en background, verifica HTTP 200 en healthcheck."""
    port = 8599
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app/dashboard.py",
         "--server.port", str(port), "--server.headless", "true",
         "--server.runOnSave", "false", "--browser.gatherUsageStats", "false"],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        # Esperar hasta 25s a que el endpoint responda
        for _ in range(25):
            try:
                r = requests.get(f"http://localhost:{port}/_stcore/health", timeout=1)
                if r.status_code == 200:
                    return
            except requests.RequestException:
                pass
            time.sleep(1)
        pytest.fail("Dashboard no respondio HTTP 200 en 25s")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
