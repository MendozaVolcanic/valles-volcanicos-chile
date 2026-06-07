"""
08_descargar_senapred.py
------------------------
Descarga las capas oficiales de SENAPRED desde sus FeatureServers publicos
de ArcGIS Online (los mismos que consume el Visor Chile Preparado).

Fuente: services5.arcgis.com / org SENAPRED (geoportalonemi)

Capas integradas:
  AMENAZA_VOLCANICA_2024 / FeatureServer
    0 Puntos de Encuentro (168 features) ← evacuacion oficial
    1 Vias de Evacuacion  (195 features)
    2 Areas de Peligro Volcanico (3499 polygons, peligro Alto/Medio/Bajo)
    3 Volcanes Geologicamente Activos: Peligrosidad
  BUFFER_VOLCANES_2024 / FeatureServer
    0 Distancia a crater (poligonos)
    1 Distancia a crater (lineas)
  Per_Seguridad_Villarrica / FeatureServer / 0  Perimetro de seguridad
  Servicios_2024 / FeatureServer
    0 SALUD, 1 BOMBEROS, 2 EDUCACION, 3 CARABINEROS

Cada layer se baja paginada (1000 features/req) y se guarda como GeoJSON
en data/processed/senapred/{nombre}.geojson.

Estos datos van versionados — actualizan poco (anuales) y son livianos.
"""
from pathlib import Path
import requests
import json
import sys
from urllib.parse import quote

ROOT     = Path(__file__).resolve().parent.parent
OUT_DIR  = ROOT / "data" / "processed" / "senapred"
OUT_DIR.mkdir(parents=True, exist_ok=True)

BASE = "https://services5.arcgis.com/i7S5PSnIJAUcWvSE/arcgis/rest/services"

# (path, layer_id, nombre_archivo, descripcion)
CAPAS = [
    (f"AMENAZA_VOLC{quote('Á')}NICA_2024", 0, "puntos_encuentro",      "Puntos de encuentro oficiales"),
    (f"AMENAZA_VOLC{quote('Á')}NICA_2024", 1, "vias_evacuacion",       "Vías de evacuación"),
    (f"AMENAZA_VOLC{quote('Á')}NICA_2024", 2, "areas_peligro",         "Áreas de peligro volcánico"),
    (f"AMENAZA_VOLC{quote('Á')}NICA_2024", 3, "volcanes_peligrosidad", "Volcanes activos: peligrosidad"),
    ("BUFFER_VOLCANES_2024",               0, "buffer_volcanes_poly",  "Distancia a cráter (polígonos)"),
    ("BUFFER_VOLCANES_2024",               1, "buffer_volcanes_line",  "Distancia a cráter (líneas)"),
    ("Per_Seguridad_Villarrica",           0, "perimetro_villarrica",  "Perímetro seguridad Villarrica"),
    ("Servicios_2024",                     0, "servicios_salud",       "Servicios SALUD"),
    ("Servicios_2024",                     1, "servicios_bomberos",    "Servicios BOMBEROS"),
    ("Servicios_2024",                     2, "servicios_educacion",   "Servicios EDUCACION"),
    ("Servicios_2024",                     3, "servicios_carabineros", "Servicios CARABINEROS"),
]


def descargar_capa(service_path: str, layer_id: int, out_name: str, desc: str):
    out_f = OUT_DIR / f"{out_name}.geojson"
    base_url = f"{BASE}/{service_path}/FeatureServer/{layer_id}"
    # Conteo
    try:
        cnt = requests.get(f"{base_url}/query",
                           params={"where": "1=1", "returnCountOnly": "true", "f": "json"},
                           timeout=15).json().get("count", 0)
    except Exception as e:
        print(f"  [!] {out_name}: falla conteo: {e}")
        return
    print(f"  {desc} ({cnt} features) -> {out_f.name}")

    all_features = []
    offset = 0
    page   = 1000
    while True:
        r = requests.get(f"{base_url}/query", params={
            "where": "1=1",
            "outFields": "*",
            "outSR": "4326",
            "f": "geojson",
            "resultOffset": str(offset),
            "resultRecordCount": str(page),
        }, timeout=60)
        if not r.ok:
            print(f"    HTTP {r.status_code}")
            return
        data = r.json()
        feats = data.get("features", [])
        all_features.extend(feats)
        if len(feats) < page:
            break
        offset += page

    fc = {"type": "FeatureCollection", "features": all_features}
    out_f.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    print(f"    {len(all_features)} features, {out_f.stat().st_size/1024:.0f} KB")


def main():
    print(f"Descargando capas SENAPRED a {OUT_DIR}/\n")
    for service, layer, name, desc in CAPAS:
        descargar_capa(service, layer, name, desc)
    print("\nListo.")


if __name__ == "__main__":
    main()
