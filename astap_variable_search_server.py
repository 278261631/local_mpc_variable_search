"""ASTAP Variable Star Search Web Service

Fast cone search service with pre-loaded catalog data.

API Endpoints:
  GET /search?ra=<deg>&dec=<deg>&radius=<arcsec>&max_mag=<mag>&top=<n>
  GET /health
  GET /info

Example:
  curl "http://localhost:5000/search?ra=88.79&dec=7.41&radius=60"
  curl "http://localhost:5000/info"
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from astropy.coordinates import SkyCoord
import astropy.units as u
from flask import Flask, request, jsonify

# ============ Default Configuration ============
DEFAULT_PORT = 5000
DEFAULT_CATALOG = "data/variable_stars_13.csv"
# ===============================================

app = Flask(__name__)

# Global catalog data (loaded at startup)
CATALOG_DF = None
CATALOG_COORDS = None
CATALOG_PATH = None
LOAD_TIME = None


def _parse_label(label: str) -> dict:
    """Parse ASTAP label: 'name mag_min-mag_max[Period_xxx]'"""
    result = {"name": "", "mag_min": None, "mag_max": None, "period": None}
    if not label:
        return result
    
    parts = label.split()
    if len(parts) >= 1:
        result["name"] = parts[0]
    if len(parts) >= 2:
        mag_period = parts[1]
        if "_Period_" in mag_period:
            mag_part, period_part = mag_period.rsplit("_Period_", 1)
            try:
                result["period"] = float(period_part)
            except ValueError:
                pass
        else:
            mag_part = mag_period
        
        mag_str = mag_part.rstrip("VRIBKp<>:()")
        if "-" in mag_str[1:]:
            idx = mag_str.find("-", 1)
            try:
                result["mag_min"] = float(mag_str[:idx].rstrip("VRIBKp<>:()"))
            except ValueError:
                pass
            try:
                result["mag_max"] = float(mag_str[idx+1:].rstrip("VRIBKp<>:()"))
            except ValueError:
                pass
    return result


def _read_astap_catalog(path: Path) -> pd.DataFrame:
    """Read ASTAP variable star catalog and decode coordinates."""
    print(f"Loading catalog: {path}")
    start = time.time()
    
    lines = path.read_text(encoding="utf-8").splitlines()
    data_lines = lines[2:]
    
    records = []
    for line in data_lines:
        parts = line.split(",", 2)
        if len(parts) < 3:
            continue
        try:
            ra_enc = int(parts[0])
            dec_enc = int(parts[1])
            label = parts[2]
        except ValueError:
            continue
        
        ra_deg = ra_enc / 2400.0
        dec_deg = dec_enc / 3600.0
        
        info = _parse_label(label)
        records.append({
            "ra": ra_deg,
            "dec": dec_deg,
            "name": info["name"],
            "mag_min": info["mag_min"],
            "mag_max": info["mag_max"],
            "period": info["period"],
            "label": label,
        })
    
    df = pd.DataFrame(records)
    elapsed = time.time() - start
    print(f"Loaded {len(df)} stars in {elapsed:.2f}s")
    return df


def load_catalog(path: Path):
    """Load catalog into global variables."""
    global CATALOG_DF, CATALOG_COORDS, CATALOG_PATH, LOAD_TIME
    
    CATALOG_PATH = path
    LOAD_TIME = time.time()
    CATALOG_DF = _read_astap_catalog(path)
    CATALOG_COORDS = SkyCoord(
        CATALOG_DF["ra"].to_numpy() * u.deg,
        CATALOG_DF["dec"].to_numpy() * u.deg
    )
    print("Catalog ready for queries")


@app.route("/health")
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "catalog_loaded": CATALOG_DF is not None})


@app.route("/info")
def info():
    """Catalog information endpoint."""
    if CATALOG_DF is None:
        return jsonify({"error": "Catalog not loaded"}), 500
    
    return jsonify({
        "catalog_path": str(CATALOG_PATH),
        "total_stars": len(CATALOG_DF),
        "load_time": LOAD_TIME,
        "uptime_seconds": time.time() - LOAD_TIME,
    })


@app.route("/search")
def search():
    """Cone search endpoint.
    
    Query parameters:
      ra: Right Ascension in degrees (required)
      dec: Declination in degrees (required)
      radius: Search radius in arcseconds (default: 60)
      max_mag: Maximum magnitude limit (optional)
      top: Maximum number of results (default: 50)
    """
    if CATALOG_DF is None:
        return jsonify({"error": "Catalog not loaded"}), 500
    
    try:
        ra = float(request.args.get("ra"))
        dec = float(request.args.get("dec"))
    except (TypeError, ValueError):
        return jsonify({"error": "Missing or invalid ra/dec parameters"}), 400
    
    radius = float(request.args.get("radius", 60.0))
    max_mag = request.args.get("max_mag")
    top = int(request.args.get("top", 50))
    
    start = time.time()
    
    target = SkyCoord(ra * u.deg, dec * u.deg)
    sep = CATALOG_COORDS.separation(target).arcsec
    
    df = CATALOG_DF.assign(separation_arcsec=sep)
    df = df[df["separation_arcsec"] <= radius].copy()
    
    if max_mag is not None:
        max_mag_val = float(max_mag)
        df = df[(df["mag_max"].isna()) | (df["mag_max"] <= max_mag_val)]
    
    df = df.sort_values("separation_arcsec", ascending=True)
    df = df.head(top)
    
    elapsed = time.time() - start

    # Convert to dict and replace NaN with None for valid JSON
    results = df.replace({np.nan: None}).to_dict(orient="records")

    return jsonify({
        "query": {
            "ra": ra,
            "dec": dec,
            "radius_arcsec": radius,
            "max_mag": max_mag,
        },
        "count": len(results),
        "query_time_ms": elapsed * 1000,
        "results": results,
    })


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="ASTAP Variable Star Search Web Service")
    p.add_argument("--catalog", default=DEFAULT_CATALOG, help="ASTAP catalog path")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help="Server port")
    p.add_argument("--host", default="127.0.0.1", help="Server host")
    args = p.parse_args(argv)
    
    catalog_path = Path(args.catalog).expanduser()
    if not catalog_path.exists():
        raise SystemExit(f"Catalog not found: {catalog_path}")
    
    load_catalog(catalog_path)
    
    print(f"\nStarting server on http://{args.host}:{args.port}")
    print(f"Try: curl \"http://{args.host}:{args.port}/info\"")
    print(f"     curl \"http://{args.host}:{args.port}/search?ra=88.79&dec=7.41&radius=60\"")
    
    app.run(host=args.host, port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

