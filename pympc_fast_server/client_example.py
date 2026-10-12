"""Client example for the Fast PyMPC server."""

from __future__ import annotations

import requests

BASE_URL = "http://127.0.0.1:5001"


def search_asteroids(ra, dec, epoch, radius=60, max_mag=None, observatory=500):
    params = {"ra": ra, "dec": dec, "epoch": epoch, "radius": radius}
    if max_mag is not None:
        params["max_mag"] = max_mag
    if observatory is not None:
        params["observatory"] = observatory
    r = requests.get(f"{BASE_URL}/search", params=params, timeout=120)
    r.raise_for_status()
    return r.json()


def batch_search(queries, radius=60, max_mag=None, observatory=500):
    payload = {"queries": queries, "radius": radius, "observatory": observatory}
    if max_mag is not None:
        payload["max_mag"] = max_mag
    r = requests.post(f"{BASE_URL}/batch", json=payload, timeout=600)
    r.raise_for_status()
    return r.json()


def warm(epoch):
    r = requests.post(f"{BASE_URL}/warm", params={"epoch": epoch}, timeout=600)
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    result = search_asteroids(ra=88.79, dec=7.41, epoch=60000, radius=300)
    print(f"Found {result['count']} objects in {result['query_time_ms']:.1f} ms")
    for row in result["results"]:
        print(f"  {row['name']:<16} sep={row['separation']:.2f}\" mag={row['mag']}")

    queries = [
        {"ra": 88.79, "dec": 7.41, "epoch": 60000},
        {"ra": 120.5, "dec": -12.3, "epoch": 60000},
        {"ra": 0.0, "dec": 0.0, "epoch": 60000},
    ]
    batch = batch_search(queries, radius=300)
    print(f"\nBatch {batch['total_queries']} queries in {batch['total_time_ms']:.1f} ms")
