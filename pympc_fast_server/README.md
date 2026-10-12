# Fast PyMPC Asteroid Search Server

An API-compatible replacement for `pympc_server/pympc_asteroid_server.py`.

The stock server re-scans and re-propagates the entire ~1.57 M object catalogue
for **every** request (~5.5 s/query), and its threads give no speed-up because
the hot loop holds the GIL. This server uses a **time-window ephemeris**
(`EphemerisEngine`):

1. **Parse once** – the xephem catalogue is parsed into libastro bodies once per
   worker process (parsing, not propagation, is the dominant per-object cost).
2. **Propagate once per window** – for each time window the whole catalogue is
   propagated once into base position `u0`, sky velocity `v` and sky
   acceleration `a` (a live process pool, one catalogue slice per worker).
3. **Extrapolate per query** – a query at *any* epoch inside the window scores
   every object with a vectorised 2nd-order Taylor expansion (three
   matrix-vector products, no Python loop), selects a small candidate set, and
   **re-computes those candidates exactly** with libastro.
4. **Exact results** – returned astrometry is identical to
   `pympc.minor_planet_check`; the extrapolation is only used for candidate
   retrieval.

## Results (16 logical cores, 1.57 M objects)

Measured versus stock `pympc.minor_planet_check` (chunk_size=0) at 5.4–5.6 s/query:

| Workload | Stock | This server |
|---|---|---|
| New window build (once) | — | **~1.0 s** |
| Query at a new epoch in-window | 5.5 s | **~10–20 ms** |
| Query at a cached epoch | 5.5 s | **~10 ms** |
| Correctness | — | exact (25/25 random cases) |

Extrapolation accuracy for the whole population over a 12 h window: p99.9 < 0.1″
(quadratic), with only a handful of very fast NEOs handled by an inflated
candidate margin.

## Install

```bash
pip install -r requirements.txt
```

## Quick start

```bash
python pympc_fast_server.py --workers 8
# or
start_pympc_fast_server.bat
```

The catalogue is looked up in the system temp dir (same file the stock server
uses). Use `--catalog <path>` / `--catalog-dir <dir>` to override, and
`--update-catalog` / `--update-only` to (re)download from the MPC.

## API (identical to the stock server)

| Endpoint | Description |
|---|---|
| `GET /health` | liveness / object count |
| `GET /info` | catalogue version, workers, cached windows |
| `GET /search?ra=&dec=&epoch=&radius=&max_mag=&observatory=` | cone search |
| `POST /batch` | `{"queries":[...], ...}` multi-position search |
| `POST /warm?epoch=<mjd>` | pre-build the ephemeris window |
| `POST /update_catalog` | download the MPC catalogue **and hot-rebuild** |

```bash
curl.exe "http://127.0.0.1:5001/search?ra=88.79&dec=7.41&epoch=60000&radius=300"
curl.exe -X POST "http://127.0.0.1:5001/warm?epoch=60000"
```

## Options

```
--port 5001            Server port (default 5001, same as the stock server)
--host 127.0.0.1
--workers N            Worker processes / catalogue slices (default: min(16, ncpu))
--window-hours H       Ephemeris validity window around each base epoch (default 12)
--base-cache N         Number of ephemeris windows kept in memory (default 4)
--margin-arcsec S      Candidate-search inflation for completeness (default 900)
--prewarm MJD          Pre-build a window at startup (repeatable)
--catalog PATH         Explicit mpcorb_xephem.csv path
--catalog-dir DIR      Directory holding the catalogue
--update-catalog       Re-download the MPC catalogue before starting
--update-only          Download the catalogue and exit
--log-level LEVEL      INFO (default), DEBUG, WARNING...
```

## Logging & timing

The server logs every ephemeris-window build and every query to the console:

```
[window] building     idx=1477911 center=2023-02-24 23:05 (mjd 59999.9624, decimalyear 2023.150582) ...
[window] built in 1451 ms  idx=1477911 objects=1571421 skipped=0 cached=1/4
[query] ra=88.79000 dec=7.41000 epoch=60000.00000 radius=300.0 max_mag=None -> 1 hit(s) in 1726.7 ms (candidates=9, window built +1451 ms build)
[query] ra=0.00000 dec=0.00000 epoch=60000.00000 radius=300.0 max_mag=None -> 9 hit(s) in 12.9 ms (candidates=166, window cached)
```

* A **new window** costs ~1.5 s once; subsequent queries in the same window are ~10 ms
  (`window cached`).
* `--log-level DEBUG` also logs window cache **hits** and LRU evictions.
* `/search` responses include `query_time_ms`, `window_built`, `window_build_ms`,
  `candidates`, and send an HTTP `Server-Timing` header (`search;dur=...`,
  `window-build;dur=...`) for use in browser devtools.

## Benchmark

```bash
python benchmark.py --with-original
```

## Design notes / tuning

* **Window length** trades accuracy for rebuild frequency. 12 h covers a survey
  night; shorter windows improve extrapolation accuracy for fast movers.
* **`--margin-arcsec`** guarantees completeness: candidates are selected within
  `radius + margin` and then refined exactly. It must exceed the largest
  extrapolation residual over the window (≈857″ over 10 h for the fastest NEO);
  the default 900″ is a safe value.
* **Daily catalogue updates**: the ephemeris windows are derived at runtime from
  the current catalogue (memory only). When the MPC catalogue changes the engine
  is rebuilt (~1–2 s) and `catalog_version` (path/size/mtime) is refreshed. No
  per-day data is persisted, so daily updates cost nothing in storage.
* **Batch / same-epoch** workloads benefit most: a whole night of cutouts is
  answered from a single ~1 s window build.
