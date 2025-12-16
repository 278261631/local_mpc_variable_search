"""演示：使用 pympc 在本地（xephem 轨道库文件）进行小行星/彗星/主天体锥形检索。

前置：请先用 demo_mpc_prepare_xephem.py 生成本地 xephem CSV，然后用 --xephem 指定。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from astropy.coordinates import SkyCoord
from astropy.time import Time
import astropy.units as u

from pympc.pympc import minor_planet_check

# ============ Default Configuration ============
DEFAULT_RA = "120.5"
DEFAULT_DEC = "-12.3"
DEFAULT_EPOCH = "now"
DEFAULT_RADIUS_ARCSEC = 60.0
DEFAULT_XEPHEM = ".cache/mpcorb_xephem.csv"
# ===============================================


def _parse_skycoord(ra: str, dec: str) -> SkyCoord:
    try:
        return SkyCoord(ra, dec, unit=(u.deg, u.deg), frame="icrs")
    except Exception:
        return SkyCoord(ra, dec, frame="icrs")


def _parse_epoch(epoch: str) -> Time:
    if epoch.lower() == "now":
        return Time.now()
    if epoch.lower().startswith("mjd:"):
        return Time(float(epoch.split(":", 1)[1]), format="mjd")
    try:
        return Time(epoch)
    except Exception as exc:
        raise SystemExit(
            f"Cannot parse epoch={epoch!r}, use 'now' or 'mjd:60200.5' or ISO time string.\n{exc}"
        )


def _parse_observatory(value: str):
    if value is None:
        return (0.0, 0.0, 0.0)
    if "," in value:
        parts = [p.strip() for p in value.split(",")]
        if len(parts) != 3:
            raise SystemExit("--observatory requires 3 values: lon_deg,rhocosphi,rhosinphi")
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    return value


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ra", default=DEFAULT_RA, help="RA: degrees (e.g. 120.5) or hms (e.g. 08:02:00)")
    p.add_argument("--dec", default=DEFAULT_DEC, help="Dec: degrees (e.g. -12.3) or dms (e.g. -12:18:00)")
    p.add_argument("--epoch", default=DEFAULT_EPOCH, help="Observation epoch: now / mjd:60200.5 / ISO string")
    p.add_argument("--radius-arcsec", type=float, default=DEFAULT_RADIUS_ARCSEC, help="Search radius (arcsec)")
    p.add_argument("--xephem", default=DEFAULT_XEPHEM, help="Local xephem CSV path (generate with demo_mpc_prepare_xephem.py)")
    p.add_argument("--max-mag", type=float, default=None, help="Maximum magnitude limit for results")
    p.add_argument(
        "--observatory",
        default=None,
        help="Observatory: MPC code (e.g. 500) or lon_deg,rhocosphi,rhosinphi",
    )
    p.add_argument("--no-minor", action="store_true", help="Do not search minor bodies (asteroids/comets)")
    p.add_argument("--no-major", action="store_true", help="Do not search major bodies (planets/moon)")
    p.add_argument("--chunk-size", type=int, default=20000, help="Parallel chunk size; 0=disable multiprocessing")
    args = p.parse_args(argv)

    coo = _parse_skycoord(args.ra, args.dec)
    epoch = _parse_epoch(args.epoch)
    observatory = _parse_observatory(args.observatory)

    xephem_path = Path(args.xephem).expanduser() if args.xephem else None
    if xephem_path is None or not xephem_path.exists():
        raise SystemExit(f"xephem file not found: {xephem_path}\nPlease run demo_mpc_prepare_xephem.py first to generate it.")

    results = minor_planet_check(
        ra=coo.ra.deg,
        dec=coo.dec.deg,
        epoch=epoch,
        search_radius=args.radius_arcsec,
        xephem_filepath=str(xephem_path),
        max_mag=args.max_mag,
        include_minor_bodies=not args.no_minor,
        include_major_bodies=not args.no_major,
        observatory=observatory,
        chunk_size=args.chunk_size,
    )

    print(f"xephem={xephem_path}")
    print(
        f"target={coo.to_string('hmsdms', precision=2)}  epoch={epoch.isot}  r={args.radius_arcsec} arcsec"
    )
    if results is None or len(results) == 0:
        print("No matching results")
        return 0

    cols = [c for c in ("name", "ra", "dec", "mag", "separation") if c in results.colnames]
    results.sort("separation")
    for line in results[cols].pformat(max_lines=50, max_width=160):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
