# -*- coding: utf-8 -*-
"""自绘标题栏、托盘、无边框窗口。"""

import os
import sys
import tkinter as tk

from app.theme import (
    ACCENT, ACCENT_RED, BG_HOVER, BG_PANEL, BORDER, FG, FG_MUTED,
    TB_ICON_MAXIMIZE, TB_ICON_RESTORE, TB_MDL2_FONT,
)
from app.ui.drop import _hdrop_paths, _warn_drop_not_video, pick_dropped_video


class TitlebarMixin(object):
    def _hide_native_titlebar(self):
        """移除系统标题栏样式，但保留任务栏可见性。

        关键：不用 overrideredirect（它会抹掉任务栏显示）。
        Tk 的窗口是「父窗口(带标题栏) + 子窗口(显示区)」结构，
        root.winfo_id() 拿到的是子窗口，真正的系统标题栏在父窗口上。
        窗口未映射时父窗口还不存在，必须等 mapped 且 GetParent 有效后再改样式。
        """
        max_tries = 40
        retry_ms = 50
        # 仅 Windows 可通过 Win32 样式去掉系统标题栏
        if os.name == "nt":
            try:
                import ctypes
                # 窗口已销毁则不再处理
                if self.root.winfo_exists():
                    user32 = ctypes.windll.user32
                    hwnd = self.root.winfo_id()
                    parent = user32.GetParent(hwnd)
                    mapped = self.root.winfo_ismapped()
                    # 尚未映射或还没有 TkTopLevel 父窗口：改子窗口无效，推迟重试
                    if (not mapped) or (not parent):
                        # 限制重试次数，避免窗口异常时空转
                        if self._hide_tb_tries < max_tries:
                            self._hide_tb_tries += 1
                            self.root.after(retry_ms, self._hide_native_titlebar)
                    else:
                        # 已拿到带系统标题栏的父窗口，移除标题栏与可缩放边框
                        GWL_STYLE = -16
                        WS_CAPTION = 0x00C00000      # 标题栏（WS_BORDER|WS_DLGFRAME）
                        WS_THICKFRAME = 0x00040000   # 可缩放粗边框
                        SWP_FRAMECHANGED = 0x0020
                        SWP_NOMOVE = 0x0002
                        SWP_NOSIZE = 0x0001
                        SWP_NOZORDER = 0x0004
                        SWP_NOACTIVATE = 0x0010

                        style = user32.GetWindowLongW(parent, GWL_STYLE)
                        style &= ~WS_CAPTION
                        style &= ~WS_THICKFRAME
                        user32.SetWindowLongW(parent, GWL_STYLE, style)
                        user32.SetWindowPos(
                            parent, 0, 0, 0, 0, 0,
                            SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE |
                            SWP_NOZORDER | SWP_NOACTIVATE)
                        # 禁止 DWM 把玻璃效果伸进客户区，否则空视频区会透视后面窗口
                        class MARGINS(ctypes.Structure):
                            _fields_ = [
                                ("cxLeftWidth", ctypes.c_int),
                                ("cxRightWidth", ctypes.c_int),
                                ("cyTopHeight", ctypes.c_int),
                                ("cyBottomHeight", ctypes.c_int),
                            ]
                        margins = MARGINS(0, 0, 0, 0)
                        ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(
                            parent, ctypes.byref(margins))
                        # 强制顶层窗口不透明，避免去掉标题栏后客户区被 DWM 当玻璃透视
                        GWL_EXSTYLE = -20
                        WS_EX_LAYERED = 0x00080000
                        LWA_ALPHA = 0x00000002
                        exstyle = user32.GetWindowLongW(parent, GWL_EXSTYLE)
                        user32.SetWindowLongW(parent, GWL_EXSTYLE, exstyle | WS_EX_LAYERED)
                        user32.SetLayeredWindowAttributes(parent, 0, 255, LWA_ALPHA)
                        # 分层顶层窗口也要允许拖放，否则资源管理器命中父窗口会禁止放下
                        ctypes.windll.shell32.DragAcceptFiles(parent, True)
                        self.root.after(0, self._enable_toplevel_file_drop)
                        # 样式改完后空视频区要重新铺像素，否则会透视
                        if hasattr(self, "view_src"):
                            self.view_src._on_video_resize()
                        if hasattr(self, "view_dst"):
                            self.view_dst._on_video_resize()
            except Exception:
                # 去标题栏失败时保持系统默认窗口，不影响主功能
                pass
        return

    def _enable_toplevel_file_drop(self):
        """挂钩 TkTopLevel：只记录 HDROP 路径，不在 WndProc 里调用 Tk。"""
        if os.name != "nt":
            return
        if self._top_drop_cb is not None:
            return
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        try:
            parent = int(user32.GetParent(self.root.winfo_id()))
        except (tk.TclError, ValueError, TypeError):
            parent = 0
        if not parent:
            return
        WM_DROPFILES = 0x0233
        GWL_WNDPROC = -4
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(
            LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        get_long = user32.GetWindowLongPtrW
        set_long = user32.SetWindowLongPtrW
        get_long.argtypes = [wintypes.HWND, ctypes.c_int]
        get_long.restype = ctypes.c_void_p
        set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        set_long.restype = ctypes.c_void_p
        user32.CallWindowProcW.argtypes = [
            ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
            wintypes.WPARAM, wintypes.LPARAM]
        user32.CallWindowProcW.restype = LRESULT
        old_proc = get_long(parent, GWL_WNDPROC)

        WM_SYSCOMMAND = 0x0112
        SC_RESTORE = 0xF120

        def _wndproc(h, msg, wp, lp):
            result = 0
            if msg == WM_DROPFILES:
                try:
                    self._pending_drop_paths = _hdrop_paths(wp)
                    self._pending_drop_bad = False
                except Exception:
                    self._pending_drop_bad = True
                result = 0
            else:
                # 任务栏再次点击会发 SC_RESTORE；无标题栏时 Tk 经常停在最小化状态
                if msg == WM_SYSCOMMAND and (int(wp) & 0xFFF0) == SC_RESTORE:
                    try:
                        self.root.after(0, self._restore_main_window)
                    except Exception:
                        pass
                result = user32.CallWindowProcW(old_proc, h, msg, wp, lp)
            return result

        cb = WNDPROC(_wndproc)
        set_long(parent, GWL_WNDPROC, ctypes.cast(cb, ctypes.c_void_p))
        shell32.DragAcceptFiles(wintypes.HWND(parent), True)
        self._top_drop_cb = cb
        return

    def _import_from_drop_paths(self, paths):
        """按当前指针所在画面区导入拖入的视频。"""
        chosen = pick_dropped_video(paths)
        if not chosen:
            _warn_drop_not_video()
            return
        x = self.root.winfo_pointerx()
        y = self.root.winfo_pointery()
        widget = self.root.winfo_containing(x, y)
        view = None
        src_set = {
            self.view_src.video_panel, self.view_src.canvas,
            self.view_src.lbl_drop_hint, self.view_src.frame,
        }
        dst_set = {
            self.view_dst.video_panel, self.view_dst.canvas,
            self.view_dst.lbl_drop_hint, self.view_dst.frame,
        }
        w = widget
        while w is not None:
            # 命中原视频区域
            if w in src_set:
                view = self.view_src
                break
            # 命中脱敏视频区域
            if w in dst_set:
                view = self.view_dst
                break
            w = getattr(w, "master", None)
        if view is None:
            return
        view.on_import(chosen)
        return

    def _setup_tray_icon(self):
        """创建系统托盘图标（深色主题蓝色圆点），支持左键恢复窗口、右键菜单退出。"""
        if os.name != "nt":
            return
        try:
            import PIL.Image
            import PIL.ImageDraw
            import pystray
            from pystray import MenuItem, Menu

            # 生成一个简单的蓝色圆点图标（64x64）
            img = PIL.Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            d = PIL.ImageDraw.Draw(img)
            d.ellipse([8, 8, 56, 56], fill=(79, 140, 255, 255))  # #4f8cff
            d.ellipse([20, 20, 44, 44], fill=(16, 17, 23, 255))  # 内圈深色

            def on_show(icon, item):
                # 托盘回调在 pystray 线程，不能直接动 Tk
                try:
                    self.root.after(0, self._restore_from_tray)
                except Exception:
                    pass

            def on_quit(icon, item):
                icon.stop()
                self.root.after(0, self._on_close)

            menu = Menu(
                MenuItem("显示窗口", on_show, default=True),
                MenuItem("退出", on_quit),
            )
            self._tray = pystray.Icon(
                "face_desens", img, "人脸脱敏率检测工具", menu)
            # 托盘图标在独立线程运行
            import threading
            threading.Thread(target=self._tray.run, daemon=True).start()
        except Exception:
            self._tray = None

    def _restore_main_window(self):
        """把主窗口从最小化或隐藏恢复到前台。必须在主线程调用。"""
        # 已经在前台就不必再 deiconify，避免把正在拖动的窗口抖一下
        if self.root.state() != "normal":
            self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except Exception:
            pass
        return

    def _restore_from_tray(self):
        """从托盘恢复窗口。"""
        self._restore_main_window()
        return

    # ---------- 自绘深色标题栏 ----------
    def _build_titlebar(self):
        """构建自绘深色标题栏：应用标题 + 最小化/最大化/关闭按钮 + 拖动支持。"""
        self._tb = tk.Frame(self.root, bg=BG_PANEL, height=36,
                            highlightthickness=0)
        self._tb.pack(fill=tk.X)
        self._tb.pack_propagate(False)

        # 左侧：应用图标占位 + 标题
        tk.Label(self._tb, text="●", bg=BG_PANEL, fg=ACCENT,
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=(14, 4))
        self._tb_title = tk.Label(self._tb, text="人脸脱敏率检测工具",
                                  bg=BG_PANEL, fg=FG,
                                  font=("Microsoft YaHei UI", 10))
        self._tb_title.pack(side=tk.LEFT)

        # 右侧：三个窗口控制按钮
        close_btn = self._make_tb_btn("✕", self._close_titlebar, "#042010")
        close_btn.pack(side=tk.RIGHT)
        close_btn.bind("<Enter>", lambda e: close_btn.config(bg=ACCENT_RED, fg="#ffffff"))
        close_btn.bind("<Leave>", lambda e: close_btn.config(bg=BG_PANEL, fg=FG))
        self._tb_max_btn = self._make_tb_btn(
            TB_ICON_MAXIMIZE, self._toggle_maximize, font=TB_MDL2_FONT)
        self._tb_max_btn.pack(side=tk.RIGHT)
        self._tb_min_btn = self._make_tb_btn("—", self._minimize)
        self._tb_min_btn.pack(side=tk.RIGHT)

        # 拖动标题栏移动窗口
        self._tb.bind("<Button-1>", self._start_drag)
        self._tb.bind("<B1-Motion>", self._do_drag)
        self._tb.bind("<Double-Button-1>", lambda e: self._toggle_maximize())
        self._tb_title.bind("<Button-1>", self._start_drag)
        self._tb_title.bind("<B1-Motion>", self._do_drag)
        self._tb_title.bind("<Double-Button-1>", lambda e: self._toggle_maximize())

    def _make_tb_btn(self, text, command, hover_bg=BG_HOVER, font=None):
        # 未指定字体时沿用标题栏默认中文字体
        if font is None:
            font = ("Microsoft YaHei UI", 10)
        btn = tk.Button(self._tb, text=text, command=command,
                        bg=BG_PANEL, fg=FG, activebackground=hover_bg,
                        activeforeground="#ffffff", relief=tk.FLAT,
                        cursor="hand2", font=font,
                        padx=12, pady=2, bd=0, highlightthickness=0,
                        width=2)
        return btn

    def _begin_native_window_drag(self):
        """把拖动交给 Windows 原生标题栏移动，避免 geometry 逐帧改位造成残影。"""
        ok = False
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = self.root.winfo_id()
            parent = user32.GetParent(hwnd)
            # 必须发给 TkTopLevel 父窗口，改子窗口不会移动整窗
            target = parent if parent else hwnd
            WM_NCLBUTTONDOWN = 0x00A1
            HTCAPTION = 2
            user32.ReleaseCapture()
            posted = user32.PostMessageW(target, WM_NCLBUTTONDOWN, HTCAPTION, 0)
            ok = bool(posted)
        except Exception:
            ok = False
        return ok

    def _start_drag(self, event):
        # 已最大化时禁止拖动，避免从最大化位置被拽乱
        if not self._maximized:
            used_native = False
            # Windows 上优先走系统拖动（DWM 整窗合成，无残影）
            if os.name == "nt":
                used_native = self._begin_native_window_drag()
            self._native_drag = used_native
            # 原生拖动失败或非 Windows：记下偏移，交给 _do_drag
            if not used_native:
                self._drag_x = event.x
                self._drag_y = event.y
        return

    def _do_drag(self, event):
        # 最大化或已交由系统拖动时，不再用 geometry 逐帧改位置
        if (not self._maximized) and (not self._native_drag):
            x = self.root.winfo_pointerx() - self._drag_x
            y = self.root.winfo_pointery() - self._drag_y
            self.root.geometry(f"+{x}+{y}")
        return

    def _work_area(self):
        """屏幕去掉任务栏后的工作区 (x, y, w, h)。"""
        x = 0
        y = 0
        w = int(self.root.winfo_screenwidth())
        h = int(self.root.winfo_screenheight())
        # Windows：按 SPI_GETWORKAREA 避开任务栏，禁止用整屏尺寸盖住任务栏
        if os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes

                class RECT(ctypes.Structure):
                    _fields_ = [
                        ("left", wintypes.LONG),
                        ("top", wintypes.LONG),
                        ("right", wintypes.LONG),
                        ("bottom", wintypes.LONG),
                    ]

                rect = RECT()
                SPI_GETWORKAREA = 0x0030
                ok = ctypes.windll.user32.SystemParametersInfoW(
                    SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
                if ok:
                    x = int(rect.left)
                    y = int(rect.top)
                    w = int(rect.right - rect.left)
                    h = int(rect.bottom - rect.top)
            except Exception:
                pass
        return x, y, w, h

    def _set_window_rect(self, x, y, w, h):
        """把顶层窗口放到指定矩形。Windows 上改 TkTopLevel，避免边框把尺寸撑出工作区。"""
        placed = False
        if os.name == "nt":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                hwnd = self.root.winfo_id()
                parent = user32.GetParent(hwnd)
                target = parent if parent else hwnd
                SWP_NOZORDER = 0x0004
                SWP_NOACTIVATE = 0x0010
                user32.SetWindowPos(target, 0, int(x), int(y), int(w), int(h),
                                    SWP_NOZORDER | SWP_NOACTIVATE)
                placed = True
            except Exception:
                placed = False
        # 非 Windows 或 Win32 失败：回退 geometry
        if not placed:
            self.root.geometry("%dx%d+%d+%d" % (w, h, x, y))
        return

    def _toggle_maximize(self):
        if self._maximized:
            # 还原到最大化前的窗口几何
            if self._normal_geometry:
                self.root.geometry(self._normal_geometry)
            self._maximized = False
            self._tb_max_btn.config(text=TB_ICON_MAXIMIZE)
            self.root.after_idle(self._sync_params_scroll)
            if hasattr(self, "_sync_desens_panel"):
                self.root.after_idle(self._sync_desens_panel)
        else:
            # 最大化到工作区（保留任务栏），不要用整屏宽高去盖住任务栏
            self._normal_geometry = self.root.geometry()
            x, y, w, h = self._work_area()
            self._set_window_rect(x, y, w, h)
            self._maximized = True
            self._tb_max_btn.config(text=TB_ICON_RESTORE)
            self.root.after_idle(self._sync_params_scroll)
            if hasattr(self, "_sync_desens_panel"):
                self.root.after_idle(self._sync_desens_panel)
        return

    def _minimize(self):
        # 最小化到任务栏。withdraw 会把按钮从任务栏拿掉，再点任务栏图标无法恢复。
        self.root.iconify()

    def _close_titlebar(self):
        self._on_close()


    def _consume_toplevel_drop(self):
        """消费顶层窗口记下的拖入路径。"""
        paths = self._pending_drop_paths
        bad = self._pending_drop_bad
        self._pending_drop_paths = None
        self._pending_drop_bad = False
        if paths:
            self._import_from_drop_paths(paths)
        elif bad:
            _warn_drop_not_video()
        return


def _enable_dark_titlebar(root):
    """在 Windows 上把窗口标题栏设为深色（与深色主题统一）。

    通过 DwmSetWindowAttribute 设置 DWMWA_USE_IMMERSIVE_DARK_MODE，
    并配合 SetPreferredAppMode 开启深色模式偏好。仅 Windows 有效，失败静默忽略。
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        # 1) 应用级深色模式偏好（Windows 10 1809+）
        try:
            ctypes.windll.uxtheme.SetPreferredAppMode(1)  # 1 = AllowDark
        except Exception:
            pass
        # 2) 标题栏深色（需要窗口已映射后设置）
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20（旧版是 19）
        value = ctypes.c_int(1)
        for attr in (20, 19):
            try:
                res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
                if res == 0:
                    break
            except Exception:
                continue
    except Exception:
        pass
