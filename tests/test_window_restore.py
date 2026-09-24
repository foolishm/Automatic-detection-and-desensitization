# -*- coding: utf-8 -*-
"""最小化后能从任务栏恢复；保存提示不锁住主窗口。

用法：python tests/test_window_restore.py
"""

import ctypes
import sys
import tkinter as tk

import _bootstrap  # noqa: F401

import face_video_detector as f


WM_SYSCOMMAND = 0x0112
SC_RESTORE = 0xF120


def _parent(root):
    """Tk 顶层窗口句柄（任务栏按钮挂在这上面）。"""
    return ctypes.windll.user32.GetParent(root.winfo_id())


def check_taskbar_restore():
    """最小化后窗口仍在任务栏上，SC_RESTORE 能把它打开。"""
    root = tk.Tk()
    app = f.FaceVideoApp(root)
    ok = False
    try:
        for _ in range(20):
            root.update()
        parent = _parent(root)
        app._minimize()
        root.update()
        iconic = root.state() == "iconic"
        # 仍可见：任务栏按钮还在。withdraw 时这里会变成 0
        on_taskbar = bool(ctypes.windll.user32.IsWindowVisible(parent))
        ctypes.windll.user32.SendMessageW(parent, WM_SYSCOMMAND, SC_RESTORE, 0)
        root.update()
        ok = iconic and on_taskbar and root.state() == "normal"
        ok = ok and bool(ctypes.windll.user32.IsWindowVisible(parent))
    finally:
        try:
            app._on_close()
        except Exception:
            root.destroy()
    return ok


def check_saving_does_not_grab():
    """正在保存不抢模态，主窗口和任务栏还能动。"""
    root = tk.Tk()
    app = f.FaceVideoApp(root)
    ok = False
    try:
        for _ in range(10):
            root.update()
        dlg = f.messagebox.open_saving(root, lambda: None)
        root.update()
        ok = root.grab_current() is None
        ok = ok and bool(dlg.win.winfo_viewable())
        dlg.close()
        root.update()
    finally:
        try:
            app._on_close()
        except Exception:
            root.destroy()
    return ok


def main():
    restore_ok = check_taskbar_restore()
    grab_ok = check_saving_does_not_grab()
    print("restore", "PASS" if restore_ok else "FAIL")
    print("no-grab", "PASS" if grab_ok else "FAIL")
    ok = restore_ok and grab_ok
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
