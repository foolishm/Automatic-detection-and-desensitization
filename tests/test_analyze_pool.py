# -*- coding: utf-8 -*-
"""多线程有序帧分析池：结果顺序、内容与单线程逐帧完全一致，且明显更快。

用法：python tests/test_analyze_pool.py [视频路径]
"""

import sys
import time

import _bootstrap  # noqa: F401
import cv2
import numpy as np

import face_video_detector as f

DEFAULT_VIDEO = r"e:\Users\Administrator\Desktop\Video_Chnl09_15fps.mp4"


def _read_frames(path, start, count):
    frames = []
    cap = cv2.VideoCapture(path)
    if cap.isOpened():
        cap.set(cv2.CAP_PROP_POS_FRAMES, start)
        for _ in range(count):
            ok, frame = cap.read()
            # 读到尾就停
            if not ok:
                break
            frames.append(frame)
        cap.release()
    return frames


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_VIDEO
    ok = True
    f.load_params()
    frames = _read_frames(path, 4200, 90)
    if not frames:
        print("SKIP: 无法读取视频", path)
    else:
        # 单线程基准
        det = f.FaceDetector()
        t0 = time.perf_counter()
        serial = [f.analyze_frame(det, fr, True) for fr in frames]
        t_serial = time.perf_counter() - t0
        det.close()
        # 线程池
        pool = f.FrameAnalyzerPool(with_mosaic=True)
        t0 = time.perf_counter()
        parallel = list(pool.run(iter(frames), lambda: True))
        t_pool = time.perf_counter() - t0
        pool.close()
        print(f"workers={pool.workers} 单线程 {t_serial:.2f}s  线程池 {t_pool:.2f}s  "
              f"加速 {t_serial / max(t_pool, 1e-6):.2f}x")
        # 1. 顺序：帧号 0..n-1 严格递增
        ok = ok and [i for i, _ in parallel] == list(range(len(frames)))
        # 2. 内容：人脸框与马赛克记录逐帧相同
        def _same_record(a, b):
            """马赛克记录相等：checker 是 tuple 列表，solid 是 int16 数组。"""
            equal = a is None and b is None
            if a is not None and b is not None:
                equal = (a["checker"] == b["checker"]
                         and np.array_equal(a["solid"], b["solid"]))
            return equal

        same = all(
            r.boxes == s.boxes and _same_record(r.record, s.record)
            and r.display_rects == s.display_rects
            for (_i, r), s in zip(parallel, serial))
        print("结果一致:", same, "· 人脸帧", sum(1 for s in serial if s.boxes),
              "· 马赛克帧", sum(1 for s in serial if s.record))
        ok = ok and same
        # 3. 多核机器上应有明显加速
        if pool.workers > 1:
            ok = ok and t_pool < t_serial * 0.7
        # 4. still_alive 变 False 时提前停止，不再消费后续帧
        pool = f.FrameAnalyzerPool(with_mosaic=False)
        alive = {"n": 0}

        def _alive():
            alive["n"] += 1
            return alive["n"] <= 5

        got = list(pool.run(iter(frames), _alive))
        pool.close()
        print("提前停止后产出帧数:", len(got))
        ok = ok and len(got) < len(frames)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
