"""
13_gvp_smithsonian.py
---------------------
Descarga las fichas del Global Volcanism Program (GVP) del Smithsonian
Institution para los 59 volcanes activos de Chile del proyecto.

CONTEXTO (por que): el GVP es el catalogo de referencia mundial para
historia eruptiva (Holoceno + Pleistoceno). Cada volcan tiene un numero
unico (Volcano_Number, p.ej. Villarrica = 357120) y una ficha publica con
tipo morfologico, ultima erupcion, VEI maximo, composicion litologica
dominante y resumen geologico. Tener este enlace para los 59 volcanes nos
permite (1) cross-checkear nuestro catalogo SERNAGEOMIN/OVDAS, (2) anclar
cada volcan a una URL canonica que el dashboard puede linkear, y (3)
calcular metricas historicas (numero de erupciones Holoceno, siglo XX-XXI,
VEI maximo) que el GVP mantiene actualizadas.

ENDPOINTS (GeoServer WFS publico del Smithsonian):
  Volcanes: https://webservices.volcano.si.edu/geoserver/GVP-VOTW/ows
    typeName: GVP-VOTW:Smithsonian_VOTW_Holocene_Volcanoes
    filtro:   Country LIKE '%Chile%'   (incluye Chile, Chile-Argentina,
              Chile-Bolivia: ~90 registros)
  Erupciones: mismo geoserver
    typeName: GVP-VOTW:Smithsonian_VOTW_Holocene_Eruptions
    filtro:   Volcano_Number = <id>

PROCESO:
  1. Cargar 59 volcanes del proyecto desde config/volcanoes.yaml
  2. Descargar lista global de volcanes GVP de la region "Chile-like" (1 req)
  3. Match: para cada volcan del proyecto:
       a) match por nombre normalizado (sin tildes, lowercase, sinonimos)
       b) si no, match por proximidad geografica < 0.1 grados (~11 km)
  4. Para cada match, descargar erupciones (1 req por volcan) y calcular:
       - ultima_erupcion (anio del Last_Eruption_Year + duracion media + VEI)
       - vei_maximo (max ExplosivityIndexMax sobre todas las erupciones)
       - num_erupciones_holoceno (todas las del feed Holocene)
       - num_erupciones_siglo_xx_xxi (StartDateYear >= 1900)
  5. Escribir data/processed/gvp.csv (59 filas)
  6. Reportar volcanes sin match.

NOTA: solo lectura de red externa (Smithsonian). No modifica raw existentes.

Ejecucion:
  python scripts/13_gvp_smithsonian.py
"""
from __future__ import annotations

from pathlib import Path
import io
import sys
import time
import unicodedata
import urllib.parse as urlparse

import pandas as pd
import requests
import yaml

# Forzar stdout UTF-8 en Windows (cp1252 default rompe tildes en logs)
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT          = Path(__file__).resolve().parent.parent
VOLCANOES_YML = ROOT / "config" / "volcanoes.yaml"
PROCESSED_DIR = ROOT / "data" / "processed"
OUT_CSV       = PROCESSED_DIR / "gvp.csv"

WFS_BASE      = "https://webservices.volcano.si.edu/geoserver/GVP-VOTW/ows"
TYPE_VOLC     = "GVP-VOTW:Smithsonian_VOTW_Holocene_Volcanoes"
TYPE_VOLC_PLE = "GVP-VOTW:Smithsonian_VOTW_Pleistocene_Volcanoes"
TYPE_ERUP     = "GVP-VOTW:Smithsonian_VOTW_Holocene_Eruptions"
VOLCANO_PAGE  = "https://volcano.si.edu/volcano.cfm?vn={vn}"

# Bounding box que cubre Chile y vecinos fronterizos (algunos volcanes
# limitrofes estan registrados con Country='Argentina' o 'Bolivia' aunque
# son binacionales — p.ej. Tata Sabaya (Bolivia), Tipas (Argentina)).
CQL_BBOX = (
    "Latitude > -57 AND Latitude < -17 "
    "AND Longitude > -76 AND Longitude < -66"
)

# Tolerancia de matching geografico (grados decimales).
# 0.1 deg ~ 11 km en Chile central. Es generoso pero el GVP a veces redondea
# coordenadas a 2 decimales y nuestro catalogo tambien, asi que el sesgo
# tipico es < 0.02 deg.
TOL_DEG       = 0.1

# Sinonimos manuales para casos en que el nombre SERNAGEOMIN difiere del
# nombre GVP. Se aplican despues de la normalizacion ASCII/lowercase.
SINONIMOS = {
    "san pedro": "san pedro",          # GVP: "San Pedro"
    "tupungatito": "tupungatito",
    "planchon peteroa": "planchon-peteroa",
    "planchon-peteroa": "planchon-peteroa",
    "descabezado grande": "descabezado grande",
    "nevados de chillan": "nevados de chillan",
    "callaqui": "callaqui",
    "copahue": "copahue",
    "chaiten": "chaiten",
    "olca paruma": "olca",
    "olca-paruma": "olca",
    "cordon caulle": "puyehue-cordon caulle",
    "puyehue cordon caulle": "puyehue-cordon caulle",
    "puyehue-cordon caulle": "puyehue-cordon caulle",
    "puyehue": "puyehue-cordon caulle",
    "calbuco": "calbuco",
    "michinmahuida": "michinmahuida",
    "huequi": "huequi",
    "yanteles": "yanteles",
    "melimoyu": "melimoyu",
    "puntiagudo": "puntiagudo-cordon cenizos",
    "antuco": "antuco",
    "longavi": "nevado de longavi",
    "nevado de longavi": "nevado de longavi",
    "azul": "cerro azul",            # ambiguo; el cerro azul del maule es 357060
    "cerro azul": "cerro azul",
    "domuyo": "domuyo",
    "lanin": "lanin",
    "lautaro": "lautaro",
    "viedma": "viedma",
    "aguilera": "aguilera",
    "reclus": "reclus",
    "burney": "monte burney",
    "monte burney": "monte burney",
    "fueguino": "fueguino",
    "hudson": "hudson cerro",
    "cerro hudson": "hudson cerro",
    "laguna del maule": "maule laguna del",
    "san pedro": "san pedro-san pablo",        # SDP en config = San Pedro de Atacama
    "tatara-san pedro": "san pedro-pellado",   # ya estaba via geo match
    "tatara san pedro": "san pedro-pellado",
    "nevado tres cruces": "nevado tres cruces",
}

REQUEST_TIMEOUT = 60
PAUSE_BETWEEN_ERUP = 0.4  # cortesia: ~150 req maximo para 59 volcanes


# ----------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------

def normalizar(s: str) -> str:
    """Lowercase + sin tildes + sin caracteres no alfanumericos al borde."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    # normalizar separadores
    s = s.replace("_", " ").replace(",", " ")
    while "  " in s:
        s = s.replace("  ", " ")
    return s


def cargar_volcanes_proyecto() -> pd.DataFrame:
    with VOLCANOES_YML.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    df = pd.DataFrame(cfg["volcanes"])
    df["nombre_norm"] = df["nombre"].map(normalizar)
    return df


def wfs_get_features(type_name: str, cql_filter: str | None = None) -> list[dict]:
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": type_name,
        "outputFormat": "application/json",
    }
    if cql_filter:
        params["CQL_FILTER"] = cql_filter
    r = requests.get(WFS_BASE, params=params, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    return data.get("features", [])


def _features_to_df(feats: list[dict], epoca: str) -> pd.DataFrame:
    rows = []
    for f in feats:
        p = f.get("properties", {})
        rows.append({
            "Volcano_Number":      p.get("Volcano_Number"),
            "Volcano_Name":        p.get("Volcano_Name"),
            "Primary_Volcano_Type": p.get("Primary_Volcano_Type"),
            "Volcanic_Landform":   p.get("Volcanic_Landform"),
            "Last_Eruption_Year":  p.get("Last_Eruption_Year"),   # solo Holocene
            "Country":             p.get("Country"),
            "Region":              p.get("Region"),
            "Subregion":           p.get("Subregion"),
            "Latitude":            p.get("Latitude"),
            "Longitude":           p.get("Longitude"),
            "Elevation":           p.get("Elevation"),
            "Major_Rock_Type":     p.get("Major_Rock_Type"),     # solo Holocene
            "_epoca":              epoca,
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["nombre_norm"] = df["Volcano_Name"].map(normalizar)
    df["Latitude"]  = pd.to_numeric(df["Latitude"], errors="coerce")
    df["Longitude"] = pd.to_numeric(df["Longitude"], errors="coerce")
    return df


def descargar_volcanes_chile() -> pd.DataFrame:
    """Trae volcanes GVP en el bounding box de Chile (Holocene + Pleistocene).

    El feed Holocene cubre ~90 volcanes con Country LIKE '%Chile%', pero
    algunos volcanes activos de nuestro catalogo (Tata Sabaya, Tipas) tienen
    Country='Bolivia'/'Argentina' aunque son binacionales. Y otros (Ollague,
    San Pedro de Atacama, Copiapo, San Francisco) estan registrados como
    Pleistoceno en GVP. Por eso queremos los dos feeds y filtramos por bbox.
    """
    holo  = _features_to_df(wfs_get_features(TYPE_VOLC, cql_filter=CQL_BBOX), "Holocene")
    plei  = _features_to_df(wfs_get_features(TYPE_VOLC_PLE, cql_filter=CQL_BBOX), "Pleistocene")
    # Holoceno tiene prioridad: si un mismo Volcano_Number apareciera en
    # ambos, nos quedamos con la entrada Holoceno (mas rica). De hecho los
    # Volcano_Number son disjuntos entre feeds, pero por las dudas:
    plei = plei[~plei["Volcano_Number"].isin(holo["Volcano_Number"])]
    return pd.concat([holo, plei], ignore_index=True)


def descargar_erupciones(volcano_number: int) -> pd.DataFrame:
    cql = f"Volcano_Number={int(volcano_number)}"
    feats = wfs_get_features(TYPE_ERUP, cql_filter=cql)
    rows = []
    for f in feats:
        p = f.get("properties", {})
        rows.append({
            "Eruption_Number":       p.get("Eruption_Number"),
            "Activity_Type":         p.get("Activity_Type"),
            "ExplosivityIndexMax":   p.get("ExplosivityIndexMax"),
            "StartDateYear":         p.get("StartDateYear"),
            "EndDateYear":           p.get("EndDateYear"),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["ExplosivityIndexMax"] = pd.to_numeric(df["ExplosivityIndexMax"], errors="coerce")
        df["StartDateYear"]       = pd.to_numeric(df["StartDateYear"], errors="coerce")
        df["EndDateYear"]         = pd.to_numeric(df["EndDateYear"], errors="coerce")
    return df


# ----------------------------------------------------------------------
# Matching
# ----------------------------------------------------------------------

def match_volcan(nombre_norm: str, lat: float, lon: float,
                 gvp: pd.DataFrame) -> tuple[pd.Series | None, str]:
    """Devuelve (fila_gvp, metodo). metodo in {'nombre', 'sinonimo', 'geo', 'sin match'}."""
    # 1) match exacto por nombre normalizado
    hit = gvp[gvp["nombre_norm"] == nombre_norm]
    if len(hit) == 1:
        return hit.iloc[0], "nombre"
    if len(hit) > 1:
        # desempatar por proximidad
        d2 = (hit["Latitude"] - lat) ** 2 + (hit["Longitude"] - lon) ** 2
        return hit.iloc[d2.values.argmin()], "nombre+geo"

    # 2) sinonimo manual
    if nombre_norm in SINONIMOS:
        target = SINONIMOS[nombre_norm]
        hit = gvp[gvp["nombre_norm"] == target]
        if len(hit) >= 1:
            if len(hit) > 1:
                d2 = (hit["Latitude"] - lat) ** 2 + (hit["Longitude"] - lon) ** 2
                return hit.iloc[d2.values.argmin()], "sinonimo+geo"
            return hit.iloc[0], "sinonimo"

    # 3) substring (nombre proyecto contenido en nombre gvp o viceversa)
    sub = gvp[
        gvp["nombre_norm"].str.contains(nombre_norm, regex=False, na=False)
        | gvp["nombre_norm"].apply(lambda x: x in nombre_norm if x else False)
    ]
    # filtrar por proximidad para evitar falsos positivos
    if not sub.empty:
        d2 = (sub["Latitude"] - lat) ** 2 + (sub["Longitude"] - lon) ** 2
        sub = sub.assign(_d2=d2.values)
        sub = sub.sort_values("_d2")
        cand = sub.iloc[0]
        if cand["_d2"] <= TOL_DEG ** 2 * 4:  # un poco mas laxo si el nombre matchea
            return cand.drop("_d2"), "substring+geo"

    # 4) proximidad geografica pura
    d2 = (gvp["Latitude"] - lat) ** 2 + (gvp["Longitude"] - lon) ** 2
    idx = d2.values.argmin()
    if d2.iloc[idx] <= TOL_DEG ** 2:
        return gvp.iloc[idx], "geo"

    return None, "sin match"


# ----------------------------------------------------------------------
# Reduccion de erupciones a campos resumen
# ----------------------------------------------------------------------

def resumir_erupciones(df_erup: pd.DataFrame, last_eruption_year_gvp) -> dict:
    if df_erup.empty:
        return {
            "vei_maximo":                 None,
            "num_erupciones_holoceno":    0,
            "num_erupciones_siglo_xx_xxi": 0,
            "ultima_erupcion_anio":       last_eruption_year_gvp,
            "ultima_erupcion_vei":        None,
            "ultima_erupcion_duracion_dias": None,
        }
    vei_max = df_erup["ExplosivityIndexMax"].max(skipna=True)
    n_holo  = len(df_erup)
    n_xx    = int((df_erup["StartDateYear"] >= 1900).sum())

    # ultima erupcion = max StartDateYear
    if df_erup["StartDateYear"].notna().any():
        idx_last = df_erup["StartDateYear"].idxmax()
        ult = df_erup.loc[idx_last]
        anio_last = int(ult["StartDateYear"])
        vei_last  = ult["ExplosivityIndexMax"]
        if pd.notna(ult["EndDateYear"]) and pd.notna(ult["StartDateYear"]):
            duracion_dias = int((ult["EndDateYear"] - ult["StartDateYear"]) * 365)
        else:
            duracion_dias = None
    else:
        anio_last     = last_eruption_year_gvp
        vei_last      = None
        duracion_dias = None

    return {
        "vei_maximo":                    None if pd.isna(vei_max) else int(vei_max),
        "num_erupciones_holoceno":       n_holo,
        "num_erupciones_siglo_xx_xxi":   n_xx,
        "ultima_erupcion_anio":          anio_last,
        "ultima_erupcion_vei":           None if pd.isna(vei_last) else int(vei_last),
        "ultima_erupcion_duracion_dias": duracion_dias,
    }


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[1/4] Cargando volcanes del proyecto desde {VOLCANOES_YML.name}...")
    df_proj = cargar_volcanes_proyecto()
    print(f"      {len(df_proj)} volcanes proyecto.")

    print(f"[2/4] Descargando catalogo GVP (Country LIKE '%Chile%')...")
    df_gvp = descargar_volcanes_chile()
    print(f"      {len(df_gvp)} volcanes GVP en Chile / Chile-Argentina / Chile-Bolivia.")

    print(f"[3/4] Match + descarga erupciones por volcan (esto toma ~1-2 min)...")
    out_rows = []
    sin_match = []
    for i, vol in df_proj.iterrows():
        m, metodo = match_volcan(vol["nombre_norm"], vol["lat"], vol["lon"], df_gvp)
        if m is None:
            sin_match.append(vol["nombre"])
            out_rows.append({
                "codigo":                vol["codigo"],
                "nombre_proyecto":       vol["nombre"],
                "gvp_id":                None,
                "nombre_oficial_gvp":    None,
                "tipo_morfologico":      None,
                "elevacion_gvp":         None,
                "composicion":           None,
                "region_smithsonian":    None,
                "subregion_smithsonian": None,
                "ultima_erupcion_anio":  None,
                "ultima_erupcion_vei":   None,
                "ultima_erupcion_duracion_dias": None,
                "vei_maximo":            None,
                "num_erupciones_holoceno":      None,
                "num_erupciones_siglo_xx_xxi":  None,
                "epoca_gvp":             None,
                "url_pagina_si_edu":     None,
                "metodo_match":          "sin match",
            })
            continue

        vn = int(m["Volcano_Number"])
        epoca = m.get("_epoca", "Holocene")
        # Erupciones: solo el feed Holocene tiene historia eruptiva publicada.
        # Para volcanes Pleistoceno GVP no publica erupciones (no las hay
        # registradas en Holoceno por definicion).
        if epoca == "Holocene":
            try:
                df_erup = descargar_erupciones(vn)
            except Exception as e:
                print(f"      [warn] erupciones {vol['nombre']} (vn={vn}): {e}")
                df_erup = pd.DataFrame()
        else:
            df_erup = pd.DataFrame()
        resumen = resumir_erupciones(df_erup, m.get("Last_Eruption_Year"))

        out_rows.append({
            "codigo":                vol["codigo"],
            "nombre_proyecto":       vol["nombre"],
            "gvp_id":                vn,
            "nombre_oficial_gvp":    m["Volcano_Name"],
            "tipo_morfologico":      m["Primary_Volcano_Type"],
            "elevacion_gvp":         m["Elevation"],
            "composicion":           m["Major_Rock_Type"],
            "region_smithsonian":    m["Region"],
            "subregion_smithsonian": m["Subregion"],
            "ultima_erupcion_anio":  resumen["ultima_erupcion_anio"],
            "ultima_erupcion_vei":   resumen["ultima_erupcion_vei"],
            "ultima_erupcion_duracion_dias": resumen["ultima_erupcion_duracion_dias"],
            "vei_maximo":            resumen["vei_maximo"],
            "num_erupciones_holoceno":     resumen["num_erupciones_holoceno"],
            "num_erupciones_siglo_xx_xxi": resumen["num_erupciones_siglo_xx_xxi"],
            "epoca_gvp":             epoca,
            "url_pagina_si_edu":     VOLCANO_PAGE.format(vn=vn),
            "metodo_match":          metodo,
        })
        print(f"      [{i+1:>2}/{len(df_proj)}] {vol['nombre']:<28} -> {m['Volcano_Name']:<28} vn={vn} [{epoca[:4]}] ({metodo})")
        time.sleep(PAUSE_BETWEEN_ERUP)

    print(f"[4/4] Escribiendo {OUT_CSV}...")
    df_out = pd.DataFrame(out_rows)
    df_out.to_csv(OUT_CSV, index=False, encoding="utf-8")
    print(f"      {len(df_out)} filas escritas.")
    print(f"      Con gvp_id: {df_out['gvp_id'].notna().sum()} / {len(df_out)}")
    if sin_match:
        print(f"      [!] Sin match ({len(sin_match)}): {', '.join(sin_match)}")

    # Cross-checks de QA
    print("\n--- QA: cross-checks ---")
    for nombre_test in ["Villarrica", "Lascar", "Chaiten"]:
        sub = df_out[df_out["nombre_proyecto"].str.lower().str.contains(nombre_test.lower())]
        if not sub.empty:
            row = sub.iloc[0]
            print(f"  {nombre_test}: vn={row['gvp_id']} tipo={row['tipo_morfologico']} "
                  f"comp={row['composicion']} VEI_max={row['vei_maximo']} "
                  f"n_holoceno={row['num_erupciones_holoceno']}")


if __name__ == "__main__":
    main()
