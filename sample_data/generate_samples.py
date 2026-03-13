"""
generate_samples.py
-------------------
Generates synthetic cadastral shapefiles simulating raw field delivery.

Simulates what a GIS analyst receives from field operators:
- Multiple SHP files in different CRS
- Geometry issues (invalid, slivers, duplicates)
- Inconsistent field naming

Output (all in sample_data/raw/):
    parcelas.shp       — urban parcels, some in wrong CRS (EPSG:4326 instead of 3116)
    manzanas.shp       — urban blocks, EPSG:3116, has duplicate
    construcciones.shp — buildings, EPSG:3116, has invalid geometry
"""

from pathlib import Path
import numpy as np
import geopandas as gpd
from shapely.geometry import Polygon, Point
from shapely.affinity import rotate

RNG    = np.random.default_rng(42)
BASE_X = 1_000_000.0
BASE_Y = 1_000_000.0


# -------------------------------------------------------------------
# Geometry helpers
# -------------------------------------------------------------------

def rect(x, y, w, h, angle=0):
    p = Polygon([(x, y), (x+w, y), (x+w, y+h), (x, y+h)])
    return rotate(p, angle, origin=(x, y)) if angle else p


def bow_tie(x, y, w, h):
    """Self-intersecting polygon — topology error."""
    return Polygon([(x, y), (x+w, y+h), (x+w, y), (x, y+h)])


def sliver(x, y, length=50):
    """Extremely thin polygon — sliver."""
    return Polygon([(x, y), (x+0.05, y), (x+0.05, y+length), (x, y+length)])


# -------------------------------------------------------------------
# Dataset builders
# -------------------------------------------------------------------

def build_parcelas():
    """
    150 parcels in EPSG:4326 (wrong CRS — field operator mistake).
    Includes 2 invalid geometries and 1 sliver.
    """
    geoms, codes, areas, usos = [], [], [], []

    # Convert BASE to approximate geographic coords
    # EPSG:3116 ~= lon -74.08, lat 4.68 for BASE_X/Y = 1_000_000
    base_lon, base_lat = -74.080, 4.680
    cell = 0.0009  # ~100m in degrees

    rows, cols = 12, 12
    for i in range(rows):
        for j in range(cols):
            lon = base_lon + j * cell
            lat = base_lat + i * cell
            w   = cell * 0.8
            h   = cell * 0.8
            geoms.append(Polygon([
                (lon, lat), (lon+w, lat),
                (lon+w, lat+h), (lon, lat+h)
            ]))
            codes.append(f"PAR{i*cols+j:04d}")
            areas.append(round(w * h * 1e10, 2))
            usos.append(RNG.choice(["Residencial", "Comercial", "Dotacional"]))

    # Invalid geometry (bow-tie in geographic coords)
    geoms.append(Polygon([
        (-74.060, 4.690), (-74.055, 4.695),
        (-74.055, 4.690), (-74.060, 4.695)
    ]))
    codes.append("PAR_ERR1"); areas.append(0); usos.append("Residencial")

    # Sliver
    geoms.append(Polygon([
        (-74.050, 4.680), (-74.049999, 4.680),
        (-74.049999, 4.690), (-74.050, 4.690)
    ]))
    codes.append("PAR_ERR2"); areas.append(0); usos.append("Residencial")

    return gpd.GeoDataFrame({
        "codigo": codes,
        "area_aprox": areas,
        "uso": usos,
    }, geometry=geoms, crs="EPSG:4326")   # ← wrong CRS intentionally


def build_manzanas():
    """
    25 urban blocks in EPSG:3116 (correct CRS).
    Includes 1 duplicate geometry.
    """
    geoms, ids, barrios = [], [], []
    spacing = 600

    for i in range(5):
        for j in range(5):
            x = BASE_X + i * spacing
            y = BASE_Y + j * spacing
            geoms.append(rect(x, y, 500, 500))
            ids.append(i * 5 + j)
            barrios.append(RNG.choice(["Centro", "Norte", "Sur", "Oriente", "Occidente"]))

    # Duplicate of block 0
    geoms.append(geoms[0])
    ids.append(999)
    barrios.append("Centro")

    return gpd.GeoDataFrame({
        "manzana_id": ids,
        "barrio": barrios,
        "area_m2": [round(g.area, 2) for g in geoms],
    }, geometry=geoms, crs="EPSG:3116")


def build_construcciones():
    """
    80 buildings in EPSG:3116.
    Includes 1 self-intersecting geometry.
    """
    geoms, codes, plantas, tipos = [], [], [], []
    spacing = 120

    for i in range(8):
        for j in range(9):
            x = BASE_X + 50 + i * spacing
            y = BASE_Y + 50 + j * spacing
            w = RNG.uniform(40, 80)
            h = RNG.uniform(30, 60)
            geoms.append(rect(x, y, w, h))
            codes.append(f"CON{i*9+j:04d}")
            plantas.append(RNG.integers(1, 6))
            tipos.append(RNG.choice(["Casa", "Apartamento", "Local", "Bodega"]))

    # Self-intersecting building
    geoms.append(bow_tie(BASE_X + 1200, BASE_Y + 1200, 60, 60))
    codes.append("CON_ERR1")
    plantas.append(1)
    tipos.append("Casa")

    return gpd.GeoDataFrame({
        "codigo": codes,
        "num_plantas": plantas,
        "tipo": tipos,
        "area_m2": [round(g.area, 2) for g in geoms],
    }, geometry=geoms, crs="EPSG:3116")


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

def generate_all(output_dir: str = "sample_data/raw"):
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    print("  Generating raw cadastral shapefiles...\n")

    gdf_p = build_parcelas()
    gdf_p.to_file(f"{output_dir}/parcelas.shp")
    print(f"  ✓ parcelas.shp        — {len(gdf_p):>4} features | CRS: EPSG:4326 (wrong — demo)")

    gdf_m = build_manzanas()
    gdf_m.to_file(f"{output_dir}/manzanas.shp")
    print(f"  ✓ manzanas.shp        — {len(gdf_m):>4} features | CRS: EPSG:3116 | 1 duplicate")

    gdf_c = build_construcciones()
    gdf_c.to_file(f"{output_dir}/construcciones.shp")
    print(f"  ✓ construcciones.shp  — {len(gdf_c):>4} features | CRS: EPSG:3116 | 1 invalid geom")

    print(f"\n  Raw data ready in '{output_dir}/'")
    print("  Run the pipeline: python pipeline.py\n")


if __name__ == "__main__":
    generate_all()
