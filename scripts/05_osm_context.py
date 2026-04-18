"""
05_osm_context.py
-----------------
Descarga capas de contexto desde OpenStreetMap (Chile completo):
  - Red vial principal (motorway, trunk, primary)
  - Infraestructura critica (hospitales, helipuertos, represas, centrales electricas)
  - Centros poblados como poligonos (landuse=residential + place boundaries)

Salida:
  data/processed/red_vial.geojson          (~2-5 MB)
  data/processed/infraestructura.geojson   (~300 KB)
  data/processed/centros_poblados.geojson  (~1-3 MB)
"""

import requests, json, time
from pathlib import Path

PROCESSED = Path("data/processed")
PROCESSED.mkdir(parents=True, exist_ok=True)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Bounding box Chile: (S, W, N, E)
CHILE_BBOX = "-56,-76,-17,-66"


def log(msg):
    print(msg, flush=True)


def overpass_query(query, desc, max_retries=5):
    log(f"\nDescargando: {desc}...")
    wait = 15
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.post(OVERPASS_URL, data={"data": query}, timeout=240)
            if r.status_code == 429:
                log(f"  [rate limit] espera {wait}s (intento {attempt})")
                time.sleep(wait); wait *= 2; continue
            if r.status_code == 504:
                log(f"  [timeout 504] espera {wait}s (intento {attempt})")
                time.sleep(wait); wait *= 2; continue
            r.raise_for_status()
            data = r.json()
            log(f"  {len(data.get('elements', []))} elementos recibidos")
            return data
        except Exception as e:
            if attempt == max_retries:
                log(f"  [fallo definitivo] {e}")
                return None
            log(f"  [error] {e} — reintentando en {wait}s")
            time.sleep(wait); wait *= 2
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 1. RED VIAL PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

vial_query = f"""
[out:json][timeout:240];
(
  way["highway"~"^(motorway|trunk|primary)$"]({CHILE_BBOX});
);
out geom;
"""

vial_data = overpass_query(vial_query, "red vial principal (motorway / trunk / primary)")

if vial_data:
    TIPO_COLOR = {
        "motorway": "#e63946",
        "trunk":    "#f4a261",
        "primary":  "#f9c74f",
    }
    features = []
    for el in vial_data.get("elements", []):
        if el["type"] != "way" or "geometry" not in el:
            continue
        coords = [[p["lon"], p["lat"]] for p in el["geometry"]]
        if len(coords) < 2:
            continue
        tags = el.get("tags", {})
        tipo = tags.get("highway", "")
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {
                "tipo":   tipo,
                "nombre": tags.get("name", ""),
                "ref":    tags.get("ref", ""),
                "color":  TIPO_COLOR.get(tipo, "#aaa"),
            },
        })
    gj = {"type": "FeatureCollection", "features": features}
    out = PROCESSED / "red_vial.geojson"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(gj, f)
    kb = out.stat().st_size // 1024
    by_tipo = {}
    for ft in features:
        t = ft["properties"]["tipo"]
        by_tipo[t] = by_tipo.get(t, 0) + 1
    log(f"  -> red_vial.geojson  ({kb} KB)")
    for t, n in sorted(by_tipo.items()):
        log(f"     {t}: {n} vias")

time.sleep(10)

# ─────────────────────────────────────────────────────────────────────────────
# 2. INFRAESTRUCTURA CRITICA
# ─────────────────────────────────────────────────────────────────────────────

infra_query = f"""
[out:json][timeout:180];
(
  node["amenity"~"^(hospital|clinic)$"]({CHILE_BBOX});
  way["amenity"="hospital"]({CHILE_BBOX});
  node["aeroway"="helipad"]({CHILE_BBOX});
  node["waterway"="dam"]({CHILE_BBOX});
  way["waterway"="dam"]({CHILE_BBOX});
  node["power"="plant"]({CHILE_BBOX});
  way["power"="plant"]({CHILE_BBOX});
);
out center geom;
"""

infra_data = overpass_query(infra_query, "infraestructura critica (hospitales / helipuertos / represas / centrales)")

INFRA_CONFIG = {
    "hospital":          {"icono": "🏥", "color": "#e63946"},
    "clinic":            {"icono": "🏥", "color": "#ff8fa3"},
    "helipuerto":        {"icono": "🚁", "color": "#00b4d8"},
    "represa":           {"icono": "💧", "color": "#0077b6"},
    "planta_electrica":  {"icono": "⚡", "color": "#f9c74f"},
}

def tipo_infra(tags):
    amenity  = tags.get("amenity", "")
    aeroway  = tags.get("aeroway", "")
    waterway = tags.get("waterway", "")
    power    = tags.get("power", "")
    if amenity == "hospital":  return "hospital"
    if amenity == "clinic":    return "clinic"
    if aeroway == "helipad":   return "helipuerto"
    if waterway == "dam":      return "represa"
    if power == "plant":       return "planta_electrica"
    return ""

if infra_data:
    features = []
    for el in infra_data.get("elements", []):
        tags = el.get("tags", {})
        tipo = tipo_infra(tags)
        if not tipo:
            continue
        # Coordenada: node tiene lat/lon directas; way tiene center
        if el["type"] == "node":
            lat, lon = el.get("lat"), el.get("lon")
        elif el["type"] == "way":
            center = el.get("center", {})
            lat, lon = center.get("lat"), center.get("lon")
        else:
            continue
        if lat is None or lon is None:
            continue
        cfg = INFRA_CONFIG.get(tipo, {"icono": "·", "color": "#aaa"})
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "tipo":   tipo,
                "nombre": tags.get("name", "Sin nombre"),
                "icono":  cfg["icono"],
                "color":  cfg["color"],
            },
        })
    gj = {"type": "FeatureCollection", "features": features}
    out = PROCESSED / "infraestructura.geojson"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(gj, f)
    kb = out.stat().st_size // 1024
    by_tipo = {}
    for ft in features:
        t = ft["properties"]["tipo"]
        by_tipo[t] = by_tipo.get(t, 0) + 1
    log(f"  -> infraestructura.geojson  ({kb} KB)")
    for t, n in sorted(by_tipo.items()):
        log(f"     {t}: {n}")

time.sleep(10)

# ─────────────────────────────────────────────────────────────────────────────
# 3. CENTROS POBLADOS (poligonos)
# ─────────────────────────────────────────────────────────────────────────────
# Busca poligonos de lugar habitado: city/town/village/hamlet + residential areas

poblados_query = f"""
[out:json][timeout:240];
(
  relation["boundary"="administrative"]["admin_level"="8"]({CHILE_BBOX});
  way["landuse"="residential"]["name"]({CHILE_BBOX});
  way["place"~"^(city|town|village|hamlet)$"]({CHILE_BBOX});
);
out geom;
"""

poblados_data = overpass_query(poblados_query, "centros poblados (poligonos OSM)")

if poblados_data:
    features = []
    for el in poblados_data.get("elements", []):
        tags = el.get("tags", {})
        nombre = tags.get("name", "")
        tipo   = tags.get("place", tags.get("landuse", tags.get("boundary", "")))
        pop_str = tags.get("population", "")
        try:
            pop = int(pop_str.replace(",", "").replace(".", ""))
        except Exception:
            pop = 0

        if el["type"] == "way":
            geom_pts = el.get("geometry", [])
            if len(geom_pts) < 3:
                continue
            coords = [[p["lon"], p["lat"]] for p in geom_pts]
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            geometry = {"type": "Polygon", "coordinates": [coords]}

        elif el["type"] == "relation":
            # Simplificado: tomar el outer mas largo como poligono
            outers = [m for m in el.get("members", []) if m.get("role") == "outer"]
            if not outers:
                continue
            # Usar el geometry de la relacion si esta disponible
            geom_pts = el.get("geometry", [])
            if len(geom_pts) < 3:
                continue
            coords = [[p["lon"], p["lat"]] for p in geom_pts if "lon" in p]
            if len(coords) < 3:
                continue
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            geometry = {"type": "Polygon", "coordinates": [coords]}
        else:
            continue

        features.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": {
                "nombre":     nombre,
                "tipo":       tipo,
                "poblacion":  pop,
            },
        })

    gj = {"type": "FeatureCollection", "features": features}
    out = PROCESSED / "centros_poblados.geojson"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(gj, f)
    kb = out.stat().st_size // 1024
    log(f"  -> centros_poblados.geojson  ({len(features)} poligonos, {kb} KB)")

log("\n=== Listo. ===")
