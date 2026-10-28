# Fast Variable Star Search Server

API-compatible replacement for the repository's `astap_variable_search_server.py`.

The stock server runs an `astropy` `SkyCoord.separation` over the **whole**
catalogue on every request (≈ 72 ms for 1.11 M stars) and then copies the entire
DataFrame (≈ 46 ms) just to filter it, for ≈ 121 ms per query. This server keeps
the catalogue sorted by declination and answers each query with two binary
searches plus an exact spherical-distance pass over the few hundred rows inside
the declination slab:

```
|dec - dec0| <= angular distance      (always true for a cone search)
```

## Results (1,115,118 stars, `variable_stars_15.csv`)

| Workload | Stock server | This server |
|---|---|---|
| Startup, first run (parse + build index) | 4.0 s | **1.1 s** |
| Startup, cached index (`.npz`) | 4.0 s | **0.10 s** |
| Query, radius 60″ | 121 ms | **0.27 ms** HTTP / **0.030 ms** compute |
| Query, radius 300″ | 128 ms | **0.07 ms** compute |
| Query, radius 1200″ | 145 ms | **0.18 ms** compute |
| Query, radius 1° + `max_mag` | 121 ms | **0.6 ms** compute |
| 500-position batch | ~60 s | **5 ms** |
| RSS after load | 902 MB (peak 1.24 GB) | **130 MB** (index 90 MB) |
| Correctness | — | exact (600 random queries, 0 mismatches) |

Measured against the stock module on the same machine (Windows, Python 3.10).
Startup numbers use the 15th-magnitude catalogue; the 11th-magnitude catalogue
(140 k stars) builds in ≈ 0.2 s and loads from cache in ≈ 0.02 s.

## How it works

1. **Parse once** – the ASTAP CSV is turned into flat numpy arrays (`ra`, `dec`)
   plus the raw label text as one byte blob with an offset table. No per-row
   dicts / Python string objects, which is what made the stock loader peak at
   1.2 GB, and no label parsing: `name` / magnitudes / period are only decoded
   for the stars a query actually touches.
2. **Sort once** – `order = argsort(dec)`; `dec_sorted` makes the slab a pair of
   `searchsorted` calls. This is an `int32` permutation, ~4.5 MB.
3. **Score exactly, cheaply** – candidates inside the slab are scored with the
   haversine formula (accurate at arbitrarily small angles, unlike `arccos` of a
   dot product), then filtered by `max_mag` and cut to `top` with `argpartition`.
4. **Labels are lazy** – decoding and label parsing happen only for the handful
   of stars that survive the distance filter, so the build stays at ~1.1 s and
   a cached start at ~0.1 s.

The label parser follows `astap_variable_search_server._parse_label` byte for
byte, including its quirks (`11.78g-(0.27)g` yields no magnitudes because `g`
is not in the stripped character set), so `name` / `mag_min` / `mag_max` /
`period` are identical to the stock server.

## Install

```bash
pip install -r requirements.txt
```

`astropy` is only needed by `benchmark.py` for the correctness cross-check; the
server itself needs `flask` + `numpy`.

## Quick start

```bash
python varstar_fast_server.py                       # port 5000, 15th-mag catalogue
start_varstar_fast_server.bat                       # same, foreground
start_varstar_fast_server_new_window.bat            # same, own console window
```

The stock server also uses port 5000. Run the new one on another port if both
are needed:

```bat
start_varstar_fast_server_new_window.bat 5003
start_varstar_fast_server_new_window.bat 5003 ..\data\variable_stars_13.csv
```

## API (identical to the stock server, plus extras)

| Endpoint | Description |
|---|---|
| `GET /health` | liveness / object count |
| `GET /info` | catalogue, index, cache and memory stats |
| `GET /search?ra=&dec=&radius=&max_mag=&top=` | cone search |
| `POST /search_batch` | `{"queries":[...], "radius":.., "max_mag":.., "top":..}` |
| `POST /reload?rebuild=1` | reload the catalogue (optionally rebuild the index) |

```bash
curl.exe "http://127.0.0.1:5000/search?ra=88.79&dec=7.41&radius=60"
curl.exe "http://127.0.0.1:5000/search?ra=88.79&dec=7.41&radius=300&max_mag=8&top=20"
curl.exe -X POST "http://127.0.0.1:5000/search_batch" -H "Content-Type: application/json" ^
  -d "{\"queries\":[{\"ra\":88.79,\"dec\":7.41},{\"ra\":279.23,\"dec\":38.78}],\"radius\":120}"
```

`/search` returns the stock JSON schema (`query`, `count`, `query_time_ms`,
`results`) plus a `candidates` field and a `Server-Timing` header.

`/search_batch` returns `{count, query_time_ms, per_query_ms, results:[...]}`,
where each entry is a normal `/search` body.

## Options

```
--catalog PATH       ASTAP catalogue (default: data/variable_stars_15.csv)
--port 5000          Server port
--host 127.0.0.1
--cache-dir DIR      Where to keep the .npz index cache (default: system temp)
--no-cache           Parse the catalogue on every start, never touch the cache
--rebuild-cache      Ignore an existing cache and rebuild it
--server flask       flask (default) or waitress (pip install waitress, threads)
--log-level INFO     INFO (default), DEBUG, WARNING ...
```

## Index cache

The first start parses the CSV (≈ 1.1 s) and writes an `.npz` cache to the
system temp directory, keyed by catalogue name, size, mtime and cache version:

```
%TEMP%\varstar_fast_server\variable_stars_15-<size>-<mtime>-v2.npz
```

Subsequent starts load it in ≈ 0.1 s. Stale caches (different size/mtime/version)
are pruned automatically, and a corrupt cache is detected and rebuilt. Delete it,
pass `--rebuild-cache` or edit the CSV to force a rebuild.

## Logging & timing

```
[index] cache hit: variable_stars_15-...-v2.npz (95 ms)
[index] ready in 0.10 s  objects=1,115,118  cache_hit=True  memory=90 MB
[request] GET /search from 127.0.0.1  query=ra=88.79&dec=7.41&radius=60
[query] ra=88.79000 dec=7.41000 radius=60.0 max_mag=None -> 1 hit(s) in 0.030 ms (candidates=138)
```

`[query]` is logged at `DEBUG`; set `--log-level DEBUG` to see it. Responses
include `query_time_ms`, `candidates` and the `Server-Timing` header
(`search;dur=...`) for browser devtools.

## Benchmark

```bash
python benchmark.py                     # startup, correctness, timings
python benchmark.py --with-stock        # also time the stock server module
python benchmark.py --queries 500 --radii 60,300,1200
```

`benchmark.py` validates the index against astropy brute force at several
radii, reports build-vs-cache startup, per-query cost, batch throughput and a
sample response.

## Notes and limits

- **Exactness**: the returned set is identical to the stock server. Two stars at
  *exactly* the same separation may appear in a different order (the stock uses
  pandas' unstable `sort_values`; this server uses a stable sort).
- `separation_arcsec` differs from astropy in the last few 1e-11″ (different
  formula), which only matters for a star sitting exactly on the radius edge.
- Query cost grows with radius because the slab grows: 60″ touches ~130 rows,
  1° touches ~12 k, 10° touches ~110 k. A 1° query with `max_mag` costs ~0.6 ms
  because the stars inside the cone must have their labels parsed; 10° in a
  dense field costs a few ms. That is still orders of magnitude below a full
  scan; only pathological whole-sky radii need a hierarchical (HEALPix) index.
- Memory after load is ~90 MB of index (most of it the raw label text) instead
  of ~900 MB; the whole Python process sits at ~130 MB.
- `benchmark.py --with-stock` keeps the stock DataFrame **and** this index in the
  same process, so its stock/astropy timings are inflated (≈ 190 ms vs the
  ≈ 121 ms measured in a clean process).
