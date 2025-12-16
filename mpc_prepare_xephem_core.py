"""主程序：准备 pympc 所需的本地 xephem 轨道库（CSV）。

该模块不负责命令行解析；请用 demo_mpc_prepare_xephem.py 作为运行入口。
"""

from __future__ import annotations

from pathlib import Path

from pympc.pympc import update_catalogue


def prepare_xephem(
    cat_dir: str | Path = ".cache",
    include_nea: bool = True,
    include_comets: bool = True,
    cleanup: bool = True,
) -> Path:
    """下载/更新 MPC 轨道目录并生成 xephem CSV。

    返回：生成的 xephem CSV 绝对路径。

    注意：需要网络。
    """

    out_dir = Path(cat_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    xephem_csv = update_catalogue(
        include_nea=include_nea,
        include_comets=include_comets,
        cat_dir=str(out_dir),
        cleanup=cleanup,
    )
    return Path(xephem_csv).resolve()

