# -*- coding: utf-8 -*-
"""复现：最大化显示大图后再还原，其它控件被视频区挤掉。"""

import numpy as np
import tkinter as tk

import _bootstrap
import face_video_detector as f


def main():
    exit_code = 1
    root = tk.Tk()
    app = f.FaceVideoApp(root)
    root.geometry("1120x720")
    root.update_idletasks()
    root.update()

    app._toggle_maximize()
    root.update_idletasks()
    root.update()

    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    frame[:, :] = (30, 30, 180)
    app.view_src._last_frame = frame
    app.view_src._show(frame)
    root.update_idletasks()
    root.update()

    app._toggle_maximize()
    root.geometry("1120x720")
    root.update_idletasks()
    root.update()

    win_bottom = root.winfo_rooty() + root.winfo_height()
    info = app.view_src.lbl_info
    info_bottom = info.winfo_rooty() + info.winfo_height()
    import_btn = app.view_src.btn_import
    video_h = app.view_src.video_panel.winfo_height()
    win_h = root.winfo_height()

    info_visible = info.winfo_viewable() and info_bottom <= win_bottom - 8
    btn_visible = import_btn.winfo_viewable() and import_btn.winfo_height() >= 8
    video_not_full = video_h < win_h * 0.82

    print("win", win_h, "video_h", video_h, "info_visible", info_visible,
          "btn_visible", btn_visible, "video_not_full", video_not_full)

    if info_visible and btn_visible and video_not_full:
        print("PASS")
        exit_code = 0
    else:
        print("FAIL: restored window layout swallowed by video")
    app._on_close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
