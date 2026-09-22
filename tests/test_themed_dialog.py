# -*- coding: utf-8 -*-
"""深色弹窗模板：背景色与主界面一致，且走兼容入口 messagebox。"""

import tkinter as tk

import _bootstrap
import face_video_detector as f


def test_themed_dialog_uses_app_bg():
    seen = {"bg": None, "over": None}
    root = tk.Tk()
    root.withdraw()
    root.update()

    def grab_and_close():
        for w in root.winfo_children():
            try:
                if w.winfo_class() != "Toplevel":
                    continue
                seen["bg"] = str(w.cget("bg"))
                seen["over"] = bool(w.overrideredirect())
                w.destroy()
            except tk.TclError:
                continue
        if seen["bg"] is None:
            root.after(20, grab_and_close)
        return

    root.after(80, grab_and_close)
    f.messagebox.showinfo("成功", "参数已保存，请重新导入视频进行分析。", parent=root)
    ok = seen["bg"] == "#0f1117" and bool(seen["over"])
    try:
        root.destroy()
    except tk.TclError:
        pass
    return ok, seen


def main():
    exit_code = 1
    ok, seen = test_themed_dialog_uses_app_bg()
    if ok:
        print("PASS: themed dialog bg=%s overrideredirect=%s" % (
            seen["bg"], seen["over"]))
        exit_code = 0
    else:
        print("FAIL: seen=%s expected bg=#0f1117" % seen)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
