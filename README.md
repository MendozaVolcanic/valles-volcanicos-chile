# Valles Volcánicos Chile

Dashboard de cuencas hidrográficas y población para los 43 volcanes monitoreados por OVDAS-SERNAGEOMIN.

## Objetivo

Identificar quebradas, valles y ríos que nacen de cada volcán activo de Chile, con estimación de población en riesgo, para apoyar la elaboración de informes de impacto volcánico.

## Stack

- **Python 3.11+** + GeoPandas + pysheds
- **Streamlit** + Folium (dashboard)
- **GeoPackage** (almacenamiento local, offline-ready)

## Fuentes de datos

| Dato | Fuente | Descarga |
|---|---|---|
| Volcanes | SERNAGEOMIN | `config/volcanoes.yaml` |
| Hidrografía | OpenStreetMap (Overpass API) | Automática |
| DEM | SRTM 30m (OpenTopography) | Automática |
| Cuencas | Calculadas con pysheds | Script 03 |
| Población | INE Censo 2024 | Automática |

## Instalación

```bash
pip install -r requirements.txt
```

## Uso

### 1. Procesar datos (primera vez)

```bash
python scripts/run_pipeline.py
```

O paso a paso:
```bash
python scripts/01_download_hydro.py   # Hidrografía OSM
python scripts/02_download_dem.py     # DEM SRTM
python scripts/03_watershed.py        # Delineación de cuencas
python scripts/04_census.py           # Población censal
```

### 2. Lanzar dashboard

```bash
streamlit run app/dashboard.py
```

## Estructura

```
valles-volcanicos-chile/
├── config/
│   └── volcanoes.yaml       # 43 volcanes OVDAS (fuente compartida)
├── data/
│   ├── raw/                 # datos descargados (.gitignored)
│   └── processed/           # GeoPackages procesados (.gitignored)
├── scripts/
│   ├── 01_download_hydro.py
│   ├── 02_download_dem.py
│   ├── 03_watershed.py
│   ├── 04_census.py
│   └── run_pipeline.py
├── app/
│   └── dashboard.py
└── .streamlit/
    └── config.toml          # tema oscuro para sala de monitoreo
```

## Arquitectura futura

`config/volcanoes.yaml` y los GeoPackages en `data/processed/` están diseñados para ser consumidos por el dashboard unificado OVDAS (VRP + OpenVIS + Valles).

## Contacto

OVDAS — SERNAGEOMIN
