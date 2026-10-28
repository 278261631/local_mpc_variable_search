"""Benchmark / validation for the fast variable-star search index.

Usage:
    python benchmark.py                     # index vs astropy brute force
    python benchmark.py --with-stock        # also time the stock server module
    python benchmark.py --catalog ..\\data\\variable_stars_15.csv --queries 500
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from varstar_index import load_index


def rand_positions(rng: np.random.Generator, n: int) -> np.ndarray:
    ra = rng.uniform(0.0, 360.0, n)
    dec = np.rad2deg(np.arcsin(rng.uniform(-1.0, 1.0, n)))
    return np.column_stack([ra, dec])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default=str(HERE.parent / "data" / "variable_stars_15.csv"))
    ap.add_argument("--queries", type=int, default=300)
    ap.add_argument("--radii", default="60,300,1200", help="comma separated arcsec values")
    ap.add_argument("--with-stock", action="store_true", help="time astap_variable_search_server too")
    ap.add_argument("--http", type=int, default=100, help="number of HTTP round-trips to time")
    args = ap.parse_args()

    catalog = Path(args.catalog).resolve()
    radii = [float(x) for x in args.radii.split(",")]
    rng = np.random.default_rng(1234)
    positions = rand_positions(rng, args.queries)

    print(f"catalogue: {catalog}")
    print(f"size:      {catalog.stat().st_size/1e6:.1f} MB")

    # ---------------- startup: cold build vs cache ------------------------- #
    tmp_cache = Path(tempfile.mkdtemp(prefix="varstar_bench_"))
    t = time.perf_counter()
    cold = load_index(catalog, cache_dir=tmp_cache, use_cache=True, rebuild=True, log=lambda *_: None)
    cold_s = time.perf_counter() - t

    t = time.perf_counter()
    warm = load_index(catalog, cache_dir=tmp_cache, use_cache=True, rebuild=False, log=lambda *_: None)
    warm_s = time.perf_counter() - t

    print(f"\n== startup ==")
    print(f"cold build : {cold_s:6.2f} s   ({cold.n_objects:,} stars, index {cold.memory_bytes()/1e6:.0f} MB)")
    print(f"cache load : {warm_s:6.2f} s   cache={warm.cache_path.name if warm.cache_path else '-'} "
          f"({(warm.cache_path.stat().st_size/1e6) if warm.cache_path else 0:.0f} MB)")
    print(f"speedup    : {cold_s/max(warm_s, 1e-9):6.1f}x")

    idx = warm

    # ---------------- correctness vs astropy brute force ------------------- #
    try:
        import astropy.units as u
        from astropy.coordinates import SkyCoord

        coords = SkyCoord(idx.ra * u.deg, idx.dec * u.deg, frame="icrs")
        print(f"\n== correctness vs astropy SkyCoord.separation ==")
        mismatches = 0
        for radius in radii:
            bad = 0
            for ra, dec in positions[: min(len(positions), 150)]:
                hits = idx.search(ra, dec, radius, top=10 ** 9)
                ref = coords.separation(SkyCoord(ra * u.deg, dec * u.deg)).arcsec
                ref_idx = np.nonzero(ref <= radius)[0]
                if not np.array_equal(np.sort(hits.idx), ref_idx):
                    bad += 1
            mismatches += bad
            print(f"  radius {radius:7.0f}\" : {bad} mismatching query(s)")
        print(f"  total mismatches: {mismatches}")
        astropy_ok = True
    except ImportError:
        print("\n(astropy not installed - skipping correctness check)")
        astropy_ok = False

    # ---------------- index timing ----------------------------------------- #
    print(f"\n== index search ==")
    for radius in radii:
        N = 2000
        t = time.perf_counter()
        hits_total = 0
        for i in range(N):
            ra, dec = positions[i % len(positions)]
            hits_total += idx.search(ra, dec, radius, top=50).idx.size
        dt = (time.perf_counter() - t) / N * 1e6
        print(f"  radius {radius:7.0f}\" : {dt:8.1f} us/query   ({hits_total/max(N,1):.1f} hits avg)")

    # ---------------- astropy brute force timing --------------------------- #
    if astropy_ok:
        print(f"\n== astropy brute force (same scan as the stock server) ==")
        print("   (co-loaded with the index in this process; a clean stock process is faster)")
        for radius in radii[:1]:
            N = 10
            t = time.perf_counter()
            for i in range(N):
                ra, dec = positions[i % len(positions)]
                coords.separation(SkyCoord(ra * u.deg, dec * u.deg)).arcsec
            dt = (time.perf_counter() - t) / N * 1e3
            print(f"  radius {radius:7.0f}\" : {dt:8.1f} ms/query")

    # ---------------- stock module timing ---------------------------------- #
    if args.with_stock:
        sys.path.insert(0, str(HERE.parent))
        try:
            import astap_variable_search_server as stock
            stock.load_catalog(catalog)
            client = stock.app.test_client()
            qs = [f"/search?ra={p[0]}&dec={p[1]}&radius=60" for p in positions[:20]]
            for q in qs[:3]:
                client.get(q)
            t = time.perf_counter()
            for q in qs:
                client.get(q)
            dt = (time.perf_counter() - t) / len(qs) * 1e3
            print(f"\n== stock server HTTP ==")
            print(f"  /search : {dt:8.1f} ms/query")
        except Exception as exc:  # pragma: no cover - diagnostics only
            print(f"\n(stock server harness failed: {exc})")

    # ---------------- HTTP (this server) ----------------------------------- #
    import varstar_fast_server as fast

    fast.INDEX = idx
    fast.LOADED_AT = time.time()
    client = fast.app.test_client()

    qs = [f"/search?ra={p[0]:.6f}&dec={p[1]:.6f}&radius=60" for p in positions[: args.http]]
    for q in qs[:3]:
        client.get(q)
    t = time.perf_counter()
    for q in qs:
        client.get(q)
    http_ms = (time.perf_counter() - t) / len(qs) * 1e3

    batch = {"queries": [{"ra": float(p[0]), "dec": float(p[1])} for p in positions[:500]], "radius": 60}
    t = time.perf_counter()
    resp = client.post("/search_batch", json=batch)
    batch_ms = (time.perf_counter() - t) * 1e3
    assert resp.status_code == 200, resp.data[:200]

    print(f"\n== this server (HTTP, in-process) ==")
    print(f"  GET  /search       : {http_ms:8.2f} ms/query")
    print(f"  POST /search_batch : {batch_ms:8.2f} ms for 500 queries "
          f"({batch_ms/500*1000:.0f} us/query)")

    # ---------------- payload sanity --------------------------------------- #
    one = client.get("/search?ra=88.79&dec=7.41&radius=60").get_json()
    print("\n== sample result ==")
    print(json.dumps(one, indent=2)[:900])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
