"""
geo_utils.py — Utilidades geograficas y de normalizacion de texto.
Sin dependencias de streamlit ni geopandas.
"""
import math
import re
import unicodedata


def normalizar(s: str) -> str:
    """Normaliza texto para comparaciones: minusculas, sin tildes, separadores
    colapsados. Usada para matchear nombres entre fuentes (yaml vs shapefile)."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    s = re.sub(r"[\s\-_]+", " ", s)
    return s


def latlon_a_utm(lat: float, lon: float) -> tuple[float, float, int]:
    """WGS84 → UTM. Formula Karney/USGS, precision metrica."""
    zone    = int((lon + 180) / 6) + 1
    lon_rad = math.radians(lon)
    lat_rad = math.radians(lat)
    a   = 6378137.0
    f   = 1 / 298.257223563
    e2  = 1 - (1 - f) ** 2
    lon0 = math.radians((zone - 1) * 6 - 180 + 3)
    N    = a / math.sqrt(1 - e2 * math.sin(lat_rad) ** 2)
    T    = math.tan(lat_rad) ** 2
    C    = e2 / (1 - e2) * math.cos(lat_rad) ** 2
    A    = math.cos(lat_rad) * (lon_rad - lon0)
    M    = a * (
        (1 - e2/4 - 3*e2**2/64 - 5*e2**3/256)  * lat_rad
        - (3*e2/8 + 3*e2**2/32 + 45*e2**3/1024) * math.sin(2*lat_rad)
        + (15*e2**2/256 + 45*e2**3/1024)         * math.sin(4*lat_rad)
        - (35*e2**3/3072)                         * math.sin(6*lat_rad)
    )
    easting = 500000.0 + 0.9996 * N * (
        A + (1 - T + C) * A**3 / 6
        + (5 - 18*T + T**2 + 72*C - 58*(e2/(1-e2))) * A**5 / 120
    )
    northing = (0.0 if lat >= 0 else 10_000_000.0) + 0.9996 * (
        M + N * math.tan(lat_rad) * (
            A**2 / 2
            + (5 - T + 9*C + 4*C**2) * A**4 / 24
            + (61 - 58*T + T**2 + 600*C - 330*(e2/(1-e2))) * A**6 / 720
        )
    )
    return easting, northing, zone


# Conectores que las distintas fuentes ponen o sacan sin criterio:
# SERNAGEOMIN escribe "Nevados Chillan" y el catalogo "Nevados de Chillan".
_CONECTORES = {"de", "del", "la", "las", "los", "el", "y", "o"}


def nombres_equivalentes(a: str, b: str) -> bool:
    """True si dos nombres de volcan designan al mismo, tolerando conectores.

    Compara el conjunto de palabras significativas, no la cadena literal:
      "Nevados Chillan"    == "Nevados de Chillan"   -> True
      "Mocho - Choshuenco" == "Mocho-Choshuenco"     -> True
      "San Pedro"          != "Tatara-San Pedro"     -> False  (son distintos)
      "Nevado de Longavi"  != "Nevados Chillan"      -> False
    """
    if not a or not b:
        return False
    na, nb = normalizar(a), normalizar(b)
    if na == nb:
        return True
    ta = {p for p in na.split() if p not in _CONECTORES}
    tb = {p for p in nb.split() if p not in _CONECTORES}
    return bool(ta) and ta == tb


def punto_representativo(geom: dict | None) -> tuple[float, float] | None:
    """Un punto cualquiera dentro de la geometria, como (lat, lon).

    No es el centroide real: toma el primer vertice que encuentre recorriendo
    las coordenadas anidadas. Alcanza para discriminar a que volcan pertenece
    un poligono cuando los candidatos estan a decenas o cientos de km.
    """
    if not geom:
        return None
    coords = geom.get("coordinates")
    # Descender por listas anidadas hasta el primer par [lon, lat]
    while isinstance(coords, (list, tuple)) and coords:
        primero = coords[0]
        if isinstance(primero, (int, float)):
            if len(coords) >= 2 and isinstance(coords[1], (int, float)):
                return float(coords[1]), float(coords[0])
            return None
        coords = primero
    return None


def volcanes_en_bbox(volcanes: list[dict], bounds: dict,
                     margen_deg: float = 0.45) -> list[dict]:
    """Volcanes cuyo edificio cae dentro del encuadre actual del mapa.

    `bounds` viene de streamlit-folium con la forma que usa Leaflet:
        {"_southWest": {"lat": .., "lng": ..}, "_northEast": {"lat": .., "lng": ..}}

    El margen extiende el encuadre porque un volcán apenas fuera de pantalla
    igual aporta quebradas que SÍ entran en la vista (el buffer de influencia
    es de 50 km ~ 0.45°). Devuelve la lista ordenada por cercanía al centro
    del encuadre, para poder recortar a los N más relevantes.
    """
    sw = (bounds or {}).get("_southWest") or {}
    ne = (bounds or {}).get("_northEast") or {}
    lat_min, lon_min = sw.get("lat"), sw.get("lng")
    lat_max, lon_max = ne.get("lat"), ne.get("lng")
    if None in (lat_min, lon_min, lat_max, lon_max):
        return []
    # Leaflet puede devolver el par invertido segun como se armo el encuadre
    if lat_min > lat_max:
        lat_min, lat_max = lat_max, lat_min
    if lon_min > lon_max:
        lon_min, lon_max = lon_max, lon_min

    dentro = [
        v for v in volcanes
        if lat_min - margen_deg <= v["lat"] <= lat_max + margen_deg
        and lon_min - margen_deg <= v["lon"] <= lon_max + margen_deg
    ]
    cy = (lat_min + lat_max) / 2
    cx = (lon_min + lon_max) / 2
    dentro.sort(key=lambda v: (v["lat"] - cy) ** 2 + (v["lon"] - cx) ** 2)
    return dentro


def midpoint_geojson(feature: dict) -> tuple[float, float] | None:
    """Coordenada media de LineString/MultiLineString para etiquetas."""
    try:
        geom   = feature["geometry"]
        coords = geom["coordinates"]
        if geom["type"] == "MultiLineString":
            coords = coords[0]
        mid = coords[len(coords) // 2]
        return mid[1], mid[0]
    except (KeyError, IndexError, TypeError):
        return None
