# -*- coding: utf-8 -*-
"""复现：cap.set 跳转后不能再用 POS 去取预处理框画在当前画面上。"""

import numpy as np
import tkinter as tk

import _bootstrap
import face_video_detector as f


def _green_at(img, y, x):
    """检测框是 BGR 绿色 (0, 255, 0)。"""
    pix = img[y, x]
    return int(pix[1]) >= 200 and int(pix[0]) <= 40 and int(pix[2]) <= 40


def main():
    exit_code = 1
    root = tk.Tk()
    root.withdraw()
    view = f._VideoView(root, "原视频", lambda: None, config_key="show_boxes_src")
    view.show_boxes = True
    view.face_boxes_by_frame = {0: [(0, 0, 80, 80)]}
    frame = np.zeros((200, 200, 3), dtype=np.uint8)

    # 顺序播放、帧号可信：必须用预处理缓存框
    view._index_trusted = True
    stored = view._draw_boxes(frame.copy(), 0)
    stored_ok = _green_at(stored, 1, 1)

    # cap.set 之后帧号不可信：禁止再用缓存框（否则会画到别人脸上）
    view._index_trusted = False
    live = view._draw_boxes(frame.copy(), 0)
    live_ok = not _green_at(live, 1, 1)

    root.destroy()
    if stored_ok and live_ok:
        print("PASS: trusted uses cache, untrusted ignores stale boxes")
        exit_code = 0
    else:
        print(
            f"FAIL: stored_ok={stored_ok} live_ok={live_ok} "
            "(untrusted path still drew cached box)"
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
