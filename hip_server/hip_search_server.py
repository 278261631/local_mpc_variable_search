"""HIP Star Search Web Service

Fast cone search service for HIP star catalogs.

API Endpoints:
  GET /search?ra=<deg>&dec=<deg>&radius=<arcsec>&max_mag=<mag>&top=<n>
  GET /health
  GET /info
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
from flask import Flask, jsonify, request


DEFAULT_PORT = 5002
DEFAULT_CATALOG = "data/hip_catalog.csv"

app = Flask(__name__)

CATALOG_DF: pd.DataFrame | None = None
CATALOG_COORDS: SkyCoord | None = None
CATALOG_PATH: Path | None = None
LOAD_TIME: float | None = None
COLUMN_MAP: dict[str, str | None] = {"hip": None, "ra": None, "dec": None, "mag": None}


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    return out


def _find_column(columns: list[str], candidates: list[str]) -> str | None:
    lower_map = {c.lower(): c for c in columns}
    for name in candidates:
        if name in lower_map:
            return lower_map[name]
    return None


def _load_hip_catalog(path: Path) -> tuple[pd.DataFrame, dict[str, str | None]]:
    print(f"Loading HIP catalog: {path}")
    start = time.time()

    df = pd.read_csv(path)
    df = _normalize_columns(df)

    cols = list(df.columns)
    hip_col = _find_column(cols, ["hip", "hip_id", "hipid", "id"])
    ra_col = _find_column(cols, ["ra", "ra_deg", "radeg", "raj2000", "raj2000_deg"])
    dec_col = _find_column(cols, ["dec", "dec_deg", "dedeg", "dej2000", "dej2000_deg"])
    mag_col = _find_column(cols, ["mag", "vmag", "v_mag", "hp_mag", "phot_g_mean_mag"])

    if ra_col is None or dec_col is None:
        raise ValueError(
            "Catalog must include RA/DEC columns. Supported names include: "
            "ra/ra_deg/radeg and dec/dec_deg/dedeg."
        )

    out = pd.DataFrame()
    if hip_col is not None:
        out["hip"] = pd.to_numeric(df[hip_col], errors="coerce")
    else:
        out["hip"] = np.arange(1, len(df) + 1, dtype=float)

    out["ra"] = pd.to_numeric(df[ra_col], errors="coerce")
    out["dec"] = pd.to_numeric(df[dec_col], errors="coerce")
    if mag_col is not None:
        out["mag"] = pd.to_numeric(df[mag_col], errors="coerce")
    else:
        out["mag"] = np.nan

    out = out.dropna(subset=["ra", "dec"]).copy()
    out["hip"] = out["hip"].astype("Int64")

    elapsed = time.time() - start
    print(f"Loaded {len(out)} stars in {elapsed:.2f}s")

    return out, {"hip": hip_col, "ra": ra_col, "dec": dec_col, "mag": mag_col}


def load_catalog(path: Path) -> None:
    global CATALOG_DF, CATALOG_COORDS, CATALOG_PATH, LOAD_TIME, COLUMN_MAP

    df, column_map = _load_hip_catalog(path)
    CATALOG_DF = df
    CATALOG_COORDS = SkyCoord(df["ra"].to_numpy() * u.deg, df["dec"].to_numpy() * u.deg)
    CATALOG_PATH = path
    LOAD_TIME = time.time()
    COLUMN_MAP = column_map
    print("HIP catalog ready for queries")


@app.route("/health")
def health():
    return jsonify({"status": "ok", "catalog_loaded": CATALOG_DF is not None})


@app.route("/info")
def info():
    if CATALOG_DF is None:
        return jsonify({"error": "Catalog not loaded"}), 500

    return jsonify(
        {
            "catalog_path": str(CATALOG_PATH),
            "total_stars": len(CATALOG_DF),
            "load_time": LOAD_TIME,
            "uptime_seconds": time.time() - LOAD_TIME if LOAD_TIME else None,
            "column_map": COLUMN_MAP,
        }
    )


@app.route("/search")
def search():
    if CATALOG_DF is None or CATALOG_COORDS is None:
        return jsonify({"error": "Catalog not loaded"}), 500

    try:
        ra = float(request.args.get("ra"))
        dec = float(request.args.get("dec"))
    except (TypeError, ValueError):
        return jsonify({"error": "Missing or invalid ra/dec parameters"}), 400

    radius = float(request.args.get("radius", 60.0))
    top = int(request.args.get("top", 50))
    max_mag_str = request.args.get("max_mag")

    start = time.time()

    target = SkyCoord(ra * u.deg, dec * u.deg)
    separation_arcsec = CATALOG_COORDS.separation(target).arcsec

    df = CATALOG_DF.assign(separation_arcsec=separation_arcsec)
    df = df[df["separation_arcsec"] <= radius].copy()

    if max_mag_str is not None:
        max_mag = float(max_mag_str)
        df = df[(df["mag"].isna()) | (df["mag"] <= max_mag)]
    else:
        max_mag = None

    df = df.sort_values("separation_arcsec", ascending=True).head(top)
    results = df.replace({np.nan: None}).to_dict(orient="records")

    elapsed = time.time() - start
    return jsonify(
        {
            "query": {
                "ra": ra,
                "dec": dec,
                "radius_arcsec": radius,
                "max_mag": max_mag,
            },
            "count": len(results),
            "query_time_ms": elapsed * 1000,
            "results": results,
        }
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="HIP Star Search Web Service")
    parser.add_argument("--catalog", default=DEFAULT_CATALOG, help="HIP catalog path")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Server port")
    parser.add_argument("--host", default="127.0.0.1", help="Server host")
    args = parser.parse_args(argv)

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

