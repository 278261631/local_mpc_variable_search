"""Benchmark: stock pympc full scan vs the EphemerisEngine time-window model.

Usage:
    python benchmark.py                 # fast engine only
    python benchmark.py --with-original # also time stock pympc.minor_planet_check
"""

from __future__ import annotations

import argparse
import os
import tempfile
import time

import astropy.units as u
from astropy.time import Time

from fast_engine import EphemerisEngine, DEFAULT_CATALOG_NAME


def stock_query(cat, ra, dec, mjd, radius, max_mag=None, obs=500, chunk_size=0):
    import pympc
    t = time.time()
    out = pympc.minor_planet_check(
        ra=ra * u.deg, dec=dec * u.deg, epoch=Time(mjd, format="mjd"),
        search_radius=radius * u.arcsec, xephem_filepath=cat, max_mag=max_mag,
        include_minor_bodies=True, include_major_bodies=True,
        observatory=obs, chunk_size=chunk_size,
    )
    n = len(out) if out is not None else 0
    return time.time() - t, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=max(1, min(16, os.cpu_count() or 4)))
    ap.add_argument("--window-hours", type=float, default=12.0)
    ap.add_argument("--with-original", action="store_true")
    args = ap.parse_args()

    cat = os.path.join(tempfile.gettempdir(), DEFAULT_CATALOG_NAME)
    if not os.path.exists(cat):
        raise SystemExit(f"catalogue not found at {cat}; run pympc.update_catalogue() first")

    cat_path = cat

    print("== EphemerisEngine ==")
    t = time.time()
    eng = EphemerisEngine(catalog_path=cat_path, workers=args.workers, window_hours=args.window_hours)
    print(f"startup (load+parse+pool): {time.time() - t:.2f} s   objects={eng.n_objects:,}")

    t = time.time()
    r = eng.warm(60000.0)
    print(f"window build (first query): {time.time() - t:.2f} s  skipped={r['skipped']}")

    # same-epoch hot queries
    N = 200
    t = time.time()
    for _ in range(N):
        eng.search(ra=0.0, dec=0.0, epoch_mjd=60000.0, radius_arcsec=300)
    dt = time.time() - t
    print(f"same-window queries: {N} in {dt:.2f} s -> {N/dt:,.0f} qps ({dt/N*1000:.1f} ms each)")

    # cross-epoch queries across a night (the key win)
    import random
    random.seed(1)
    epochs = [60000.0 + random.uniform(0, 0.5) for _ in range(100)]
    t = time.time()
    for ep in epochs:
        eng.search(ra=0.0, dec=0.0, epoch_mjd=ep, radius_arcsec=300)
    dt = time.time() - t
    print(f"cross-epoch queries: 100 in {dt:.2f} s -> {100/dt:,.0f} qps ({dt/100*1000:.1f} ms each)")

    if args.with_original:
        print("\n== stock pympc.minor_planet_check (chunk_size=0) ==")
        for ra, dec, mjd in [(0.0, 0.0, 60000.0), (88.79, 7.41, 60000.0)]:
            dt, n = stock_query(cat_path, ra, dec, mjd, 300)
            print(f"  ra={ra:<7} dec={dec:<7} epoch={mjd}: {dt:.2f} s  count={n}")
        dt, n = stock_query(cat_path, 0.0, 0.0, 60000.0, 300, chunk_size=20000)
        print(f"  stock multiprocessing (chunk=20000): {dt:.2f} s  count={n}")

    eng.close()


if __name__ == "__main__":
    main()
