# -*- coding: utf-8 -*-
"""验证启动后系统标题栏会被移除（窗口映射后再改 TkTopLevel 样式）。"""

import ctypes
import os
import tkinter as tk

import _bootstrap
import face_video_detector as f

WS_CAPTION = 0x00C00000
GWL_STYLE = -16


def _toplevel_style(root):
    user32 = ctypes.windll.user32
    child = root.winfo_id()
    parent = user32.GetParent(child)
    target = parent if parent else child
    style = user32.GetWindowLongW(target, GWL_STYLE) & 0xFFFFFFFF
    return style


def main():
    exit_code = 1
    if os.name != "nt":
        print("SKIP: Windows only")
        exit_code = 0
    else:
        root = tk.Tk()
        app = f.FaceVideoApp(root)
        result = {"style": None, "caption": True}

        def check():
            result["style"] = _toplevel_style(root)
            result["caption"] = bool(result["style"] & WS_CAPTION)
            root.quit()

        # 等主循环映射窗口，并给隐藏逻辑足够的重试时间
        root.after(1500, check)
        root.mainloop()
        app._on_close()
        if result["caption"]:
            print("FAIL: native caption still present style=0x%08X" % result["style"])
        else:
            print("PASS: native caption removed style=0x%08X" % result["style"])
            exit_code = 0
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
