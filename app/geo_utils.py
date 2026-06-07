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
