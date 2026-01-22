"""Demo: Local cone search on ASTAP variable star catalog.

ASTAP variable star catalog format (V003/V006 series):
  - RA encoded as [0..864000], unit = RA_encoded / 2400 degrees
  - DEC encoded as [-324000..324000], unit = DEC_encoded / 3600 degrees
  - Label contains: name, magnitude range, period info

Supported catalog files:
  - variable_stars.csv (mag <= 11)
  - variable_stars_13.csv (mag <= 13)  
  - variable_stars_15.csv (mag <= 15)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from astropy.coordinates import SkyCoord
import astropy.units as u

# ============ Default Configuration ============
DEFAULT_INPUT = "data/variable_stars_15.csv"
DEFAULT_RA = "05h55m10s"
DEFAULT_DEC = "+07d24m25s"
DEFAULT_RADIUS_ARCSEC = 60.0
# ===============================================


def _parse_skycoord(ra: str, dec: str) -> SkyCoord:
    """Parse RA/Dec from degrees or sexagesimal format."""
    try:
        return SkyCoord(ra, dec, unit=(u.deg, u.deg), frame="icrs")
    except Exception:
        return SkyCoord(ra, dec, frame="icrs")


def _parse_label(label: str) -> dict:
    """Parse ASTAP label: 'name mag_min-mag_max[Period_xxx]'"""
    result = {"name": "", "mag_min": None, "mag_max": None, "period": None}
    if not label:
        return result
    
    parts = label.split()
    if len(parts) >= 1:
        result["name"] = parts[0]
    if len(parts) >= 2:
        mag_period = parts[1]
        # Extract period if present
        if "_Period_" in mag_period:
            mag_part, period_part = mag_period.rsplit("_Period_", 1)
            try:
                result["period"] = float(period_part)
            except ValueError:
                pass
        else:
            mag_part = mag_period
        
        # Parse magnitude range (e.g., "0.0V-1.6V" or "-0.07V--0.02V")
        mag_str = mag_part.rstrip("VRIBKp<>:()")
        if "-" in mag_str[1:]:
            idx = mag_str.find("-", 1)
            try:
                result["mag_min"] = float(mag_str[:idx].rstrip("VRIBKp<>:()"))
            except ValueError:
                pass
            try:
                result["mag_max"] = float(mag_str[idx+1:].rstrip("VRIBKp<>:()"))
            except ValueError:
                pass
    return result


def _read_astap_catalog(path: Path) -> pd.DataFrame:
    """Read ASTAP variable star catalog and decode coordinates."""
    lines = path.read_text(encoding="utf-8").splitlines()
    
    # Skip header lines (first 2 lines are metadata)
    data_lines = lines[2:]
    
    records = []
    for line in data_lines:
        parts = line.split(",", 2)
        if len(parts) < 3:
            continue
        try:
            ra_enc = int(parts[0])
            dec_enc = int(parts[1])
            label = parts[2]
        except ValueError:
            continue
        
        # Decode coordinates
        ra_deg = ra_enc / 2400.0
        dec_deg = dec_enc / 3600.0
        
        # Parse label
        info = _parse_label(label)
        records.append({
            "ra": ra_deg,
            "dec": dec_deg,
            "name": info["name"],
            "mag_min": info["mag_min"],
            "mag_max": info["mag_max"],
            "period": info["period"],
            "label": label,
        })
    
    return pd.DataFrame(records)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Search ASTAP variable star catalog")
    p.add_argument("--input", default=DEFAULT_INPUT, help="ASTAP variable star catalog path")
    p.add_argument("--ra", default=DEFAULT_RA, help="Target RA: degrees or hms")
    p.add_argument("--dec", default=DEFAULT_DEC, help="Target Dec: degrees or dms")
    p.add_argument("--radius-arcsec", type=float, default=DEFAULT_RADIUS_ARCSEC, help="Search radius (arcsec)")
    p.add_argument("--top", type=int, default=50, help="Maximum number of results")
    p.add_argument("--max-mag", type=float, default=None, help="Maximum magnitude limit")
    args = p.parse_args(argv)

    path = Path(args.input).expanduser()
    if not path.exists():
        raise SystemExit(f"Input file not found: {path}")

    target = _parse_skycoord(args.ra, args.dec)
    
    print(f"Loading catalog: {path}")
    df = _read_astap_catalog(path)
    print(f"Total stars in catalog: {len(df)}")

    # Calculate separation
    coords = SkyCoord(df["ra"].to_numpy() * u.deg, df["dec"].to_numpy() * u.deg)
    sep = coords.separation(target).arcsec
    df = df.assign(separation_arcsec=sep)
    
    # Filter by radius
    df = df[df["separation_arcsec"] <= float(args.radius_arcsec)].copy()
    
    # Filter by magnitude if specified
    if args.max_mag is not None:
        df = df[(df["mag_max"].isna()) | (df["mag_max"] <= args.max_mag)]
    
    df = df.sort_values("separation_arcsec", ascending=True)

    print(f"Target: {target.to_string('hmsdms', precision=2)}  radius={args.radius_arcsec} arcsec")
    print("-" * 80)
    
    if df.empty:
        print("No matching results")
        return 0

    cols = ["name", "ra", "dec", "mag_min", "mag_max", "period", "separation_arcsec"]
    out = df[cols].head(int(args.top))
    print(out.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

