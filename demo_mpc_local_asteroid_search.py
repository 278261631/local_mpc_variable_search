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
            f"无法解析 epoch={epoch!r}，可用 'now' 或 'mjd:60200.5' 或 ISO 时间字符串。\n{exc}"
        )


def _parse_observatory(value: str):
    if value is None:
        return (0.0, 0.0, 0.0)
    if "," in value:
        parts = [p.strip() for p in value.split(",")]
        if len(parts) != 3:
            raise SystemExit("--observatory 逗号形式需要 3 个数：lon_deg,rhocosphi,rhosinphi")
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    return value


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ra", required=True, help="RA：度数(如 120.5) 或时分秒(如 08:02:00)")
    p.add_argument("--dec", required=True, help="Dec：度数(如 -12.3) 或度分秒(如 -12:18:00)")
    p.add_argument("--epoch", default="now", help="观测历元：now / mjd:60200.5 / ISO 字符串")
    p.add_argument("--radius-arcsec", type=float, default=60.0, help="搜索半径(角秒)")
    p.add_argument("--xephem", required=True, help="本地 xephem CSV 路径（必填，先用 demo_mpc_prepare_xephem.py 生成）")
    p.add_argument("--max-mag", type=float, default=None, help="返回结果的最大星等限制")
    p.add_argument(
        "--observatory",
        default=None,
        help="台站：MPC 代码(如 500) 或 lon_deg,rhocosphi,rhosinphi",
    )
    p.add_argument("--no-minor", action="store_true", help="不搜索小天体(小行星/彗星)")
    p.add_argument("--no-major", action="store_true", help="不搜索大天体(行星/月)")
    p.add_argument("--chunk-size", type=int, default=20000, help="并行分块大小；0=禁用多进程")
    args = p.parse_args(argv)

    coo = _parse_skycoord(args.ra, args.dec)
    epoch = _parse_epoch(args.epoch)
    observatory = _parse_observatory(args.observatory)

    xephem_path = Path(args.xephem).expanduser() if args.xephem else None
    if xephem_path and not xephem_path.exists():
        raise SystemExit(f"找不到 --xephem 文件：{xephem_path}")

    if xephem_path is None or not xephem_path.exists():
        raise SystemExit(f"找不到 --xephem 文件：{xephem_path}")

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
        print("没有匹配结果")
        return 0

    cols = [c for c in ("name", "ra", "dec", "mag", "separation") if c in results.colnames]
    results.sort("separation")
    for line in results[cols].pformat(max_lines=50, max_width=160):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
