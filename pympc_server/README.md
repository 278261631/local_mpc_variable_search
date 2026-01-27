# PyMPC Asteroid Search Server

Multi-threaded asteroid cone search service using [pympc](https://github.com/Lyalpha/pympc).

## Requirements

```bash
pip install pympc flask astropy
```

## Quick Start

```bash
# Start the server
python pympc_asteroid_server.py

# Or use the batch file
start_pympc_server.bat
```

## API Endpoints

### GET /health
Health check endpoint.

```bash
curl.exe "http://localhost:5001/health"
```

### GET /info
Server and catalog information.

```bash
curl.exe "http://localhost:5001/info"
```

### GET /search
Asteroid cone search.

Parameters:
- `ra` (required): Right Ascension in degrees
- `dec` (required): Declination in degrees  
- `epoch` (required): Observation epoch as MJD
- `radius` (optional): Search radius in arcseconds (default: 60)
- `max_mag` (optional): Maximum magnitude limit
- `observatory` (optional): Observatory code (default: 500 for geocentric)
- `include_major` (optional): Include major planets (default: true)
- `include_minor` (optional): Include minor bodies (default: true)

```bash
curl.exe "http://localhost:5001/search?ra=88.79&dec=7.41&epoch=60700&radius=300"
```

### POST /batch
Batch search for multiple positions (multi-threaded).

```python
import requests

data = {
    "queries": [
        {"ra": 88.79, "dec": 7.41, "epoch": 60700},
        {"ra": 120.5, "dec": -12.3, "epoch": 60700}
    ],
    "radius": 300,
    "max_mag": 20,
    "observatory": 500
}
response = requests.post("http://localhost:5001/batch", json=data)
print(response.json())
```

### POST /update_catalog
Trigger catalog update from Minor Planet Center.

```bash
curl.exe -X POST "http://localhost:5001/update_catalog"
```

## Command Line Options

```
--port PORT           Server port (default: 5001)
--host HOST           Server host (default: 127.0.0.1)
--workers WORKERS     Number of worker threads (default: 4)
--catalog-dir DIR     Directory for catalog files
--update-catalog      Force update catalog from MPC at startup
--threaded           Enable threaded request handling
```

## Python Client Example

```python
from pympc_server.client_example import search_asteroids, batch_search

# Single search
result = search_asteroids(ra=88.79, dec=7.41, epoch=60700, radius=300)
print(f"Found {result['count']} objects")

# Batch search
queries = [
    {"ra": 88.79, "dec": 7.41, "epoch": 60700},
    {"ra": 120.5, "dec": -12.3, "epoch": 60700},
]
results = batch_search(queries, radius=300)
```

