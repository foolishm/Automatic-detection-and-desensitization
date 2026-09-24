# -*- coding: utf-8 -*-
"""最小马赛克边长可在参数页设置，并真正参与过滤。

用法：python tests/test_mosaic_min_side.py
"""

import sys

import _bootstrap  # noqa: F401
import numpy as np

import face_video_detector as f
from app import settings as cfg


def _checker_patch(size=24, cell=2):
    """灰底上贴一块 size×size 的 2px 实心棋盘格。"""
    frame = np.full((80, 80, 3), 80, np.uint8)
    y0, x0 = 28, 28
    for y in range(size):
        for x in range(size):
            on = ((x // cell) + (y // cell)) % 2 == 0
            frame[y0 + y, x0 + x] = 255 if on else 0
    return frame


def main():
    ok = True
    f.load_params()
    keys = [p["key"] for p in f.PARAM_DEFS]
    ok = ok and "MOSAIC_MASK_MIN_SIDE" in keys
    frame = _checker_patch()
    # 默认 6：24px 码块应留下
    f.apply_params({"MOSAIC_MASK_MIN_SIDE": 6})
    ok = ok and cfg.MOSAIC_MASK_MIN_SIDE == 6
    mask_keep = f.checker_mosaic_mask(frame, cells=(2,))
    keep = bool(mask_keep.any())
    print("min_side=6 命中:", keep)
    ok = ok and keep
    # 调到 40：24px 码块应被滤掉
    f.apply_params({"MOSAIC_MASK_MIN_SIDE": 40})
    ok = ok and cfg.MOSAIC_MASK_MIN_SIDE == 40
    mask_drop = f.checker_mosaic_mask(frame, cells=(2,))
    drop = not bool(mask_drop.any())
    print("min_side=40 滤掉:", drop)
    ok = ok and drop
    f.apply_params({"MOSAIC_MASK_MIN_SIDE": 6})
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
