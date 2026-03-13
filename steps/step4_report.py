"""
step4_report.py
---------------
STEP 4 — Delivery Report Generation

Consolidates results from all pipeline steps into a
delivery-ready report (CSV + printed summary).

Report includes:
- Pipeline execution summary
- Per-layer feature counts and CRS
- Topology error inventory
- Delivery checklist (pass/fail per item)

Input  : results dict from pipeline.py
Output : outputs/delivery_report.csv
         outputs/delivery_checklist.txt
"""

import csv
from pathlib import Path
from datetime import datetime

import geopandas as gpd


CHECKLIST_ITEMS = [
    ("CRS standardized to EPSG:3116",       "crs_ok"),
    ("No critical topology errors",          "no_critical"),
    ("All layers converted to GeoPackage",   "gpkg_ok"),
    ("Delivery package generated",           "package_ok"),
]


def run(
    results: dict,
    output_dir: str,
    gpkg_path: str,
    logger,
) -> dict:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    crs_result = results.get("step1", {})
    topo_result= results.get("step2", {})
    conv_result= results.get("step3", {})

    # -----------------------------------------------------------
    # Build checklist
    # -----------------------------------------------------------
    checklist = {
        "crs_ok":     crs_result.get("status") in ("ok", "warning"),
        "no_critical":topo_result.get("critical", 1) == 0,
        "gpkg_ok":    conv_result.get("status") == "ok",
        "package_ok": bool(gpkg_path and Path(gpkg_path).exists()),
    }

    all_pass = all(checklist.values())

    # -----------------------------------------------------------
    # Layer summary from GeoPackage
    # -----------------------------------------------------------
    layer_summary = []
    if gpkg_path and Path(gpkg_path).exists():
        try:
            import fiona
            for layer_name in fiona.listlayers(gpkg_path):
                gdf = gpd.read_file(gpkg_path, layer=layer_name)
                topo_errors = [
                    e for e in topo_result.get("all_errors", [])
                    if e["layer"] == layer_name
                ]
                layer_summary.append({
                    "layer":       layer_name,
                    "features":    len(gdf),
                    "crs":         f"EPSG:{gdf.crs.to_epsg()}" if gdf.crs else "Unknown",
                    "geom_type":   gdf.geom_type.mode()[0] if not gdf.empty else "Unknown",
                    "topo_errors": len(topo_errors),
                    "critical":    sum(1 for e in topo_errors if e["severity"] == "critical"),
                    "moderate":    sum(1 for e in topo_errors if e["severity"] == "moderate"),
                })
        except Exception as e:
            logger.error(f"Could not read GeoPackage for report: {e}")

    # -----------------------------------------------------------
    # Print delivery report
    # -----------------------------------------------------------
    logger.info(f"  Timestamp  : {timestamp}")
    logger.info(f"  Package    : {Path(gpkg_path).name if gpkg_path else '—'}\n")

    logger.info(f"  {'Layer':<25} {'Features':>10}  {'CRS':>12}  {'Errors':>8}")
    logger.info("  " + "─" * 62)
    for row in layer_summary:
        err_str = f"C:{row['critical']} M:{row['moderate']}" if row["topo_errors"] else "✓ Clean"
        logger.info(f"  {row['layer']:<25} {row['features']:>10}  {row['crs']:>12}  {err_str:>8}")

    logger.info(f"\n  {'─' * 40}")
    logger.info(f"  DELIVERY CHECKLIST")
    logger.info(f"  {'─' * 40}")
    for label, key in CHECKLIST_ITEMS:
        icon = "✓" if checklist[key] else "✗"
        logger.info(f"  {icon}  {label}")

    overall = "APPROVED FOR DELIVERY" if all_pass else "REVIEW REQUIRED BEFORE DELIVERY"
    logger.info(f"\n  {'─' * 40}")
    logger.info(f"  RESULT: {overall}")
    logger.info(f"  {'─' * 40}")

    # -----------------------------------------------------------
    # Write CSV report
    # -----------------------------------------------------------
    csv_path = output_path / "delivery_report.csv"
    with open(str(csv_path), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "layer", "features", "crs", "geom_type",
            "topo_errors", "critical", "moderate"
        ])
        writer.writeheader()
        writer.writerows(layer_summary)

    # -----------------------------------------------------------
    # Write checklist TXT
    # -----------------------------------------------------------
    txt_path = output_path / "delivery_checklist.txt"
    with open(str(txt_path), "w", encoding="utf-8") as f:
        f.write(f"CADASTRAL PIPELINE — DELIVERY CHECKLIST\n")
        f.write(f"Generated: {timestamp}\n")
        f.write(f"Package  : {Path(gpkg_path).name if gpkg_path else '—'}\n\n")
        for label, key in CHECKLIST_ITEMS:
            icon = "PASS" if checklist[key] else "FAIL"
            f.write(f"[{icon}] {label}\n")
        f.write(f"\nOVERALL: {overall}\n")

    logger.info(f"\n  Delivery report → {csv_path.name}")
    logger.info(f"  Checklist      → {txt_path.name}")

    return {
        "status":        "ok" if all_pass else "warning",
        "all_pass":      all_pass,
        "checklist":     checklist,
        "layer_summary": layer_summary,
        "csv_path":      str(csv_path),
        "txt_path":      str(txt_path),
    }
