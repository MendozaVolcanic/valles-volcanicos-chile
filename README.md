# Valles Volcanicos Chile

Dashboard de quebradas, rios y valles para los 44 volcanes monitoreados por OVDAS-SERNAGEOMIN.

**Dashboard publico:** https://valles-volcanicos-chile.streamlit.app  
**Repositorio:** https://github.com/MendozaVolcanic/valles-volcanicos-chile  
**Local:** `streamlit run app/dashboard.py --server.port 8505`

---

## Objetivo

Identificar todas las quebradas, valles y rios que nacen o pasan por el area de influencia de cada volcan activo de Chile, con estimacion de poblacion en riesgo, para apoyar la elaboracion de informes de impacto volcanico en OVDAS.

## Estado del pipeline

| Script | Estado | Resultado |
|---|---|---|
| `01_download_hydro.py` | Completado | 28.870 tramos OSM, 44 volcanes |
| `02_download_dem.py` | Completado | 43 DEMs SRTM 30m (AWS S3) |
| `03_watershed.py` | Completado | 22.915 tramos en zonas de influencia |
| `04_census.py` | Pendiente descarga manual | Requiere manzanas INE 2024 |

## Stack

- **Python 3.11+** — GeoPandas, pysheds, rasterio, pyproj
- **Streamlit + Folium** — dashboard modo oscuro, fondo satelital ESRI
- **GeoPackage** — almacenamiento local offline-ready
- **GitHub** — control de versiones

## Fuentes de datos

| Dato | Fuente | Descarga |
|---|---|---|
| Volcanes | SERNAGEOMIN | `config/volcanoes.yaml` (manual) |
| Hidrografia | OpenStreetMap (Overpass API) | Automatica |
| DEM SRTM 30m | AWS S3 (elevation-tiles-prod) | Automatica |
| Zonas de influencia | Buffer 50 km + OSM | Script 03 |
| Poblacion | INE Censo 2024 | Descarga manual (ver abajo) |

## Instalacion

```bash
pip install -r requirements.txt
```

## Uso

### 1. Procesar datos (primera vez, ~40 min)

```bash
python scripts/run_pipeline.py
```

O paso a paso:
```bash
python scripts/01_download_hydro.py   # Hidrografia OSM (~25 min)
python scripts/02_download_dem.py     # DEM SRTM desde AWS (~12 min)
python scripts/03_watershed.py        # Zonas de influencia + quebradas (~1 min)
python scripts/04_census.py           # Poblacion censal
```

### 2. Lanzar dashboard

```bash
streamlit run app/dashboard.py
```

Abre en: **http://localhost:8505**

### Censo 2024 (descarga manual)

Los datos de manzanas del Censo 2024 requieren descarga manual:

1. Ir a https://www.ine.gob.cl/estadisticas-por-tema/demografia-y-poblacion/resultados-censo-2024
2. Descargar el shapefile de manzanas con poblacion
3. Guardar en `data/raw/manzanas_censales.gpkg`
4. Ejecutar `python scripts/04_census.py`

## Funcionalidades del dashboard

- **Vista general**: mapa de Chile con los 44 volcanes y sus zonas de influencia (50 km)
- **Vista por volcan**: zoom automatico, estadisticas UTM, quebradas nombradas con etiquetas
- **Capas tematicas**: zona de influencia, quebradas/rios, nombres, marcadores de volcanes
- **Capas de contexto**: limites comunales (WMS BCN Chile) + ciudades y pueblos (~45 localidades) + zonas de peligro volcanico (SERNAGEOMIN, Alto/Medio/Bajo)
- **Fondo**: satelital ESRI World Imagery + rotulos de referencia
- **Tabla**: lista de quebradas con nombre, tipo y tramos OSM
- **Exportar**: descarga CSV con quebradas del volcan seleccionado

## Estructura

```
valles-volcanicos-chile/
├── config/
│   └── volcanoes.yaml        # 43 volcanes OVDAS (fuente compartida)
├── data/
│   ├── raw/                  # datos descargados (.gitignored)
│   │   ├── hydro/            # hidrografia por volcan (.gpkg)
│   │   ├── dem/              # DEMs SRTM por volcan (.tif)
│   │   └── hgt_cache/        # tiles SRTM crudos (.hgt)
│   └── processed/            # GeoPackages procesados (.gitignored)
│       └── cuencas.gpkg      # layers: cuencas, drenajes
├── scripts/
│   ├── 01_download_hydro.py  # OSM via Overpass API
│   ├── 02_download_hydro.py  # SRTM desde AWS S3
│   ├── 03_watershed.py       # buffer + interseccion OSM
│   ├── 04_census.py          # poblacion censal
│   └── run_pipeline.py       # ejecuta todo en secuencia
├── app/
│   └── dashboard.py          # Streamlit + Folium
└── .streamlit/
    └── config.toml           # tema oscuro, puerto 8505
```

## Arquitectura futura

`config/volcanoes.yaml` y los GeoPackages en `data/processed/` estan disenados
para ser consumidos por el dashboard unificado OVDAS (VRP termico + OpenVIS infrasonido + Valles).

## Contacto

OVDAS - SERNAGEOMIN
