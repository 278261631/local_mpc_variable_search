"""Sorted-declination slab index for ASTAP variable-star catalogues.

Why this is fast
----------------
A cone search only needs the stars whose *declination* lies within ``radius`` of
the query centre, because ``|dec - dec0| <= angular distance`` always holds.
Keeping the catalogue sorted by declination turns every query into two binary
searches plus an exact spherical-distance pass over the few hundred rows inside
that slab.

For the 15th-magnitude catalogue (1.11 M stars) a 60" query touches ~130 rows
and costs ~0.035 ms, versus ~90 ms for a ``SkyCoord.separation`` scan over the
whole table.

Labels are kept as one raw byte blob; they are only parsed for the stars a
query actually touches (a handful), which keeps the loader at ~1.3 s instead of
re-parsing 1.1 M labels at startup.

The label parser (``name mag_min-mag_max[_Period_x]``) follows exactly the rules
of ``astap_variable_search_server._parse_label`` so results are identical to the
stock server.

Catalogue format (ASTAP V003/V005)
----------------------------------
    line 1: header
    line 2: header
    RA_encoded,DEC_encoded,label        # RA/2400 deg, DEC/3600 deg
"""

from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

CACHE_VERSION = 2
CACHE_DIR_NAME = "varstar_fast_server"

# characters stripped from the magnitude field by the stock parser
_STRIP_CHARS = b"VRIBKp<>:()"
_PERIOD_TAG = b"_Period_"
_ARCSEC_PER_DEG = 3600.0


class CatalogError(RuntimeError):
    """Raised when the catalogue file cannot be parsed."""


# --------------------------------------------------------------------------- #
# label parsing (byte-identical to the stock implementation)
# --------------------------------------------------------------------------- #
def parse_mag_token(tok: bytes) -> tuple[float, float, float]:
    """Parse ``mag_min-mag_max[_Period_x]`` -> (mag_min, mag_max, period).

    Missing/invalid values become ``NaN``.  This mirrors the reference parser
    ``_parse_label`` in ``astap_variable_search_server.py`` exactly, including
    its quirks (e.g. ``11.78g-(0.27)g`` yields no magnitudes because ``g`` is not
    in the strip set).
    """
    mag_min = mag_max = period = np.nan
    if not tok:
        return mag_min, mag_max, period

    mag_part = tok
    if _PERIOD_TAG in tok:
        mag_part, _, period_part = tok.rpartition(_PERIOD_TAG)
        try:
            period = float(period_part)
        except ValueError:
            period = np.nan

    mag_str = mag_part.rstrip(_STRIP_CHARS)
    dash = mag_str.find(b"-", 1)
    if dash > 0:
        try:
            mag_min = float(mag_str[:dash].rstrip(_STRIP_CHARS))
        except ValueError:
            pass
        try:
            mag_max = float(mag_str[dash + 1:].rstrip(_STRIP_CHARS))
        except ValueError:
            pass
    return mag_min, mag_max, period


def parse_label(label: bytes) -> tuple[str, float, float, float]:
    """Split a raw label into (name, mag_min, mag_max, period).

    Whitespace handling mirrors ``str.split()`` in the stock parser.
    """
    if not label:
        return "", np.nan, np.nan, np.nan
    parts = label.split()
    name = parts[0].decode("utf-8", "replace")
    if len(parts) < 2:
        return name, np.nan, np.nan, np.nan
    mag_min, mag_max, period = parse_mag_token(parts[1])
    return name, mag_min, mag_max, period


# --------------------------------------------------------------------------- #
# parsing the catalogue
# --------------------------------------------------------------------------- #
def _parse_catalog(path: Path) -> dict:
    """Parse an ASTAP variable-star CSV into plain numpy arrays."""
    raw = path.read_bytes()

    pos = 0
    for _ in range(2):  # skip the two header lines
        nl = raw.find(b"\n", pos)
        if nl < 0:
            raise CatalogError(f"{path}: file has fewer than two header lines")
        pos = nl + 1

    lines = raw[pos:].split(b"\n")
    del raw

    capacity = len(lines)
    ra_enc = np.empty(capacity, np.int32)
    dec_enc = np.empty(capacity, np.int32)
    offsets = np.empty(capacity + 1, np.int64)

    labels: list[bytes] = []
    blob_len = 0
    n = 0

    for line in lines:
        if not line:
            continue
        parts = line.split(b",", 2)
        if len(parts) < 3:
            continue
        try:
            ra_v = int(parts[0])
            dec_v = int(parts[1])
        except ValueError:  # legend / comment lines
            continue

        label = parts[2]
        if label.endswith(b"\r"):
            label = label[:-1]

        ra_enc[n] = ra_v
        dec_enc[n] = dec_v
        offsets[n] = blob_len
        labels.append(label)
        blob_len += len(label) + 1
        n += 1
    del lines

    offsets[n] = blob_len
    if n == 0:
        raise CatalogError(f"{path}: no catalogue rows found")

    blob = b"\n".join(labels)
    del labels

    ra = ra_enc[:n].astype(np.float64) / 2400.0
    dec = dec_enc[:n].astype(np.float64) / 3600.0

    return {
        "ra": ra,
        "dec": dec,
        "label_blob": blob,
        "label_offset": offsets[: n + 1].astype(np.int32),
    }


# --------------------------------------------------------------------------- #
# index object
# --------------------------------------------------------------------------- #
@dataclass
class Hits:
    """Result of a cone search."""

    idx: np.ndarray
    sep_arcsec: np.ndarray
    candidates: int
    elapsed_ms: float


@dataclass
class VarStarIndex:
    """Declination-sorted cone-search index over a variable-star catalogue."""

    ra: np.ndarray                 # float64 [n], degrees
    dec: np.ndarray                # float64 [n], degrees
    order: np.ndarray              # int32 [n], indices sorted by declination
    dec_sorted: np.ndarray         # float64 [n], dec[order]
    label_blob: bytes              # newline-joined raw labels
    label_offset: np.ndarray       # int32 [n+1] offsets into label_blob

    source: Path = Path()
    source_size: int = 0
    source_mtime_ns: int = 0
    build_seconds: float = 0.0
    load_seconds: float = 0.0
    cache_hit: bool = False
    cache_path: Path | None = None

    # -- construction ------------------------------------------------------- #
    @classmethod
    def from_arrays(cls, data: dict, source: Path | None = None) -> "VarStarIndex":
        order = np.argsort(data["dec"], kind="stable").astype(np.int32)
        index = cls(
            ra=data["ra"],
            dec=data["dec"],
            order=order,
            dec_sorted=data["dec"][order],
            label_blob=data["label_blob"],
            label_offset=data["label_offset"],
        )
        if source is not None:
            index.source = Path(source)
            st = index.source.stat()
            index.source_size = st.st_size
            index.source_mtime_ns = st.st_mtime_ns
        return index

    # -- introspection ------------------------------------------------------ #
    @property
    def n_objects(self) -> int:
        return int(self.ra.size)

    def memory_bytes(self) -> int:
        return int(
            self.ra.nbytes + self.dec.nbytes + self.order.nbytes
            + self.dec_sorted.nbytes + self.label_offset.nbytes
            + len(self.label_blob)
        )

    def stats(self) -> dict:
        return {
            "total_stars": self.n_objects,
            "catalog_path": str(self.source),
            "catalog_bytes": self.source_size,
            "label_bytes": len(self.label_blob),
            "cache_hit": self.cache_hit,
            "cache_path": str(self.cache_path) if self.cache_path else None,
            "build_seconds": round(self.build_seconds, 3),
            "load_seconds": round(self.load_seconds, 3),
            "index_memory_mb": round(self.memory_bytes() / 1e6, 1),
        }

    # -- labels ------------------------------------------------------------- #
    def raw_label(self, i: int) -> bytes:
        start = int(self.label_offset[i])
        end = int(self.label_offset[i + 1]) - 1  # drop the trailing newline
        return self.label_blob[start:end]

    def label(self, i: int) -> str:
        return self.raw_label(i).decode("utf-8", "replace")

    def fields(self, i: int) -> tuple[str, float, float, float]:
        """(name, mag_min, mag_max, period) for one catalogue row."""
        return parse_label(self.raw_label(i))

    def mag_max_of(self, idx: np.ndarray) -> np.ndarray:
        """Vectorised mag_max for a small set of indices (lazy label parsing)."""
        out = np.empty(len(idx), np.float64)
        for k, i in enumerate(idx.tolist()):
            parts = self.raw_label(i).split()
            out[k] = parse_mag_token(parts[1])[1] if len(parts) > 1 else np.nan
        return out

    # -- query -------------------------------------------------------------- #
    def search(
        self,
        ra: float,
        dec: float,
        radius_arcsec: float = 60.0,
        max_mag: float | None = None,
        top: int = 50,
    ) -> Hits:
        """Exact cone search around (ra, dec) in degrees."""
        t0 = time.perf_counter()
        radius_arcsec = float(radius_arcsec)
        top = int(top)

        if radius_arcsec < 0 or top <= 0:
            return Hits(np.empty(0, np.int64), np.empty(0), 0,
                        (time.perf_counter() - t0) * 1e3)

        if radius_arcsec >= 180.0 * 3600.0:
            idx = np.arange(self.n_objects, dtype=np.int64)
        else:
            r_deg = radius_arcsec / _ARCSEC_PER_DEG
            lo = int(np.searchsorted(self.dec_sorted, max(dec - r_deg, -90.0), side="left"))
            hi = int(np.searchsorted(self.dec_sorted, min(dec + r_deg, 90.0), side="right"))
            idx = self.order[lo:hi].astype(np.int64, copy=False)

        candidates = int(idx.size)
        if candidates == 0:
            return Hits(idx, np.empty(0), 0, (time.perf_counter() - t0) * 1e3)

        sep = self._separation_arcsec(idx, ra, dec)
        keep = sep <= radius_arcsec
        idx = idx[keep]
        sep = sep[keep]

        if max_mag is not None and idx.size:
            mag = self.mag_max_of(idx)
            keep = np.isnan(mag) | (mag <= float(max_mag))
            idx = idx[keep]
            sep = sep[keep]

        if idx.size > top:
            k = np.argpartition(sep, top - 1)[:top]
            idx = idx[k]
            sep = sep[k]

        order = np.argsort(sep, kind="stable")
        return Hits(idx[order], sep[order], candidates,
                    (time.perf_counter() - t0) * 1e3)

    def _separation_arcsec(self, idx: np.ndarray, ra0: float, dec0: float) -> np.ndarray:
        """Haversine separation, accurate at arbitrarily small angles."""
        a = np.deg2rad(self.ra[idx])
        b = np.deg2rad(self.dec[idx])
        a0 = np.deg2rad(ra0)
        b0 = np.deg2rad(min(max(float(dec0), -90.0), 90.0))
        h = np.sin((b - b0) * 0.5) ** 2 + np.cos(b) * np.cos(b0) * np.sin((a - a0) * 0.5) ** 2
        return np.rad2deg(2.0 * np.arcsin(np.sqrt(np.clip(h, 0.0, 1.0)))) * _ARCSEC_PER_DEG

    # -- result formatting -------------------------------------------------- #
    def records(self, hits: Hits) -> list[dict]:
        """Format hits exactly like the stock server's JSON records."""
        out: list[dict] = []
        for i, sep in zip(hits.idx.tolist(), hits.sep_arcsec.tolist()):
            raw = self.raw_label(i)
            label = raw.decode("utf-8", "replace")
            name, mag_min, mag_max, period = parse_label(raw)
            out.append({
                "ra": float(self.ra[i]),
                "dec": float(self.dec[i]),
                "name": name,
                "mag_min": None if np.isnan(mag_min) else float(mag_min),
                "mag_max": None if np.isnan(mag_max) else float(mag_max),
                "period": None if np.isnan(period) else float(period),
                "label": label,
                "separation_arcsec": float(sep),
            })
        return out


# --------------------------------------------------------------------------- #
# on-disk cache
# --------------------------------------------------------------------------- #
def default_cache_dir() -> Path:
    return Path(tempfile.gettempdir()) / CACHE_DIR_NAME


def cache_path_for(source: Path, cache_dir: Path | None = None) -> Path:
    source = Path(source)
    st = source.stat()
    directory = Path(cache_dir) if cache_dir else default_cache_dir()
    name = f"{source.stem}-{st.st_size:x}-{st.st_mtime_ns:x}-v{CACHE_VERSION}.npz"
    return directory / name


def save_index(index: VarStarIndex, cache_path: Path) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    # np.savez appends ".npz" unless the name already ends with it
    tmp = cache_path.with_name(cache_path.name + ".tmp.npz")
    np.savez(
        tmp,
        version=np.array(CACHE_VERSION, np.int64),
        source_size=np.array(index.source_size, np.int64),
        source_mtime_ns=np.array(index.source_mtime_ns, np.int64),
        rows=np.array(index.n_objects, np.int64),
        ra=index.ra,
        dec=index.dec,
        order=index.order,
        dec_sorted=index.dec_sorted,
        label_offset=index.label_offset,
        label_blob=np.frombuffer(index.label_blob, np.uint8),
    )
    tmp.replace(cache_path)


def _prune_stale_caches(cache_dir: Path, source: Path, keep: Path) -> None:
    """Remove older cache files for the same catalogue (previous sizes/mtimes)."""
    try:
        for old in cache_dir.glob(f"{source.stem}-*-v{CACHE_VERSION}.npz"):
            if old == keep:
                continue
            try:
                old.unlink()
            except OSError:  # locked by another running server
                pass
    except OSError:
        pass


def _load_cache(cache_path: Path, source: Path, st: os.stat_result) -> VarStarIndex:
    t0 = time.perf_counter()
    with np.load(cache_path, allow_pickle=False) as z:
        if int(z["version"]) != CACHE_VERSION:
            raise CatalogError("cache version mismatch")
        if int(z["source_size"]) != st.st_size or int(z["source_mtime_ns"]) != st.st_mtime_ns:
            raise CatalogError("cache does not match catalogue file")
        data = {
            "ra": z["ra"],
            "dec": z["dec"],
            "order": z["order"].astype(np.int32, copy=False),
            "dec_sorted": z["dec_sorted"],
            "label_offset": z["label_offset"].astype(np.int32, copy=False),
            "label_blob": z["label_blob"].tobytes(),
        }

    return VarStarIndex(
        source=Path(source),
        source_size=st.st_size,
        source_mtime_ns=st.st_mtime_ns,
        cache_hit=True,
        cache_path=cache_path,
        load_seconds=time.perf_counter() - t0,
        **data,
    )


def load_index(
    path: Path,
    cache_dir: Path | None = None,
    use_cache: bool = True,
    rebuild: bool = False,
    log=print,
) -> VarStarIndex:
    """Load (or build) the index for ``path``, using the npz cache when possible."""
    path = Path(path).expanduser().resolve()
    if not path.exists():
        raise CatalogError(f"Catalog not found: {path}")
    st = path.stat()

    cache_path = cache_path_for(path, cache_dir) if use_cache else None
    if use_cache and not rebuild and cache_path is not None and cache_path.exists():
        try:
            index = _load_cache(cache_path, path, st)
            log(f"[index] cache hit: {cache_path.name} ({index.load_seconds*1000:.0f} ms)")
            return index
        except Exception as exc:  # corrupt / stale cache -> rebuild
            log(f"[index] ignoring cache ({exc}); rebuilding")

    t0 = time.perf_counter()
    data = _parse_catalog(path)
    index = VarStarIndex.from_arrays(data, source=path)
    index.cache_path = cache_path
    index.build_seconds = time.perf_counter() - t0
    log(f"[index] built in {index.build_seconds:.2f} s "
        f"({index.n_objects:,} stars, {index.memory_bytes()/1e6:.0f} MB)")

    if use_cache and cache_path is not None:
        try:
            save_index(index, cache_path)
            _prune_stale_caches(cache_path.parent, path, cache_path)
            log(f"[index] cache written: {cache_path}")
        except OSError as exc:
            log(f"[index] could not write cache ({exc})")
            index.cache_path = None

    return index
