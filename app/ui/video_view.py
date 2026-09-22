# -*- coding: utf-8 -*-
"""原视频 / 脱敏视频预览播放器。"""

import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

import cv2

from app.detect.detector import FaceDetector
from app.settings import load_config, save_config
from app.theme import (
    ACCENT, ACCENT_GREEN, ACCENT_HOVER, ACCENT_RED, BG_CARD, BG_HOVER,
    BG_VIDEO, BORDER, BTN_ACCENT_BORDER, BTN_ACCENT_PRESS, BTN_GREEN_BORDER,
    BTN_GREEN_PRESS, BTN_NORMAL_BORDER, BTN_NORMAL_HOVER, BTN_NORMAL_PRESS, FG,
    FG_FAINT, FG_MUTED,
)
from app.ui.drop import _hdrop_paths, _warn_drop_not_video, pick_dropped_video
from app.video.formats import (
    decode_seek, duration_seconds, format_frame_count, normalize_frame_count,
    probe_frame_count,
)
from app.settings import BOX_COLOR, BOX_THICKNESS


class VideoView:
    """封装单个视频的预览窗口：画布 + 播放/暂停按钮 + 进度条 + 时间标签。

    独立维护自己的 VideoCapture 和播放线程，用于原视频/脱敏视频的比对预览。
    """

    def __init__(self, parent, title, on_import, config_key="show_boxes", padx=(0, 10)):
        self.title = title
        self.on_import = on_import  # 导入按钮回调（由主程序注入）
        self.config_key = config_key  # 配置持久化的键名（每个开关单独记录）
        self.video_path = None
        self.cap = None
        self.total_frames = 0
        self.fps = 25.0
        self.width = 0
        self.height = 0
        self.playing = False
        self._stop = threading.Event()
        self._seek_pending = None    # 待跳转帧号（松手后才真正解码）
        self._updating_progress = False  # 程序更新时间戳时的标志（区分用户拖动）
        self._scrubbing = False      # 正在按住进度条，禁止播放把滑块拽回去
        self._scrub_after = None     # 兼容旧字段：不再用 after 结束拖动
        self._scrub_bound = False    # 已 bind_all 松手，防止重复绑定
        self._linear_seek = False    # True=无容器索引，禁止 cap.set
        self._decode_idx = -1        # 当前 cap 实际解到的帧号（顺序计数）
        self._cap_lock = threading.Lock()
        self._seek_gen = 0           # 暂停态跳转代次，新拖动作废旧线程
        self._tk_image = None
        self._last_frame = None      # 最近显示的原始帧（用于窗口缩放时重绘）
        self._last_cw = 0            # 上次渲染时的 canvas 宽度
        self._last_ch = 0            # 上次渲染时的 canvas 高度
        self._display_q = queue.Queue(maxsize=2)  # 播放线程→主线程 的帧队列
        self._display_pos = 0        # 待显示帧的播放位置
        # 检测框显示开关 + 人脸框数据（帧号 -> boxes，由主程序在预处理完成后注入）
        self.show_boxes = bool(load_config().get(self.config_key, True))
        self.face_boxes_by_frame = {}
        self._index_trusted = True   # True=顺序解码，帧号与预处理一致；cap.set 之后必须改 False
        self._frame_idx = 0          # 当前画面对应的播放帧号（进度条用）
        self._overlay_det = None     # 现场画框用的检测器（跳转后 POS 不可信时使用）
        self._last_raw = None        # 最近一帧未画框原图，供开关切换时重绘

        # 外层容器（整列：标题栏 + 画布 + 控制条）
        self.frame = tk.Frame(parent, bg=BG_CARD, highlightthickness=1,
                              highlightbackground=BORDER)
        self.frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=padx)

        # 标题栏
        head = tk.Frame(self.frame, bg=BG_CARD)
        head.pack(fill=tk.X, padx=12, pady=(10, 8))
        tk.Label(head, text=title, bg=BG_CARD, fg=FG,
                 font=("Microsoft YaHei UI", 11, "bold")).pack(side=tk.LEFT)
        self.btn_import = tk.Button(head, text="导入视频", command=self.on_import,
                                    bg=ACCENT, fg="#ffffff",
                                    activebackground=ACCENT_HOVER, activeforeground="#ffffff",
                                    relief=tk.FLAT, cursor="hand2",
                                    font=("Microsoft YaHei UI", 9), padx=12, pady=3,
                                    bd=0, highlightthickness=1,
                                    highlightbackground=BTN_ACCENT_BORDER,
                                    highlightcolor=BTN_ACCENT_BORDER)
        self._bind_press_feedback(self.btn_import, BTN_ACCENT_PRESS, ACCENT)
        self.btn_import.pack(side=tk.RIGHT)
        self.btn_play = tk.Button(head, text="播放", command=self.toggle_play,
                                  bg=BG_HOVER, fg=FG, state=tk.DISABLED,
                                  activebackground=BTN_NORMAL_HOVER, activeforeground="#ffffff",
                                  relief=tk.FLAT, cursor="hand2",
                                  font=("Microsoft YaHei UI", 9), padx=12, pady=3,
                                  bd=0, highlightthickness=1,
                                  highlightbackground=BTN_NORMAL_BORDER,
                                  highlightcolor=BTN_NORMAL_BORDER,
                                  disabledforeground=FG_FAINT)
        self._bind_press_feedback(self.btn_play, BTN_NORMAL_PRESS, BG_HOVER)
        self.btn_play.pack(side=tk.RIGHT, padx=(0, 8))

        # 显示检测框：与参数页开关同一套开/关按钮，避免系统复选框样式突兀
        self.btn_boxes = tk.Button(
            head, command=self._on_boxes_toggle,
            relief=tk.FLAT, cursor="hand2",
            font=("Microsoft YaHei UI", 9), padx=10, pady=3,
            bd=0, highlightthickness=1)
        self.btn_boxes.pack(side=tk.RIGHT, padx=(0, 8))
        self._sync_boxes_btn()

        # 画面区：面板尺寸由父布局分配，不随图片请求尺寸膨胀
        self.video_panel = tk.Frame(self.frame, bg=BG_VIDEO)
        self.video_panel.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 4))
        self.video_panel.pack_propagate(False)
        self.canvas = tk.Label(self.video_panel, bg=BG_VIDEO, bd=0,
                               highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", self._on_video_resize)
        self.video_panel.bind("<Configure>", self._on_video_resize)
        # 空画面提示：可把视频拖进这块区域导入
        self.lbl_drop_hint = tk.Label(
            self.video_panel, text="将视频拖到此处导入",
            bg=BG_VIDEO, fg=FG_MUTED,
            font=("Microsoft YaHei UI", 10))
        self.lbl_drop_hint.place(relx=0.5, rely=0.5, anchor="center")
        self._drop_hooks = []       # [(hwnd, old_proc, wndproc)]，必须持有回调防 GC
        self._pending_drop_path = None   # WndProc 里只记路径，主循环再导入
        self._pending_drop_bad = False
        self.frame.after(200, self._on_video_resize)
        self.frame.after(250, self._enable_file_drop)

        # 播放进度条（紧贴视频下方）：进度条 + 时间
        ctrl = tk.Frame(self.frame, bg=BG_CARD)
        ctrl.pack(fill=tk.X, padx=12, pady=(4, 0))
        self.lbl_time = tk.Label(ctrl, text="00:00 / 00:00", bg=BG_CARD, fg=FG_MUTED,
                                 font=("Consolas", 9))
        self.lbl_time.pack(side=tk.RIGHT, padx=(8, 0))
        self.progress = ttk.Scale(ctrl, from_=0, to=1000, orient=tk.HORIZONTAL,
                                  command=self._on_scrub)
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True)
        # 拖动中只改时间标签；松手再跳转，避免裸流 cap.set 连跳 GOP
        self.progress.bind("<ButtonPress-1>", self._on_scrub_press)
        self.progress.bind("<ButtonRelease-1>", self._on_scrub_release)

        # 脱敏相关数据标签（多行：文件信息 + 帧率 + 分析进度，由主程序更新）
        self.lbl_info = tk.Label(self.frame, text="未导入视频", bg=BG_CARD, fg=FG_MUTED,
                                 font=("Microsoft YaHei UI", 8), anchor="w", justify="left")
        self.lbl_info.pack(fill=tk.X, padx=12, pady=(8, 0))

        # 分析进度条（由主程序更新）
        self.analyze_progress = ttk.Progressbar(self.frame, orient=tk.HORIZONTAL,
                                                mode="determinate", maximum=100)
        self.analyze_progress.pack(fill=tk.X, padx=12, pady=(4, 12))

        # 主线程渲染轮询器（每 ~15ms 从显示队列取帧刷新画面）
        self.frame.after(15, self._render_tick)

    # ---------- 主线程渲染 ----------
    def _render_tick(self):
        """主线程定时器：从显示队列取最新帧刷新画面与进度。

        窗口尺寸变化时（即便暂停、队列无新帧），也会用缓存帧重绘，保证画面跟随窗口缩放。
        """
        self._consume_pending_drop()
        need_redraw = False
        try:
            frame = self._display_q.get_nowait()
            self._show(frame)
            # 按住进度条时不要用播放位置覆盖滑块和时间
            if not self._scrubbing:
                self._update_progress(self._display_pos)
                self._update_time(self._display_pos)
        except queue.Empty:
            # 队列空（如已暂停）：检查窗口尺寸是否变化，变了就重绘缓存帧
            if self._last_frame is not None:
                cw, ch = self._alloc_size()
                if cw != self._last_cw or ch != self._last_ch:
                    need_redraw = True
        if need_redraw:
            self._show(self._last_frame)
        self.frame.after(15, self._render_tick)

    def _consume_pending_drop(self):
        """主循环消费 WndProc 记下的拖入路径。"""
        path = self._pending_drop_path
        bad = self._pending_drop_bad
        self._pending_drop_path = None
        self._pending_drop_bad = False
        if path:
            self.on_import(path)
        elif bad:
            _warn_drop_not_video()
        return

    # ---------- 载入 ----------
    def load(self, path):
        self._release()
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            return False
        self.cap = cap
        self.video_path = path
        reported = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        # OpenCV 给不出总帧 = 没有索引，cap.set 只会前进 GOP
        self._linear_seek = normalize_frame_count(reported) <= 0
        self.total_frames = probe_frame_count(path, reported)
        self.fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.btn_play.config(state=tk.NORMAL)

        # 读取并显示第一帧（顺序解码，帧号从 0 可信）
        self._index_trusted = True
        self._frame_idx = 0
        self._decode_idx = -1
        ok, frame = cap.read()
        if ok:
            self._decode_idx = 0
            self._last_raw = frame
            self._show(self._draw_boxes(frame, 0))
        self._updating_progress = True
        try:
            self.progress.set(0)
        finally:
            self._updating_progress = False
        self._seek_pending = None
        self._update_time(0)
        # 填充脱敏相关信息（文件名 + 元数据）
        name = os.path.basename(path)
        self.lbl_info.config(
            text=f"文件：{name}\n分辨率：{self.width}×{self.height}\n"
                 f"帧率：{self.fps:.1f} fps · 总帧数：{format_frame_count(self.total_frames)}\n待分析…")
        return True

    # ---------- 播放 ----------
    def toggle_play(self):
        if self.playing:
            self.pause()
        else:
            self.play()

    def _on_boxes_toggle(self):
        """显示检测框开关切换：更新状态并持久化到配置文件（每个开关单独记录）。"""
        self.show_boxes = not self.show_boxes
        self._sync_boxes_btn()
        cfg = load_config()
        cfg[self.config_key] = self.show_boxes
        save_config(cfg)
        self._refresh_overlay()
        return

    def _sync_boxes_btn(self):
        """同步检测框按钮的开/关外观。"""
        # 开启时用绿色，关闭时用灰色，与参数页布尔开关一致
        if self.show_boxes:
            self.btn_boxes.config(
                text="检测框：开", bg=ACCENT_GREEN, fg="#04110a",
                activebackground=BTN_GREEN_PRESS, activeforeground="#04110a",
                highlightbackground=BTN_GREEN_BORDER,
                highlightcolor=BTN_GREEN_BORDER)
        else:
            self.btn_boxes.config(
                text="检测框：关", bg=BG_HOVER, fg=FG_MUTED,
                activebackground=BTN_NORMAL_HOVER, activeforeground="#ffffff",
                highlightbackground=BTN_NORMAL_BORDER,
                highlightcolor=BTN_NORMAL_BORDER)
        return

    def _get_overlay_detector(self):
        """惰性创建现场画框检测器；创建失败则返回 None。"""
        det = self._overlay_det
        if det is None:
            try:
                det = FaceDetector()
                self._overlay_det = det
            except Exception:
                det = None
        return det

    def _refresh_overlay(self):
        """按当前开关，用未画框的原帧重绘检测框。"""
        if self._last_raw is None:
            pass
        else:
            self._show(self._draw_boxes(self._last_raw, self._frame_idx))
        return

    def _draw_boxes(self, frame, frame_idx):
        """若开关开启，在帧上画人脸框，返回标注后的帧。

        顺序播放且帧号可信时用预处理缓存（与脱敏率同一套框）；
        cap.set 跳转后解码帧常落到邻近关键帧，POS 仍报目标号，缓存框会对不齐，
        此时必须按当前像素现场检测。
        """
        out = frame
        if not self.show_boxes:
            pass
        else:
            boxes = None
            # 顺序解码且帧号可信：直接用预处理结果，避免播放时再跑一遍检测
            if self._index_trusted and frame_idx is not None and frame_idx >= 0:
                boxes = self.face_boxes_by_frame.get(frame_idx)
            if boxes:
                out = frame.copy()
                for i, (x, y, w, h) in enumerate(boxes, start=1):
                    cv2.rectangle(out, (x, y), (x + w, y + h), BOX_COLOR, BOX_THICKNESS)
                    cv2.putText(out, f"Face {i}", (x, max(y - 10, 15)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2,
                                cv2.LINE_AA)
            else:
                # 刚拖进度条 / 该帧缓存还没有：按当前画面检测
                det = self._get_overlay_detector()
                if det is not None:
                    out, _ = det.detect_and_draw(frame.copy())
        return out

    def play(self):
        if self.cap is None:
            return
        self.playing = True
        self._stop.clear()
        self.btn_play.config(text="暂停", bg=ACCENT_RED, fg="#ffffff")
        threading.Thread(target=self._play_loop, daemon=True).start()

    def pause(self):
        self.playing = False
        self._stop.set()
        self.btn_play.config(text="播放", bg=BG_HOVER, fg=FG)

    def _play_loop(self):
        delay = 1.0 / self.fps if self.fps > 0 else 0.04
        while self.playing and not self._stop.is_set():
            if self.cap is None:
                break  # 视频已被释放（如重新导入/关闭）
            t0 = time.time()
            ok = False
            frame = None
            with self._cap_lock:
                # 松手后的跳转：裸流走顺序解码，有索引才 cap.set
                if self._seek_pending is not None:
                    target = self._seek_pending
                    self._seek_pending = None
                    if target == self._decode_idx and self._last_raw is not None:
                        ok = True
                        frame = self._last_raw
                        self._frame_idx = target
                    else:
                        self.cap, self._decode_idx, ok, frame = decode_seek(
                            self.cap, self.video_path, self._decode_idx,
                            target, self._linear_seek)
                        if ok:
                            self._frame_idx = self._decode_idx
                            # 顺序解码到的就是目标帧，框可再用缓存；cap.set 仍不可信
                            self._index_trusted = bool(self._linear_seek)
                if not ok:
                    ok, frame = self.cap.read() if self.cap is not None else (False, None)
                    if ok:
                        if self._decode_idx is None or self._decode_idx < 0:
                            self._decode_idx = 0
                        else:
                            self._decode_idx += 1
                        if self._linear_seek:
                            self._frame_idx = self._decode_idx
                            self._index_trusted = True
                        elif self._index_trusted:
                            self._frame_idx = int(round(
                                self.cap.get(cv2.CAP_PROP_POS_FRAMES))) - 1
                        else:
                            # 容器跳转后的顺序播放：进度条继续走，画框仍现场检测
                            self._frame_idx += 1
                if not ok:
                    # 播完：裸流 cap.set(0) 无效，必须重开
                    self.cap, self._decode_idx, ok, frame = decode_seek(
                        self.cap, self.video_path, None, 0, True)
                    if ok:
                        self._frame_idx = 0
                        self._index_trusted = True
                    else:
                        ok = False
                if ok and frame is not None:
                    frame = frame.copy()  # OpenCV 缓冲会被下一次 read 覆盖
            if not ok:
                self.pause()
                break
            self._last_raw = frame
            frame = self._draw_boxes(frame, self._frame_idx)
            self._push_display(frame, self._frame_idx)
            remain = delay - (time.time() - t0)
            if remain > 0:
                self._stop.wait(remain)

    def _push_display(self, frame, pos):
        """把帧丢进显示队列，满则丢旧帧。"""
        self._display_pos = max(pos, 0)
        try:
            self._display_q.put_nowait(frame)
        except queue.Full:
            try:
                self._display_q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._display_q.put_nowait(frame)
            except queue.Full:
                pass
        return

    def _on_scrub_press(self, event=None):
        self._scrubbing = True
        # 指针拖出进度条再松手也要收到 Release，否则 _scrubbing 会一直为 True
        if not self._scrub_bound:
            self.frame.bind_all("<ButtonRelease-1>", self._on_scrub_release)
            self._scrub_bound = True
        return

    def _on_scrub(self, val):
        if self.cap is None:
            return
        if self._updating_progress:
            return  # 程序更新进度条触发的回调，忽略（避免干扰播放）
        # 裸码流没有可靠总帧数，拖进度条无法换算目标帧
        if self.total_frames <= 1:
            return
        ratio = float(val) / 1000.0
        target = int(ratio * max(self.total_frames - 1, 0))
        # 拖动中只改时钟，不解码、不结束拖动（停顿 180ms 也必须仍按住）
        self._frame_idx = target
        self._update_time(target)
        # 没有鼠标 Press 的调节（如键盘）：立刻记跳转
        if not self._scrubbing:
            self._seek_pending = target
            if not self.playing:
                self._seek_gen += 1
                gen = self._seek_gen
                threading.Thread(
                    target=self._paused_seek_loop, args=(gen, target),
                    daemon=True).start()
        return

    def _on_scrub_release(self, event=None):
        if not self._scrubbing:
            return  # 全局松手可能连发，只处理一次
        if self._scrub_bound:
            try:
                self.frame.unbind_all("<ButtonRelease-1>")
            except tk.TclError:
                pass
            self._scrub_bound = False
        self._scrubbing = False
        if self._scrub_after is not None:
            try:
                self.frame.after_cancel(self._scrub_after)
            except Exception:
                pass
            self._scrub_after = None
        if self.cap is None or self.total_frames <= 1:
            return
        target = int(self._frame_idx)
        self._seek_pending = target
        # 播放中由 _play_loop 消费；暂停则后台跳转，避免卡死界面
        if not self.playing:
            self._seek_gen += 1
            gen = self._seek_gen
            threading.Thread(
                target=self._paused_seek_loop, args=(gen, target),
                daemon=True).start()
        return

    def _paused_seek_loop(self, gen, target):
        """暂停时跳到目标帧：只碰 cap/队列，不调用 Tk。"""
        if gen != self._seek_gen or self.cap is None:
            return
        with self._cap_lock:
            if gen != self._seek_gen or self.cap is None:
                return
            ok = False
            frame = None
            if target == self._decode_idx and self._last_raw is not None:
                ok = True
                frame = self._last_raw
            else:
                self.cap, self._decode_idx, ok, frame = decode_seek(
                    self.cap, self.video_path, self._decode_idx,
                    target, self._linear_seek)
            if ok and gen == self._seek_gen:
                self._frame_idx = self._decode_idx
                self._index_trusted = bool(self._linear_seek)
                if frame is not None:
                    frame = frame.copy()
                self._last_raw = frame
                drawn = self._draw_boxes(frame, self._decode_idx)
                self._push_display(drawn, self._decode_idx)
                self._seek_pending = None
        return

    def _alloc_size(self):
        """返回视频面板当前被分配的宽高，不用 Label 请求尺寸（图片会把它撑大）。"""
        w = int(self.video_panel.winfo_width())
        h = int(self.video_panel.winfo_height())
        if w < 10 or h < 10:
            w, h = 420, 260
        return w, h

    def _show(self, frame_bgr):
        self._last_frame = frame_bgr          # 缓存原始帧，供窗口缩放时重绘
        cw, ch = self._alloc_size()
        self._last_cw, self._last_ch = cw, ch  # 记录上次渲染尺寸
        h, w = frame_bgr.shape[:2]
        # 按分配区域等比缩小，禁止用图片尺寸反推布局
        scale = min(cw / w, ch / h)
        nw = max(int(w * scale), 1)
        nh = max(int(h * scale), 1)
        resized = cv2.resize(frame_bgr, (nw, nh), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        import PIL.Image
        import PIL.ImageTk
        img = PIL.Image.fromarray(rgb)
        self._tk_image = PIL.ImageTk.PhotoImage(img)
        self.canvas.config(image=self._tk_image, width=cw, height=ch)
        self._set_drop_hint_visible(False)

    def _on_video_resize(self, event=None):
        cw, ch = self._alloc_size()
        # 尺寸没变则不必重绘，避免 Configure 循环
        if cw == self._last_cw and ch == self._last_ch:
            return
        # 有画面则按新尺寸缩放；无画面则铺实心底
        if self._last_frame is None:
            self._paint_canvas_bg()
        else:
            self._show(self._last_frame)
        return

    def _paint_canvas_bg(self):
        """用实心位图铺满视频区，DWM 玻璃下 Label 背景色本身不够。"""
        import PIL.Image
        import PIL.ImageTk
        self._last_frame = None
        w, h = self._alloc_size()
        self._last_cw, self._last_ch = w, h
        img = PIL.Image.new("RGB", (w, h), (0x05, 0x07, 0x0b))
        self._tk_image = PIL.ImageTk.PhotoImage(img)
        self.canvas.config(image=self._tk_image, width=w, height=h)
        self._set_drop_hint_visible(True)
        return

    def _set_drop_hint_visible(self, visible):
        """空画面显示拖入提示；已有视频则隐藏。"""
        if not hasattr(self, "lbl_drop_hint"):
            pass
        elif visible:
            self.lbl_drop_hint.place(relx=0.5, rely=0.5, anchor="center")
            self.lbl_drop_hint.lift()
        else:
            self.lbl_drop_hint.place_forget()
        return

    def _enable_file_drop(self):
        """让画面区接受资源管理器拖入的视频文件。"""
        if sys.platform != "win32":
            return
        widgets = [self.video_panel, self.canvas]
        if getattr(self, "lbl_drop_hint", None) is not None:
            widgets.append(self.lbl_drop_hint)
        for w in widgets:
            try:
                self._hook_file_drop(w)
            except Exception:
                continue  # 单个控件挂钩失败不影响其它
        return

    def _hook_file_drop(self, widget):
        """对单个控件 HWND 启用 WM_DROPFILES，并替换窗口过程以收取路径。"""
        import ctypes
        from ctypes import wintypes
        hwnd = 0
        try:
            hwnd = int(widget.winfo_id())
        except (tk.TclError, ValueError, TypeError):
            hwnd = 0
        if not hwnd:
            return
        for item in self._drop_hooks:
            if item[0] == hwnd:
                return  # 已挂钩，避免重复替换 WndProc
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        WM_DROPFILES = 0x0233
        GWL_WNDPROC = -4
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(
            LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        # 64 位必须用 *PtrW，并把第三参当成指针，否则会 OverflowError
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
        old_proc = get_long(hwnd, GWL_WNDPROC)

        def _wndproc(h, msg, wp, lp):
            result = 0
            # 禁止在 WndProc 里调 Tk（after/弹窗会把 GIL 弄乱），只记下路径
            if msg == WM_DROPFILES:
                try:
                    paths = _hdrop_paths(wp)
                    chosen = pick_dropped_video(paths)
                    if chosen:
                        self._pending_drop_path = chosen
                        self._pending_drop_bad = False
                    else:
                        self._pending_drop_bad = True
                except Exception:
                    self._pending_drop_bad = True
                result = 0
            else:
                result = user32.CallWindowProcW(old_proc, h, msg, wp, lp)
            return result

        cb = WNDPROC(_wndproc)
        set_long(hwnd, GWL_WNDPROC, ctypes.cast(cb, ctypes.c_void_p))
        shell32.DragAcceptFiles(wintypes.HWND(hwnd), True)
        self._drop_hooks.append((hwnd, old_proc, cb))
        return

    def _update_progress(self, pos):
        if getattr(self, "_scrubbing", False):
            return  # 用户正拖进度条，不要把滑块拽回播放位置
        if self.total_frames > 1:
            self._updating_progress = True
            try:
                self.progress.set(pos / (self.total_frames - 1) * 1000.0)
            finally:
                self._updating_progress = False

    def _update_time(self, pos):
        cur_sec = duration_seconds(pos, self.fps)
        # 未知总帧：只显示当前时间
        if self.total_frames > 0:
            total_txt = self._fmt(duration_seconds(self.total_frames, self.fps))
        else:
            total_txt = "--:--"
        self.lbl_time.config(text=f"{self._fmt(cur_sec)} / {total_txt}")

    @staticmethod
    def _fmt(seconds):
        seconds = max(0, int(seconds))
        m, s = divmod(seconds, 60)
        return f"{m:02d}:{s:02d}"

    @staticmethod
    def _bind_press_feedback(btn, press_color, normal_color):
        """给按钮绑定按下变暗/松开还原的交互反馈。"""
        btn.bind("<ButtonPress-1>", lambda e: btn.config(bg=press_color))
        btn.bind("<ButtonRelease-1>", lambda e: btn.config(bg=normal_color))

    def _release(self):
        # 先停止播放，避免播放线程在释放后继续读 cap
        self.playing = False
        self._stop.set()
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        if self._overlay_det is not None:
            self._overlay_det.close()
            self._overlay_det = None
        self._last_raw = None
        self._index_trusted = True
        self._frame_idx = 0
        self._decode_idx = -1
        self._seek_pending = None
        self._seek_gen += 1
        self._scrubbing = False
        if self._scrub_bound:
            try:
                self.frame.unbind_all("<ButtonRelease-1>")
            except tk.TclError:
                pass
            self._scrub_bound = False
        return

