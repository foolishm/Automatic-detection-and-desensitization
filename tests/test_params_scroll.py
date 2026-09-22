# -*- coding: utf-8 -*-
"""参数页：小窗口应可滚动；全屏内容能放下时滚轮不得再空滚。"""

import tkinter as tk

import _bootstrap
import face_video_detector as f


def _params_canvas(app):
    return app._params_canvas


def dump(app, tag):
    c = _params_canvas(app)
    app._sync_params_scroll()
    app.root.update_idletasks()
    app.root.update()
    bbox = c.bbox("all")
    content_h = bbox[3] - bbox[1] if bbox else 0
    ch = c.winfo_height()
    before = c.yview()
    c.yview_scroll(5, "units")
    after = c.yview()
    c.yview_moveto(0)
    print(tag, "canvas_h", ch, "content_h", content_h, "fits", content_h <= ch,
          "yview_before", before, "yview_after_scroll5", after)
    return content_h, ch, before, after


def main():
    exit_code = 1
    root = tk.Tk()
    app = f.FaceVideoApp(root)
    root.geometry("1120x720")
    root.update()
    app.show_params_page()
    root.update()
    root.update_idletasks()

    small_c, small_v, _, small_after = dump(app, "small")
    small_can_scroll = small_after[0] > 0.001

    root.geometry("1920x1080+0+0")
    root.update()
    root.update_idletasks()
    app._sync_params_scroll()
    root.update()
    full_c, full_v, full_before, full_after = dump(app, "1080p")

    app._toggle_maximize()
    root.update()
    root.update_idletasks()
    app._sync_params_scroll()
    root.update()
    max_c, max_v, max_before, max_after = dump(app, "maximize")

    # 小窗口内容超出视口时必须能滚
    # 全屏若内容已放下，滚动后 yview 必须仍停在顶部
    full_ok = True
    if full_c <= full_v:
        full_ok = full_after[0] <= 0.001
    max_ok = True
    if max_c <= max_v:
        max_ok = max_after[0] <= 0.001

    print("small_can_scroll", small_can_scroll, "full_ok", full_ok, "max_ok", max_ok)
    if small_can_scroll and full_ok and max_ok:
        print("PASS")
        exit_code = 0
    else:
        print("FAIL")
    app._on_close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
