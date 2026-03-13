"""
input_reader.py
---------------
Universal spatial file reader for the cadastral pipeline.

Supported formats:
    .shp        Shapefile (via Fiona/GeoPandas)
    .gpkg       GeoPackage — multi-layer (via Fiona/GeoPandas)
    .gdb        File Geodatabase — read-only (via Fiona OpenFileGDB driver)
    .dxf        AutoCAD DXF (via Fiona)
    .dwg        AutoCAD DWG — requires ezdxf + conversion to DXF first
    .geojson    GeoJSON

Returns a list of LayerResult objects, each containing:
    - name      : layer name
    - gdf       : GeoDataFrame
    - source    : original file path
    - format    : detected format string
    - warnings  : list of non-fatal issues
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import fiona


# -------------------------------------------------------------------
# Supported formats
# -------------------------------------------------------------------

FORMATS = {
    ".shp":     "Shapefile",
    ".gpkg":    "GeoPackage",
    ".gdb":     "File Geodatabase",
    ".dxf":     "AutoCAD DXF",
    ".dwg":     "AutoCAD DWG",
    ".geojson": "GeoJSON",
    ".json":    "GeoJSON",
}

# Formats that may contain multiple layers
MULTI_LAYER_FORMATS = {".gpkg", ".gdb"}

# Formats requiring special handling
SPECIAL_FORMATS = {".dwg", ".dxf", ".gdb"}


# -------------------------------------------------------------------
# Result dataclass
# -------------------------------------------------------------------

@dataclass
class LayerResult:
    name:     str
    gdf:      gpd.GeoDataFrame | None
    source:   str
    format:   str
    warnings: list[str] = field(default_factory=list)
    error:    str | None = None

    @property
    def ok(self) -> bool:
        return self.gdf is not None and self.error is None


# -------------------------------------------------------------------
# Format-specific readers
# -------------------------------------------------------------------

def _read_shp(path: Path) -> list[LayerResult]:
    gdf = gpd.read_file(str(path))
    return [LayerResult(
        name=path.stem, gdf=gdf,
        source=str(path), format="Shapefile"
    )]


def _read_gpkg(path: Path) -> list[LayerResult]:
    results = []
    try:
        layers = fiona.listlayers(str(path))
    except Exception as e:
        return [LayerResult(
            name=path.stem, gdf=None,
            source=str(path), format="GeoPackage",
            error=f"Could not list layers: {e}"
        )]

    for layer_name in layers:
        try:
            gdf = gpd.read_file(str(path), layer=layer_name)
            results.append(LayerResult(
                name=layer_name, gdf=gdf,
                source=str(path), format="GeoPackage"
            ))
        except Exception as e:
            results.append(LayerResult(
                name=layer_name, gdf=None,
                source=str(path), format="GeoPackage",
                error=str(e)
            ))
    return results


def _read_gdb(path: Path) -> list[LayerResult]:
    """Read File Geodatabase using Fiona's OpenFileGDB driver."""
    results = []
    try:
        layers = fiona.listlayers(str(path))
    except Exception as e:
        return [LayerResult(
            name=path.stem, gdf=None,
            source=str(path), format="File Geodatabase",
            error=f"Could not open GDB (requires GDAL with OpenFileGDB driver): {e}"
        )]

    for layer_name in layers:
        try:
            gdf = gpd.read_file(str(path), layer=layer_name, driver="OpenFileGDB")
            w   = []
            if gdf.crs is None:
                w.append("No CRS found in GDB layer — verify projection")
            results.append(LayerResult(
                name=layer_name, gdf=gdf,
                source=str(path), format="File Geodatabase",
                warnings=w
            ))
        except Exception as e:
            results.append(LayerResult(
                name=layer_name, gdf=None,
                source=str(path), format="File Geodatabase",
                error=str(e)
            ))
    return results


def _read_dxf(path: Path) -> list[LayerResult]:
    """
    Read AutoCAD DXF via Fiona.
    DXF files often have geometry type issues and no CRS — warnings are added.
    """
    try:
        gdf = gpd.read_file(str(path))
        warnings = []

        if gdf.crs is None:
            warnings.append(
                "DXF has no embedded CRS — assign manually (e.g. EPSG:3116) "
                "before running CRS standardization"
            )
        if gdf.empty:
            warnings.append("DXF layer is empty — verify entity types (only LINE/POLYLINE/POLYGON read)")

        return [LayerResult(
            name=path.stem, gdf=gdf,
            source=str(path), format="AutoCAD DXF",
            warnings=warnings
        )]

    except Exception as e:
        return [LayerResult(
            name=path.stem, gdf=None,
            source=str(path), format="AutoCAD DXF",
            error=str(e)
        )]


def _read_dwg(path: Path) -> list[LayerResult]:
    """
    DWG is Autodesk proprietary — requires ezdxf to convert to DXF first.
    If ezdxf is not installed, returns a clear error with install instructions.
    """
    try:
        import ezdxf
        import tempfile
        import os

        # Convert DWG → DXF using ezdxf
        doc      = ezdxf.readfile(str(path))
        dxf_path = Path(tempfile.mktemp(suffix=".dxf"))
        doc.saveas(str(dxf_path))

        results = _read_dxf(dxf_path)
        dxf_path.unlink(missing_ok=True)

        # Update source and format on results
        for r in results:
            r.source = str(path)
            r.format = "AutoCAD DWG"
            r.warnings.append("DWG converted to DXF internally via ezdxf")

        return results

    except ImportError:
        return [LayerResult(
            name=path.stem, gdf=None,
            source=str(path), format="AutoCAD DWG",
            error=(
                "DWG support requires 'ezdxf'. "
                "Install it with: pip install ezdxf\n"
                "         Alternatively, export your DWG as DXF from AutoCAD/Civil 3D first."
            )
        )]
    except Exception as e:
        return [LayerResult(
            name=path.stem, gdf=None,
            source=str(path), format="AutoCAD DWG",
            error=f"Could not read DWG: {e}"
        )]


def _read_geojson(path: Path) -> list[LayerResult]:
    try:
        gdf = gpd.read_file(str(path))
        return [LayerResult(
            name=path.stem, gdf=gdf,
            source=str(path), format="GeoJSON"
        )]
    except Exception as e:
        return [LayerResult(
            name=path.stem, gdf=None,
            source=str(path), format="GeoJSON",
            error=str(e)
        )]


# -------------------------------------------------------------------
# Format router
# -------------------------------------------------------------------

_READERS = {
    ".shp":     _read_shp,
    ".gpkg":    _read_gpkg,
    ".gdb":     _read_gdb,
    ".dxf":     _read_dxf,
    ".dwg":     _read_dwg,
    ".geojson": _read_geojson,
    ".json":    _read_geojson,
}


def read_file(path: Path) -> list[LayerResult]:
    """Read a single spatial file and return a list of LayerResult objects."""
    suffix = path.suffix.lower()
    reader = _READERS.get(suffix)

    if reader is None:
        return [LayerResult(
            name=path.stem, gdf=None,
            source=str(path), format="Unknown",
            error=f"Unsupported format: '{suffix}'. "
                  f"Supported: {', '.join(FORMATS.keys())}"
        )]

    return reader(path)


# -------------------------------------------------------------------
# Directory scanner
# -------------------------------------------------------------------

def scan_directory(input_dir: str) -> list[LayerResult]:
    """
    Scan a directory for all supported spatial files.
    .gdb directories are treated as a single file.
    """
    input_path = Path(input_dir)
    results    = []
    seen_gdbs  = set()

    # Walk directory
    for path in sorted(input_path.rglob("*")):

        # Handle .gdb as directory
        if path.suffix.lower() == ".gdb" and path.is_dir():
            if str(path) not in seen_gdbs:
                seen_gdbs.add(str(path))
                results.extend(read_file(path))
            continue

        # Skip files inside .gdb directories (already handled above)
        if any(p.suffix.lower() == ".gdb" for p in path.parents):
            continue

        # Skip sidecar files (.dbf, .prj, .shx, .cpg, .sbx, .sbn)
        if path.suffix.lower() in (".dbf", ".prj", ".shx", ".cpg", ".sbx", ".sbn", ".xml"):
            continue

        if path.suffix.lower() in FORMATS and path.is_file():
            results.extend(read_file(path))

    return results


# -------------------------------------------------------------------
# Summary printer
# -------------------------------------------------------------------

def print_scan_summary(results: list[LayerResult], logger) -> None:
    """Print a formatted summary of scanned layers."""
    logger.info(f"  {'Layer':<28} {'Format':<22} {'Features':>10}  {'CRS':<18}  Status")
    logger.info("  " + "─" * 88)

    for r in results:
        if r.ok:
            crs_str = f"EPSG:{r.gdf.crs.to_epsg()}" if r.gdf.crs and r.gdf.crs.to_epsg() else str(r.gdf.crs) if r.gdf.crs else "No CRS"
            status  = "✓" if not r.warnings else f"⚠ {len(r.warnings)} warning(s)"
            logger.info(f"  {r.name:<28} {r.format:<22} {len(r.gdf):>10}  {crs_str:<18}  {status}")
            for w in r.warnings:
                logger.info(f"    {'':28} ⚠ {w}")
        else:
            logger.info(f"  {r.name:<28} {r.format:<22} {'—':>10}  {'—':<18}  ✗ {r.error}")
