# -*- coding: utf-8 -*-
"""深色主题弹窗模板。后续 info / error / warning 都走这里。"""

import tkinter as tk

from app.theme import (
    ACCENT, ACCENT_HOVER, ACCENT_RED, ACCENT_WARN, BG, BG_PANEL,
    BTN_ACCENT_BORDER, BTN_ACCENT_PRESS, FG,
)


_KIND_ACCENT = {
    "info": ACCENT,
    "error": ACCENT_RED,
    "warning": ACCENT_WARN,
}
_DIALOG_WIDTH = 420


def showinfo(title, message, parent=None, **kwargs):
    """信息提示（蓝强调）。"""
    host = kwargs["parent"] if "parent" in kwargs else parent
    return _show(title, message, "info", host)


def showerror(title, message, parent=None, **kwargs):
    """错误提示（红强调）。"""
    host = kwargs["parent"] if "parent" in kwargs else parent
    return _show(title, message, "error", host)


def showwarning(title, message, parent=None, **kwargs):
    """警告提示（橙强调）。"""
    host = kwargs["parent"] if "parent" in kwargs else parent
    return _show(title, message, "warning", host)


def open_saving(parent, on_cancel):
    """「正在保存」提示。返回对话框，close() 关掉；点取消或关闭会调用 on_cancel。"""
    dialog = _SavingDialog(parent, on_cancel)
    return dialog


class _SavingDialog(object):
    """非阻塞的保存中弹窗，主线程仍能收到取消。"""

    def __init__(self, parent, on_cancel):
        self._on_cancel = on_cancel
        self._closed = False
        parent = _resolve_parent(parent)
        win = tk.Toplevel(parent)
        win.withdraw()
        win.configure(bg=BG)
        win.resizable(False, False)
        win.overrideredirect(True)
        # 有父窗口时挂到父窗口上
        if parent is not None:
            win.transient(parent)
        win.attributes("-topmost", True)
        self.win = win

        header = tk.Frame(win, bg=BG_PANEL, height=36)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(header, text="正在保存", bg=BG_PANEL, fg=FG,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(
            side=tk.LEFT, padx=(14, 8))
        close_btn = tk.Button(
            header, text="✕", command=self._cancel,
            bg=BG_PANEL, fg=FG, activebackground=ACCENT_RED,
            activeforeground="#ffffff", relief=tk.FLAT, cursor="hand2",
            font=("Microsoft YaHei UI", 10), padx=12, pady=2, bd=0,
            highlightthickness=0, width=2)
        close_btn.pack(side=tk.RIGHT)

        tk.Frame(win, bg=ACCENT, height=2).pack(fill=tk.X)
        body = tk.Frame(win, bg=BG)
        body.pack(fill=tk.BOTH, expand=True, padx=18, pady=(16, 8))
        tk.Label(
            body, text="正在保存检测报告…", bg=BG, fg=FG,
            font=("Microsoft YaHei UI", 10), justify="left", anchor="w").pack(fill=tk.X)

        btn_row = tk.Frame(win, bg=BG)
        btn_row.pack(fill=tk.X, padx=18, pady=(8, 16))
        cancel_btn = tk.Button(
            btn_row, text="取消", command=self._cancel,
            bg=ACCENT, fg="#ffffff",
            activebackground=ACCENT_HOVER, activeforeground="#ffffff",
            relief=tk.FLAT, cursor="hand2",
            font=("Microsoft YaHei UI", 10, "bold"),
            padx=22, pady=6, bd=0, highlightthickness=1,
            highlightbackground=BTN_ACCENT_BORDER, highlightcolor=BTN_ACCENT_BORDER)
        cancel_btn.pack(side=tk.RIGHT)

        win.bind("<Escape>", lambda _event: self._cancel())
        win.update_idletasks()
        height = max(win.winfo_reqheight(), 140)
        _center_on_parent(win, parent, _DIALOG_WIDTH, height)
        win.deiconify()
        win.lift()
        # 不 grab_set：模态抢焦点会把主窗口和任务栏还原一起锁死，取消也点不了
        try:
            cancel_btn.focus_set()
        except Exception:
            pass
        return

    def _cancel(self):
        """通知调用方停写，并关掉提示。"""
        callback = self._on_cancel
        self.close()
        # 先关窗再回调，避免回调里再关一次时序搅在一起
        if callback is not None:
            callback()
        return

    def close(self):
        """关掉提示。重复调用无副作用。"""
        if not self._closed:
            self._closed = True
            try:
                self.win.grab_release()
            except Exception:
                pass
            try:
                self.win.destroy()
            except Exception:
                pass
        return


def _resolve_parent(parent):
    """没有显式 parent 时用 Tk 默认根窗口。"""
    result = parent
    if result is None:
        try:
            result = tk._get_default_root()
        except Exception:
            result = None
    return result


def _center_on_parent(win, parent, width, height):
    """把弹窗放到父窗口中央；没有父窗口则居中屏幕。"""
    x = 80
    y = 80
    if parent is not None and parent.winfo_exists():
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = max(parent.winfo_width(), 1)
        ph = max(parent.winfo_height(), 1)
        x = px + (pw - width) // 2
        y = py + (ph - height) // 2
    else:
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = (sw - width) // 2
        y = (sh - height) // 2
    if x < 0:
        x = 0
    if y < 0:
        y = 0
    win.geometry("%dx%d+%d+%d" % (width, height, x, y))
    return


def _show(title, message, kind, parent):
    """通用深色模态弹窗。返回 'ok'，API 与 tkinter.messagebox 对齐。"""
    result = "ok"
    parent = _resolve_parent(parent)
    accent = _KIND_ACCENT.get(kind, ACCENT)
    win = tk.Toplevel(parent)
    win.withdraw()
    win.configure(bg=BG)
    win.resizable(False, False)
    # 去掉系统标题栏，和主窗口一样用自绘顶栏
    win.overrideredirect(True)
    # 有父窗口时挂到父窗口上，避免沉到主窗口后面
    if parent is not None:
        win.transient(parent)
    win.attributes("-topmost", True)

    # 顶栏
    header = tk.Frame(win, bg=BG_PANEL, height=36)
    header.pack(fill=tk.X)
    header.pack_propagate(False)
    tk.Label(header, text=str(title), bg=BG_PANEL, fg=FG,
             font=("Microsoft YaHei UI", 10, "bold")).pack(
        side=tk.LEFT, padx=(14, 8))

    def _close(_event=None):
        try:
            win.grab_release()
        except Exception:
            pass
        win.destroy()
        return

    close_btn = tk.Button(
        header, text="✕", command=_close,
        bg=BG_PANEL, fg=FG, activebackground=ACCENT_RED,
        activeforeground="#ffffff", relief=tk.FLAT, cursor="hand2",
        font=("Microsoft YaHei UI", 10), padx=12, pady=2, bd=0,
        highlightthickness=0, width=2)
    close_btn.pack(side=tk.RIGHT)
    close_btn.bind("<Enter>", lambda e: close_btn.config(bg=ACCENT_RED, fg="#ffffff"))
    close_btn.bind("<Leave>", lambda e: close_btn.config(bg=BG_PANEL, fg=FG))

    # 拖动顶栏移动弹窗
    drag = {"x": 0, "y": 0}

    def _start_drag(event):
        drag["x"] = event.x_root - win.winfo_x()
        drag["y"] = event.y_root - win.winfo_y()
        return

    def _do_drag(event):
        win.geometry("+%d+%d" % (event.x_root - drag["x"], event.y_root - drag["y"]))
        return

    header.bind("<Button-1>", _start_drag)
    header.bind("<B1-Motion>", _do_drag)

    # 种类色条
    tk.Frame(win, bg=accent, height=2).pack(fill=tk.X)

    body = tk.Frame(win, bg=BG)
    body.pack(fill=tk.BOTH, expand=True, padx=18, pady=(16, 8))
    tk.Label(
        body, text=str(message), bg=BG, fg=FG,
        font=("Microsoft YaHei UI", 10), justify="left", anchor="w",
        wraplength=_DIALOG_WIDTH - 48).pack(fill=tk.X)

    btn_row = tk.Frame(win, bg=BG)
    btn_row.pack(fill=tk.X, padx=18, pady=(8, 16))
    ok_btn = tk.Button(
        btn_row, text="确定", command=_close,
        bg=ACCENT, fg="#ffffff",
        activebackground=ACCENT_HOVER, activeforeground="#ffffff",
        relief=tk.FLAT, cursor="hand2",
        font=("Microsoft YaHei UI", 10, "bold"),
        padx=22, pady=6, bd=0, highlightthickness=1,
        highlightbackground=BTN_ACCENT_BORDER, highlightcolor=BTN_ACCENT_BORDER)
    ok_btn.pack(side=tk.RIGHT)
    ok_btn.bind("<ButtonPress-1>", lambda e: ok_btn.config(bg=BTN_ACCENT_PRESS))
    ok_btn.bind("<ButtonRelease-1>", lambda e: ok_btn.config(bg=ACCENT))

    win.bind("<Escape>", _close)
    win.bind("<Return>", _close)
    win.update_idletasks()
    height = max(win.winfo_reqheight(), 140)
    _center_on_parent(win, parent, _DIALOG_WIDTH, height)
    win.deiconify()
    win.lift()
    try:
        win.grab_set()
    except Exception:
        pass
    ok_btn.focus_set()
    win.wait_window()
    return result
