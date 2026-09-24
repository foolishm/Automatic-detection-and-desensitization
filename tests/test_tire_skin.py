# -*- coding: utf-8 -*-
"""小框轮胎：几乎没有肤色且画面很暗才丢，马赛克人脸和有肤色的小脸留下。

用法：python tests/test_tire_skin.py
"""

import sys

import numpy as np

import _bootstrap  # noqa: F401
import face_video_detector as f
from app import settings as cfg


def _patch(h, w, bgr):
    """纯色图。"""
    img = np.zeros((h, w, 3), np.uint8)
    img[:, :] = bgr
    return img


def main():
    f.load_params()
    old = cfg.SKIN_FILTER_ENABLED
    ok = True
    try:
        cfg.SKIN_FILTER_ENABLED = True
        # 车轮：暗、无肤色、边长小于 60
        tire = _patch(40, 40, (20, 20, 20))
        ok = ok and f._reject_by_skin(tire, (4, 4, 28, 30))
        # 远处人脸：有肤色，即使偏暗也不丢
        skin = _patch(40, 40, (80, 130, 200))
        ok = ok and not f._reject_by_skin(skin, (4, 4, 28, 30))
        # 马赛克人脸：无肤色但更亮，小框不丢
        bright = _patch(40, 40, (180, 180, 180))
        ok = ok and not f._reject_by_skin(bright, (4, 4, 28, 30))
        # 开关关掉：轮胎也不丢
        cfg.SKIN_FILTER_ENABLED = False
        ok = ok and not f._reject_by_skin(tire, (4, 4, 28, 30))
    finally:
        cfg.SKIN_FILTER_ENABLED = old
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
