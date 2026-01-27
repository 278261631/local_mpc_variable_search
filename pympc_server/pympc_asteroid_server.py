"""PyMPC Asteroid Search Web Service

Multi-threaded asteroid cone search service using pympc.

API Endpoints:
  GET /search?ra=<deg>&dec=<deg>&epoch=<mjd>&radius=<arcsec>&max_mag=<mag>&observatory=<code>
  GET /health
  GET /info

Example:
  curl "http://localhost:5001/search?ra=88.79&dec=7.41&epoch=60000&radius=60"
  curl "http://localhost:5001/info"
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Union

import numpy as np
from flask import Flask, request, jsonify
from astropy.time import Time
import astropy.units as u

import pympc

# ============ Default Configuration ============
DEFAULT_PORT = 5001
DEFAULT_CATALOG_DIR = None  # Will use system temp if not specified
DEFAULT_MAX_WORKERS = 4
# ===============================================

app = Flask(__name__)

# Global state
CATALOG_PATH = None
LOAD_TIME = None
EXECUTOR: ThreadPoolExecutor = None
MAX_WORKERS = DEFAULT_MAX_WORKERS


def get_catalog_path() -> Optional[str]:
    """Get the path to the xephem catalog file."""
    global CATALOG_PATH
    if CATALOG_PATH and os.path.exists(CATALOG_PATH):
        return CATALOG_PATH
    
    # Check default locations
    temp_dir = tempfile.gettempdir()
    default_path = os.path.join(temp_dir, "mpcorb_xephem.csv")
    if os.path.exists(default_path):
        CATALOG_PATH = default_path
        return CATALOG_PATH
    
    return None


def init_catalog(cat_dir: Optional[str] = None, force_update: bool = False):
    """Initialize or update the asteroid catalog."""
    global CATALOG_PATH, LOAD_TIME
    
    existing_path = get_catalog_path()
    
    if existing_path and not force_update:
        print(f"Using existing catalog: {existing_path}")
        CATALOG_PATH = existing_path
        LOAD_TIME = time.time()
        return CATALOG_PATH
    
    print("Downloading/updating asteroid catalog from MPC...")
    start = time.time()
    
    try:
        if cat_dir:
            CATALOG_PATH = pympc.update_catalogue(cat_dir=cat_dir)
        else:
            CATALOG_PATH = pympc.update_catalogue()
        
        elapsed = time.time() - start
        print(f"Catalog ready: {CATALOG_PATH} (took {elapsed:.1f}s)")
        LOAD_TIME = time.time()
        return CATALOG_PATH
    except Exception as e:
        print(f"Error updating catalog: {e}")
        if existing_path:
            print(f"Falling back to existing catalog: {existing_path}")
            CATALOG_PATH = existing_path
            LOAD_TIME = time.time()
            return CATALOG_PATH
        raise


def init_executor(max_workers: int = DEFAULT_MAX_WORKERS):
    """Initialize the thread pool executor."""
    global EXECUTOR, MAX_WORKERS
    MAX_WORKERS = max_workers
    EXECUTOR = ThreadPoolExecutor(max_workers=max_workers)
    print(f"Thread pool initialized with {max_workers} workers")


def _do_search(ra: float, dec: float, epoch: float, radius: float,
               max_mag: Optional[float] = None, 
               observatory: Union[int, str, tuple] = 500,
               include_major: bool = True,
               include_minor: bool = True) -> dict:
    """Perform a single asteroid search."""
    start = time.time()
    
    try:
        # Convert epoch to astropy Time if it's MJD
        if isinstance(epoch, (int, float)):
            epoch_time = Time(epoch, format='mjd')
        else:
            epoch_time = Time(epoch)
        
        # Perform the search
        result = pympc.minor_planet_check(
            ra=ra * u.deg,
            dec=dec * u.deg,
            epoch=epoch_time,
            search_radius=radius * u.arcsec,
            xephem_filepath=CATALOG_PATH,
            max_mag=max_mag,
            include_minor_bodies=include_minor,
            include_major_bodies=include_major,
            observatory=observatory,
        )
        
        elapsed = time.time() - start
        
        # Convert astropy table to list of dicts
        if result is not None and len(result) > 0:
            records = []
            for row in result:
                record = {}
                for col in result.colnames:
                    val = row[col]
                    # Convert numpy types to Python types
                    if hasattr(val, 'item'):
                        val = val.item()
                    elif hasattr(val, 'value'):
                        val = float(val.value)
                    record[col] = val
                records.append(record)
        else:
            records = []
        
        return {
            "success": True,
            "count": len(records),
            "query_time_ms": elapsed * 1000,
            "results": records,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "query_time_ms": (time.time() - start) * 1000,
        }


@app.route("/health")
def health():
    """Health check endpoint."""
    catalog_exists = CATALOG_PATH is not None and os.path.exists(CATALOG_PATH)
    return jsonify({
        "status": "ok" if catalog_exists else "degraded",
        "catalog_loaded": catalog_exists,
        "workers": MAX_WORKERS,
    })


@app.route("/info")
def info():
    """Catalog and server information endpoint."""
    catalog_exists = CATALOG_PATH is not None and os.path.exists(CATALOG_PATH)

    info_data = {
        "catalog_path": CATALOG_PATH,
        "catalog_exists": catalog_exists,
        "max_workers": MAX_WORKERS,
    }

    if LOAD_TIME:
        info_data["load_time"] = LOAD_TIME
        info_data["uptime_seconds"] = time.time() - LOAD_TIME

    if catalog_exists:
        try:
            stat = os.stat(CATALOG_PATH)
            info_data["catalog_size_mb"] = stat.st_size / (1024 * 1024)
            info_data["catalog_modified"] = stat.st_mtime
        except:
            pass

    return jsonify(info_data)


@app.route("/search")
def search():
    """Asteroid cone search endpoint.

    Query parameters:
      ra: Right Ascension in degrees (required)
      dec: Declination in degrees (required)
      epoch: Observation epoch as MJD (required)
      radius: Search radius in arcseconds (default: 60)
      max_mag: Maximum magnitude limit (optional)
      observatory: Observatory code (default: 500 for geocentric)
      include_major: Include major planets (default: true)
      include_minor: Include minor bodies (default: true)
    """
    if not CATALOG_PATH or not os.path.exists(CATALOG_PATH):
        return jsonify({"error": "Catalog not loaded"}), 500

    try:
        ra = float(request.args.get("ra"))
        dec = float(request.args.get("dec"))
        epoch = float(request.args.get("epoch"))
    except (TypeError, ValueError):
        return jsonify({"error": "Missing or invalid ra/dec/epoch parameters"}), 400

    radius = float(request.args.get("radius", 60.0))
    max_mag = request.args.get("max_mag")
    if max_mag is not None:
        max_mag = float(max_mag)

    observatory = request.args.get("observatory", "500")
    try:
        observatory = int(observatory)
    except ValueError:
        pass  # Keep as string (observatory name)

    include_major = request.args.get("include_major", "true").lower() == "true"
    include_minor = request.args.get("include_minor", "true").lower() == "true"

    result = _do_search(
        ra=ra,
        dec=dec,
        epoch=epoch,
        radius=radius,
        max_mag=max_mag,
        observatory=observatory,
        include_major=include_major,
        include_minor=include_minor,
    )

    result["query"] = {
        "ra": ra,
        "dec": dec,
        "epoch": epoch,
        "radius_arcsec": radius,
        "max_mag": max_mag,
        "observatory": observatory,
    }

    if result.get("success"):
        return jsonify(result)
    else:
        return jsonify(result), 500


@app.route("/batch", methods=["POST"])
def batch_search():
    """Batch search endpoint for multiple positions.

    POST JSON body:
    {
      "queries": [
        {"ra": 88.79, "dec": 7.41, "epoch": 60000},
        {"ra": 120.5, "dec": -12.3, "epoch": 60000}
      ],
      "radius": 60,
      "max_mag": 20,
      "observatory": 500
    }
    """
    if not CATALOG_PATH or not os.path.exists(CATALOG_PATH):
        return jsonify({"error": "Catalog not loaded"}), 500

    data = request.get_json()
    if not data or "queries" not in data:
        return jsonify({"error": "Missing queries in request body"}), 400

    queries = data["queries"]
    radius = data.get("radius", 60.0)
    max_mag = data.get("max_mag")
    observatory = data.get("observatory", 500)
    include_major = data.get("include_major", True)
    include_minor = data.get("include_minor", True)

    start = time.time()
    results = []

    # Submit all queries to thread pool
    futures = {}
    for i, q in enumerate(queries):
        try:
            ra = float(q["ra"])
            dec = float(q["dec"])
            epoch = float(q["epoch"])
        except (KeyError, TypeError, ValueError) as e:
            results.append({"index": i, "error": f"Invalid query: {e}"})
            continue

        future = EXECUTOR.submit(
            _do_search,
            ra=ra,
            dec=dec,
            epoch=epoch,
            radius=radius,
            max_mag=max_mag,
            observatory=observatory,
            include_major=include_major,
            include_minor=include_minor,
        )
        futures[future] = i

    # Collect results
    result_map = {}
    for future in as_completed(futures):
        idx = futures[future]
        try:
            result_map[idx] = future.result()
            result_map[idx]["index"] = idx
        except Exception as e:
            result_map[idx] = {"index": idx, "error": str(e)}

    # Sort by index
    for i in sorted(result_map.keys()):
        results.append(result_map[i])

    total_time = time.time() - start

    return jsonify({
        "total_queries": len(queries),
        "total_time_ms": total_time * 1000,
        "results": results,
    })


@app.route("/update_catalog", methods=["POST"])
def update_catalog():
    """Trigger catalog update from MPC."""
    try:
        start = time.time()
        init_catalog(force_update=True)
        elapsed = time.time() - start
        return jsonify({
            "status": "ok",
            "message": "Catalog updated successfully",
            "catalog_path": CATALOG_PATH,
            "update_time_seconds": elapsed,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="PyMPC Asteroid Search Web Service")
    p.add_argument("--catalog-dir", default=DEFAULT_CATALOG_DIR,
                   help="Directory for catalog files")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help="Server port")
    p.add_argument("--host", default="127.0.0.1", help="Server host")
    p.add_argument("--workers", type=int, default=DEFAULT_MAX_WORKERS,
                   help="Number of worker threads")
    p.add_argument("--update-catalog", action="store_true",
                   help="Force update catalog from MPC")
    p.add_argument("--threaded", action="store_true", default=True,
                   help="Enable threaded request handling")
    args = p.parse_args(argv)

    # Initialize executor
    init_executor(args.workers)

    # Initialize catalog
    try:
        init_catalog(cat_dir=args.catalog_dir, force_update=args.update_catalog)
    except Exception as e:
        print(f"Warning: Failed to initialize catalog: {e}")
        print("Server will start but searches will fail until catalog is available.")
        print("Use POST /update_catalog to download the catalog.")

    print(f"\nStarting PyMPC Asteroid Server on http://{args.host}:{args.port}")
    print(f"Workers: {args.workers}")
    print(f"\nEndpoints:")
    print(f"  GET  /health")
    print(f"  GET  /info")
    print(f"  GET  /search?ra=<deg>&dec=<deg>&epoch=<mjd>&radius=<arcsec>")
    print(f"  POST /batch")
    print(f"  POST /update_catalog")
    print(f"\nExample:")
    print(f"  curl \"http://{args.host}:{args.port}/info\"")
    print(f"  curl \"http://{args.host}:{args.port}/search?ra=88.79&dec=7.41&epoch=60000&radius=60\"")

    app.run(host=args.host, port=args.port, debug=False, threaded=args.threaded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

