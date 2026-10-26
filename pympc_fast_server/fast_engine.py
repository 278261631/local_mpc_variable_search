"""Fast PyMPC cone-search engines.

Two engines live here:

* ``FastEngine`` – propagates the whole catalogue once per **epoch** and caches a
  KD-tree snapshot per epoch.  Great when many queries share an epoch.
* ``EphemerisEngine`` (used by the server) – propagates the catalogue once per
  **time window** into base position ``u0``, sky velocity ``v`` and sky
  acceleration ``a``.  Any epoch inside the window is then answered by a
  vectorised second-order Taylor expansion plus exact refinement of the handful
  of candidates.  This removes the per-epoch propagation from the query path.

Profiling the 1.57 M object catalogue shows the per-object cost is dominated by:

  * ``ephem.readdb``  (parsing the xephem string)          ~1.3 s / full scan
  * ``ephem.separation`` (angular distance to the target)  ~2.5 s / full scan
  * ``ephem.compute`` (orbit propagation to the epoch)     ~0.13 s / full scan
  * reading astrometric ``a_ra``/``a_dec``                  ~2 s / full scan

All of those costs are paid again for every query in the stock implementation,
and the Python loop holds the GIL so threads give no speed-up at all.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
import math
import logging
from collections import OrderedDict
from multiprocessing import get_context
from typing import Optional, Union

import numpy as np

import ephem

logger = logging.getLogger("pympc_fast")

RADTODEG = 180.0 / np.pi
DEGTORAD = np.pi / 180.0
SOLAR_PARALLAX_ARCSEC = 8.794143
DEFAULT_CATALOG_NAME = "mpcorb_xephem.csv"


def _decimal_year(epoch_mjd: float) -> float:
    from astropy.time import Time

    return float(Time(epoch_mjd, format="mjd").decimalyear)


def _mjd_from_decimalyear(dy: float) -> float:
    from astropy.time import Time

    return float(Time(dy, format="decimalyear").mjd)


def _safe_utc(mjd: float) -> str:
    """Format MJD as UTC without exploding on pre-1970 / out-of-range dates."""
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.gmtime((float(mjd) - 40587.0) * 86400.0))
    except (OSError, OverflowError, ValueError):
        return "?"

_cKDTree = None
_scipy_checked = False


def _kdtree_cls():
    global _cKDTree, _scipy_checked
    if not _scipy_checked:
        _scipy_checked = True
        try:
            from scipy.spatial import cKDTree

            _cKDTree = cKDTree
        except Exception:
            _cKDTree = None
    return _cKDTree


def _pympc_impl():
    import pympc.pympc as impl

    return impl


def _observatory_data(observatory):
    from pympc.utils import get_observatory_data

    return get_observatory_data(observatory)


def _unit_vectors(ra, dec):
    cd = np.cos(dec)
    return np.stack([cd * np.cos(ra), cd * np.sin(ra), np.sin(dec)], axis=-1)


def _parse_name(line: bytes) -> str:
    s = line.decode("utf-8", "replace")
    if not s:
        return ""
    if s[0] == '"':
        end = s.find('"', 1)
        if end > 0:
            return s[1:end]
    comma = s.find(",")
    return s if comma < 0 else s[:comma]


def _worker_main(wid, catalog_path, start, end, task_q, result_q):
    import numpy as np
    import ephem

    with open(catalog_path, "rb") as f:
        f.seek(start)
        chunk = f.read(end - start)

    bodies = []
    for raw in chunk.split(b"\n"):
        line = raw.strip()
        if not line:
            continue
        try:
            bodies.append(ephem.readdb(line.decode("utf-8", "replace")))
        except Exception:
            bodies.append(None)

    result_q.put(("ready", wid, len(bodies)))

    while True:
        task = task_q.get()
        if task is None:
            break
        req_id, kind, params = task
        n = len(bodies)

        if kind == "base":
            decimalyear, eps = params
            date0 = ephem.date(str(decimalyear))
            datep = ephem.date(str(decimalyear + eps))
            datem = ephem.date(str(decimalyear - eps))

            def _pass(dt_):
                ra = np.full(n, np.nan, dtype=np.float64)
                dec = np.full(n, np.nan, dtype=np.float64)
                for k, b in enumerate(bodies):
                    if b is None:
                        continue
                    try:
                        b.compute(dt_)
                        ra[k] = float(b.a_ra)
                        dec[k] = float(b.a_dec)
                    except Exception:
                        pass
                return ra, dec

            ram, decm = _pass(datem)
            ra0, dec0 = _pass(date0)
            rap, decp = _pass(datep)

            def _unit(ra, dec):
                cd = np.cos(dec)
                return np.stack([cd * np.cos(ra), cd * np.sin(ra), np.sin(dec)], axis=-1)

            um = _unit(ram, decm)
            u0d = _unit(ra0, dec0)
            up = _unit(rap, decp)
            u0 = u0d.astype(np.float32)
            vv = ((up - um) / (2.0 * eps)).astype(np.float32)
            aa = ((up - 2.0 * u0d + um) / (eps * eps)).astype(np.float32)
            bad = int(np.count_nonzero(~np.isfinite(u0[:, 0])))
            result_q.put(("base", req_id, wid, u0, vv, aa, bad))
            continue

        decimalyear = params[0]
        date = ephem.date(str(decimalyear))
        ra_arr = np.empty(n, dtype=np.float64)
        dec_arr = np.empty(n, dtype=np.float64)
        mag = np.empty(n, dtype=np.float32)
        dist = np.empty(n, dtype=np.float64)
        bad = 0
        for k, b in enumerate(bodies):
            if b is None:
                ra_arr[k] = np.nan
                dec_arr[k] = np.nan
                mag[k] = np.nan
                dist[k] = np.nan
                bad += 1
                continue
            try:
                b.compute(date)
                ra_arr[k] = float(b.a_ra)
                dec_arr[k] = float(b.a_dec)
                mag[k] = float(b.mag)
                dist[k] = float(b.earth_distance)
            except Exception:
                ra_arr[k] = np.nan
                dec_arr[k] = np.nan
                mag[k] = np.nan
                dist[k] = np.nan
                bad += 1

        result_q.put(("positions", req_id, wid, ra_arr, dec_arr, mag, dist, bad))


class WorkerPool:
    """Persistent worker processes, one contiguous catalogue slice each."""

    def __init__(self, catalog_path: str, n_workers: int, slices, startup_timeout: float = 300.0):
        self.n = n_workers
        self._ctx = get_context("spawn")
        self._task_q = [self._ctx.Queue() for _ in range(n_workers)]
        self._result_q = self._ctx.Queue()
        self._procs = []
        self._counts = [0] * n_workers
        for wid, (start, end) in enumerate(slices):
            p = self._ctx.Process(
                target=_worker_main,
                args=(wid, catalog_path, start, end, self._task_q[wid], self._result_q),
                daemon=True,
                name=f"pympc-fast-worker-{wid}",
            )
            p.start()
            self._procs.append(p)
        self._wait_ready(startup_timeout)

    def _wait_ready(self, timeout: float):
        deadline = time.time() + timeout
        got = set()
        while len(got) < self.n:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError("worker pool failed to become ready in time")
            try:
                msg = self._result_q.get(timeout=remaining)
            except Exception as exc:  # queue.Empty
                raise TimeoutError("worker pool failed to become ready in time") from exc
            if msg[0] == "ready":
                got.add(msg[1])
                self._counts[msg[1]] = msg[2]

    def positions(self, req_id: int, decimalyear: float, timeout: float = 300.0):
        for q in self._task_q:
            q.put((req_id, "positions", (decimalyear,)))
        parts = self._collect("positions", req_id, timeout)
        ra = np.concatenate([parts[k][3] for k in range(self.n)])
        dec = np.concatenate([parts[k][4] for k in range(self.n)])
        mag = np.concatenate([parts[k][5] for k in range(self.n)])
        dist = np.concatenate([parts[k][6] for k in range(self.n)])
        bad = sum(parts[k][7] for k in range(self.n))
        return ra, dec, mag, dist, bad

    def base(self, req_id: int, decimalyear: float, eps: float, timeout: float = 300.0):
        for q in self._task_q:
            q.put((req_id, "base", (decimalyear, eps)))
        parts = self._collect("base", req_id, timeout)
        u0 = np.concatenate([parts[k][3] for k in range(self.n)])
        v = np.concatenate([parts[k][4] for k in range(self.n)])
        a = np.concatenate([parts[k][5] for k in range(self.n)])
        bad = sum(parts[k][6] for k in range(self.n))
        return u0, v, a, bad

    def _collect(self, kind, req_id, timeout):
        parts = [None] * self.n
        got = 0
        deadline = time.time() + timeout
        while got < self.n:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError(f"{kind} build timed out")
            try:
                msg = self._result_q.get(timeout=remaining)
            except Exception as exc:
                raise TimeoutError(f"{kind} build timed out") from exc
            if msg[0] == kind and msg[1] == req_id:
                parts[msg[2]] = msg
                got += 1
        return parts

    def close(self):
        for q in self._task_q:
            try:
                q.put(None)
            except Exception:
                pass
        for p in self._procs:
            p.join(timeout=5)
            if p.is_alive():
                p.terminate()


class EpochIndex:
    __slots__ = ("decimalyear", "gidx", "V", "ra", "dec", "mag", "dist", "tree", "skipped")

    def __init__(self, decimalyear, gidx, ra, dec, mag, dist, skipped):
        self.decimalyear = decimalyear
        self.gidx = gidx
        self.ra = ra
        self.dec = dec
        self.V = _unit_vectors(ra, dec).astype(np.float32)
        self.mag = mag
        self.dist = dist
        self.tree = None
        self.skipped = skipped

    def build_tree(self):
        cls = _kdtree_cls()
        if self.tree is None and cls is not None:
            self.tree = cls(self.V)


def _sep_arcsec_rad(ra1_rad, dec1_rad, ra2_rad, dec2_rad):
    return 3600.0 * RADTODEG * float(
        ephem.separation((ra1_rad, dec1_rad), (ra2_rad, dec2_rad))
    )


class FastEngine:
    def __init__(
        self,
        catalog_path: Optional[str] = None,
        workers: int = 8,
        cache_size: int = 8,
        use_kdtree: bool = True,
    ):
        self.catalog_path = catalog_path or os.path.join(
            tempfile.gettempdir(), DEFAULT_CATALOG_NAME
        )
        if not os.path.exists(self.catalog_path):
            raise FileNotFoundError(
                f"xephem catalogue not found at {self.catalog_path}. "
                "Run pympc.update_catalogue() first."
            )

        with open(self.catalog_path, "rb") as f:
            data = f.read()

        buf = np.frombuffer(data, dtype=np.uint8)
        nl = np.flatnonzero(buf == 10).astype(np.int64)
        bounds = np.concatenate((np.zeros(1, dtype=np.int64), nl + 1, [len(data)]))
        if len(bounds) >= 2 and bounds[-2] == bounds[-1]:
            bounds = bounds[:-1]

        self._data = data
        self._bounds = bounds
        n = int(len(bounds) - 1)
        if n <= 0:
            raise RuntimeError(f"catalogue at {self.catalog_path} appears to be empty")

        self.n_objects = n
        self.use_kdtree = use_kdtree and _kdtree_cls() is not None

        n_workers = max(1, min(workers, n))
        step = n // n_workers
        line_bounds = [i * step for i in range(n_workers)] + [n]
        self._slices = [(int(bounds[line_bounds[k]]), int(bounds[line_bounds[k + 1]]))
                        for k in range(n_workers)]
        self._slice_lines = line_bounds

        self.pool = WorkerPool(self.catalog_path, n_workers, self._slices)
        if sum(self.pool._counts) != n:
            raise RuntimeError(
                f"worker slice counts ({sum(self.pool._counts)}) do not match "
                f"catalogue length ({n})"
            )

        self.cache_size = max(1, cache_size)
        self._cache: "OrderedDict[float, EpochIndex]" = OrderedDict()
        self._lock = threading.Lock()
        self._req = 0
        self._obs_cache = {}
        self._impl = _pympc_impl()

    def _line_bytes(self, g: int) -> bytes:
        return self._data[self._bounds[g]:self._bounds[g + 1]].strip()

    def _observatory(self, observatory):
        key = str(observatory)
        if key in self._obs_cache:
            return self._obs_cache[key]
        try:
            lon, rc, rs = _observatory_data(observatory)
        except Exception:
            lon, rc, rs = 0.0, 0.0, 0.0
        self._obs_cache[key] = (lon, rc, rs)
        return lon, rc, rs

    def _build_index(self, decimalyear: float) -> EpochIndex:
        self._req += 1
        ra, dec, mag, dist, bad = self.pool.positions(self._req, decimalyear)
        valid = ~np.isnan(ra)
        gidx = np.nonzero(valid)[0]
        idx = EpochIndex(decimalyear, gidx, ra[valid], dec[valid], mag[valid], dist[valid], bad)
        idx.build_tree()
        return idx

    def get_index(self, epoch_mjd: float) -> EpochIndex:
        dy = round(_decimal_year(epoch_mjd), 9)
        with self._lock:
            idx = self._cache.get(dy)
            if idx is not None:
                self._cache.move_to_end(dy)
                return idx
            idx = self._build_index(dy)
            self._cache[dy] = idx
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
            return idx

    def warm(self, epoch_mjd: float) -> dict:
        start = time.time()
        idx = self.get_index(epoch_mjd)
        return {
            "decimalyear": idx.decimalyear,
            "objects": int(len(idx.gidx)),
            "skipped": int(idx.skipped),
            "time_ms": (time.time() - start) * 1000.0,
        }

    def search(
        self,
        ra: float,
        dec: float,
        epoch_mjd: float,
        radius_arcsec: float = 60.0,
        max_mag: Optional[float] = None,
        observatory: Union[int, str, tuple] = 500,
        include_major: bool = True,
        include_minor: bool = True,
    ) -> dict:
        start = time.time()
        try:
            idx = self.get_index(epoch_mjd)
        except Exception as exc:
            return {"success": False, "error": str(exc), "query_time_ms": (time.time() - start) * 1000.0}

        lon, rho_cos_phi, rho_sin_phi = self._observatory(observatory)
        topocentric = any((lon, rho_cos_phi, rho_sin_phi))
        buffer = SOLAR_PARALLAX_ARCSEC * 3 if topocentric else 0.0
        impl = self._impl if (topocentric or include_major) else None

        ra0 = ra * DEGTORAD
        dec0 = dec * DEGTORAD
        q = np.array([np.cos(dec0) * np.cos(ra0), np.cos(dec0) * np.sin(ra0), np.sin(dec0)],
                     dtype=np.float64)

        search_radius = radius_arcsec
        limits = search_radius + buffer
        limit_rad = limits / 3600.0 * DEGTORAD
        cos_lim = np.cos(limit_rad)

        records = []
        if include_minor and len(idx.gidx):
            if idx.tree is not None:
                chord = 2.0 * np.sin(limit_rad / 2.0)
                local = np.asarray(idx.tree.query_ball_point(q, chord), dtype=np.int64)
            else:
                local = np.nonzero(idx.V.astype(np.float64) @ q >= cos_lim)[0]

            if len(local) and max_mag is not None:
                local = local[idx.mag[local] <= max_mag]

            date = ephem.date(str(idx.decimalyear))
            for j in local:
                g = int(idx.gidx[j])
                o_ra_r = float(idx.ra[j])
                o_dec_r = float(idx.dec[j])
                sep = _sep_arcsec_rad(o_ra_r, o_dec_r, ra0, dec0)
                if sep > limits:
                    continue
                if topocentric:
                    o_ra_r, o_dec_r = impl.equitorial_geocentric_to_topocentric(
                        o_ra_r, o_dec_r, float(idx.dist[j]),
                        date.datetime(), lon, rho_cos_phi, rho_sin_phi,
                    )
                    sep = _sep_arcsec_rad(o_ra_r, o_dec_r, ra0, dec0)
                    if sep > search_radius:
                        continue
                line = self._line_bytes(g)
                records.append({
                    "name": _parse_name(line),
                    "ra": o_ra_r * RADTODEG,
                    "dec": o_dec_r * RADTODEG,
                    "separation": sep,
                    "mag": float(idx.mag[j]),
                    "xephem_str": line.decode("utf-8", "replace"),
                })

        if include_major:
            date = ephem.date(str(idx.decimalyear))
            major = impl._cone_search_major_bodies(
                (ra0, dec0), date, search_radius, max_mag if max_mag is not None else np.inf,
                lon, rho_cos_phi, rho_sin_phi, buffer,
            )
            for m in major:
                records.append({
                    "name": m[0],
                    "ra": float(m[1]),
                    "dec": float(m[2]),
                    "separation": float(m[3]),
                    "mag": float(m[4]),
                    "xephem_str": m[5],
                })

        return {
            "success": True,
            "count": len(records),
            "query_time_ms": (time.time() - start) * 1000.0,
            "results": records,
        }

    def close(self):
        try:
            self.pool.close()
        except Exception:
            pass


def _load_catalog(catalog_path: str):
    with open(catalog_path, "rb") as f:
        data = f.read()
    buf = np.frombuffer(data, dtype=np.uint8)
    nl = np.flatnonzero(buf == 10).astype(np.int64)
    bounds = np.concatenate((np.zeros(1, dtype=np.int64), nl + 1, [len(data)]))
    if len(bounds) >= 2 and bounds[-2] == bounds[-1]:
        bounds = bounds[:-1]
    n = int(len(bounds) - 1)
    if n <= 0:
        raise RuntimeError(f"catalogue at {catalog_path} appears to be empty")
    return data, bounds, n


class EphemerisWindow:
    """Positions + velocity + acceleration for every object at a base epoch."""

    __slots__ = ("center", "gidx", "u0", "v", "a", "bad")

    def __init__(self, center, gidx, u0, v, a, bad):
        self.center = center
        self.gidx = gidx
        self.u0 = u0
        self.v = v
        self.a = a
        self.bad = bad


class EphemerisEngine:
    """Time-window ephemeris engine.

    Instead of re-propagating the whole catalogue for every epoch, this engine
    propagates it **once per time window** into base position ``u0``, sky
    velocity ``v`` and sky acceleration ``a``.  A query at any epoch inside the
    window scores every object with a vectorised second-order Taylor expansion
    (three matrix-vector products, no Python loop), selects a small candidate
    set, and then re-computes those candidates **exactly** with libastro so the
    returned astrometry is identical to ``pympc.minor_planet_check``.
    """

    def __init__(
        self,
        catalog_path: Optional[str] = None,
        workers: int = 8,
        window_hours: float = 12.0,
        base_cache: int = 4,
        margin_arcsec: float = 900.0,
        deriv_minutes: float = 2.0,
    ):
        self.catalog_path = catalog_path or os.path.join(
            tempfile.gettempdir(), DEFAULT_CATALOG_NAME
        )
        if not os.path.exists(self.catalog_path):
            raise FileNotFoundError(
                f"xephem catalogue not found at {self.catalog_path}. "
                "Run pympc.update_catalogue() first."
            )

        self._data, self._bounds, n = _load_catalog(self.catalog_path)
        self.n_objects = n

        n_workers = max(1, min(workers, n))
        step = n // n_workers
        lb = [i * step for i in range(n_workers)] + [n]
        self._slices = [(int(self._bounds[lb[k]]), int(self._bounds[lb[k + 1]])) for k in range(n_workers)]

        self.pool = WorkerPool(self.catalog_path, n_workers, self._slices)
        if sum(self.pool._counts) != n:
            raise RuntimeError("worker slice counts do not match catalogue length")

        # window = window_hours expressed in decimal years
        self.window = window_hours / 24.0 / 365.25
        self.deriv_eps = deriv_minutes / 1440.0 / 365.25
        self.margin_arcsec = float(margin_arcsec)
        self.base_cache = max(1, base_cache)
        self._windows: "OrderedDict[int, EphemerisWindow]" = OrderedDict()
        self._lock = threading.Lock()
        self._req = 0
        self._obs_cache = {}
        self._impl = _pympc_impl()

    # ---- window management -------------------------------------------------
    def _window_index(self, dy: float) -> int:
        return int(math.floor(dy / self.window))

    def _get_window(self, dy: float):
        """Return (window, built, build_ms). Logs window creation / cache hits."""
        idx = self._window_index(dy)
        with self._lock:
            win = self._windows.get(idx)
            if win is not None:
                self._windows.move_to_end(idx)
                logger.debug(
                    "[window] cache hit   idx=%d center=%.6f (mjd %.4f)", idx, win.center,
                    _mjd_from_decimalyear(win.center),
                )
                return win, False, 0.0
            center = (idx + 0.5) * self.window
            center_mjd = _mjd_from_decimalyear(center)
            self._req += 1
            t0 = time.time()
            logger.info(
                "[window] building     idx=%d center=%s (mjd %.4f, decimalyear %.6f) ...",
                idx, _safe_utc(center_mjd), center_mjd, center,
            )
            u0, v, a, bad = self.pool.base(self._req, center, self.deriv_eps)
            valid = np.isfinite(u0[:, 0]) & np.isfinite(v[:, 0]) & np.isfinite(a[:, 0])
            gidx = np.nonzero(valid)[0]
            win = EphemerisWindow(center, gidx, u0[valid], v[valid], a[valid], bad)
            self._windows[idx] = win
            while len(self._windows) > self.base_cache:
                evicted = self._windows.popitem(last=False)[0]
                logger.debug("[window] evicted LRU  idx=%d", evicted)
            build_ms = (time.time() - t0) * 1000.0
            logger.info(
                "[window] built in %.0f ms  idx=%d objects=%d skipped=%d cached=%d/%d",
                build_ms, idx, len(gidx), bad, len(self._windows), self.base_cache,
            )
            return win, True, build_ms

    def warm(self, epoch_mjd: float) -> dict:
        start = time.time()
        dy = _decimal_year(epoch_mjd)
        win, built, build_ms = self._get_window(dy)
        return {
            "window_center_decimalyear": win.center,
            "objects": int(len(win.gidx)),
            "skipped": int(win.bad),
            "built": built,
            "build_ms": build_ms,
            "time_ms": (time.time() - start) * 1000.0,
        }

    def _observatory(self, observatory):
        key = str(observatory)
        if key in self._obs_cache:
            return self._obs_cache[key]
        try:
            lon, rc, rs = _observatory_data(observatory)
        except Exception:
            lon, rc, rs = 0.0, 0.0, 0.0
        self._obs_cache[key] = (lon, rc, rs)
        return lon, rc, rs

    def _line_bytes(self, g: int) -> bytes:
        return self._data[self._bounds[g]:self._bounds[g + 1]].strip()

    # ---- query -------------------------------------------------------------
    def search(self, *args, **kwargs) -> dict:
        try:
            return self._search_impl(*args, **kwargs)
        except Exception as exc:
            logger.exception("[query] failed: %s", exc)
            return {"success": False, "error": str(exc), "query_time_ms": 0.0}

    def _search_impl(
        self,
        ra: float,
        dec: float,
        epoch_mjd: float,
        radius_arcsec: float = 60.0,
        max_mag: Optional[float] = None,
        observatory: Union[int, str, tuple] = 500,
        include_major: bool = True,
        include_minor: bool = True,
    ) -> dict:
        start = time.time()
        try:
            dy = _decimal_year(epoch_mjd)
            win, window_built, build_ms = self._get_window(dy)
        except Exception as exc:
            return {"success": False, "error": str(exc), "query_time_ms": (time.time() - start) * 1000.0}

        lon, rho_cos_phi, rho_sin_phi = self._observatory(observatory)
        topocentric = any((lon, rho_cos_phi, rho_sin_phi))
        buffer = SOLAR_PARALLAX_ARCSEC * 3 if topocentric else 0.0
        limits = radius_arcsec + buffer

        dt = dy - win.center
        ra0 = ra * DEGTORAD
        dec0 = dec * DEGTORAD
        q = np.array(
            [np.cos(dec0) * np.cos(ra0), np.cos(dec0) * np.sin(ra0), np.sin(dec0)],
            dtype=np.float32,
        )

        theta_rad = (limits + self.margin_arcsec) / 3600.0 * DEGTORAD
        cth = math.cos(theta_rad)

        n_cand = 0
        records = []
        if include_minor and len(win.gidx):
            # second-order Taylor score of every object, fully vectorised
            score = win.u0 @ q + (win.v @ q) * dt + (0.5 * dt * dt) * (win.a @ q)
            cand = np.nonzero(score >= cth)[0]
            n_cand = int(len(cand))

            if len(cand):
                date = ephem.date(str(dy))
                for j in cand:
                    g = int(win.gidx[j])
                    line = self._line_bytes(g)
                    try:
                        body = ephem.readdb(line.decode("utf-8", "replace"))
                        body.compute(date)
                    except Exception:
                        continue
                    o_ra_r = float(body.a_ra)
                    o_dec_r = float(body.a_dec)
                    sep = _sep_arcsec_rad(o_ra_r, o_dec_r, ra0, dec0)
                    if sep > limits:
                        continue
                    mag = float(body.mag)
                    if max_mag is not None and mag > max_mag:
                        continue
                    if topocentric:
                        o_ra_r, o_dec_r = self._impl.equitorial_geocentric_to_topocentric(
                            o_ra_r, o_dec_r, float(body.earth_distance),
                            date.datetime(), lon, rho_cos_phi, rho_sin_phi,
                        )
                        sep = _sep_arcsec_rad(o_ra_r, o_dec_r, ra0, dec0)
                        if sep > radius_arcsec:
                            continue
                    records.append({
                        "name": _parse_name(line),
                        "ra": o_ra_r * RADTODEG,
                        "dec": o_dec_r * RADTODEG,
                        "separation": sep,
                        "mag": mag,
                        "xephem_str": line.decode("utf-8", "replace"),
                    })

        if include_major:
            date = ephem.date(str(dy))
            major = self._impl._cone_search_major_bodies(
                (ra0, dec0), date, radius_arcsec,
                max_mag if max_mag is not None else np.inf,
                lon, rho_cos_phi, rho_sin_phi, buffer,
            )
            for m in major:
                records.append({
                    "name": m[0],
                    "ra": float(m[1]),
                    "dec": float(m[2]),
                    "separation": float(m[3]),
                    "mag": float(m[4]),
                    "xephem_str": m[5],
                })

        query_ms = (time.time() - start) * 1000.0
        logger.info(
            "[query] ra=%.5f dec=%.5f epoch=%.5f radius=%.1f max_mag=%s -> %d hit(s) "
            "in %.1f ms (candidates=%d, window %s%s)",
            ra, dec, epoch_mjd, radius_arcsec, max_mag, len(records), query_ms, n_cand,
            "built" if window_built else "cached",
            f" +{build_ms:.0f} ms build" if window_built else "",
        )
        return {
            "success": True,
            "count": len(records),
            "query_time_ms": query_ms,
            "window_built": window_built,
            "window_build_ms": build_ms,
            "candidates": n_cand,
            "results": records,
        }

    def close(self):
        try:
            self.pool.close()
        except Exception:
            pass
