"""
11_estado_reav.py — Estado de alerta REAV (SERNAGEOMIN) para los 59 volcanes.

Fenomeno / por que:
  Los Reportes Especiales de Actividad Volcanica (REAV) son la voz oficial del
  OVDAS-SERNAGEOMIN sobre el estado de un volcan. El nivel de alerta tiene 4
  pasos (Verde -> Amarillo -> Naranja -> Rojo) y refleja la probabilidad y/o
  inminencia de una erupcion. Para el dashboard de Valles necesitamos, por cada
  volcan, el ultimo nivel de alerta y el link al ultimo REAV.

Realidad de la fuente publica (jun-2026):
  - SERNAGEOMIN expone PUBLICAMENTE solo las alertas distintas de verde en
    https://www.sernageomin.cl/alertas-volcanicas/. Esa pagina lista los
    volcanes con alerta amarilla/naranja/roja vigente y muestra imagenes con
    patron `Alerta_<slug-volcan>_<color>.png` (alojadas bajo wp-content/uploads).
  - No hay listado HTML/JSON publico del nivel verde por volcan ni endpoint
    REAV historico abierto. La pagina RNVV principal lo declara explicitamente
    ("visualizacion en tiempo real no disponible en el sitio web").

Estrategia:
  1. Scrapear /alertas-volcanicas/ para extraer los volcanes con alerta activa
     (amarilla/naranja/roja), su slug y la URL de la imagen como referencia.
  2. Asumir VERDE para todos los volcanes con `monitoreado_ovdas != False` que
     NO aparecen en alerta activa (asuncion conservadora: si OVDAS los vigila
     24/7 y no hay alerta publicada, su nivel reportado es verde).
  3. Para los 16 volcanes con `monitoreado_ovdas: false`, dejar nivel = None
     (no son parte del monitoreo permanente, no aplica REAV).

Output: data/processed/estado_reav.csv

Limitaciones documentadas en consola al final.
"""
from __future__ import annotations

import csv
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
YAML_PATH = ROOT / "config" / "volcanoes.yaml"
OUT_CSV = ROOT / "data" / "processed" / "estado_reav.csv"

URL_ALERTAS = "https://www.sernageomin.cl/alertas-volcanicas/"
URL_RNVV = "https://www.sernageomin.cl/rnvv/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
}

NIVELES = {
    "verde": "Verde",
    "amarilla": "Amarillo",
    "amarillo": "Amarillo",
    "naranja": "Naranja",
    "naranjo": "Naranja",
    "roja": "Rojo",
    "rojo": "Rojo",
}


def _normalizar(s: str) -> str:
    """Lowercase, sin tildes, espacios colapsados; para matching tolerante."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s


def fetch(url: str, intentos: int = 3, pausa: float = 1.0) -> str | None:
    """
    GET con reintentos y rate limit.

    Nota SSL: el certificado de sernageomin.cl no siempre valida con el bundle
    de Windows. Probamos primero con verify=True (certifi); si falla por SSL,
    reintentamos con verify=False (documentado en consola). Es una fuente
    publica gubernamental sin datos sensibles del lado cliente, asi que el
    riesgo de MITM es bajo para lectura.
    """
    for i in range(1, intentos + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                return r.text
            print(f"  [intento {i}/{intentos}] {url} -> HTTP {r.status_code}")
        except requests.exceptions.SSLError as e:
            print(f"  [intento {i}/{intentos}] {url} -> SSL fail, reintentando sin verify")
            try:
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                r = requests.get(url, headers=HEADERS, timeout=20, verify=False)
                if r.status_code == 200:
                    return r.text
                print(f"  [intento {i}/{intentos}] {url} (no-verify) -> HTTP {r.status_code}")
            except requests.RequestException as e2:
                print(f"  [intento {i}/{intentos}] {url} (no-verify) -> {e2.__class__.__name__}")
        except requests.RequestException as e:
            print(f"  [intento {i}/{intentos}] {url} -> {e.__class__.__name__}: {e}")
        time.sleep(pausa)
    return None


def parse_alertas_activas(html: str) -> list[dict]:
    """
    Extrae alertas activas de /alertas-volcanicas/.

    Returns: lista de dicts con keys: slug, nivel, url_imagen, fecha_imagen
    """
    soup = BeautifulSoup(html, "html.parser")
    alertas = []
    vistos = set()

    # Patron de imagen: Alerta_<slug>_<color>.png (a veces con guiones bajos)
    re_img = re.compile(
        r"Alerta[_-](?P<slug>[a-z0-9\-]+)[_-](?P<color>verde|amarilla|amarillo|naranja|naranjo|roja|rojo)\.(?:png|jpg|jpeg|webp)",
        re.IGNORECASE,
    )
    # Fecha del path: /uploads/YYYY/MM/
    re_fecha = re.compile(r"/uploads/(?P<y>20\d{2})/(?P<m>\d{2})/")

    for img in soup.find_all("img"):
        src = img.get("src", "") or img.get("data-src", "")
        if not src:
            continue
        m = re_img.search(src)
        if not m:
            continue
        slug = m.group("slug").lower()
        color = m.group("color").lower()
        nivel = NIVELES.get(color)
        if nivel is None or nivel == "Verde":
            # La pagina publica no publica verdes; si apareciera, lo ignoramos
            # aqui porque se asume verde por default mas adelante.
            continue
        clave = (slug, nivel)
        if clave in vistos:
            continue
        vistos.add(clave)

        fecha = None
        mf = re_fecha.search(src)
        if mf:
            try:
                fecha = f"{mf.group('y')}-{mf.group('m')}-01"
            except Exception:
                fecha = None

        alertas.append(
            {
                "slug": slug,
                "slug_norm": _normalizar(slug.replace("-", " ")),
                "nivel": nivel,
                "url_imagen": src if src.startswith("http") else f"https://www.sernageomin.cl{src}",
                "fecha_imagen": fecha,
            }
        )

    return alertas


def match_slug_to_volcano(slug_norm: str, volcanes_norm: dict[str, str]) -> str | None:
    """
    Matcha slug normalizado (ej 'nevado de longavi') contra el dict
    {nombre_normalizado: codigo}. Tolera prefijos comunes.
    """
    candidatos = [slug_norm]
    # Heuristicas: remover prefijo "volcan", "complejo", "nevado", "cerro"
    sin_prefijos = re.sub(r"^(volcan|complejo|nevado de|nevados de|nevado|cerro)\s+", "", slug_norm)
    if sin_prefijos != slug_norm:
        candidatos.append(sin_prefijos)
    # Probar match exacto y luego contencion
    for c in candidatos:
        if c in volcanes_norm:
            return volcanes_norm[c]
    for c in candidatos:
        for nombre_norm, codigo in volcanes_norm.items():
            if c == nombre_norm or c in nombre_norm or nombre_norm in c:
                return codigo
    return None


def main() -> int:
    t0 = time.time()
    print(f"[1/4] Leyendo {YAML_PATH.relative_to(ROOT)}")
    with YAML_PATH.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    volcanes = cfg.get("volcanes", [])
    if not volcanes:
        print("ERROR: yaml sin volcanes")
        return 1
    print(f"      {len(volcanes)} volcanes cargados")

    # Diccionario nombre normalizado -> codigo
    volcanes_norm = {_normalizar(v["nombre"]): v["codigo"] for v in volcanes}

    print(f"[2/4] Fetching {URL_ALERTAS}")
    html = fetch(URL_ALERTAS)
    url_funciono = URL_ALERTAS
    time.sleep(1.0)
    if html is None:
        print(f"      Fallback: probando {URL_RNVV}")
        html = fetch(URL_RNVV)
        url_funciono = URL_RNVV if html else None
        time.sleep(1.0)

    if html is None:
        print("ERROR: SERNAGEOMIN no respondio en 3 intentos a las URLs probadas:")
        print(f"  - {URL_ALERTAS}")
        print(f"  - {URL_RNVV}")
        return 2

    print(f"      OK ({len(html)} bytes) desde {url_funciono}")

    print("[3/4] Parseando alertas activas (amarilla/naranja/roja)")
    alertas = parse_alertas_activas(html)
    print(f"      {len(alertas)} alertas activas detectadas")
    for a in alertas:
        print(f"        - slug='{a['slug']}' nivel={a['nivel']} fecha~{a['fecha_imagen']}")

    # Mapear alertas a codigo de volcan
    estado_por_codigo: dict[str, dict] = {}
    no_mapeadas = []
    for a in alertas:
        codigo = match_slug_to_volcano(a["slug_norm"], volcanes_norm)
        if codigo is None:
            no_mapeadas.append(a["slug"])
            continue
        # Si hay duplicados, gana el nivel mas alto
        prioridad = {"Verde": 0, "Amarillo": 1, "Naranja": 2, "Rojo": 3}
        actual = estado_por_codigo.get(codigo)
        if actual is None or prioridad[a["nivel"]] > prioridad[actual["nivel"]]:
            estado_por_codigo[codigo] = {
                "nivel": a["nivel"],
                "fecha_reav": a["fecha_imagen"],
                "url_reav": url_funciono,  # No tenemos PDF directo, devolvemos pagina oficial
                "resumen": f"Alerta {a['nivel'].lower()} vigente segun SERNAGEOMIN (imagen: {a['url_imagen']})",
            }

    if no_mapeadas:
        print(f"      WARN: alertas no mapeadas a yaml: {no_mapeadas}")

    print("[4/4] Construyendo CSV")
    fecha_scrape = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    cuenta_nivel = {"Verde": 0, "Amarillo": 0, "Naranja": 0, "Rojo": 0, "Sin datos": 0}
    for v in volcanes:
        codigo = v["codigo"]
        nombre = v["nombre"]
        monitoreado = v.get("monitoreado_ovdas", True)  # default True (43 OVDAS)
        if codigo in estado_por_codigo:
            est = estado_por_codigo[codigo]
            nivel = est["nivel"]
            fecha_reav = est["fecha_reav"]
            url_reav = est["url_reav"]
            resumen = est["resumen"]
        elif monitoreado:
            nivel = "Verde"
            fecha_reav = None
            url_reav = url_funciono
            resumen = "Sin alerta publicada; OVDAS mantiene vigilancia 24/7 (nivel verde por defecto)"
        else:
            nivel = None
            fecha_reav = None
            url_reav = None
            resumen = "Volcan no incluido en monitoreo permanente OVDAS"

        cuenta_nivel[nivel if nivel else "Sin datos"] += 1
        rows.append(
            {
                "codigo": codigo,
                "nombre": nombre,
                "nivel": nivel if nivel else "",
                "fecha_reav": fecha_reav if fecha_reav else "",
                "url_reav": url_reav if url_reav else "",
                "resumen": resumen,
                "fecha_scrape": fecha_scrape,
            }
        )

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["codigo", "nombre", "nivel", "fecha_reav", "url_reav", "resumen", "fecha_scrape"],
        )
        w.writeheader()
        w.writerows(rows)

    dt = time.time() - t0
    print()
    print("=" * 70)
    print("RESUMEN")
    print("=" * 70)
    print(f"URL fuente que funciono : {url_funciono}")
    print(f"CSV escrito             : {OUT_CSV.relative_to(ROOT)}")
    print(f"Total volcanes          : {len(rows)}")
    print(f"  Verde     : {cuenta_nivel['Verde']}")
    print(f"  Amarillo  : {cuenta_nivel['Amarillo']}")
    print(f"  Naranja   : {cuenta_nivel['Naranja']}")
    print(f"  Rojo      : {cuenta_nivel['Rojo']}")
    print(f"  Sin datos : {cuenta_nivel['Sin datos']}")
    print(f"Alertas activas detectadas en la fuente: {len(alertas)}")
    print(f"Alertas mapeadas a volcanes del yaml   : {len(estado_por_codigo)}")
    print(f"Alertas NO mapeadas                    : {len(no_mapeadas)}")
    print(f"Tiempo total            : {dt:.1f}s")
    print()
    print("Limitaciones de la fuente publica:")
    print("  - SERNAGEOMIN solo publica volcanes con alerta != Verde.")
    print("  - 'Verde' se asume para los 43 monitoreados OVDAS sin alerta listada.")
    print("  - 'fecha_reav' es la fecha del directorio /uploads/YYYY/MM/ de la imagen,")
    print("    aproximada al mes; no es la fecha exacta del REAV individual.")
    print("  - 'url_reav' apunta a la pagina oficial de alertas (no al PDF del REAV).")
    print()
    print("Primeras 5 filas del CSV:")
    for r in rows[:5]:
        print(f"  {r['codigo']:>4} | {r['nombre']:<22} | {r['nivel']:<9} | {r['fecha_reav']:<10} | {r['resumen'][:60]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
