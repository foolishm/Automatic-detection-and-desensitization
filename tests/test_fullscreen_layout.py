# -*- coding: utf-8 -*-
"""全屏：不盖任务栏；参数卡片限宽；右侧结果区撑满。"""

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
    app._sync_desens_panel()
    root.update_idletasks()
    root.update()

    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    wx = root.winfo_rootx()
    wy = root.winfo_rooty()
    ww = root.winfo_width()
    wh = root.winfo_height()
    # 允许边框几个像素，但不能按整屏铺出去盖住任务栏
    within_screen = (
        (wy + wh) <= (sh + 8)
        and (wx + ww) <= (sw + 8)
        and wh <= sh
    )
    result_h = app.desens_result.winfo_height()
    result_fills = result_h >= 400

    app.show_params_page()
    root.update_idletasks()
    root.update()
    app._sync_params_scroll()
    root.update_idletasks()
    root.update()
    canvas = app._params_canvas
    bbox = canvas.bbox(app._params_window)
    card_w = (bbox[2] - bbox[0]) if bbox else 0
    canvas_w = canvas.winfo_width()
    # 超宽视口时卡片必须限宽，不能拉到整屏
    card_ok = True
    if canvas_w > 1200:
        card_ok = card_w <= 970 and card_w < canvas_w * 0.6
    else:
        card_ok = card_w >= canvas_w - 8

    print(
        "screen", sw, sh, "win", wx, wy, ww, wh,
        "within", within_screen, "result_h", result_h,
        "card_w", card_w, "canvas_w", canvas_w, "card_ok", card_ok,
    )
    if within_screen and result_fills and card_ok:
        print("PASS: fullscreen layout")
        exit_code = 0
    else:
        print("FAIL: fullscreen layout")
    app._on_close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
