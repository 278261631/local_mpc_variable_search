"""演示：生成/更新 pympc 所需的本地 xephem 轨道库（CSV）。

该脚本会调用 pympc.pympc.update_catalogue 下载 MPCORB/NEA/Comet 并生成 xephem CSV。
生成完成后，把输出路径传给 demo_mpc_local_asteroid_search.py 的 --xephem 即可离线检索。

注意：此步骤需要网络。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pympc.pympc import update_catalogue


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cat-dir", default=".cache", help="目录：保存下载文件与生成的 xephem CSV")
    p.add_argument("--no-nea", action="store_true", help="不合并 NEA 目录")
    p.add_argument("--no-comets", action="store_true", help="不合并彗星目录")
    p.add_argument("--no-cleanup", action="store_true", help="保留下载的原始文件")
    args = p.parse_args(argv)

    cat_dir = Path(args.cat_dir).expanduser().resolve()
    cat_dir.mkdir(parents=True, exist_ok=True)

    xephem_csv = update_catalogue(
        include_nea=not args.no_nea,
        include_comets=not args.no_comets,
        cat_dir=str(cat_dir),
        cleanup=not args.no_cleanup,
    )

    print(str(Path(xephem_csv).resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

