"""Fast PyMPC Asteroid Search Web Service.

API-compatible with ``pympc_server.pympc_asteroid_server`` but backed by
:class:`fast_engine.EphemerisEngine`, which propagates the catalogue once per
time window and answers any epoch inside the window by vectorised extrapolation
+ exact per-candidate refinement.

Endpoints:
  GET  /health
  GET  /info
  GET  /search?ra=<deg>&dec=<deg>&epoch=<mjd>&radius=<arcsec>&max_mag=<mag>&observatory=<code>
  POST /batch
  POST /warm            (pre-build the ephemeris window for an epoch)
  POST /update_catalog  (download + hot rebuild)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, request, jsonify

from fast_engine import EphemerisEngine, DEFAULT_CATALOG_NAME

DEFAULT_PORT = 5001
DEFAULT_HOST = "127.0.0.1"
DEFAULT_WORKERS = max(1, min(16, os.cpu_count() or 4))

app = Flask(__name__)

ENGINE: EphemerisEngine = None
LOAD_TIME: float = None
CATALOG_PATH: str = None
CATALOG_VERSION: dict = {}
ENGINE_PARAMS: dict = {}
_rebuild_lock = threading.Lock()


def catalog_version(path: str) -> dict:
    try:
        st = os.stat(path)
        return {"path": path, "size": st.st_size, "mtime": st.st_mtime}
    except OSError:
        return {"path": path, "size": None, "mtime": None}


def resolve_catalog(cat_dir=None, force_update=False) -> str:
    candidate = os.path.join(cat_dir or tempfile.gettempdir(), DEFAULT_CATALOG_NAME)
    if os.path.exists(candidate) and not force_update:
        return candidate

    import pympc

    print("Downloading/updating asteroid catalogue from MPC...")
    start = time.time()
    try:
        path = pympc.update_catalogue(cat_dir=cat_dir)
        print(f"Catalogue ready: {path} ({time.time() - start:.1f}s)")
        return path
    except Exception:
        if os.path.exists(candidate):
            print(f"Update failed, falling back to existing catalogue: {candidate}")
            return candidate
        raise


def build_engine(catalog_path: str, params: dict) -> EphemerisEngine:
    start = time.time()
    eng = EphemerisEngine(
        catalog_path=catalog_path,
        workers=params["workers"],
        window_hours=params["window_hours"],
        base_cache=params["base_cache"],
        margin_arcsec=params["margin_arcsec"],
    )
    print(
        f"EphemerisEngine ready: {eng.n_objects:,} objects, "
        f"{len(eng._slices)} workers, window={params['window_hours']}h "
        f"({time.time() - start:.1f}s)"
    )
    return eng


def init_engine(catalog_path: str, params: dict):
    global ENGINE, LOAD_TIME, CATALOG_PATH, CATALOG_VERSION, ENGINE_PARAMS
    ENGINE = build_engine(catalog_path, params)
    LOAD_TIME = time.time()
    CATALOG_PATH = catalog_path
    CATALOG_VERSION = catalog_version(catalog_path)
    ENGINE_PARAMS = dict(params)


def rebuild_engine():
    """Atomic hot-swap of the engine after a catalogue update."""
    global ENGINE, LOAD_TIME, CATALOG_PATH, CATALOG_VERSION
    with _rebuild_lock:
        old = ENGINE
        new = build_engine(CATALOG_PATH, ENGINE_PARAMS)
        ENGINE = new
        LOAD_TIME = time.time()
        CATALOG_VERSION = catalog_version(CATALOG_PATH)
        if old is not None:
            threading.Timer(30.0, old.close).start()
        return new


@app.route("/health")
def health():
    ready = ENGINE is not None
    return jsonify({
        "status": "ok" if ready else "degraded",
        "engine_ready": ready,
        "objects": ENGINE.n_objects if ready else 0,
        "windows_cached": len(ENGINE._windows) if ready else 0,
    })


@app.route("/info")
def info():
    if ENGINE is None:
        return jsonify({"error": "engine not ready"}), 503
    return jsonify({
        "engine": "EphemerisEngine",
        "catalog_path": ENGINE.catalog_path,
        "catalog_version": CATALOG_VERSION,
        "objects": ENGINE.n_objects,
        "workers": ENGINE.pool.n,
        "window_hours": ENGINE_PARAMS.get("window_hours"),
        "base_cache": ENGINE.base_cache,
        "cached_windows": [round(c, 6) for c in ENGINE._windows.keys()],
        "load_time": LOAD_TIME,
        "uptime_seconds": time.time() - LOAD_TIME if LOAD_TIME else None,
    })


def _parse_common(args, default_radius=60.0):
    ra = float(args.get("ra"))
    dec = float(args.get("dec"))
    epoch = float(args.get("epoch"))
    radius = float(args.get("radius", default_radius))
    max_mag = args.get("max_mag")
    if max_mag is not None:
        max_mag = float(max_mag)
    observatory = args.get("observatory", "500")
    try:
        observatory = int(observatory)
    except (TypeError, ValueError):
        pass
    include_major = str(args.get("include_major", "true")).lower() == "true"
    include_minor = str(args.get("include_minor", "true")).lower() == "true"
    return ra, dec, epoch, radius, max_mag, observatory, include_major, include_minor


@app.route("/search")
def search():
    if ENGINE is None:
        return jsonify({"error": "engine not ready"}), 503
    try:
        ra, dec, epoch, radius, max_mag, observatory, inc_major, inc_minor = _parse_common(request.args)
    except (TypeError, ValueError):
        return jsonify({"error": "Missing or invalid ra/dec/epoch parameters"}), 400

    result = ENGINE.search(
        ra=ra, dec=dec, epoch_mjd=epoch, radius_arcsec=radius, max_mag=max_mag,
        observatory=observatory, include_major=inc_major, include_minor=inc_minor,
    )
    result["query"] = {
        "ra": ra, "dec": dec, "epoch": epoch, "radius_arcsec": radius,
        "max_mag": max_mag, "observatory": observatory,
    }
    resp = jsonify(result)
    resp.headers["Server-Timing"] = f'search;dur={result.get("query_time_ms", 0.0):.1f}'
    if result.get("window_built"):
        resp.headers["Server-Timing"] += f', window-build;dur={result.get("window_build_ms", 0.0):.1f}'
    return (resp, 200) if result.get("success") else (resp, 500)


@app.route("/batch", methods=["POST"])
def batch_search():
    if ENGINE is None:
        return jsonify({"error": "engine not ready"}), 503
    data = request.get_json(silent=True)
    if not data or "queries" not in data:
        return jsonify({"error": "Missing queries in request body"}), 400

    queries = data["queries"]
    radius = data.get("radius", 60.0)
    max_mag = data.get("max_mag")
    observatory = data.get("observatory", 500)
    include_major = data.get("include_major", True)
    include_minor = data.get("include_minor", True)

    start = time.time()
    results = [None] * len(queries)
    engine = ENGINE

    def run(iq):
        i, q = iq
        try:
            return i, engine.search(
                ra=float(q["ra"]), dec=float(q["dec"]), epoch_mjd=float(q["epoch"]),
                radius_arcsec=radius, max_mag=max_mag, observatory=observatory,
                include_major=include_major, include_minor=include_minor,
            )
        except (KeyError, TypeError, ValueError) as exc:
            return i, {"error": f"Invalid query: {exc}"}

    with ThreadPoolExecutor(max_workers=min(len(queries), DEFAULT_WORKERS)) as ex:
        for i, res in ex.map(run, list(enumerate(queries))):
            res["index"] = i
            results[i] = res

    return jsonify({
        "total_queries": len(queries),
        "total_time_ms": (time.time() - start) * 1000.0,
        "results": results,
    })


@app.route("/warm", methods=["POST", "GET"])
def warm():
    if ENGINE is None:
        return jsonify({"error": "engine not ready"}), 503
    epoch = request.args.get("epoch")
    if epoch is None:
        data = request.get_json(silent=True) or {}
        epoch = data.get("epoch")
    if epoch is None:
        return jsonify({"error": "Missing epoch"}), 400
    return jsonify(ENGINE.warm(float(epoch)))


@app.route("/update_catalog", methods=["POST"])
def update_catalog():
    if ENGINE is None:
        return jsonify({"error": "engine not ready"}), 503
    import pympc

    try:
        start = time.time()
        path = pympc.update_catalogue()
        global CATALOG_PATH
        CATALOG_PATH = path
        rebuild_engine()
        return jsonify({
            "status": "ok",
            "message": "Catalogue updated and engine hot-rebuilt.",
            "catalog_path": path,
            "catalog_version": CATALOG_VERSION,
            "update_and_rebuild_seconds": time.time() - start,
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def main(argv):
    p = argparse.ArgumentParser(description="Fast PyMPC Asteroid Search Web Service")
    p.add_argument("--catalog-dir", default=None)
    p.add_argument("--catalog", default=None, help="Explicit path to mpcorb_xephem.csv")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    p.add_argument("--window-hours", type=float, default=12.0,
                   help="Ephemeris validity window (hours) around each base epoch")
    p.add_argument("--base-cache", type=int, default=4,
                   help="Number of ephemeris windows kept in memory")
    p.add_argument("--margin-arcsec", type=float, default=900.0,
                   help="Candidate-search inflation to guarantee completeness")
    p.add_argument("--prewarm", type=float, action="append", default=[],
                   help="MJD epoch to pre-build at startup (repeatable)")
    p.add_argument("--update-catalog", action="store_true")
    p.add_argument("--update-only", action="store_true")
    p.add_argument("--log-level", default="INFO",
                   help="Logging level for window/query messages (default INFO)")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.update_only:
        import pympc

        print("Updating asteroid catalogue from Minor Planet Center...")
        start = time.time()
        path = pympc.update_catalogue(cat_dir=args.catalog_dir)
        print(f"Updated: {path} ({time.time() - start:.1f}s)")
        return 0

    catalog_path = args.catalog or resolve_catalog(args.catalog_dir, args.update_catalog)
    params = {
        "workers": args.workers,
        "window_hours": args.window_hours,
        "base_cache": args.base_cache,
        "margin_arcsec": args.margin_arcsec,
    }

    try:
        init_engine(catalog_path, params)
    except Exception as exc:
        print(f"Failed to initialise engine: {exc}")
        return 1

    for epoch in args.prewarm:
        print(f"Pre-warming epoch {epoch}... {ENGINE.warm(epoch)}")

    print(f"\nStarting Fast PyMPC Server on http://{args.host}:{args.port}")
    print(f"  workers={args.workers}  window={args.window_hours}h  base_cache={args.base_cache}")
    print("  GET  /health")
    print("  GET  /info")
    print("  GET  /search?ra=<deg>&dec=<deg>&epoch=<mjd>&radius=<arcsec>")
    print("  POST /batch")
    print("  POST /warm?epoch=<mjd>")
    print("  POST /update_catalog")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
