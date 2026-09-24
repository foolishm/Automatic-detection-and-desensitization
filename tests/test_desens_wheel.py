# -*- coding: utf-8 -*-
"""检测页右侧：滚轮滚统计区或漏帧列表，一屏放得下时不空滚。"""

import tkinter as tk

import _bootstrap  # noqa: F401
import face_video_detector as f


class _Event(object):
    def __init__(self, delta):
        self.delta = delta


def main():
    root = tk.Tk()
    app = f.FaceVideoApp(root)
    root.geometry("1280x520+40+40")
    root.update()
    root.update_idletasks()
    ok = True
    try:
        app._arm_right_wheel()
        bound = root.tk.call("bind", "all", "<MouseWheel>")
        ok = ok and bool(bound)

        for i in range(80):
            app.miss_list.insert(tk.END, "00:0%d 原帧%d → 00:0%d 脱敏帧%d  1/1" % (i, i, i, i))
        app.lbl_miss_empty.place_forget()
        root.update_idletasks()
        app._widget_under_pointer = lambda: app.miss_list
        before = app.miss_list.yview()
        app._on_right_mousewheel(_Event(-120))
        after = app.miss_list.yview()
        ok = ok and after[0] > before[0] + 0.001

        app._sync_desens_panel()
        root.update_idletasks()
        canvas = app._desens_canvas
        content_h = int(app._scroll_content.winfo_reqheight())
        view_h = canvas.winfo_height()
        app._widget_under_pointer = lambda: canvas
        canvas.yview_moveto(0)
        before_c = canvas.yview()
        app._on_right_mousewheel(_Event(-120))
        after_c = canvas.yview()
        # 统计区高出视口时必须滚；放得下则停在顶部
        if content_h > view_h:
            ok = ok and after_c[0] > before_c[0] + 0.001
        else:
            ok = ok and after_c[0] <= 0.001

        root.geometry("1280x1400+40+40")
        root.update()
        root.update_idletasks()
        app._desens_sync_key = None
        app._sync_desens_panel()
        root.update_idletasks()
        canvas.yview_moveto(0)
        app._on_right_mousewheel(_Event(-120))
        tall_content = int(app._scroll_content.winfo_reqheight())
        tall_view = canvas.winfo_height()
        if tall_content <= tall_view:
            ok = ok and canvas.yview()[0] <= 0.001
    finally:
        try:
            app._on_close()
        except Exception:
            root.destroy()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
