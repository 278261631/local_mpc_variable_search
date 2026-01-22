"""Python client example for ASTAP Variable Star Search Server"""

import requests
import json


def search_variable_stars(ra, dec, radius=60, max_mag=None, top=50, host="localhost", port=5000):
    """Search for variable stars using the web service.
    
    Args:
        ra: Right Ascension in degrees
        dec: Declination in degrees
        radius: Search radius in arcseconds (default: 60)
        max_mag: Maximum magnitude limit (optional)
        top: Maximum number of results (default: 50)
        host: Server host (default: localhost)
        port: Server port (default: 5000)
    
    Returns:
        dict: JSON response with query results
    """
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


def get_server_info(host="localhost", port=5000):
    """Get server and catalog information."""
    url = f"http://{host}:{port}/info"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()


def check_health(host="localhost", port=5000):
    """Check server health."""
    url = f"http://{host}:{port}/health"
    response = requests.get(url)
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    # Example usage
    print("ASTAP Variable Star Search Client Example")
    print("=" * 60)
    
    # Check server health
    print("\n1. Health check:")
    health = check_health()
    print(json.dumps(health, indent=2))
    
    # Get server info
    print("\n2. Server info:")
    info = get_server_info()
    print(json.dumps(info, indent=2))
    
    # Search for Betelgeuse
    print("\n3. Search Betelgeuse (RA=88.79, DEC=7.41):")
    result = search_variable_stars(ra=88.79, dec=7.41, radius=60)
    print(f"Found {result['count']} stars in {result['query_time_ms']:.2f}ms")
    for star in result['results']:
        print(f"  - {star['name']}: mag {star['mag_min']}-{star['mag_max']}, "
              f"sep={star['separation_arcsec']:.2f}\"")
    
    # Search for Vega
    print("\n4. Search Vega (RA=279.23, DEC=38.78):")
    result = search_variable_stars(ra=279.23, dec=38.78, radius=120)
    print(f"Found {result['count']} stars in {result['query_time_ms']:.2f}ms")
    for star in result['results']:
        print(f"  - {star['name']}: sep={star['separation_arcsec']:.2f}\"")
    
    # Wide search with magnitude limit
    print("\n5. Wide search with magnitude limit:")
    result = search_variable_stars(ra=120.5, dec=-12.3, radius=3600, max_mag=10, top=5)
    print(f"Found {result['count']} stars in {result['query_time_ms']:.2f}ms")
    for star in result['results']:
        mag_str = f"{star['mag_min']}-{star['mag_max']}" if star['mag_max'] else "N/A"
        print(f"  - {star['name']}: mag {mag_str}, sep={star['separation_arcsec']:.2f}\"")

