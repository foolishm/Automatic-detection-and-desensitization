# -*- coding: utf-8 -*-
"""漏脱敏列表：全量行、单击精确跳转、短视频停在指定帧号。"""

import os
import sys
import tempfile
import time
import tkinter as tk

import _bootstrap  # noqa: F401
import cv2
import numpy as np

import face_video_detector as f


def _faces(spec):
    rows = []
    for frame, count in spec:
        boxes = [(100, 100, 40, 50)] * count
        rows.append((frame, boxes))
    return rows


def _pair(src_faces, dst_faces, dst_total=30):
    src = {"path": "D:/样例/原视频.mp4", "fps": 10.0, "total": 30, "done": True,
           "width": 320, "height": 240,
           "faces": _faces(src_faces), "mosaics": {}}
    dst = {"path": "D:/样例/脱敏视频.mp4", "fps": 10.0, "total": dst_total, "done": True,
           "width": 320, "height": 240,
           "faces": _faces(dst_faces), "mosaics": {}}
    return src, dst


class _App(object):
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = f.FaceVideoApp(self.root)
        self.root.update()

    def close(self):
        try:
            self.app._on_close()
        except Exception:
            self.root.destroy()
        return


def _run(app, src, dst):
    app.src_info = src
    app.dst_info = dst
    app._compute_desensitization()
    app.root.update()
    return


def check_list_rows():
    """漏帧全部进列表；越界不进；结果框不再写逐条漏帧。"""
    host = _App()
    ok = True
    try:
        app = host.app
        ok = ok and app.root.geometry().startswith("1280x720")
        right = app.miss_list.master.master.master
        ok = ok and int(right.cget("width")) == 460
        _run(app, *_pair([(0, 1), (10, 2), (400, 1)], [(10, 1)], dst_total=30))
        text = app.desens_result.get("1.0", tk.END)
        ok = ok and app.miss_list.size() == 1
        ok = ok and app.lbl_miss_title.cget("text") == "漏脱敏帧（1）"
        line = app.miss_list.get(0)
        ok = ok and line == "00:01 原帧10 → 00:01 脱敏帧10  2/1"
        ok = ok and "原帧10" not in text
        ok = ok and "漏脱敏帧（" not in text
        ok = ok and "全部人脸帧均已脱敏" not in text
        _run(app, *_pair([(0, 1), (10, 1)], []))
        ok = ok and app.miss_list.size() == 0
        ok = ok and app.lbl_miss_title.cget("text") == "漏脱敏帧"
        ok = ok and bool(app.lbl_miss_empty.place_info())
    finally:
        host.close()
    return ok


def check_click_calls_show_frame():
    """单击一行把两边的帧号交给 show_frame；再点另一行不再使用前一次的帧号。"""
    host = _App()
    ok = True
    calls = []
    try:
        app = host.app
        _run(app, *_pair([(0, 1), (10, 1)], [(0, 1), (10, 1)]))
        ok = ok and app.miss_list.size() == 2

        def _src(frame_idx):
            calls.append(("src", frame_idx))
            return True

        def _dst(frame_idx):
            calls.append(("dst", frame_idx))
            return True

        app.view_src.show_frame = _src
        app.view_dst.show_frame = _dst
        app.miss_list.selection_clear(0, tk.END)
        app.miss_list.selection_set(0)
        app.miss_list.event_generate("<<ListboxSelect>>")
        app.miss_list.selection_clear(0, tk.END)
        app.miss_list.selection_set(1)
        app.miss_list.event_generate("<<ListboxSelect>>")
        ok = ok and calls == [
            ("src", 0), ("dst", 0),
            ("src", 10), ("dst", 10),
        ]
    finally:
        host.close()
    return ok


def _write_clip(path, count):
    writer = cv2.VideoWriter(
        path, cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (32, 32))
    opened = writer.isOpened()
    if opened:
        for i in range(count):
            frame = np.zeros((32, 32, 3), np.uint8)
            frame[:, :] = (i * 40, 20, 20)
            writer.write(frame)
    writer.release()
    return opened


def _pump(root, view, rounds=40):
    i = 0
    while i < rounds and view._exact_loading:
        root.update()
        time.sleep(0.05)
        i += 1
    root.update()
    return


def check_exact_show_frame(tmp):
    """短视频精确停在帧号上，经过「加载中」，往回跳不调用 cap.set。"""
    path = os.path.join(tmp, "clip.avi")
    ok = _write_clip(path, 6)
    if not ok:
        return False
    root = tk.Tk()
    root.geometry("640x480+80+80")
    view = f.VideoView(root, "原视频", lambda p=None: None)
    root.update()
    sets = []
    real_set = cv2.VideoCapture.set

    def _spy(self, prop, value):
        if int(prop) == int(cv2.CAP_PROP_POS_FRAMES):
            sets.append(value)
        return real_set(self, prop, value)

    cv2.VideoCapture.set = _spy
    try:
        ok = ok and view.load(path)
        view._cap_lock.acquire()
        ok = ok and view.show_frame(4)
        loading = bool(view.lbl_loading.place_info())
        ok = ok and loading
        ok = ok and view._frame_idx == 4
        view.show_frame(1)
        ok = ok and view._frame_idx == 1
        view._cap_lock.release()
        _pump(root, view)
        ok = ok and not view._exact_loading
        ok = ok and view._decode_idx == 1
        ok = ok and not view.lbl_loading.place_info()
        mean_b = float(view._last_raw[:, :, 0].mean())
        ok = ok and abs(mean_b - 40) < 8
        ok = ok and not sets
    finally:
        cv2.VideoCapture.set = real_set
        if view._cap_lock.locked():
            view._cap_lock.release()
        try:
            view._release()
        except Exception:
            pass
        root.destroy()
    return ok


def main():
    ok = check_list_rows()
    print("3.1", "PASS" if ok else "FAIL")
    click_ok = check_click_calls_show_frame()
    print("3.2", "PASS" if click_ok else "FAIL")
    tmp = tempfile.mkdtemp()
    try:
        seek_ok = check_exact_show_frame(tmp)
    finally:
        try:
            os.remove(os.path.join(tmp, "clip.avi"))
        except OSError:
            pass
        os.rmdir(tmp)
    print("3.3", "PASS" if seek_ok else "FAIL")
    all_ok = ok and click_ok and seek_ok
    print("PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
