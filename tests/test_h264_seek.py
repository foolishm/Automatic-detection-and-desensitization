# -*- coding: utf-8 -*-
"""裸 H.264 不能 cap.set 跳转，必须顺序解码到目标帧（含回退重开）。"""

import os

import cv2
import numpy as np

import _bootstrap
import face_video_detector as f

H264 = r"E:\Users\Administrator\Desktop\Video_Chnl09.h264"


def _mean_diff(a, b):
    d = 1e9
    if a is not None and b is not None:
        d = float(np.mean(np.abs(a.astype(np.int16) - b.astype(np.int16))))
    return d


def _seq_frame(path, idx):
    cap = cv2.VideoCapture(path)
    frame = None
    ok = False
    i = 0
    while i <= idx:
        ok, frame = cap.read()
        if not ok:
            break
        i += 1
    cap.release()
    return frame if ok else None


def test_decode_seek_hits_target():
    """前进、后退都应解出与顺序读相同的那一帧，而不是只快进 GOP。"""
    ok_all = False
    d50 = d20 = d80 = dset = None
    if not os.path.isfile(H264):
        return False, "missing h264", d50, d20, d80, dset
    ref50 = _seq_frame(H264, 50)
    ref20 = _seq_frame(H264, 20)
    ref80 = _seq_frame(H264, 80)
    cap = cv2.VideoCapture(H264)
    ok0, f0 = cap.read()
    decode_idx = 0 if ok0 else -1
    cap, decode_idx, ok, f50 = f.decode_seek(cap, H264, decode_idx, 50, True)
    d50 = _mean_diff(f50, ref50)
    cap, decode_idx, ok2, f20 = f.decode_seek(cap, H264, decode_idx, 20, True)
    d20 = _mean_diff(f20, ref20)
    cap, decode_idx, ok3, f80 = f.decode_seek(cap, H264, decode_idx, 80, True)
    d80 = _mean_diff(f80, ref80)
    if cap is not None:
        cap.release()
    # 对照：cap.set 不能落到 50
    cap2 = cv2.VideoCapture(H264)
    cap2.read()
    cap2.set(cv2.CAP_PROP_POS_FRAMES, 50)
    _, fset = cap2.read()
    cap2.release()
    dset = _mean_diff(fset, ref50)
    ok_all = (
        ok and ok2 and ok3
        and d50 is not None and d50 < 1.0
        and d20 is not None and d20 < 1.0
        and d80 is not None and d80 < 1.0
    )
    return ok_all, "ok", d50, d20, d80, dset


def main():
    exit_code = 1
    seek_ok, why, d50, d20, d80, dset = test_decode_seek_hits_target()
    if seek_ok:
        print("PASS: h264 linear seek matches sequential frames")
        exit_code = 0
    else:
        print(
            f"FAIL: why={why} d50={d50} d20={d20} d80={d80} "
            f"cap.set_vs_50={dset}"
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
