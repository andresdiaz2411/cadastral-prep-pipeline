# 🏗️ Cadastral Data Preparation Pipeline

> **Python pipeline that automates the full cadastral data preparation workflow — from raw field shapefiles to a delivery-ready GeoPackage — replacing manual ArcGIS/QGIS processing steps.**

[![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)](https://python.org)
[![GeoPandas](https://img.shields.io/badge/GeoPandas-1.0.0-green)](https://geopandas.org)
[![Standard](https://img.shields.io/badge/Standard-LADM--COL%20%7C%20CTM12-orange)](https://www.igac.gov.co)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📌 Overview

In multipurpose cadastral projects, GIS analysts receive raw shapefiles from field operators with inconsistent coordinate systems, geometry errors, and fragmented file structures. Preparing these files for delivery to IGAC requires several manual steps in ArcGIS or QGIS.

This pipeline automates the entire preparation workflow in a single command:

```
python pipeline.py --input my_raw_data/
```

---

## 🔄 Pipeline Steps

```
RAW SHP FILES  (any CRS, geometry errors, multiple files)
      │
      ▼  STEP 1 — CRS Standardization
      │  Detect source CRS → reproject all layers to EPSG:3116
      │  (MAGNA-SIRGAS / Colombia Bogotá)
      │
      ▼  STEP 2 — Topology Validation
      │  Flag invalid geometries, slivers, duplicates
      │  Export topology_errors.csv
      │
      ▼  STEP 3 — GeoPackage Conversion
      │  Consolidate all SHP layers into cadastral_package.gpkg
      │  Verify feature counts post-conversion
      │
      ▼  STEP 4 — Delivery Report
         Generate delivery_report.csv + delivery_checklist.txt
         Pass/fail verdict per checklist item
```

Each step receives the output of the previous one — no manual handoffs.

---

## ⚡ Quick Start

```bash
git clone https://github.com/andresdiaz2411/cadastral-prep-pipeline.git
cd cadastral-prep-pipeline
pip install -r requirements.txt

# Generate synthetic sample data and run the full pipeline
python pipeline.py --generate-samples
```

### Sample pipeline output

```
  ──────────────────────────────────────────────────────────
  STEP 1  CRS STANDARDIZATION → EPSG:3116
  ──────────────────────────────────────────────────────────

  · Target CRS : EPSG:3116 (MAGNA-SIRGAS / Colombia Bogotá)
  · Files found: 3

    Layer                     Source CRS           Action
    ────────────────────────────────────────────────────────────
    parcelas                  EPSG:4326            → EPSG:3116 ✓
    manzanas                  EPSG:3116            ✓ Already EPSG:3116
    construcciones            EPSG:3116            ✓ Already EPSG:3116

  · Reprojected : 1 file(s)
  · Already OK  : 2 file(s)
  ✓ Step 1 complete (0.8s)

  ──────────────────────────────────────────────────────────
  STEP 2  TOPOLOGY & GEOMETRY VALIDATION
  ──────────────────────────────────────────────────────────

    Layer                     Features    Critical    Moderate  Status
    ──────────────────────────────────────────────────────────────────
    parcelas                       146           1           1  ✗ 1 critical
    manzanas                        26           0           1  ⚠ 1 moderate
    construcciones                  81           1           0  ✗ 1 critical

  · Total errors : 4 (critical: 2, moderate: 2)
  ✓ Step 2 complete (1.2s)

  ──────────────────────────────────────────────────────────
  STEP 3  SHAPEFILE → GEOPACKAGE CONVERSION
  ──────────────────────────────────────────────────────────

    Layer                     Features          CRS  Status
    ─────────────────────────────────────────────────────────
    parcelas                       146    EPSG:3116  ✓ OK
    manzanas                        26    EPSG:3116  ✓ OK
    construcciones                  81    EPSG:3116  ✓ OK

  · GeoPackage layers: ['parcelas', 'manzanas', 'construcciones']
  ✓ Step 3 complete (0.5s)

  ──────────────────────────────────────────────────────────
  STEP 4  DELIVERY REPORT
  ──────────────────────────────────────────────────────────

  · DELIVERY CHECKLIST
    ────────────────────────────────────────
    ✓  CRS standardized to EPSG:3116
    ✗  No critical topology errors
    ✓  All layers converted to GeoPackage
    ✓  Delivery package generated

  RESULT: REVIEW REQUIRED BEFORE DELIVERY

══════════════════════════════════════════════════════════
  PIPELINE COMPLETE

  Output folder    : outputs/
  GeoPackage       : cadastral_package.gpkg
  Delivery report  : delivery_report.csv
  Topology errors  : topology_errors.csv
  Checklist        : delivery_checklist.txt

  ⚠ REVIEW REQUIRED
```

---

## 📁 Repository Structure

```
cadastral-prep-pipeline/
│
├── pipeline.py             # Main orchestrator — runs all 4 steps in sequence
│
├── steps/
│   ├── step1_crs.py        # CRS detection and reprojection
│   ├── step2_topology.py   # Geometry validation and error logging
│   ├── step3_convert.py    # SHP → GeoPackage consolidation
│   └── step4_report.py     # Delivery report and checklist
│
├── sample_data/
│   └── generate_samples.py # Synthetic cadastral dataset generator
│
├── outputs/                # Pipeline outputs (git-ignored, except .gitkeep)
│   ├── cadastral_package.gpkg
│   ├── topology_errors.csv
│   ├── delivery_report.csv
│   └── delivery_checklist.txt
│
└── working/                # Intermediate files per step (git-ignored)
```

---

## 🔍 Topology Checks

| Check | Severity | Description |
|---|---|---|
| Invalid geometry | Critical | Self-intersections, malformed rings |
| Empty geometry | Critical | Null or zero-area features |
| Sliver polygon | Moderate | Area < 1.0 m² threshold |
| Duplicate geometry | Moderate | Exact geometry duplicate |

---

## 🔧 Tech Stack

| Category | Tools |
|---|---|
| Spatial processing | GeoPandas, Shapely, Fiona |
| CRS handling | PyProj |
| Cadastral standard | LADM-COL / CTM12 (IGAC) |
| Target CRS | EPSG:3116 — MAGNA-SIRGAS / Colombia Bogotá |
| Output format | GeoPackage (.gpkg) |
| Interface | Python CLI with `argparse` |

---

## 👤 Author

**German Andrés Diaz Gelves**
GIS & Spatial Data Analyst | Cadastral QA/QC | LADM-COL

5+ years processing cadastral datasets for IGAC and multipurpose cadastre projects across Colombia.

[![LinkedIn](https://img.shields.io/badge/LinkedIn-Connect-blue?logo=linkedin)](https://linkedin.com/in/adiaz96/)
[![Email](https://img.shields.io/badge/Email-Contact-red?logo=gmail)](mailto:andresdgel96@gmail.com)
