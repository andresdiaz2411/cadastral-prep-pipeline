"""
step1_crs.py
------------
STEP 1 — Coordinate System Standardization
Target CRS: EPSG:3116 (MAGNA-SIRGAS / Colombia Bogotá)

Accepts any format supported by input_reader:
    .shp | .gpkg | .gdb | .dxf | .dwg | .geojson

Input  : raw spatial files (any format, any CRS)
Output : reprojected SHP files in working/01_crs/
"""

from pathlib import Path
import geopandas as gpd

from steps.input_reader import scan_directory, print_scan_summary

TARGET_CRS   = "EPSG:3116"
TARGET_LABEL = "MAGNA-SIRGAS / Colombia Bogotá"


def run(input_dir: str, output_dir: str, logger) -> dict:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Scan all supported formats
    logger.info(f"Scanning '{input_dir}' for spatial files...\n")
    layer_results = scan_directory(input_dir)

    if not layer_results:
        logger.error(f"No supported spatial files found in '{input_dir}'")
        logger.info(f"Supported: .shp, .gpkg, .gdb, .dxf, .dwg, .geojson")
        return {"status": "error", "reprojected": 0, "already_ok": 0,
                "errors": 1, "files": [], "details": []}

    print_scan_summary(layer_results, logger)
    print()
    logger.info(f"Target CRS : {TARGET_CRS} ({TARGET_LABEL})\n")
    logger.info(f"  {'Layer':<28} {'Source CRS':<20}  {'Action'}")
    logger.info("  " + "─" * 65)

    reprojected = 0
    already_ok  = 0
    errors      = 0
    out_files   = []
    details     = []

    for result in layer_results:

        if not result.ok:
            logger.info(f"  {result.name:<28} {'—':<20}  ✗ {result.error}")
            details.append(f"{result.name}: READ ERROR — {result.error}")
            errors += 1
            continue

        gdf      = result.gdf
        src_epsg = f"EPSG:{gdf.crs.to_epsg()}" if gdf.crs and gdf.crs.to_epsg() else str(gdf.crs) if gdf.crs else "UNKNOWN"

        if not gdf.crs:
            logger.info(f"  {result.name:<28} {'NO CRS':<20}  ⚠ Skipped — assign CRS manually")
            details.append(f"{result.name}: no CRS — skipped")
            errors += 1
            continue

        out_file = output_path / f"{result.name}.shp"

        try:
            if gdf.crs.to_epsg() == 3116:
                gdf.to_file(str(out_file))
                logger.info(f"  {result.name:<28} {src_epsg:<20}  ✓ Already EPSG:3116")
                details.append(f"{result.name}: already EPSG:3116")
                already_ok += 1
            else:
                gdf_repr = gdf.to_crs(TARGET_CRS)
                gdf_repr.to_file(str(out_file))
                logger.info(f"  {result.name:<28} {src_epsg:<20}  → EPSG:3116 ✓")
                details.append(f"{result.name}: reprojected {src_epsg} → EPSG:3116")
                reprojected += 1

            out_files.append(str(out_file))

        except Exception as e:
            logger.error(f"  {result.name}: {e}")
            details.append(f"{result.name}: ERROR — {e}")
            errors += 1

    status = "error" if errors and not out_files else "warning" if errors else "ok"

    logger.info(f"\n  Reprojected : {reprojected} layer(s)")
    logger.info(f"  Already OK  : {already_ok} layer(s)")
    if errors:
        logger.info(f"  Skipped     : {errors} layer(s)")

    return {
        "status":      status,
        "reprojected": reprojected,
        "already_ok":  already_ok,
        "errors":      errors,
        "files":       out_files,
        "details":     details,
    }