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
APP       = ROOT / "app"


# ---------------------------------------------------------------------------
# Deploy / imports (Streamlit Cloud regresión)
# ---------------------------------------------------------------------------

def test_modulos_app_importables_aislados():
    """Simula el entorno Streamlit Cloud: con SOLO app/ en sys.path (lo que
    Streamlit inyecta), loaders y geo_utils deben importar sin error.
    Si esto falla, el deploy cae con ImportError en 'from loaders import ...'."""
    code = (
        "import sys; sys.path.insert(0, r'%s'); "
        "import loaders, geo_utils; "
        "print('OK', bool(loaders.cargar_config), bool(geo_utils.normalizar))"
        % str(APP)
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT.parent),
                       capture_output=True, text=True)
    assert r.returncode == 0, f"import aislado falló:\nSTDOUT {r.stdout}\nSTDERR {r.stderr[-800:]}"
    assert "OK True True" in r.stdout


def test_dashboard_bootstrap_syspath_antes_de_imports():
    """Guard de regresión: dashboard.py DEBE insertar app/ en sys.path ANTES
    de 'from loaders import'. Sin esto, Streamlit Cloud rompe (line-15 ImportError).
    Se anclan los matches a inicio de línea para no confundir con menciones
    dentro de comentarios."""
    import re
    txt = (APP / "dashboard.py").read_text(encoding="utf-8")
    m_boot = re.search(r"^\s*sys\.path\.insert\(", txt, re.MULTILINE)
    m_imp  = re.search(r"^from loaders import", txt, re.MULTILINE)
    assert m_boot is not None, "falta el bootstrap sys.path.insert en dashboard.py"
    assert m_imp is not None, "no se encontró 'from loaders import' a inicio de línea"
    assert m_boot.start() < m_imp.start(), "el bootstrap sys.path debe ir ANTES del import de loaders"


def test_dashboard_csv_runtime_versionados():
    """Los CSV que el dashboard lee en runtime deben estar versionados en git
    (no gitignored), o el deploy mostrará datos vacíos."""
    import subprocess as sp
    requeridos = ["estado_reav.csv", "sismos_resumen.csv", "gvp.csv",
                  "poblacion_expuesta.csv", "indice_quebradas.csv", "resumen_drenaje.csv"]
    for csv in requeridos:
        ruta = PROCESSED / csv
        if not ruta.exists():
            continue  # si no se generó aún, no aplica
        # git check-ignore devuelve 0 si está ignorado → eso es el bug
        res = sp.run(["git", "check-ignore", str(ruta)], cwd=str(ROOT),
                     capture_output=True, text=True)
        assert res.returncode != 0, f"{csv} está gitignored — no deployará a Streamlit Cloud"


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


def test_tooltips_senapred_campos_existen():
    """Verifica que los campos que el dashboard usa en tooltips existen en los
    GeoJSON SENAPRED. Si SENAPRED cambia su schema, este test falla y avisa."""
    capas_y_campos = {
        "servicios_salud":       ["simbologia", "nombre_dep", "dirección", "comuna", "nivel_de_a"],
        "servicios_bomberos":    ["nombre", "tipo", "direccion", "telefono"],
        "servicios_educacion":   ["nombre_establecimiento", "dependencia", "urbano_rural", "matricula", "comuna"],
        "servicios_carabineros": ["nombre_uni", "tipo_de_un", "prefectura", "comuna", "region"],
        "puntos_encuentro":      ["nombre", "tipo", "volcan"],
        "vias_evacuacion":       ["volcan"],
    }
    base = PROCESSED / "senapred"
    if not base.exists():
        pytest.skip("SENAPRED no descargado")
    for capa, campos in capas_y_campos.items():
        d = base / capa
        if not d.exists():
            pytest.skip(f"shards {capa} no existen")
        sample = next(d.glob("*.geojson"), None)
        if sample is None:
            continue
        gj = json.load(open(sample, encoding="utf-8"))
        if not gj["features"]:
            continue
        props = gj["features"][0]["properties"].keys()
        faltan = [c for c in campos if c not in props]
        assert not faltan, f"{capa}: campos faltantes {faltan} (presentes: {list(props)[:10]})"


def test_sprint1_estado_reav_csv():
    """Sprint 1: estado REAV scraping SERNAGEOMIN."""
    p = PROCESSED / "estado_reav.csv"
    if not p.exists():
        pytest.skip("REAV no scrapeado")
    d = pd.read_csv(p)
    assert len(d) >= 50, f"esperaba 59 volcanes, hay {len(d)}"
    for c in ["codigo", "nombre", "nivel"]:
        assert c in d.columns


def test_sprint1_sismos_shards():
    """Sprint 1: USGS ComCat sismicidad por volcán."""
    d = PROCESSED / "sismos"
    if not d.exists():
        pytest.skip("sismos no descargados")
    shards = list(d.glob("*.geojson"))
    assert len(shards) >= 50
    # Cualquier shard debe ser FeatureCollection válido
    sample = json.load(open(shards[0], encoding="utf-8"))
    assert sample["type"] == "FeatureCollection"


def test_sprint1_poblacion_expuesta():
    """Sprint 1: población expuesta Censo 2024 INE."""
    p = PROCESSED / "poblacion_expuesta.csv"
    if not p.exists():
        pytest.skip("poblacion_expuesta no calculada")
    d = pd.read_csv(p)
    for c in ["volcan", "peligro_nivel", "poblacion_estimada"]:
        assert c in d.columns
    # Cross-check: Villarrica > 10k expuestos
    vil_total = d[d["volcan"] == "Villarrica"]["poblacion_estimada"].sum()
    assert vil_total > 10_000, f"Villarrica pob expuesta sospechosa: {vil_total}"


def test_geo_utils_match_nombres_volcan():
    """Los nombres difieren entre fuentes (yaml vs shapefile SERNAGEOMIN vs
    SENAPRED). Este matcher decide a qué volcán pertenece cada dato: si afloja,
    se le atribuyen zonas de peligro o población de OTRO volcán."""
    sys.path.insert(0, str(APP))
    from geo_utils import nombres_equivalentes as eq
    # Deben unificarse: misma entidad escrita distinto
    assert eq("Nevados Chillan", "Nevados de Chillan")
    assert eq("Mocho - Choshuenco", "Mocho-Choshuenco")
    assert eq("Chaitén", "Chaiten")
    assert eq("Puyehue-Cordón Caulle", "Puyehue-Cordon Caulle")
    # NO deben unificarse: volcanes distintos a cientos de km
    assert not eq("San Pedro", "Tatara-San Pedro")
    assert not eq("Nevado de Longavi", "Nevados Chillan")
    assert not eq("", "Villarrica")


def test_geo_utils_volcanes_en_bbox():
    """Selección de volcanes por encuadre del mapa (carga al hacer zoom)."""
    sys.path.insert(0, str(APP))
    from geo_utils import volcanes_en_bbox
    vs = [{"nombre": "Villarrica", "lat": -39.42, "lon": -71.93, "codigo": "VIL"},
          {"nombre": "Lascar", "lat": -23.37, "lon": -67.73, "codigo": "LAS"}]
    b = {"_southWest": {"lat": -39.8, "lng": -72.3},
         "_northEast": {"lat": -39.0, "lng": -71.5}}
    assert [v["codigo"] for v in volcanes_en_bbox(vs, b)] == ["VIL"]
    # Entradas degradadas no deben romper el render del mapa
    assert volcanes_en_bbox(vs, {}) == []
    assert volcanes_en_bbox(vs, None) == []
    assert volcanes_en_bbox([], b) == []


def test_peligros_no_se_cruzan_entre_volcanes():
    """Un volcán no puede mostrar las zonas de peligro de otro.
    Regresión: el filtro por token suelto hacía que 'Nevado de Longaví' se
    quedara con los polígonos de 'Nevados Chillán', a ~200 km."""
    sys.path.insert(0, str(APP))
    from geo_utils import normalizar, punto_representativo
    p = PROCESSED / "peligros_volcanicos.geojson"
    if not p.exists():
        pytest.skip("peligros_volcanicos.geojson no disponible")
    feats = json.load(open(p, encoding="utf-8"))["features"]
    volcanes = _load_yaml(CONFIG)["volcanes"]

    def filtro(volcan):
        nv = normalizar(volcan["nombre"])
        out = []
        for f in feats:
            pn = normalizar((f.get("properties") or {}).get("volcan") or "")
            if not pn or not (nv in pn or pn in nv):
                continue
            pt = punto_representativo(f.get("geometry"))
            if pt is None or (abs(pt[0] - volcan["lat"]) <= 1.0
                              and abs(pt[1] - volcan["lon"]) <= 1.0):
                out.append(f)
        return out

    for v in volcanes:
        for f in filtro(v):
            pn = (f.get("properties") or {}).get("volcan") or ""
            pt = punto_representativo(f.get("geometry"))
            if pt is None:
                continue
            dist = max(abs(pt[0] - v["lat"]), abs(pt[1] - v["lon"]))
            assert dist <= 1.0, (
                f"{v['nombre']} recibe polígono de '{pn}' a {dist:.1f}° de distancia")


def test_drenajes_lite_generados():
    """Shards livianos que alimentan la carga por zoom. Sin ellos el loader cae
    al shard completo y consume más RAM que antes de la optimización."""
    d = PROCESSED / "drenajes_lite"
    if not d.exists():
        pytest.skip("drenajes_lite no generado — correr scripts/16_drenajes_lite.py")
    lite = list(d.glob("*.geojson"))
    completos = list((PROCESSED / "drenajes").glob("*.geojson"))
    assert len(lite) == len(completos), "falta un shard lite por volcán"
    peso_lite = sum(f.stat().st_size for f in lite)
    peso_full = sum(f.stat().st_size for f in completos)
    assert peso_lite < peso_full * 0.5, (
        f"lite ({peso_lite/1e6:.1f} MB) debería pesar mucho menos que completo "
        f"({peso_full/1e6:.1f} MB)")
    # Todo feature del lite tiene nombre: ese es el punto de la capa
    muestra = json.load(open(PROCESSED / "drenajes_lite" / "VIL.geojson", encoding="utf-8"))
    for f in muestra["features"]:
        n = (f.get("properties") or {}).get("nombre")
        assert n and n != "Sin nombre"


def test_comunas_local():
    """Comunas locales (reemplaza WMS BCN roto) — global + shards por volcan."""
    glob_p = PROCESSED / "comunas.geojson"
    if not glob_p.exists():
        pytest.skip("comunas no procesadas — correr scripts/10_comunas_local.py")
    g = json.load(open(glob_p, encoding="utf-8"))
    n = len(g["features"])
    assert n >= 340, f"esperaba ~345 comunas, hay {n}"
    # Verificar schema esperado por dashboard tooltip
    for campo in ["nombre_comuna", "nombre_provincia", "nombre_region"]:
        assert campo in g["features"][0]["properties"], f"falta campo {campo}"
    # Shard Villarrica deberia incluir las 4 esperadas
    vil = json.load(open(PROCESSED / "comunas" / "VIL.geojson", encoding="utf-8"))
    vil_nombres = {f["properties"]["nombre_comuna"] for f in vil["features"]}
    esperadas = {"Villarrica", "Pucón", "Curarrehue", "Panguipulli"}
    assert esperadas <= vil_nombres, f"VIL faltan comunas: {esperadas - vil_nombres}"


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
