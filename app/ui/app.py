# -*- coding: utf-8 -*-
"""主窗口：组装标题栏、检测页、参数页。"""

import queue
import threading
import tkinter as tk
from tkinter import ttk

from app.detect.track import FaceTracker, TrackGate
from app import settings as cfg
from app.settings import (
    DETECTOR, QUEUE_MAXSIZE, load_params,
)
from app.theme import (
    ACCENT, ACCENT_GREEN, ACCENT_HOVER, ACCENT_RED, BG, BG_CARD, BG_CHIP,
    BG_HOVER, BG_PANEL, BORDER, BTN_ACCENT_BORDER, BTN_ACCENT_PRESS,
    BTN_NORMAL_BORDER, BTN_NORMAL_HOVER, BTN_NORMAL_PRESS, CHIP_BORDER, FG,
    FG_FAINT, FG_MUTED,
)
from app.ui.desens import DesensMixin
from app.ui.params import ParamsMixin
from app.ui.pipeline import PipelineMixin
from app.ui.titlebar import TitlebarMixin, _enable_dark_titlebar
from app.ui.video_view import VideoView
from app.ui import dialogs as messagebox


class FaceVideoApp(TitlebarMixin, ParamsMixin, DesensMixin, PipelineMixin):
    def __init__(self, root):
        self.root = root
        root.title("人脸检测视频工具")
        root.geometry("1280x720")
        root.minsize(900, 600)
        root.configure(bg=BG)

        # 自绘标题栏相关状态
        self._maximized = False            # 是否已最大化
        self._normal_geometry = None       # 还原时的窗口几何
        self._drag_x = 0                   # 拖动用：鼠标按下时的相对偏移（仅几何回退）
        self._drag_y = 0
        self._native_drag = False          # True=已交给 Windows 原生拖动，禁止 geometry 逐帧移动
        self._tray = None                  # 系统托盘图标（pystray）
        self._hide_tb_tries = 0            # 隐藏系统标题栏的重试次数（窗口未映射时需推迟）

        # 不再用 overrideredirect(True)（它会让窗口从任务栏消失）。
        # 改为：保留系统窗口（含任务栏可见性），稍后靠 _hide_native_titlebar()
        # 仅移除系统标题栏样式，自绘深色标题栏照常工作。

        # 从配置恢复所有检测参数
        load_params()
        self.detector = None
        self.video_path = None
        self.total_frames = 0
        self.fps = 0.0
        self.width = 0
        self.height = 0

        self.playing = False                  # 是否处于播放状态
        self._stop_play = threading.Event()
        self._play_pos = 0                    # 当前播放帧号
        self._ended = False                   # 是否已播放到结尾
        self._updating_progress = False       # 程序更新时间戳时的标志（区分用户拖动）

        # ---- 三级流水线 ----
        self._raw_q = queue.Queue(maxsize=QUEUE_MAXSIZE)    # 原始帧 (idx, frame)
        self._frame_cache = {}     # idx -> (annotated_frame, boxes) 检测结果缓存
        self._frames_done = set()  # 已检测帧号集合
        self._display_q = queue.Queue(maxsize=2)  # 待显示帧队列（只有最新帧，播放线程→主线程）
        self._pipeline_stop = threading.Event()
        self._reader_thread = None
        self._detect_thread = None
        self._play_thread = None
        self._pipeline_gen = 0        # 流水线代次（重新导入时递增，旧线程据此识别自己已过时）

        # ---- 统计相关 ----
        self.faces_frames = []      # 检测到人脸的帧号列表（从小到大）
        self.frame_face_counts = {}  # 帧号 -> 该帧人脸数量
        self.face_tracks = []       # 聚类后的人脸轨迹
        self._tracker = FaceTracker()
        self._smoother = TrackGate()
        self._stats_ready = False
        # 跨线程共享状态（子线程写、主线程轮询读）
        self._analyze_done = 0       # 已检测帧数
        self._scan_finished = False  # 扫描是否结束
        self._stats_applied = False  # 统计面板是否已刷新
        self._last_progress_ui = -1  # 上次刷新的进度值（避免重复刷新）
        self._detector_name = ""
        self._detector_error = None
        self._detector_label_pending = False
        self._export_done_flag = False
        self._export_result = None
        self._export_progress = None   # (done, total)

        # ---- 脱敏率检测（原视频 + 脱敏视频，两套并存） ----
        self.src_info = None   # 原视频分析结果 {fps, total, faces: [(frame_idx, boxes)], done}
        self.dst_info = None   # 脱敏视频分析结果 {fps, total, faces: [(frame_idx, boxes)], done}
        self._desens_progress_src = 0   # 原视频分析进度(帧百分比)
        self._desens_progress_dst = 0   # 脱敏视频分析进度(帧百分比)
        self._desens_done_src = 0       # 原视频已分析帧数
        self._desens_done_dst = 0       # 脱敏视频已分析帧数
        self._desens_total_src = 0      # 原视频总帧数
        self._desens_total_dst = 0      # 脱敏视频总帧数
        self._desens_gen_src = 0        # 原视频预处理代次（重新导入时递增，旧线程据此退出）
        self._desens_gen_dst = 0        # 脱敏视频预处理代次
        self._preprocess_results = {}   # {is_src: info/错误} 预处理完成结果暂存（子线程写，主线程读）
        # 脱敏率检测进度
        self._check_progress = 0        # 检测进度(0-1)，检测线程写，主线程轮询读
        self._check_total = 0           # 检测的应脱敏帧总数
        self.last_desens_report = None  # 最近一次成功检测的冻结结果，供导出报告
        self._desens_report_gen = 0     # 冻结结果代次；重新导入或清空时递增，旧结果作废
        self._report_save_gen = 0       # 报告保存代次，避免上一次轮询吃掉这一次的结果
        self._report_save_box = None    # 子线程写入的保存结果，主线程轮询读取
        self._top_drop_cb = None
        self._pending_drop_paths = None
        self._pending_drop_bad = False

        self._build_ui()
        self._apply_theme()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 后台尝试加载检测器（如 mediapipe 首次加载较慢）
        self._detector_ready = False
        threading.Thread(target=self._load_detector, daemon=True).start()

        # 主线程渲染轮询器（每 ~30ms 刷新一次画面与进度）
        self.root.after(30, self._render_tick)

    # ---------- UI ----------
    def _build_ui(self):
        # ---------- 自绘深色标题栏 ----------
        self._build_titlebar()
        # ---------- 系统托盘图标 ----------
        self._setup_tray_icon()
        # ---------- 隐藏系统标题栏（保留任务栏可见）----------
        self.root.after(100, self._hide_native_titlebar)

        # 顶栏：页签 + 检测器徽标 + 肤色过滤（标题已在自绘标题栏，这里不再重复）
        top = tk.Frame(self.root, bg=BG_PANEL)
        top.pack(fill=tk.X)
        row = tk.Frame(top, bg=BG_PANEL)
        row.pack(fill=tk.X, padx=16, pady=(8, 8))

        tabs = tk.Frame(row, bg=BG_PANEL)
        tabs.pack(side=tk.LEFT)
        self.btn_page_detect = self._make_btn(
            tabs, "检测", self.show_detect_page, accent=True, compact=True)
        self.btn_page_detect.pack(side=tk.LEFT)
        self.btn_page_params = self._make_btn(
            tabs, "参数设置", self.show_params_page, accent=False, compact=True)
        self.btn_page_params.pack(side=tk.LEFT, padx=(8, 0))

        chip = tk.Frame(row, bg=BG_CHIP, highlightthickness=1,
                        highlightbackground=CHIP_BORDER)
        self.lbl_detector = tk.Label(
            chip, text="YuNet", bg=BG_CHIP, fg=ACCENT_GREEN,
            font=("Microsoft YaHei UI", 8, "bold"))
        self.lbl_detector.pack(padx=8, pady=2)
        chip.pack(side=tk.LEFT, padx=(12, 0))

        # 肤色过滤开关（初始状态从配置读取）
        skin_on = cfg.SKIN_FILTER_ENABLED
        self.btn_skin = self._make_btn(
            row, "肤色过滤：开" if skin_on else "肤色过滤：关",
            self.toggle_skin_filter, accent=False, compact=True)
        self.btn_skin.pack(side=tk.RIGHT)
        self._sync_skin_btn()

        tk.Frame(self.root, bg=BORDER, height=1).pack(fill=tk.X)

        # 页面容器（两个页面：检测页 / 参数设置页）
        self.page_container = tk.Frame(self.root, bg=BG)
        self.page_container.pack(fill=tk.BOTH, expand=True, padx=16, pady=(12, 16))

        # ===== 检测页 =====
        self.page_detect = tk.Frame(self.page_container, bg=BG)
        self.page_detect.pack(fill=tk.BOTH, expand=True)

        # 主体：左（双视频窗口） + 右（滚动信息面板）
        body = self.page_detect

        # 左侧：两个视频预览窗口（左右并排）
        vids = tk.Frame(body, bg=BG)
        vids.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.view_src = VideoView(
            vids, "原视频", self.import_src_video,
            config_key="show_boxes_src", padx=(0, 10))
        self.view_dst = VideoView(
            vids, "脱敏视频", self.import_dst_video,
            config_key="show_boxes_dst", padx=(0, 0),
            mosaic_toggle=True)   # 只有脱敏视频检测马赛克，才有马赛克框开关

        # 右侧：滚动列表（脱敏检测信息）
        right = tk.Frame(body, bg=BG_CARD, width=460,
                         highlightthickness=1, highlightbackground=BORDER)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(12, 0))
        right.pack_propagate(False)

        # Canvas + Scrollbar 实现滚动
        scroll_canvas = tk.Canvas(right, bg=BG_CARD, highlightthickness=0)
        scrollbar = ttk.Scrollbar(right, orient=tk.VERTICAL, command=scroll_canvas.yview)
        self._scroll_content = tk.Frame(scroll_canvas, bg=BG_CARD)
        self._desens_canvas = scroll_canvas
        self._desens_sbar = scrollbar
        # 关键：让内部 frame 宽度跟随 Canvas，高度至少撑满视口，检测结果框才能吃掉全屏留白
        self._scroll_window = scroll_canvas.create_window(
            (0, 0), window=self._scroll_content, anchor="nw")
        self._scroll_content.bind("<Configure>", self._sync_desens_panel)
        scroll_canvas.bind("<Configure>", self._sync_desens_panel)
        scroll_canvas.configure(yscrollcommand=scrollbar.set)
        # 漏帧列表在栏底，不放进上方 Canvas，避免两层滚动抢滚轮
        miss_host = tk.Frame(right, bg=BG_CARD)
        miss_host.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True)
        self._build_miss_list(miss_host)
        scroll_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 滚动内容：脱敏率检测
        self._panel_head(self._scroll_content, "脱敏率检测")

        self.lbl_src_state = tk.Label(self._scroll_content, text="原视频：未导入",
                                      bg=BG_CARD, fg=FG_FAINT,
                                      font=("Microsoft YaHei UI", 9), anchor="w")
        self.lbl_src_state.pack(fill=tk.X, padx=16)
        self.src_progress = ttk.Progressbar(self._scroll_content, orient=tk.HORIZONTAL,
                                            mode="determinate", maximum=100)
        self.src_progress.pack(fill=tk.X, padx=16, pady=(4, 10))

        self.lbl_dst_state = tk.Label(self._scroll_content, text="脱敏视频：未导入",
                                      bg=BG_CARD, fg=FG_FAINT,
                                      font=("Microsoft YaHei UI", 9), anchor="w")
        self.lbl_dst_state.pack(fill=tk.X, padx=16)
        self.dst_progress = ttk.Progressbar(self._scroll_content, orient=tk.HORIZONTAL,
                                            mode="determinate", maximum=100)
        self.dst_progress.pack(fill=tk.X, padx=16, pady=(4, 10))

        self.btn_check_desens = self._make_btn(self._scroll_content, "开始检测脱敏率",
                                               self.check_desensitization_ui, accent=True)
        self.btn_check_desens.pack(fill=tk.X, padx=16, pady=(2, 6))
        self.btn_export_report = self._make_btn(self._scroll_content, "生成检测报告",
                                                self.export_desens_report, disabled=True)
        self.btn_export_report.pack(fill=tk.X, padx=16, pady=(0, 10))

        # 检测进度条
        self.lbl_check_state = tk.Label(self._scroll_content, text="检测进度：未开始",
                                        bg=BG_CARD, fg=FG_FAINT,
                                        font=("Microsoft YaHei UI", 8), anchor="w")
        self.lbl_check_state.pack(fill=tk.X, padx=16)
        self.check_progress = ttk.Progressbar(self._scroll_content, orient=tk.HORIZONTAL,
                                              mode="determinate", maximum=100)
        self.check_progress.pack(fill=tk.X, padx=16, pady=(4, 10))

        # 脱敏率计算公式（常显）
        formula_box = tk.Frame(self._scroll_content, bg=BG_PANEL,
                               highlightthickness=1, highlightbackground=BORDER)
        formula_box.pack(fill=tk.X, padx=16, pady=(0, 12))
        self.lbl_formula = tk.Label(
            formula_box,
            text="脱敏率 = 已脱敏人脸数 ÷ 帧率换算后原视频应脱敏人脸数 × 100%\n"
                 "换算公式：脱敏帧号 = round(原帧号 ÷ 原帧率 × 脱敏帧率) + 帧偏移\n"
                 "原视频人脸数、脱敏视频人脸数 = 换算前各自检出的总数\n"
                 "帧率换算后原视频应脱敏人脸数 = 落在脱敏视频时长内的原视频人脸数\n"
                 "帧率换算后脱敏视频检测出人脸数 = 对上的脱敏帧检出人脸数，同一帧只计一次\n"
                 "帧数用同一套名称：原视频人脸帧数、脱敏视频人脸帧数、"
                 "帧率换算后原视频应脱敏帧数、帧率换算后脱敏视频检测出帧数",
            bg=BG_PANEL, fg=FG_MUTED, font=("Microsoft YaHei UI", 8),
            anchor="w", justify="left", wraplength=400)
        self.lbl_formula.pack(fill=tk.X, padx=10, pady=8)

        # 检测结果（标题 + 结果框）
        tk.Label(self._scroll_content, text="检测结果", bg=BG_CARD, fg=FG,
                 font=("Microsoft YaHei UI", 10, "bold"), anchor="w").pack(
            fill=tk.X, padx=16, pady=(0, 6))

        self.desens_result = tk.Text(self._scroll_content, height=14, wrap="word",
                                     state=tk.DISABLED, bg=BG_PANEL, fg=FG,
                                     insertbackground=FG, relief=tk.FLAT,
                                     font=("Consolas", 9),
                                     highlightthickness=1, highlightbackground=BORDER)
        self.desens_result.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))
        self._desens_right = right
        self._hook_right_wheel(right)
        # 结果框自己的滚轮绑定会先吃掉事件，这里改滚上方 Canvas 并拦住
        self.desens_result.bind("<MouseWheel>", self._on_right_mousewheel)

        # ===== 参数设置页 =====
        self.page_params = tk.Frame(self.page_container, bg=BG)
        self._build_params_page(self.page_params)

        # 默认显示检测页
        self.show_detect_page()

    def _sync_desens_panel(self, event=None):
        """右侧脱敏面板：宽度跟 Canvas，高度至少撑满视口。

        全屏时视口远高于内容，若不撑满，检测结果框下面会留下大块空白。
        """
        canvas = getattr(self, "_desens_canvas", None)
        if canvas is None:
            return
        if not canvas.winfo_exists():
            return
        view_w = canvas.winfo_width()
        view_h = canvas.winfo_height()
        if view_w < 10 or view_h < 10:
            return
        canvas.itemconfigure(self._scroll_window, width=view_w)
        self._scroll_content.update_idletasks()
        need_h = int(self._scroll_content.winfo_reqheight())
        # 内容不足一屏：把内框拉到视口高，让结果 Text 的 expand 吃掉底部空白
        if need_h < view_h:
            use_h = view_h
        else:
            use_h = need_h
        key = (view_w, view_h, use_h)
        if getattr(self, "_desens_sync_key", None) == key:
            return
        self._desens_sync_key = key
        canvas.itemconfigure(self._scroll_window, height=use_h)
        canvas.configure(scrollregion=(0, 0, view_w, use_h))
        return

    def _hook_right_wheel(self, widget):
        """右侧栏里每个控件进出时接上滚轮。子控件盖住父控件时，只绑父控件收不到进入事件。"""
        widget.bind("<Enter>", self._arm_right_wheel, add="+")
        widget.bind("<Leave>", self._disarm_right_wheel, add="+")
        for child in widget.winfo_children():
            self._hook_right_wheel(child)
        return

    def _arm_right_wheel(self, event=None):
        self.root.bind_all("<MouseWheel>", self._on_right_mousewheel)
        return

    def _disarm_right_wheel(self, event=None):
        hit = self._widget_under_pointer()
        # 还在右侧栏内部移动（例如从标题进到结果框）时保持滚轮
        if not self._widget_is_under(hit, getattr(self, "_desens_right", None)):
            self.root.unbind_all("<MouseWheel>")
        return

    def _widget_under_pointer(self):
        hit = None
        if self.root.winfo_exists():
            hit = self.root.winfo_containing(
                self.root.winfo_pointerx(), self.root.winfo_pointery())
        return hit

    def _widget_is_under(self, widget, ancestor):
        found = False
        current = widget
        while current is not None and ancestor is not None:
            if current == ancestor:
                found = True
                break
            parent = current.winfo_parent()
            # 到顶层就停，避免再往上找
            if not parent:
                current = None
            else:
                current = current.nametowidget(parent)
        return found

    def _on_right_mousewheel(self, event):
        """指针在漏帧列表上滚列表，在上方统计区滚那一块 Canvas。一屏放得下则不动。"""
        hit = self._widget_under_pointer()
        miss_host = getattr(self, "_miss_host", None)
        canvas = getattr(self, "_desens_canvas", None)
        if self._widget_is_under(hit, miss_host):
            self.miss_list.yview_scroll(int(-event.delta / 120), "units")
        elif canvas is not None and (
                self._widget_is_under(hit, canvas)
                or hit == getattr(self, "_desens_sbar", None)):
            content_h = int(self._scroll_content.winfo_reqheight())
            view_h = canvas.winfo_height()
            # 内容不超过视口时锁在顶部，避免空滚
            if content_h <= view_h:
                canvas.yview_moveto(0)
            else:
                canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def show_detect_page(self):
        """切换到检测页。"""
        self.page_params.pack_forget()
        self.page_detect.pack(fill=tk.BOTH, expand=True)
        self.btn_page_detect.config(bg=ACCENT, fg="#ffffff")
        self.btn_page_params.config(bg=BG_HOVER, fg=FG)

    def show_params_page(self):
        """切换到参数设置页。"""
        self.page_detect.pack_forget()
        self.page_params.pack(fill=tk.BOTH, expand=True)
        self.btn_page_params.config(bg=ACCENT, fg="#ffffff")
        self.btn_page_detect.config(bg=BG_HOVER, fg=FG)
        self.root.after_idle(self._sync_params_scroll)
    def _make_btn(self, parent, text, command, disabled=False, accent=False, compact=False):
        # 顶栏页签用紧凑尺寸，主操作按钮保持默认大小
        if compact:
            padx = 14
            pady = 4
            font = ("Microsoft YaHei UI", 9, "bold") if accent else ("Microsoft YaHei UI", 9)
        else:
            padx = 16
            pady = 6
            font = ("Microsoft YaHei UI", 10, "bold") if accent else ("Microsoft YaHei UI", 10)
        if accent:
            bg = ACCENT
            fg = "#ffffff"
            hover = ACCENT_HOVER
            press = BTN_ACCENT_PRESS
            border = BTN_ACCENT_BORDER
        else:
            bg = BG_HOVER
            fg = FG
            hover = BTN_NORMAL_HOVER
            press = BTN_NORMAL_PRESS
            border = BTN_NORMAL_BORDER
        btn = tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
                        activebackground=hover, activeforeground="#ffffff",
                        relief=tk.FLAT, cursor="hand2",
                        font=font, padx=padx, pady=pady,
                        bd=0, highlightthickness=1, highlightbackground=border,
                        highlightcolor=border)
        # 按下时变暗（更明显的交互反馈）
        btn.bind("<ButtonPress-1>", lambda e, b=btn, p=press: b.config(bg=p))
        btn.bind("<ButtonRelease-1>", lambda e, b=btn, h=bg: b.config(bg=h))
        if disabled:
            btn.config(state=tk.DISABLED, disabledforeground=FG_FAINT, bg=BG_CARD,
                       highlightbackground=BORDER)
        return btn

    def _panel_head(self, parent, text):
        lbl = tk.Label(parent, text=text, bg=BG_CARD, fg=FG,
                       font=("Microsoft YaHei UI", 11, "bold"), anchor="w")
        lbl.pack(fill=tk.X, padx=16, pady=(16, 10))

    def _stat_row(self, parent, label, value):
        row = tk.Frame(parent, bg=BG_PANEL)
        row.pack(fill=tk.X, padx=14, pady=3)
        tk.Label(row, text=label, bg=BG_PANEL, fg=FG_MUTED,
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT)
        val = tk.Label(row, text=value, bg=BG_PANEL, fg=FG,
                       font=("Consolas", 11, "bold"))
        val.pack(side=tk.RIGHT)
        return val

    def _apply_theme(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Horizontal.TProgressbar", background=ACCENT,
                        troughcolor=BG_PANEL, bordercolor=BG_PANEL,
                        lightcolor=ACCENT, darkcolor=ACCENT)
        style.configure("Horizontal.TScale", background=BG_CARD,
                        troughcolor=BG_PANEL, bordercolor=BORDER,
                        lightcolor=ACCENT, darkcolor=ACCENT,
                        sliderthickness=14)
        style.map("Horizontal.TScale",
                  background=[("active", ACCENT_HOVER)])
        self._apply_dark_control_styles(style)
        # 深色标题栏（需窗口映射后设置，故延迟到主循环就绪后执行）
        self.root.after(50, lambda: _enable_dark_titlebar(self.root))

    def _apply_dark_control_styles(self, style):
        """把滚动条 / 下拉框 / 数字框改成与深色主题一致的样式。"""
        ui_font = ("Microsoft YaHei UI", 9)

        # 滚动条：保留箭头以保证宽度，配色与深色面板一致
        style.configure(
            "Vertical.TScrollbar",
            background="#3d4a63",
            troughcolor=BG_CARD,
            bordercolor=BG_CARD,
            lightcolor="#3d4a63",
            darkcolor="#3d4a63",
            arrowcolor=FG_MUTED,
            relief="flat",
            borderwidth=0,
            arrowsize=13,
            gripcount=0)
        style.map(
            "Vertical.TScrollbar",
            background=[("active", "#5a6a88"), ("pressed", ACCENT)],
            arrowcolor=[("pressed", ACCENT), ("active", FG)])

        # 下拉框（含只读态：clam 默认会丢掉深色底，必须显式 map）
        style.configure(
            "TCombobox",
            fieldbackground=BG_PANEL,
            background=BG_CARD,
            foreground=FG,
            arrowcolor=FG_MUTED,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            insertcolor=FG,
            padding=(8, 5),
            relief="flat",
            borderwidth=1,
            font=ui_font)
        style.map(
            "TCombobox",
            fieldbackground=[
                ("readonly", BG_PANEL),
                ("disabled", BG_CARD),
                ("!disabled", BG_PANEL)],
            foreground=[
                ("readonly", FG),
                ("disabled", FG_FAINT),
                ("!disabled", FG)],
            selectbackground=[("readonly", BG_PANEL), ("!disabled", BG_PANEL)],
            selectforeground=[("readonly", FG)],
            bordercolor=[("focus", ACCENT), ("hover", ACCENT_HOVER)],
            arrowcolor=[("disabled", FG_FAINT), ("pressed", ACCENT), ("active", FG)],
            background=[("readonly", BG_CARD), ("!disabled", BG_CARD)])

        # 下拉弹出列表（独立 Listbox，不走 ttk style）
        self.root.option_add("*TCombobox*Listbox.background", BG_PANEL)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        self.root.option_add("*TCombobox*Listbox.font", ui_font)
        self.root.option_add("*TCombobox*Listbox.relief", "flat")
        self.root.option_add("*TCombobox*Listbox.highlightThickness", 0)

        # 数字输入框
        style.configure(
            "TSpinbox",
            fieldbackground=BG_PANEL,
            background=BG_CARD,
            foreground=FG,
            arrowcolor=FG_MUTED,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            insertcolor=FG,
            padding=(6, 4),
            relief="flat",
            borderwidth=1,
            arrowsize=12,
            font=ui_font)
        style.map(
            "TSpinbox",
            fieldbackground=[("disabled", BG_CARD), ("focus", BG_HOVER), ("!disabled", BG_PANEL)],
            foreground=[("disabled", FG_FAINT), ("!disabled", FG)],
            bordercolor=[("focus", ACCENT), ("hover", ACCENT_HOVER)],
            arrowcolor=[("disabled", FG_FAINT), ("pressed", ACCENT), ("active", FG)])
        return
    def _render_tick(self):
        """主线程定时器：轮询检测器标签、预处理结果与脱敏分析进度。"""
        # 1) 检测器标签/错误提示
        if self._detector_label_pending:
            self._detector_label_pending = False
            if self._detector_error:
                messagebox.showerror("检测器加载失败", self._detector_error,
                                     parent=self.root)
            elif self._detector_name:
                self.lbl_detector.config(text=self._detector_name)

        # 2) 处理预处理完成结果（子线程写 _preprocess_results，主线程读取）
        if self._preprocess_results:
            for is_src, (kind, payload) in list(self._preprocess_results.items()):
                del self._preprocess_results[is_src]
                if kind == "ok":
                    self._on_preprocess_done(payload, is_src)
                else:
                    self._on_preprocess_error(payload, is_src)

        # 3) 刷新脱敏率检测进度
        self._refresh_desens_progress()

        # 4) 刷新「脱敏率检测」计算进度
        self._refresh_check_progress()
        # 5) 顶层窗口拖入的文件（WndProc 只记路径）
        self._consume_toplevel_drop()

        # 继续调度
        self.root.after(30, self._render_tick)
    def _on_close(self):
        self._stop_pipeline()
        if hasattr(self, "view_src"):
            self.view_src._release()
        if hasattr(self, "view_dst"):
            self.view_dst._release()
        if self.detector is not None:
            try:
                self.detector.close()
            except Exception:
                pass
        # 销毁托盘图标
        if self._tray is not None:
            try:
                self._tray.stop()
            except Exception:
                pass
            self._tray = None
        self.root.destroy()
