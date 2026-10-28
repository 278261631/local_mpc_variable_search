"""Python client example for the fast ASTAP Variable Star Search Server."""

from __future__ import annotations

import json

import requests

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 5000


def search_variable_stars(ra, dec, radius=60, max_mag=None, top=50,
                          host=DEFAULT_HOST, port=DEFAULT_PORT):
    """Cone search for variable stars.

    Args:
        ra: Right Ascension in degrees
        dec: Declination in degrees
        radius: Search radius in arcseconds (default 60)
        max_mag: Maximum magnitude limit (optional)
        top: Maximum number of results (default 50)
    """
    params = {"ra": ra, "dec": dec, "radius": radius, "top": top}
    if max_mag is not None:
        params["max_mag"] = max_mag
    response = requests.get(f"http://{host}:{port}/search", params=params)
    response.raise_for_status()
    return response.json()


def search_batch(queries, radius=60, max_mag=None, top=50,
                 host=DEFAULT_HOST, port=DEFAULT_PORT):
    """Search many positions in a single request.

    ``queries`` is a list of dicts with ``ra``/``dec`` (and optionally
    per-query ``radius``/``max_mag``/``top``).
    """
    body = {"queries": queries, "radius": radius, "max_mag": max_mag, "top": top}
    response = requests.post(f"http://{host}:{port}/search_batch", json=body)
    response.raise_for_status()
    return response.json()


def get_server_info(host=DEFAULT_HOST, port=DEFAULT_PORT):
    response = requests.get(f"http://{host}:{port}/info")
    response.raise_for_status()
    return response.json()


def check_health(host=DEFAULT_HOST, port=DEFAULT_PORT):
    response = requests.get(f"http://{host}:{port}/health")
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    print("Fast Variable Star Search Client Example")
    print("=" * 60)

    print("\n1. Health check:")
    print(json.dumps(check_health(), indent=2))

    print("\n2. Server info:")
    print(json.dumps(get_server_info(), indent=2))

    print("\n3. Single cone search (alf_Ori field, r=60\"):")
    print(json.dumps(search_variable_stars(88.79, 7.41, radius=60), indent=2))

    print("\n4. Batch search (3 positions):")
    batch = search_batch([
        {"ra": 88.79, "dec": 7.41},
        {"ra": 279.23, "dec": 38.78},
        {"ra": 79.17, "dec": 45.99},
    ], radius=120)
    print(json.dumps(batch, indent=2)[:1200])
