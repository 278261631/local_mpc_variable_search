"""Fast ASTAP Variable Star Search Web Service

Drop-in replacement for ``astap_variable_search_server.py`` (same endpoints,
parameters and JSON fields) backed by a declination-sorted slab index.

API Endpoints:
  GET  /search?ra=<deg>&dec=<deg>&radius=<arcsec>&max_mag=<mag>&top=<n>
  POST /search_batch   {"queries":[{"ra":..,"dec":..,"radius":..}, ...], ...}
  POST /reload         rebuild / reload the catalogue
  GET  /health
  GET  /info

Example:
  curl "http://localhost:5000/search?ra=88.79&dec=7.41&radius=60"
  curl "http://localhost:5000/info"
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np
from flask import Flask, jsonify, request

from varstar_index import CatalogError, VarStarIndex, load_index

# ============ Default Configuration ============
DEFAULT_PORT = 5000
DEFAULT_HOST = "127.0.0.1"
DEFAULT_CATALOG = "data/variable_stars_15.csv"
DEFAULT_TOP = 50
DEFAULT_RADIUS_ARCSEC = 60.0
# ===============================================

log = logging.getLogger("varstar")

app = Flask(__name__)
if hasattr(app, "json"):  # Flask >= 2.2
    app.json.sort_keys = False
else:  # pragma: no cover - older Flask
    app.config["JSON_SORT_KEYS"] = False

INDEX: VarStarIndex | None = None
LOADED_AT: float | None = None
CONFIG: dict = {"catalog": None, "cache_dir": None, "use_cache": True}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _find_default_catalog() -> Path:
    """data/variable_stars_15.csv relative to CWD or to the repository root."""
    here = Path(__file__).resolve().parent
    for base in (Path.cwd(), here.parent, here):
        candidate = base / DEFAULT_CATALOG
        if candidate.exists():
            return candidate
    return Path(DEFAULT_CATALOG)


def _resolve_catalog(path: Path) -> Path:
    path = Path(path).expanduser()
    if path.exists():
        return path
    here = Path(__file__).resolve().parent
    for base in (Path.cwd(), here.parent, here):
        candidate = base / path
        if candidate.exists():
            return candidate
    raise CatalogError(f"Catalog not found: {path}")


def _load(catalog: Path, rebuild: bool = False) -> VarStarIndex:
    global INDEX, LOADED_AT
    t0 = time.perf_counter()
    INDEX = load_index(
        catalog,
        cache_dir=CONFIG["cache_dir"],
        use_cache=CONFIG["use_cache"],
        rebuild=rebuild,
        log=log.info,
    )
    LOADED_AT = time.time()
    log.info(
        "[index] ready in %.2f s  objects=%s  cache_hit=%s  memory=%.0f MB",
        time.perf_counter() - t0, f"{INDEX.n_objects:,}", INDEX.cache_hit,
        INDEX.memory_bytes() / 1e6,
    )
    return INDEX


def _search_payload(
    ra: float,
    dec: float,
    radius: float,
    max_mag: float | None,
    top: int,
) -> tuple[dict, float]:
    """Run one query and build the JSON body. Returns (payload, elapsed_ms)."""
    t0 = time.perf_counter()
    hits = INDEX.search(ra, dec, radius, max_mag=max_mag, top=top)
    results = INDEX.records(hits)

    payload = {
        "query": {
            "ra": ra,
            "dec": dec,
            "radius_arcsec": radius,
            "max_mag": max_mag,
        },
        "count": len(results),
        "query_time_ms": round(hits.elapsed_ms, 4),
        "candidates": hits.candidates,
        "results": results,
    }
    elapsed_ms = (time.perf_counter() - t0) * 1e3
    log.debug(
        "[query] ra=%.5f dec=%.5f radius=%.1f max_mag=%s -> %d hit(s) in %.3f ms "
        "(candidates=%d)",
        ra, dec, radius, max_mag, len(results), hits.elapsed_ms, hits.candidates,
    )
    return payload, elapsed_ms


def _parse_query(args) -> dict:
    """Validate query parameters (raises ValueError with a client message)."""
    try:
        ra = float(args.get("ra"))
        dec = float(args.get("dec"))
    except (TypeError, ValueError):
        raise ValueError("Missing or invalid ra/dec parameters")

    try:
        radius = float(args.get("radius", DEFAULT_RADIUS_ARCSEC))
    except (TypeError, ValueError):
        raise ValueError("Invalid radius parameter")

    max_mag_raw = args.get("max_mag")
    max_mag = None
    if max_mag_raw not in (None, ""):
        try:
            max_mag = float(max_mag_raw)
        except (TypeError, ValueError):
            raise ValueError("Invalid max_mag parameter")

    try:
        top = int(args.get("top", DEFAULT_TOP))
    except (TypeError, ValueError):
        raise ValueError("Invalid top parameter")

    return {"ra": ra, "dec": dec, "radius": radius, "max_mag": max_mag, "top": top}


# --------------------------------------------------------------------------- #
# endpoints
# --------------------------------------------------------------------------- #
@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "catalog_loaded": INDEX is not None,
        "total_stars": INDEX.n_objects if INDEX else 0,
    })


@app.route("/info")
def info():
    if INDEX is None:
        return jsonify({"error": "Catalog not loaded"}), 500
    body = {"load_time": LOADED_AT, "uptime_seconds": time.time() - (LOADED_AT or 0)}
    body.update(INDEX.stats())
    return jsonify(body)


@app.route("/search")
def search():
    if INDEX is None:
        return jsonify({"error": "Catalog not loaded"}), 500
    log.info("[request] GET /search from %s  query=%s", request.remote_addr, request.query_string.decode())

    try:
        q = _parse_query(request.args)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    payload, elapsed_ms = _search_payload(**q)
    resp = jsonify(payload)
    resp.headers["Server-Timing"] = f"search;dur={elapsed_ms:.3f}"
    return resp


@app.route("/search_batch", methods=["POST"])
def search_batch():
    """Run many cone searches in one request.

    Body:
        {"queries": [{"ra": .., "dec": .., "radius": .., "max_mag": .., "top": ..}, ...],
         "radius": 60, "max_mag": null, "top": 50}      # per-query keys override defaults
    """
    if INDEX is None:
        return jsonify({"error": "Catalog not loaded"}), 500

    body = request.get_json(silent=True) or {}
    queries = body.get("queries")
    if not isinstance(queries, list) or not queries:
        return jsonify({"error": "Body must contain a non-empty 'queries' list"}), 400

    defaults = {
        "radius": body.get("radius", DEFAULT_RADIUS_ARCSEC),
        "max_mag": body.get("max_mag"),
        "top": body.get("top", DEFAULT_TOP),
    }

    t0 = time.perf_counter()
    results = []
    for item in queries:
        merged = dict(defaults)
        merged.update({k: v for k, v in item.items() if v is not None})
        try:
            q = _parse_query(merged)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        payload, _ = _search_payload(**q)
        results.append(payload)

    total_ms = (time.perf_counter() - t0) * 1e3
    log.info("[request] POST /search_batch from %s  n=%d -> %.2f ms",
             request.remote_addr, len(queries), total_ms)
    resp = jsonify({
        "count": len(results),
        "query_time_ms": round(total_ms, 3),
        "per_query_ms": round(total_ms / len(results), 4),
        "results": results,
    })
    resp.headers["Server-Timing"] = f"batch;dur={total_ms:.3f}"
    return resp


@app.route("/reload", methods=["POST"])
def reload_catalog():
    global CONFIG
    rebuild = request.args.get("rebuild", "0") in ("1", "true", "yes")
    try:
        _load(Path(CONFIG["catalog"]), rebuild=rebuild)
    except (CatalogError, OSError) as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"status": "reloaded", **INDEX.stats()})


@app.errorhandler(500)
def internal_error(exc):
    log.exception("unhandled error: %s", exc)
    return jsonify({"error": "internal server error"}), 500


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _serve(host: str, port: int, server: str) -> None:
    if server == "waitress":
        try:
            from waitress import serve
        except ImportError:
            raise SystemExit(
                "waitress is not installed; run 'pip install waitress' or use --server flask"
            )
        log.info("serving with waitress (threads) on http://%s:%d", host, port)
        serve(app, host=host, port=port, threads=8)
    else:
        log.info("serving with flask dev server on http://%s:%d", host, port)
        app.run(host=host, port=port, debug=False, threaded=True)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Fast ASTAP Variable Star Search Web Service")
    parser.add_argument("--catalog", default=None,
                        help=f"ASTAP catalogue path (default: {DEFAULT_CATALOG})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Server port (default 5000)")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Server host (default 127.0.0.1)")
    parser.add_argument("--cache-dir", default=None,
                        help="Directory for the .npz index cache (default: system temp dir)")
    parser.add_argument("--no-cache", action="store_true", help="Never read/write the index cache")
    parser.add_argument("--rebuild-cache", action="store_true", help="Ignore any existing cache")
    parser.add_argument("--server", choices=["flask", "waitress"], default="flask",
                        help="WSGI server to use (default flask; waitress for production)")
    parser.add_argument("--log-level", default="INFO", help="INFO (default), DEBUG, WARNING ...")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    CONFIG["cache_dir"] = Path(args.cache_dir).expanduser() if args.cache_dir else None
    CONFIG["use_cache"] = not args.no_cache

    catalog = _resolve_catalog(Path(args.catalog) if args.catalog else _find_default_catalog())
    CONFIG["catalog"] = str(catalog)

    log.info("catalog: %s", catalog)
    _load(catalog, rebuild=args.rebuild_cache)

    log.info("try: curl \"http://%s:%d/search?ra=88.79&dec=7.41&radius=60\"", args.host, args.port)
    _serve(args.host, args.port, args.server)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
