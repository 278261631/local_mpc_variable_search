"""主程序：本地查询 Gaia 变星表（圆锥检索）。

该模块不负责命令行解析；请用 demo_gaia_local_variable_search.py 作为运行入口。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.table import Table


def read_table(path: str | Path) -> pd.DataFrame:
    p = Path(path).expanduser()
    suf = p.suffix.lower()
    if suf == ".csv":
        return pd.read_csv(p)
    if suf in (".parquet", ".pq"):
        return pd.read_parquet(p)
    t = Table.read(p)
    return t.to_pandas()


def cone_search(
    df: pd.DataFrame,
    target: SkyCoord,
    radius_arcsec: float,
    ra_col: str = "ra",
    dec_col: str = "dec",
) -> pd.DataFrame:
    if ra_col not in df.columns or dec_col not in df.columns:
        raise KeyError(f"missing columns: {ra_col!r}/{dec_col!r}")

    coords = SkyCoord(df[ra_col].to_numpy() * u.deg, df[dec_col].to_numpy() * u.deg)
    sep = coords.separation(target).arcsec

    out = df.copy()
    out["separation_arcsec"] = sep
    out = out[out["separation_arcsec"] <= float(radius_arcsec)].copy()
    out = out.sort_values("separation_arcsec", ascending=True)
    return out


def create_demo_table(
    center: SkyCoord,
    n_bg: int = 2000,
    n_near: int = 50,
    near_radius_arcsec: float = 30.0,
) -> pd.DataFrame:
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

    return pd.concat([df_bg, df_near], ignore_index=True)

