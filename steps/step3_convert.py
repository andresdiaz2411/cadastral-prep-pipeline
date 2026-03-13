"""
step3_convert.py
----------------
STEP 3 — Shapefile → GeoPackage Conversion

Consolidates all validated SHP files into a single GeoPackage.
Each SHP becomes a layer in the output GPKG.

Why GeoPackage over Shapefile:
- Single file (no .dbf/.prj/.shx sidecar files)
- No 10-character field name limit
- OGC standard, supported by QGIS, ArcGIS, PostGIS
- Supports multiple layers in one file

Input  : validated SHP files from step2
Output : cadastral_package.gpkg in working/03_convert/
"""

from pathlib import Path

import geopandas as gpd
import fiona


def run(input_dir: str, output_dir: str, logger) -> dict:
    input_path  = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Collect SHP files (exclude topology error CSV)
    shp_files = sorted(input_path.glob("*.shp"))

    if not shp_files:
        logger.error(f"No .shp files found in '{input_dir}'")
        return {"status": "error", "gpkg_path": None, "layers": [], "details": []}

    gpkg_path = output_path / "cadastral_package.gpkg"
    layers    = []
    details   = []

    logger.info(f"  Output file: {gpkg_path.name}")
    logger.info(f"  Layers to pack: {len(shp_files)}\n")
    logger.info(f"  {'Layer':<25} {'Features':>10}  {'CRS':>15}  {'Status'}")
    logger.info("  " + "─" * 65)

    for shp in shp_files:
        try:
            gdf        = gpd.read_file(str(shp))
            layer_name = shp.stem
            crs_str    = f"EPSG:{gdf.crs.to_epsg()}" if gdf.crs and gdf.crs.to_epsg() else "Unknown"

            # Write layer to GeoPackage
            gdf.to_file(str(gpkg_path), driver="GPKG", layer=layer_name)

            # Verify written layer
            gdf_verify = gpd.read_file(str(gpkg_path), layer=layer_name)
            ok         = len(gdf_verify) == len(gdf)

            status_str = "✓ OK" if ok else f"⚠ Count mismatch ({len(gdf_verify)} vs {len(gdf)})"
            logger.info(f"  {layer_name:<25} {len(gdf):>10}  {crs_str:>15}  {status_str}")
            details.append(f"{layer_name}: {len(gdf)} features → GPKG")
            layers.append(layer_name)

        except Exception as e:
            logger.error(f"  {shp.stem}: {e}")
            details.append(f"{shp.stem}: ERROR — {e}")

    # Verify final GPKG
    try:
        written_layers = fiona.listlayers(str(gpkg_path))
        logger.info(f"\n  GeoPackage layers: {written_layers}")
        logger.info(f"  File size        : {gpkg_path.stat().st_size / 1024:.1f} KB")
    except Exception:
        pass

    status = "ok" if len(layers) == len(shp_files) else "warning"

    return {
        "status":    status,
        "gpkg_path": str(gpkg_path),
        "layers":    layers,
        "details":   details,
    }
