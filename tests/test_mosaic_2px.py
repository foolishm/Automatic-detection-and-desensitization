# -*- coding: utf-8 -*-
"""2px 实心棋盘格马赛克必须能被定位（桌面「脱敏视频.mp4」这类设备码）。

现有粗到精只认 4/6/8px，半分辨率还会把 2px 黑白格平均成灰，整帧记不到棋盘格，
脱敏率就会全部落成「未脱敏(无马赛克)」。

用法：python tests/test_mosaic_2px.py [视频路径]
"""

import sys

import _bootstrap  # noqa: F401
import cv2
import numpy as np

import face_video_detector as f
import desensitization_checker as dc

DEFAULT_VIDEO = r"E:\Users\Administrator\Desktop\脱敏视频\脱敏视频.mp4"
# 120s 处五张脸上的实心棋盘格（脱敏视频 1280×720，对照 dest_120 画面）
MOSAIC_BOXES = (
    (154, 338, 60, 97),
    (421, 342, 51, 61),
    (661, 349, 65, 69),
    (1023, 386, 35, 43),
    (1166, 312, 38, 70),
)


def _read_frame(path, seconds=120.0):
    frame = None
    cap = cv2.VideoCapture(path)
    # 打不开或读失败时返回 None，由 main 判 SKIP
    if cap.isOpened():
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(seconds * fps)))
        ok, im = cap.read()
        if ok:
            frame = im
        cap.release()
    return frame


def _box_hit(mask, box, ratio=0.3):
    x, y, w, h = box
    sub = mask[y:y + h, x:x + w]
    return bool(sub.size) and float((sub > 0).mean()) >= ratio


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_VIDEO
    ok = True
    f.load_params()
    frame = _read_frame(path)
    if frame is None:
        print("SKIP: 无法读取视频", path)
        return 0

    mask = f.checker_mosaic_mask(frame)
    mask_2px = f.checker_mosaic_mask(frame, cells=(2,))
    hits = sum(1 for box in MOSAIC_BOXES if _box_hit(mask, box))
    area = float((mask > 0).mean())
    print(f"2px 棋盘格命中: {hits}/{len(MOSAIC_BOXES)}，掩码覆盖 {area:.3%}")
    # 细格已经命中时默认路径必须跳过 4/6/8，结果与只跑 2px 相同
    same_2px = bool(np.array_equal(mask, mask_2px))
    print(f"默认路径 == 只跑 2px: {same_2px}")
    # 五张脸都应落到掩码里，且不能把整帧墙面/天空涂掉
    ok = ok and hits >= 4 and area < 0.08 and same_2px

    record = f.frame_mosaic_record(frame)
    checkers = record.get("checker", ()) if record else ()
    print(f"记录棋盘格矩形: {len(checkers)}")
    ok = ok and len(checkers) >= 4

    # 判定算法本身也要认这档码，不能只靠涂抹预处理
    mosaic_ok = 0
    for box in MOSAIC_BOXES:
        x, y, w, h = box
        if dc.is_mosaic(frame[y:y + h, x:x + w]):
            mosaic_ok += 1
    print(f"is_mosaic 命中: {mosaic_ok}/{len(MOSAIC_BOXES)}")
    ok = ok and mosaic_ok >= 4

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
