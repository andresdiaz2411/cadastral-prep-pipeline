"""
step2_topology.py
-----------------
STEP 2 — Topology & Geometry Validation (CTM12 / LADM-COL)

Rules implemented:
    GEOMETRY (all polygon layers)
        G1 — Must Not Have Null Geometry            [critical]
        G2 — Must Not Have Empty Geometry           [critical]
        G3 — Must Not Self-Intersect                [critical]
        G4 — Must Not Have Zero-Area Polygons       [critical]
        G5 — Must Not Have Slivers (< 1.0 m²)      [moderate]

    TOPOLOGY (polygon layers)
        T1 — Must Not Overlap (intra-layer)         [critical]
             U_UNIDAD: only within same CONSTRUCCION_CODIGO + PLANTA
        T2 — Must Not Have Gaps (intra-layer)       [moderate]
        T3 — Must Be Covered By (hierarchical)      [critical/moderate/low]
             MANZANA → TERRENO → CONSTRUCCION → UNIDAD
             Reports % of area outside parent polygon

    ATTRIBUTE INTEGRITY
        A1 — CODIGO Must Be Unique                  [moderate]
             Exempt: U_CONSTRUCCION, U_UNIDAD (LADM-COL design)
"""

import csv
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union
from shapely.validation import explain_validity
from shapely.strtree import STRtree

# -------------------------------------------------------------------
# Constants
# -------------------------------------------------------------------

SLIVER_THRESHOLD_M2  = 1.0
OVERLAP_THRESHOLD_M2 = 0.01
GAP_THRESHOLD_M2     = 0.01   # T2 — minimum gap area to flag

# Severity thresholds for T3 Must Be Covered By (% outside parent)
T3_LOW      = 1.0    # <= 1%   → low
T3_MODERATE = 10.0   # <= 10%  → moderate
                     # >  10%  → critical

# Layer name patterns for auto-detection
LAYER_PATTERNS = {
    "manzana":      ("manzana", "manzanas", "block", "blocks"),
    "terreno":      ("terreno", "terrenos", "parcel", "parcelas", "predio", "predios"),
    "construccion": ("construccion", "construcciones", "building", "buildings", "constr"),
    "unidad":       ("unidad", "unidades", "unit", "units", "u_unidad"),
}

HIERARCHY = ["manzana", "terreno", "construccion", "unidad"]

CODIGO_DUPLICATE_EXEMPT = {
    "construcciones", "unidades",
    "u_construccion_ctm12", "u_unidad_ctm12",
}

UNIDAD_PATTERNS = ("u_unidad", "unidad", "unidades")


# -------------------------------------------------------------------
# Layer role detector
# -------------------------------------------------------------------

def detect_layer_roles(shp_files: list[Path]) -> dict[str, Path | None]:
    """
    Auto-detect which file corresponds to each cadastral role
    based on filename patterns.

    Returns dict: { "manzana": Path, "terreno": Path, ... }
    Undetected roles have value None.
    """
    roles = {role: None for role in HIERARCHY}

    for shp in shp_files:
        stem = shp.stem.lower()
        for role, patterns in LAYER_PATTERNS.items():
            if any(p in stem for p in patterns):
                roles[role] = shp
                break

    return roles


def prompt_missing_roles(
    roles: dict[str, Path | None],
    shp_files: list[Path],
) -> dict[str, Path | None]:
    """
    Ask user to assign any undetected roles interactively.
    Only called when running in pipeline (not imported as module).
    """
    undetected = [r for r, p in roles.items() if p is None]
    if not undetected:
        return roles

    file_list = [f.name for f in shp_files]
    options   = "\n".join(f"  [{i}] {name}" for i, name in enumerate(file_list))
    skip_opt  = f"  [{len(file_list)}] Skip (not in dataset)"

    print(f"\n\033[93m  ⚠ Could not auto-detect the following layer roles:\033[0m")

    for role in undetected:
        print(f"\n  Which file is \033[96m{role.upper()}\033[0m?")
        print(options)
        print(skip_opt)

        while True:
            try:
                choice = int(input("  ▸ Enter number: ").strip())
                if choice == len(file_list):
                    roles[role] = None
                    break
                elif 0 <= choice < len(file_list):
                    roles[role] = shp_files[choice]
                    break
                else:
                    print("  Invalid option.")
            except ValueError:
                print("  Enter a number.")

    return roles


# -------------------------------------------------------------------
# Rule G1–G5: Geometry checks
# -------------------------------------------------------------------

def _check_geometry(gdf: gpd.GeoDataFrame, layer: str) -> list[dict]:
    errors = []

    for idx, row in gdf.iterrows():
        geom = row.geometry

        if geom is None or pd.isna(geom):
            errors.append({"layer": layer, "fid": idx, "rule": "G1",
                "check": "null_geometry", "severity": "critical",
                "detail": "Null geometry — feature has no spatial representation"})
            continue

        if geom.is_empty:
            errors.append({"layer": layer, "fid": idx, "rule": "G2",
                "check": "empty_geometry", "severity": "critical",
                "detail": "Empty geometry — no coordinates present"})
            continue

        if not geom.is_valid:
            errors.append({"layer": layer, "fid": idx, "rule": "G3",
                "check": "invalid_geometry", "severity": "critical",
                "detail": explain_validity(geom)})

        if geom.geom_type in ("Polygon", "MultiPolygon"):
            if geom.area == 0:
                errors.append({"layer": layer, "fid": idx, "rule": "G4",
                    "check": "zero_area_polygon", "severity": "critical",
                    "detail": "Zero-area polygon — degenerate feature"})
            elif 0 < geom.area < SLIVER_THRESHOLD_M2:
                errors.append({"layer": layer, "fid": idx, "rule": "G5",
                    "check": "sliver_polygon", "severity": "moderate",
                    "detail": f"Area = {geom.area:.6f} m² — below CTM12 minimum ({SLIVER_THRESHOLD_M2} m²)"})

    return errors


# -------------------------------------------------------------------
# Rule T1: Must Not Overlap
# -------------------------------------------------------------------

def _overlaps_strtree(
    gdf: gpd.GeoDataFrame,
    layer: str,
    check_label: str = "overlap",
) -> list[dict]:
    errors  = []
    valid   = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty & gdf.geometry.is_valid].copy()
    if valid.empty or valid.geom_type.iloc[0] not in ("Polygon", "MultiPolygon"):
        return errors

    tree    = STRtree(valid.geometry.values)
    indices = valid.index.tolist()
    geoms   = valid.geometry.values
    seen    = set()

    for i, geom_a in enumerate(geoms):
        for j in tree.query(geom_a):
            if j <= i:
                continue
            pair = (indices[i], indices[j])
            if pair in seen:
                continue
            seen.add(pair)
            overlap = geom_a.intersection(geoms[j]).area
            if overlap > OVERLAP_THRESHOLD_M2:
                errors.append({
                    "layer": layer, "fid": indices[i],
                    "rule": "T1", "check": check_label,
                    "severity": "critical",
                    "detail": (
                        f"Overlaps with FID {indices[j]} — "
                        f"overlap area = {overlap:.4f} m²"
                    ),
                })
    return errors


def _check_overlaps_unidad(gdf: gpd.GeoDataFrame, layer: str) -> list[dict]:
    errors = []
    has_fields = "CONSTRUCCION_CODIGO" in gdf.columns and "PLANTA" in gdf.columns

    if not has_fields:
        errors.append({
            "layer": layer, "fid": -1, "rule": "T1",
            "check": "overlap_config_warning", "severity": "moderate",
            "detail": (
                "CONSTRUCCION_CODIGO and/or PLANTA fields not found — "
                "floor-aware overlap skipped, running generic check"
            ),
        })
        return errors + _overlaps_strtree(gdf, layer)

    null_planta = gdf["PLANTA"].isna() | (gdf["PLANTA"].astype(str).str.strip() == "")
    for idx in gdf[null_planta].index:
        errors.append({
            "layer": layer, "fid": idx, "rule": "T1",
            "check": "planta_null", "severity": "moderate",
            "detail": "PLANTA is null — floor-aware overlap cannot be evaluated",
        })

    valid = gdf[
        gdf.geometry.notna() & ~gdf.geometry.is_empty &
        gdf.geometry.is_valid & ~null_planta
    ].copy()

    for (cod, planta), group in valid.groupby(["CONSTRUCCION_CODIGO", "PLANTA"]):
        if len(group) < 2:
            continue
        tree    = STRtree(group.geometry.values)
        indices = group.index.tolist()
        geoms   = group.geometry.values
        seen    = set()

        for i, geom_a in enumerate(geoms):
            for j in tree.query(geom_a):
                if j <= i:
                    continue
                pair = (indices[i], indices[j])
                if pair in seen:
                    continue
                seen.add(pair)
                overlap = geom_a.intersection(geoms[j]).area
                if overlap > OVERLAP_THRESHOLD_M2:
                    errors.append({
                        "layer": layer, "fid": indices[i],
                        "rule": "T1", "check": "overlap_same_floor",
                        "severity": "critical",
                        "detail": (
                            f"Overlaps with FID {indices[j]} — "
                            f"CONSTRUCCION_CODIGO='{cod}' PLANTA='{planta}' — "
                            f"overlap area = {overlap:.4f} m²"
                        ),
                    })
    return errors


# -------------------------------------------------------------------
# Rule T2: Must Not Have Gaps
# -------------------------------------------------------------------

def _check_gaps(gdf: gpd.GeoDataFrame, layer: str) -> list[dict]:
    """
    Detect gaps (holes) between adjacent polygons in the same layer.
    Strategy: compute convex hull of union, subtract union — remainder = gaps.
    """
    errors = []
    valid  = gdf[
        gdf.geometry.notna() & ~gdf.geometry.is_empty & gdf.geometry.is_valid
    ].copy()

    if valid.empty or valid.geom_type.iloc[0] not in ("Polygon", "MultiPolygon"):
        return errors

    try:
        union    = unary_union(valid.geometry.values)
        envelope = union.convex_hull
        gaps     = envelope.difference(union)

        if gaps.is_empty or gaps.area <= GAP_THRESHOLD_M2:
            return errors

        # Decompose multipolygon gaps into individual gap polygons
        gap_polys = (
            list(gaps.geoms)
            if gaps.geom_type == "MultiPolygon"
            else [gaps]
        )

        for i, gap in enumerate(gap_polys):
            if gap.area > GAP_THRESHOLD_M2:
                errors.append({
                    "layer": layer, "fid": f"GAP_{i}",
                    "rule": "T2", "check": "gap",
                    "severity": "moderate",
                    "detail": (
                        f"Gap #{i+1} detected — area = {gap.area:.4f} m² — "
                        f"centroid ({gap.centroid.x:.2f}, {gap.centroid.y:.2f})"
                    ),
                })
    except Exception as e:
        errors.append({
            "layer": layer, "fid": -1,
            "rule": "T2", "check": "gap_check_error",
            "severity": "moderate",
            "detail": f"Gap check failed: {e}",
        })

    return errors


# -------------------------------------------------------------------
# Rule T3: Must Be Covered By (hierarchical)
# -------------------------------------------------------------------

def _check_covered_by(
    child_gdf:  gpd.GeoDataFrame,
    parent_gdf: gpd.GeoDataFrame,
    child_layer:  str,
    parent_layer: str,
) -> list[dict]:
    """
    For each child feature, calculate what % of its area falls
    outside the parent layer union. Severity based on % outside:
        <= 1%  → low
        <= 10% → moderate
        >  10% → critical
    """
    errors = []

    valid_child  = child_gdf[
        child_gdf.geometry.notna() & ~child_gdf.geometry.is_empty
    ].copy()
    valid_parent = parent_gdf[
        parent_gdf.geometry.notna() & ~parent_gdf.geometry.is_empty
    ].copy()

    if valid_child.empty or valid_parent.empty:
        return errors

    try:
        parent_union = unary_union(valid_parent.geometry.values)
    except Exception as e:
        errors.append({
            "layer": child_layer, "fid": -1,
            "rule": "T3", "check": "covered_by_error",
            "severity": "moderate",
            "detail": f"Could not build parent union for {parent_layer}: {e}",
        })
        return errors

    for idx, row in valid_child.iterrows():
        geom = row.geometry
        if geom.area == 0:
            continue

        try:
            intersection   = geom.intersection(parent_union)
            outside_area   = geom.area - intersection.area
            pct_outside    = (outside_area / geom.area) * 100
        except Exception:
            continue

        if pct_outside <= 0:
            continue

        if pct_outside <= T3_LOW:
            severity = "low"
        elif pct_outside <= T3_MODERATE:
            severity = "moderate"
        else:
            severity = "critical"

        errors.append({
            "layer": child_layer, "fid": idx,
            "rule": "T3", "check": "not_covered_by_parent",
            "severity": severity,
            "detail": (
                f"{pct_outside:.2f}% of area falls outside {parent_layer} — "
                f"outside area = {outside_area:.4f} m²"
            ),
        })

    return errors


# -------------------------------------------------------------------
# Rule T2 duplicate geometry
# -------------------------------------------------------------------

def _check_duplicates(gdf: gpd.GeoDataFrame, layer: str) -> list[dict]:
    errors = []
    valid  = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    wkb    = valid.geometry.apply(lambda g: g.wkb)
    for idx in wkb[wkb.duplicated(keep=False)].index:
        errors.append({
            "layer": layer, "fid": idx,
            "rule": "T2", "check": "duplicate_geometry",
            "severity": "moderate",
            "detail": "Exact geometry duplicate — resolve before delivery to IGAC",
        })
    return errors


# -------------------------------------------------------------------
# Rule A1: CODIGO uniqueness
# -------------------------------------------------------------------

def _check_codigo(gdf: gpd.GeoDataFrame, layer: str) -> list[dict]:
    errors = []
    if layer.lower() in CODIGO_DUPLICATE_EXEMPT or "CODIGO" not in gdf.columns:
        return errors
    non_null   = gdf[gdf["CODIGO"].notna() & (gdf["CODIGO"].astype(str).str.strip() != "")]
    counts     = non_null["CODIGO"].value_counts()
    duplicates = counts[counts > 1].index
    for idx, row in non_null[non_null["CODIGO"].isin(duplicates)].iterrows():
        errors.append({
            "layer": layer, "fid": idx,
            "rule": "A1", "check": "duplicate_codigo",
            "severity": "moderate",
            "detail": (
                f"CODIGO '{row['CODIGO']}' appears {counts[row['CODIGO']]} times "
                f"— must be unique per CTM12"
            ),
        })
    return errors


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _is_unidad(name: str) -> bool:
    return any(p in name.lower() for p in UNIDAD_PATTERNS)


def _load_gdfs(shp_files: list[Path]) -> dict[str, gpd.GeoDataFrame]:
    gdfs = {}
    for shp in shp_files:
        try:
            gdfs[shp.stem] = gpd.read_file(str(shp))
        except Exception:
            pass
    return gdfs


# -------------------------------------------------------------------
# Main step runner
# -------------------------------------------------------------------

def run(input_dir: str, output_dir: str, logger) -> dict:
    input_path  = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    shp_files = sorted(input_path.glob("*.shp"))
    if not shp_files:
        logger.error(f"No .shp files found in '{input_dir}'")
        return {"status": "error", "total_errors": 0, "critical": 0,
                "moderate": 0, "files": [], "details": [], "all_errors": []}

    # Detect / prompt hierarchy roles
    roles = detect_layer_roles(shp_files)
    roles = prompt_missing_roles(roles, shp_files)

    logger.info("  CTM12 rules: G1–G5 · T1 (overlap) · T2 (gaps+duplicates) · T3 (covered by) · A1")
    logger.info("  T1 U_UNIDAD: floor-aware (CONSTRUCCION_CODIGO + PLANTA)")

    # Log detected roles
    logger.info("\n  Detected layer roles:")
    for role in HIERARCHY:
        path = roles.get(role)
        logger.info(f"    {role.upper():<15} → {path.name if path else '— not assigned'}")

    print()
    logger.info(f"  {'Layer':<28} {'Features':>10}  {'Critical':>10}  {'Moderate':>10}  {'Low':>6}  Status")
    logger.info("  " + "─" * 78)

    # Load all GDFs
    gdfs       = _load_gdfs(shp_files)
    all_errors = []
    out_files  = []
    details    = []

    # Per-layer checks (G1–G5, T1, T2, A1)
    for shp in shp_files:
        layer = shp.stem
        gdf   = gdfs.get(layer)
        if gdf is None:
            logger.error(f"  {layer}: could not load")
            continue

        errors  = []
        errors += _check_geometry(gdf, layer)
        errors += (_check_overlaps_unidad(gdf, layer)
                   if _is_unidad(layer)
                   else _overlaps_strtree(gdf, layer))
        errors += _check_gaps(gdf, layer)
        errors += _check_duplicates(gdf, layer)
        errors += _check_codigo(gdf, layer)

        all_errors.extend(errors)

        critical = sum(1 for e in errors if e["severity"] == "critical")
        moderate = sum(1 for e in errors if e["severity"] == "moderate")
        low      = sum(1 for e in errors if e["severity"] == "low")
        tag      = " ✦" if _is_unidad(layer) else ""

        status_str = (
            "✓ OK" if not errors else
            f"✗ {critical} critical" if critical else
            f"⚠ {moderate} moderate"
        )
        logger.info(
            f"  {layer + tag:<28} {len(gdf):>10}  "
            f"{critical:>10}  {moderate:>10}  {low:>6}  {status_str}"
        )
        details.append(f"{shp.name}: {len(errors)} errors (C:{critical} M:{moderate} L:{low})")

        out_file = output_path / shp.name
        gdf.to_file(str(out_file))
        out_files.append(str(out_file))

    # T3 — Must Be Covered By (hierarchical)
    hierarchy_pairs = [
        ("terreno",      "manzana"),
        ("construccion", "terreno"),
        ("unidad",       "construccion"),
    ]

    t3_errors = []
    print()
    logger.info("  T3 — Must Be Covered By (hierarchical)")
    logger.info("  " + "─" * 50)

    for child_role, parent_role in hierarchy_pairs:
        child_path  = roles.get(child_role)
        parent_path = roles.get(parent_role)

        if not child_path or not parent_path:
            logger.info(
                f"  {child_role.upper():<15} ← {parent_role.upper():<15}  "
                f"⚠ Skipped — layer not assigned"
            )
            continue

        child_gdf  = gdfs.get(child_path.stem)
        parent_gdf = gdfs.get(parent_path.stem)

        if child_gdf is None or parent_gdf is None:
            logger.info(
                f"  {child_role.upper():<15} ← {parent_role.upper():<15}  "
                f"✗ Could not load layer"
            )
            continue

        errs = _check_covered_by(
            child_gdf, parent_gdf,
            child_path.stem, parent_path.stem
        )
        t3_errors.extend(errs)

        critical = sum(1 for e in errs if e["severity"] == "critical")
        moderate = sum(1 for e in errs if e["severity"] == "moderate")
        low      = sum(1 for e in errs if e["severity"] == "low")

        status_str = (
            "✓ All covered" if not errs else
            f"✗ {critical} critical / {moderate} moderate / {low} low"
        )
        logger.info(
            f"  {child_role.upper():<15} ← {parent_role.upper():<15}  {status_str}"
        )

    all_errors.extend(t3_errors)

    # Write CSV
    csv_path = output_path / "topology_errors.csv"
    with open(str(csv_path), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["layer","fid","rule","check","severity","detail"])
        writer.writeheader()
        writer.writerows(all_errors)

    total    = len(all_errors)
    critical = sum(1 for e in all_errors if e["severity"] == "critical")
    moderate = sum(1 for e in all_errors if e["severity"] == "moderate")
    low      = sum(1 for e in all_errors if e["severity"] == "low")

    print()
    logger.info("  RULE REFERENCE (CTM12 / LADM-COL)")
    logger.info("  ─────────────────────────────────────────────────────────────────")
    logger.info("  G1 Null geometry         G2 Empty geometry       G3 Self-intersection")
    logger.info("  G4 Zero-area polygon     G5 Sliver (< 1.0 m²)")
    logger.info("  T1 Must Not Overlap      T2 Must Not Have Gaps   T3 Must Be Covered By")
    logger.info("  A1 Duplicate CODIGO")
    logger.info("  ✦  U_UNIDAD: T1 floor-aware (CONSTRUCCION_CODIGO + PLANTA)")
    logger.info("  T3 hierarchy: TERRENO←MANZANA · CONSTRUCCION←TERRENO · UNIDAD←CONSTRUCCION")
    print()
    logger.info(f"  Total errors : {total}  (critical: {critical}  moderate: {moderate}  low: {low})")
    logger.info(f"  Error log    : {csv_path.name}")

    status = "error" if critical > 0 else "warning" if moderate > 0 else "ok"

    return {
        "status":       status,
        "total_errors": total,
        "critical":     critical,
        "moderate":     moderate,
        "low":          low,
        "files":        out_files,
        "details":      details,
        "all_errors":   all_errors,
    }