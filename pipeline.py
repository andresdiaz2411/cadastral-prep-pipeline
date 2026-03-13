"""
pipeline.py
-----------
Cadastral Data Preparation Pipeline
====================================
Automates the full cadastral data preparation workflow:

    RAW SHP FILES
        │
        ▼  STEP 1 — CRS Standardization
        │  Reproject all layers to EPSG:3116
        │
        ▼  STEP 2 — Topology Validation
        │  Detect invalid geometries, slivers, duplicates
        │
        ▼  STEP 3 — GeoPackage Conversion
        │  Consolidate all layers into a single .gpkg
        │
        ▼  STEP 4 — Delivery Report
           Generate CSV + checklist for project delivery

Usage:
    python pipeline.py                        # uses sample_data/raw/
    python pipeline.py --input my_data/       # custom input folder
    python pipeline.py --generate-samples     # generate sample data first
"""

import os
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime


# -------------------------------------------------------------------
# ANSI colors
# -------------------------------------------------------------------
class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    CYAN   = "\033[96m"
    YELLOW = "\033[93m"
    GREEN  = "\033[92m"
    RED    = "\033[91m"
    GRAY   = "\033[90m"


def clr(text, color):
    return f"{color}{text}{C.RESET}"


# -------------------------------------------------------------------
# Logger
# -------------------------------------------------------------------
class Logger:
    def info(self, msg):
        print(f"{clr('·', C.GRAY)} {msg}")

    def success(self, msg):
        print(f"{clr('✓', C.GREEN)} {msg}")

    def error(self, msg):
        print(f"{clr('✗', C.RED)} {msg}")

    def warn(self, msg):
        print(f"{clr('⚠', C.YELLOW)} {msg}")

    def step(self, n, title):
        print(f"\n{clr('─' * 58, C.GRAY)}")
        print(f"{clr(f'  STEP {n}', C.CYAN)}  {clr(title.upper(), C.YELLOW)}")
        print(f"{clr('─' * 58, C.GRAY)}\n")

    def section(self, title):
        print(f"\n{clr('  ' + title, C.GRAY)}")


BANNER = f"""
{C.CYAN}{C.BOLD}
  ╔═══════════════════════════════════════════════════╗
  ║   CADASTRAL DATA PREPARATION PIPELINE            ║
  ║   Python-based GIS Automation · EPSG:3116        ║
  ╚═══════════════════════════════════════════════════╝
{C.RESET}"""


# -------------------------------------------------------------------
# Pipeline runner
# -------------------------------------------------------------------

def run_pipeline(input_dir: str):
    logger  = Logger()
    results = {}

    os.system("cls" if os.name == "nt" else "clear")
    print(BANNER)

    print(f"  {clr('Input folder :', C.GRAY)} {input_dir}")
    print(f"  {clr('Started      :', C.GRAY)} {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Working dirs
    work_dir = Path("working")
    out_dir  = Path("outputs")
    (work_dir / "01_crs").mkdir(parents=True, exist_ok=True)
    (work_dir / "02_topology").mkdir(parents=True, exist_ok=True)
    (work_dir / "03_convert").mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(exist_ok=True)

    # -----------------------------------------------------------
    # STEP 1 — CRS Standardization
    # -----------------------------------------------------------
    from steps.step1_crs import run as step1

    logger.step(1, "CRS Standardization → EPSG:3116")
    t0 = time.time()
    r1 = step1(input_dir, str(work_dir / "01_crs"), logger)
    results["step1"] = r1
    elapsed = time.time() - t0

    if r1["status"] == "error":
        logger.error("Step 1 failed — aborting pipeline")
        return
    logger.success(f"Step 1 complete ({elapsed:.1f}s)")

    # -----------------------------------------------------------
    # STEP 2 — Topology Validation
    # -----------------------------------------------------------
    from steps.step2_topology import run as step2

    logger.step(2, "Topology & Geometry Validation")
    t0 = time.time()
    r2 = step2(str(work_dir / "01_crs"), str(work_dir / "02_topology"), logger)
    results["step2"] = r2
    elapsed = time.time() - t0

    if r2["critical"] > 0:
        logger.warn(f"{r2['critical']} critical geometry errors found — review topology_errors.csv")
        logger.warn("Pipeline continues — errors are logged, not auto-corrected")
    logger.success(f"Step 2 complete ({elapsed:.1f}s)")

    # -----------------------------------------------------------
    # STEP 3 — GeoPackage Conversion
    # -----------------------------------------------------------
    from steps.step3_convert import run as step3

    logger.step(3, "Shapefile → GeoPackage Conversion")
    t0 = time.time()
    r3 = step3(str(work_dir / "02_topology"), str(work_dir / "03_convert"), logger)
    results["step3"] = r3
    elapsed = time.time() - t0

    if r3["status"] == "error":
        logger.error("Step 3 failed — aborting pipeline")
        return
    logger.success(f"Step 3 complete ({elapsed:.1f}s)")

    # Copy final GPKG to outputs/
    gpkg_src = Path(r3["gpkg_path"])
    gpkg_dst = out_dir / gpkg_src.name
    import shutil
    shutil.copy2(str(gpkg_src), str(gpkg_dst))

    # Copy topology errors CSV to outputs/
    topo_csv = Path(work_dir / "02_topology" / "topology_errors.csv")
    if topo_csv.exists():
        shutil.copy2(str(topo_csv), str(out_dir / "topology_errors.csv"))

    # -----------------------------------------------------------
    # STEP 4 — Delivery Report
    # -----------------------------------------------------------
    from steps.step4_report import run as step4

    logger.step(4, "Delivery Report")
    t0 = time.time()
    r4 = step4(results, str(out_dir), str(gpkg_dst), logger)
    results["step4"] = r4
    elapsed = time.time() - t0
    logger.success(f"Step 4 complete ({elapsed:.1f}s)")

    # -----------------------------------------------------------
    # Final summary
    # -----------------------------------------------------------
    print(f"\n{clr('═' * 58, C.CYAN)}")
    print(f"{clr('  PIPELINE COMPLETE', C.BOLD)}")
    print(f"{clr('═' * 58, C.CYAN)}\n")

    print(f"  {clr('Output folder    :', C.GRAY)} outputs/")
    print(f"  {clr('GeoPackage       :', C.GRAY)} {gpkg_dst.name}")
    print(f"  {clr('Delivery report  :', C.GRAY)} delivery_report.csv")
    print(f"  {clr('Topology errors  :', C.GRAY)} topology_errors.csv")
    print(f"  {clr('Checklist        :', C.GRAY)} delivery_checklist.txt")

    overall = r4.get("all_pass", False)
    verdict = clr("✓ APPROVED FOR DELIVERY", C.GREEN) if overall else clr("⚠ REVIEW REQUIRED", C.YELLOW)
    print(f"\n  {verdict}\n")


# -------------------------------------------------------------------
# Entry point
# -------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Cadastral Data Preparation Pipeline"
    )
    parser.add_argument(
        "--input", default="sample_data/raw",
        help="Input folder containing raw .shp files (default: sample_data/raw)"
    )
    parser.add_argument(
        "--generate-samples", action="store_true",
        help="Generate synthetic sample data before running the pipeline"
    )
    args = parser.parse_args()

    if args.generate_samples:
        print("\n  Generating sample data...\n")
        from sample_data.generate_samples import generate_all
        generate_all()
        print()

    if not Path(args.input).exists():
        print(f"\n  Folder '{args.input}' not found.")
        print(f"  Run with --generate-samples to create test data.\n")
        sys.exit(1)

    run_pipeline(args.input)


if __name__ == "__main__":
    main()
