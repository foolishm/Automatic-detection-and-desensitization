# -*- coding: utf-8 -*-
"""脱敏率检测只用预处理人脸记录比对，不再重新读视频。

1. 记录查表判定 box_is_mosaic 与逐区域现算 is_mosaic 口径一致（马赛克算法本身）
2. _compute_desensitization 只按「原视频有人脸、脱敏视频没有人脸」判已脱敏，
   脱敏视频路径不存在也能出报告（证明没有重新打开视频）

用法：python tests/test_desens_records.py [视频路径]
"""

import sys
import tkinter as tk

import _bootstrap  # noqa: F401
import cv2

import face_video_detector as f
import desensitization_checker as dc

DEFAULT_VIDEO = r"e:\Users\Administrator\Desktop\Video_Chnl09_15fps.mp4"


def _sample_frames(path, step=200):
    frames = []
    cap = cv2.VideoCapture(path)
    if cap.isOpened():
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        for idx in range(0, total, step):
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            # 读失败的帧跳过
            if ok:
                frames.append(frame)
        cap.release()
    return frames


def check_record_matches_pixels(frames):
    """记录查表与逐区域现算的判定一致率。"""
    agree = 0
    total = 0
    for frame in frames:
        h, w = frame.shape[:2]
        record = f.frame_mosaic_record(frame)
        boxes = []
        # 棋盘格所在位置 + 固定网格上的若干框（含无马赛克区域）
        if record:
            boxes.extend(record["checker"])
        for gy in range(0, h - 60, 120):
            for gx in range(0, w - 50, 160):
                boxes.append((gx, gy, 50, 60))
        for box in boxes:
            x, y, bw, bh = box
            by_record = dc.box_is_mosaic(box, record)
            by_pixels = dc.is_mosaic(frame[y:y + bh, x:x + bw])
            total += 1
            if by_record == by_pixels:
                agree += 1
    return agree, total


def check_compute_without_video():
    """用假记录跑一次脱敏率计算，脱敏视频路径不存在也要能算出来。"""
    root = None
    app = None
    report = {"text": None}
    try:
        root = tk.Tk()
        root.withdraw()
        app = f.FaceVideoApp(root)
        root.update()
        # 原视频：3 个人脸帧；脱敏视频：帧 1 仍检出人脸、帧 0/2 没有人脸（马赛克记录不参与判定）
        app.src_info = {"path": "X:/no_such_src.mp4", "fps": 10.0, "total": 30, "done": True,
                        "faces": [(0, [(100, 100, 40, 50)]),
                                  (10, [(100, 100, 40, 50)]),
                                  (20, [(100, 100, 40, 50)])],
                        "mosaics": {}}
        app.dst_info = {"path": "X:/no_such_dst.mp4", "fps": 10.0, "total": 30, "done": True,
                        "faces": [(10, [(100, 100, 40, 50)])],
                        "mosaics": {0: {"checker": [(95, 95, 50, 60)], "solid": []}}}
        app._on_desens_computed = lambda text: report.__setitem__("text", text)
        app._compute_desensitization()
        # 后台线程用 root.after 回主线程，这里直接同步跑，处理一次事件队列即可
        root.update()
    finally:
        if app is not None:
            try:
                app._on_close()
            except Exception:
                if root is not None:
                    root.destroy()
        elif root is not None:
            root.destroy()
    return report["text"]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_VIDEO
    ok = True
    f.load_params()
    frames = _sample_frames(path)
    if not frames:
        print("SKIP: 无法读取视频", path)
    else:
        agree, total = check_record_matches_pixels(frames)
        print(f"记录查表 vs 逐区域现算 一致: {agree}/{total}")
        ok = ok and total > 0 and agree >= total * 0.95
    text = check_compute_without_video()
    print("报告:", (text or "").replace("\n", " | "))
    ok = ok and text is not None
    ok = ok and "原视频人脸数: 3 · 脱敏视频人脸数: 1" in text
    ok = ok and "帧率换算后原视频应脱敏人脸数: 3 · 帧率换算后脱敏视频检测出人脸数: 1" in text
    ok = ok and "已脱敏人脸数: 2" in text
    ok = ok and "换算公式:" in text
    ok = ok and "帧率换算后原视频应脱敏帧数: 3 · 帧率换算后脱敏视频检测出帧数: 1" in text
    ok = ok and "原帧10→脱敏帧10" not in (text or "")
    ok = ok and "全部人脸帧均已脱敏" not in (text or "")
    ok = ok and "未脱敏(无马赛克)" not in text
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
