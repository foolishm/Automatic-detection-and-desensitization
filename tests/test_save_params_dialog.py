# -*- coding: utf-8 -*-
"""参数页点保存后必须弹出成功提示。"""

import tkinter as tk

import _bootstrap
import face_video_detector as f


def test_save_params_shows_info():
    shown = {"n": 0, "title": None, "msg": None}

    def fake_info(title, msg, **_kwargs):
        shown["n"] += 1
        shown["title"] = title
        shown["msg"] = msg
        return "ok"

    old = f.messagebox.showinfo
    f.messagebox.showinfo = fake_info
    root = None
    app = None
    exit_ok = False
    try:
        root = tk.Tk()
        root.withdraw()
        app = f.FaceVideoApp(root)
        root.update()
        app._save_params()
        exit_ok = (
            shown["n"] == 1
            and shown["title"] == "成功"
            and "已保存" in shown["msg"]
        )
    finally:
        f.messagebox.showinfo = old
        if app is not None:
            try:
                app._on_close()
            except Exception:
                if root is not None:
                    root.destroy()
        elif root is not None:
            root.destroy()
    return exit_ok, shown


def main():
    exit_code = 1
    ok, shown = test_save_params_shows_info()
    if ok:
        print("PASS: save params shows info dialog")
        exit_code = 0
    else:
        print("FAIL: shown=%s" % shown)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
