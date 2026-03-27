# HIP Star Search Server

Local cone search web service for HIP star catalogs.

## Features

- Fast cone search using pre-loaded coordinates
- HTTP JSON API (`/health`, `/info`, `/search`)
- Optional magnitude filtering (`max_mag`)
- Compatible query style with existing services in this repository

## Requirements

```bash
pip install flask pandas numpy astropy requests
```

## Catalog Format

Place your HIP catalog at `data/hip_catalog.csv` (or pass `--catalog`).

Required columns (case-insensitive, common aliases supported):
- RA: `ra` / `ra_deg` / `radeg`
- DEC: `dec` / `dec_deg` / `dedeg`

Optional columns:
- HIP id: `hip` / `hip_id` / `hipid` / `id`
- Magnitude: `mag` / `vmag` / `v_mag` / `hp_mag`

## Quick Start

```bash
python hip_server/hip_search_server.py --catalog data/hip_catalog.csv --port 5002
```

Windows:

```bat
hip_server\start_hip_server.bat
```

## API

### GET /health

```bash
curl.exe "http://localhost:5002/health"
```

### GET /info

```bash
curl.exe "http://localhost:5002/info"
```

### GET /search

Parameters:
- `ra` (required): right ascension in degrees
- `dec` (required): declination in degrees
- `radius` (optional): search radius in arcseconds, default `60`
- `max_mag` (optional): magnitude limit
- `top` (optional): maximum result count, default `50`

Example:

```bash
curl.exe "http://localhost:5002/search?ra=88.79&dec=7.41&radius=120&max_mag=8&top=10"
```

## Test Script

```bat
hip_server\test_hip_server.bat
```

## Python Client Example

```bash
python hip_server/client_example.py
```

