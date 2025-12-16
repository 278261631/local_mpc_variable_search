"""主程序：使用 pympc 读取本地 xephem CSV 做小行星/彗星/主天体锥形检索。

该模块不负责命令行解析；请用 demo_mpc_local_asteroid_search.py 作为运行入口。
"""

from __future__ import annotations

from pathlib import Path

import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.table import Table
from astropy.time import Time

from pympc.pympc import minor_planet_check


def search_minor_planets(
    target: SkyCoord,
    epoch: Time,
    radius_arcsec: float,
    xephem_csv: str | Path,
    max_mag: float | None = None,
    include_minor_bodies: bool = True,
    include_major_bodies: bool = True,
    observatory: str | int | tuple[float, float, float] = (0.0, 0.0, 0.0),
    chunk_size: int = 20000,
) -> Table:
    path = Path(xephem_csv).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(str(path))

    return minor_planet_check(
        ra=target.ra.to(u.deg).value,
        dec=target.dec.to(u.deg).value,
        epoch=epoch,
        search_radius=float(radius_arcsec),
        xephem_filepath=str(path),
        max_mag=max_mag,
        include_minor_bodies=include_minor_bodies,
        include_major_bodies=include_major_bodies,
        observatory=observatory,
        chunk_size=int(chunk_size),
    )

