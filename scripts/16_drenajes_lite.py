"""
16_drenajes_lite.py
-------------------
Genera shards livianos de drenajes para la vista por encuadre del dashboard.

POR QUE
El dashboard, cuando el usuario hace zoom sin seleccionar un volcan, carga los
cauces de TODOS los volcanes que caen en pantalla (hasta 4). Con los shards
completos eso serian ~15 MB de GeoJSON y decenas de miles de polilineas Leaflet
por render: inusable. Pero a esa escala los tramos sin nombre son ruido visual
puro — lo que el operador necesita ver es COMO SE LLAMA cada valle.

QUE HACE
  1. Descarta los tramos sin nombre (36.704 de 46.469 = 79% del volumen).
  2. Disuelve por nombre: los N tramos OSM de un mismo cauce pasan a ser una
     sola MultiLineString. Baja de 9.765 a ~4.700 features, que es lo que
     realmente pesa en el render de Leaflet.
  3. Simplifica a ~11 m (subpixel a zoom <= 14, invisible para el usuario).

El atributo drena_volcan se agrega con OR: el cauce se marca como drenante si
al menos uno de sus tramos recibe flujo del edificio. Es lo correcto para un
lahar, que baja por el cauce completo.

Salida: data/processed/drenajes_lite/{codigo}.geojson
"""
from pathlib import Path
import geopandas as gpd
import pandas as pd

ROOT     = Path(__file__).resolve().parent.parent
ORIGEN   = ROOT / "data" / "processed" / "drenajes"
DESTINO  = ROOT / "data" / "processed" / "drenajes_lite"

SIMPLIFY_DEG = 0.0001   # ~11 m
PRECISION    = 5        # ~1.1 m


def main() -> None:
    if not ORIGEN.exists():
        print(f"[!] Falta {ORIGEN} — correr scripts/export_geojson.py primero.")
        return

    DESTINO.mkdir(parents=True, exist_ok=True)
    shards = sorted(ORIGEN.glob("*.geojson"))
    if not shards:
        print(f"[!] No hay shards en {ORIGEN}")
        return

    print(f"Generando shards lite desde {len(shards)} shards completos...\n")
    bytes_origen = bytes_destino = 0
    feats_origen = feats_destino = 0

    for p in shards:
        codigo = p.stem
        bytes_origen += p.stat().st_size
        g = gpd.read_file(str(p), engine="pyogrio")
        feats_origen += len(g)

        con_nombre = g[g["nombre"].fillna("Sin nombre") != "Sin nombre"].copy()
        salida = DESTINO / f"{codigo}.geojson"

        if con_nombre.empty:
            # Igual escribimos el archivo: su ausencia dispararia el fallback
            # del loader, que cargaria el shard completo (justo lo que evitamos)
            gpd.GeoDataFrame(
                {"nombre": [], "tipo": [], "volcan_codigo": [], "volcan_nombre": [],
                 "drena_volcan": [], "geometry": []},
                crs="EPSG:4326",
            ).to_file(str(salida), driver="GeoJSON")
            print(f"  {codigo}: sin cauces nombrados")
            continue

        if "drena_volcan" not in con_nombre.columns:
            con_nombre["drena_volcan"] = False
        con_nombre["drena_volcan"] = con_nombre["drena_volcan"].fillna(False).astype(bool)

        # Un cauce = un feature. agg toma el primer tipo/volcan y OR del drenaje.
        disuelto = con_nombre.dissolve(
            by="nombre",
            aggfunc={"tipo": "first", "volcan_codigo": "first",
                     "volcan_nombre": "first", "drena_volcan": "max"},
        ).reset_index()
        disuelto["geometry"] = disuelto.geometry.simplify(
            SIMPLIFY_DEG, preserve_topology=True)

        disuelto.to_file(str(salida), driver="GeoJSON",
                         COORDINATE_PRECISION=PRECISION)
        bytes_destino += salida.stat().st_size
        feats_destino += len(disuelto)
        print(f"  {codigo}: {len(con_nombre):5d} tramos → {len(disuelto):4d} cauces "
              f"({salida.stat().st_size/1024:6.0f} KB)")

    print(f"\n[OK] {DESTINO.relative_to(ROOT)}")
    print(f"  features: {feats_origen:,} → {feats_destino:,} "
          f"({100 * feats_destino / max(feats_origen, 1):.1f}%)")
    print(f"  tamaño:   {bytes_origen/1024/1024:.1f} MB → {bytes_destino/1024/1024:.1f} MB "
          f"({100 * bytes_destino / max(bytes_origen, 1):.1f}%)")


if __name__ == "__main__":
    main()
