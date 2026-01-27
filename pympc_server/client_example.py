"""Python client example for PyMPC Asteroid Search Server"""

import requests
import json


def search_asteroids(ra, dec, epoch, radius=60, max_mag=None, observatory=500,
                     include_major=True, include_minor=True,
                     host="localhost", port=5001):
    """Search for asteroids using the web service.
    
    Args:
        ra: Right Ascension in degrees
        dec: Declination in degrees
        epoch: Observation epoch as MJD
        radius: Search radius in arcseconds (default: 60)
        max_mag: Maximum magnitude limit (optional)
        observatory: Observatory code (default: 500 for geocentric)
        include_major: Include major planets (default: True)
        include_minor: Include minor bodies (default: True)
        host: Server host (default: localhost)
        port: Server port (default: 5001)
    
    Returns:
        dict: JSON response with query results
    """
    url = f"http://{host}:{port}/search"
    params = {
        "ra": ra,
        "dec": dec,
        "epoch": epoch,
        "radius": radius,
        "observatory": observatory,
        "include_major": str(include_major).lower(),
        "include_minor": str(include_minor).lower(),
    }
    if max_mag is not None:
        params["max_mag"] = max_mag
    
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()


def batch_search(queries, radius=60, max_mag=None, observatory=500,
                 include_major=True, include_minor=True,
                 host="localhost", port=5001):
    """Batch search for asteroids at multiple positions.
    
    Args:
        queries: List of dicts with ra, dec, epoch keys
        radius: Search radius in arcseconds (default: 60)
        max_mag: Maximum magnitude limit (optional)
        observatory: Observatory code (default: 500)
        host: Server host (default: localhost)
        port: Server port (default: 5001)
    
    Returns:
        dict: JSON response with batch results
    """
    url = f"http://{host}:{port}/batch"
    data = {
        "queries": queries,
        "radius": radius,
        "observatory": observatory,
        "include_major": include_major,
        "include_minor": include_minor,
    }
    if max_mag is not None:
        data["max_mag"] = max_mag
    
    response = requests.post(url, json=data)
    response.raise_for_status()
    return response.json()


def get_server_info(host="localhost", port=5001):
    """Get server and catalog information."""
    url = f"http://{host}:{port}/info"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()


def check_health(host="localhost", port=5001):
    """Check server health."""
    url = f"http://{host}:{port}/health"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()


def update_catalog(host="localhost", port=5001):
    """Trigger catalog update from MPC."""
    url = f"http://{host}:{port}/update_catalog"
    response = requests.post(url)
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    from astropy.time import Time
    
    print("PyMPC Asteroid Search Client Example")
    print("=" * 60)
    
    # Get current MJD
    now_mjd = Time.now().mjd
    print(f"\nCurrent MJD: {now_mjd:.4f}")
    
    # Check server health
    print("\n1. Health check:")
    try:
        health = check_health()
        print(json.dumps(health, indent=2))
    except Exception as e:
        print(f"Error: {e}")
        print("Make sure the server is running!")
        exit(1)
    
    # Get server info
    print("\n2. Server info:")
    info = get_server_info()
    print(json.dumps(info, indent=2))
    
    # Search near a position
    print(f"\n3. Search at RA=88.79, DEC=7.41, epoch={now_mjd:.2f}:")
    result = search_asteroids(ra=88.79, dec=7.41, epoch=now_mjd, radius=300)
    print(f"Found {result['count']} objects in {result['query_time_ms']:.2f}ms")
    if result.get('results'):
        for obj in result['results'][:5]:
            print(f"  - {obj.get('name', 'unknown')}: "
                  f"sep={obj.get('separation', 'N/A'):.2f}\" "
                  f"mag={obj.get('mag', 'N/A')}")
    
    # Batch search example
    print("\n4. Batch search (3 positions):")
    queries = [
        {"ra": 88.79, "dec": 7.41, "epoch": now_mjd},
        {"ra": 120.5, "dec": -12.3, "epoch": now_mjd},
        {"ra": 279.23, "dec": 38.78, "epoch": now_mjd},
    ]
    batch_result = batch_search(queries, radius=300)
    print(f"Total time: {batch_result['total_time_ms']:.2f}ms")
    for r in batch_result['results']:
        count = r.get('count', 0)
        qtime = r.get('query_time_ms', 0)
        print(f"  Query {r['index']}: {count} objects, {qtime:.2f}ms")

