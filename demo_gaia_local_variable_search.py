"""Demo: Local cone search on Gaia variable star catalog.

Input file can be CSV / Parquet / FITS / VOTable (latter two read by astropy).
File must have at least two columns: RA/Dec (default column names ra/dec, unit: degrees).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from astropy.coordinates import SkyCoord
import astropy.units as u
from astropy.table import Table

# ============ Default Configuration ============
DEFAULT_INPUT = "data/gaia_var.csv"
DEFAULT_RA = "120.5"
DEFAULT_DEC = "-12.3"
DEFAULT_RADIUS_ARCSEC = 10.0
# ===============================================


def _parse_skycoord(ra: str, dec: str) -> SkyCoord:
    try:
        return SkyCoord(ra, dec, unit=(u.deg, u.deg), frame="icrs")
    except Exception:
        return SkyCoord(ra, dec, frame="icrs")


def _create_demo_csv(path: Path, center: SkyCoord, n_bg: int = 2000, n_near: int = 50) -> None:
    rng = np.random.default_rng(42)

    df_bg = pd.DataFrame(
        {
            "source_id": np.arange(1, n_bg + 1, dtype=np.int64),
            "ra": rng.uniform(0.0, 360.0, size=n_bg),
            "dec": rng.uniform(-90.0, 90.0, size=n_bg),
            "vari_class": rng.choice(["RRLYR", "CEP", "DSCT", "LPV"], size=n_bg),
            "period_day": rng.uniform(0.05, 500.0, size=n_bg),
        }
    )

    # 额外生成一批围绕目标位置的样本，确保演示时能搜到结果。
    # 在小角度范围内直接对 ra/dec 加减是近似，但足够用于 demo。
    near_radius_arcsec = 30.0
    dra = rng.uniform(-near_radius_arcsec, near_radius_arcsec, size=n_near) / 3600.0
    ddec = rng.uniform(-near_radius_arcsec, near_radius_arcsec, size=n_near) / 3600.0
    ra0 = float(center.ra.deg)
    dec0 = float(center.dec.deg)

    df_near = pd.DataFrame(
        {
            "source_id": np.arange(n_bg + 1, n_bg + n_near + 1, dtype=np.int64),
            "ra": (ra0 + dra) % 360.0,
            "dec": np.clip(dec0 + ddec, -90.0, 90.0),
            "vari_class": rng.choice(["RRLYR", "CEP", "DSCT", "LPV"], size=n_near),
            "period_day": rng.uniform(0.05, 500.0, size=n_near),
        }
    )

    df = pd.concat([df_bg, df_near], ignore_index=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def _read_all(path: Path) -> pd.DataFrame:
    suf = path.suffix.lower()
    if suf == ".csv":
        return pd.read_csv(path)
    if suf in (".parquet", ".pq"):
        return pd.read_parquet(path)
    t = Table.read(path)
    return t.to_pandas()


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", default=DEFAULT_INPUT, help="Local Gaia variable star catalog path")
    p.add_argument("--ra", default=DEFAULT_RA, help="Target RA: degrees or hms")
    p.add_argument("--dec", default=DEFAULT_DEC, help="Target Dec: degrees or dms")
    p.add_argument("--radius-arcsec", type=float, default=DEFAULT_RADIUS_ARCSEC, help="Search radius (arcsec)")
    p.add_argument("--ra-col", default="ra", help="RA column name in input table (unit: degrees)")
    p.add_argument("--dec-col", default="dec", help="Dec column name in input table (unit: degrees)")
    p.add_argument("--top", type=int, default=50, help="Maximum number of results to output")
    p.add_argument("--create-demo", action="store_true", help="Generate demo CSV if input does not exist")
    args = p.parse_args(argv)

    path = Path(args.input).expanduser()

    target = _parse_skycoord(args.ra, args.dec)
    if not path.exists():
        if not args.create_demo:
            raise SystemExit(f"Input file not found: {path} (add --create-demo to generate sample)")
        _create_demo_csv(path, center=target)

    df = _read_all(path)
    if args.ra_col not in df.columns or args.dec_col not in df.columns:
        raise SystemExit(
            f"Input table missing columns: {args.ra_col!r}/{args.dec_col!r}. Available: {list(df.columns)[:30]}"
        )

    coords = SkyCoord(
        df[args.ra_col].to_numpy() * u.deg, df[args.dec_col].to_numpy() * u.deg
    )
    sep = coords.separation(target).arcsec
    df = df.assign(separation_arcsec=sep)
    df = df[df["separation_arcsec"] <= float(args.radius_arcsec)].copy()
    df = df.sort_values("separation_arcsec", ascending=True)

    print(f"input={path}")
    print(f"target={target.to_string('hmsdms', precision=2)}  r={args.radius_arcsec} arcsec")
    if df.empty:
        print("No matching results")
        return 0

    prefer = [
        "source_id",
        "vari_class",
        "period_day",
        args.ra_col,
        args.dec_col,
        "separation_arcsec",
    ]
    cols = [c for c in prefer if c in df.columns]
    out = df[cols].head(int(args.top))
    print(out.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
