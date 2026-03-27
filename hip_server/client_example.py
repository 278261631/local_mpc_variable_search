"""Python client example for HIP Star Search Server."""

import json
import requests


def search_hip_stars(ra, dec, radius=60, max_mag=None, top=50, host="localhost", port=5002):
    """Search HIP stars using the web service."""
    url = f"http://{host}:{port}/search"
    params = {
        "ra": ra,
        "dec": dec,
        "radius": radius,
        "top": top,
    }
    if max_mag is not None:
        params["max_mag"] = max_mag

    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()


def get_server_info(host="localhost", port=5002):
    """Get server and catalog information."""
    response = requests.get(f"http://{host}:{port}/info")
    response.raise_for_status()
    return response.json()


def check_health(host="localhost", port=5002):
    """Check server health."""
    response = requests.get(f"http://{host}:{port}/health")
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    print("HIP Star Search Client Example")
    print("=" * 60)

    print("\n1. Health check:")
    health = check_health()
    print(json.dumps(health, indent=2))

    print("\n2. Server info:")
    info = get_server_info()
    print(json.dumps(info, indent=2))

    print("\n3. Search near Betelgeuse (RA=88.79, DEC=7.41):")
    result = search_hip_stars(ra=88.79, dec=7.41, radius=120, top=5)
    print(f"Found {result['count']} stars in {result['query_time_ms']:.2f}ms")
    for star in result["results"]:
        print(
            f"  - HIP {star.get('hip')}: "
            f"mag={star.get('mag')} sep={star.get('separation_arcsec'):.2f}\""
        )

