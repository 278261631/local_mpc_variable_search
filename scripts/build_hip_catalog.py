"""Build HIP catalog CSV from VizieR (I/239/hip_main).

Output columns:
  hip, ra, dec, mag
"""

from __future__ import annotations

import argparse
from pathlib import Path

from astroquery.vizier import Vizier


def build_hip_catalog(output_path: Path) -> int:
    vizier = Vizier(
        columns=["HIP", "Vmag", "RAICRS", "DEICRS", "_RA.icrs", "_DE.icrs"],
        row_limit=-1,
    )
    tables = vizier.get_catalogs("I/239/hip_main")
    if not tables:
        raise RuntimeError("No table returned from VizieR for I/239/hip_main")

    df = tables[0].to_pandas().rename(columns={"HIP": "hip", "Vmag": "mag"})
    if "RAICRS" in df.columns and "DEICRS" in df.columns:
        df = df.rename(columns={"RAICRS": "ra", "DEICRS": "dec"})
    elif "_RA.icrs" in df.columns and "_DE.icrs" in df.columns:
        df = df.rename(columns={"_RA.icrs": "ra", "_DE.icrs": "dec"})
    else:
        raise RuntimeError("No usable RA/DEC columns found in returned table")
    df = df[["hip", "ra", "dec", "mag"]]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    return len(df)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download HIP catalog to CSV")
    parser.add_argument(
        "--output",
        default="data/hip_catalog.csv",
        help="Output CSV path (default: data/hip_catalog.csv)",
    )
    args = parser.parse_args()

    output = Path(args.output).expanduser()
    n = build_hip_catalog(output)
    print(f"Saved {n} rows to: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

