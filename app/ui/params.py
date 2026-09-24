# -*- coding: utf-8 -*-
"""参数设置页。"""

import tkinter as tk
from tkinter import ttk

from app import settings as cfg
from app.settings import (
    PARAM_DEFS, apply_params, get_default_params, load_config, save_config,
)
from app.theme import (
    ACCENT, ACCENT_GREEN, ACCENT_HOVER, BG, BG_CARD, BG_HOVER, BG_PANEL, BORDER,
    BTN_GREEN_BORDER, BTN_NORMAL_BORDER, FG, FG_FAINT, FG_MUTED,
)
from app.ui import dialogs as messagebox

# 全屏时参数卡片不要拉到整屏宽，避免左侧说明和右侧控件隔太远
_PARAMS_CARD_MAX_WIDTH = 960


class ParamsMixin(object):
    def _build_params_page(self, parent):
        """构建参数设置页（参数列表可滚动，按钮固定底部）。"""
        # 标题
        head = tk.Frame(parent, bg=BG)
        head.pack(fill=tk.X, padx=8, pady=(4, 8))
        tk.Label(head, text="检测参数", bg=BG, fg=FG,
                 font=("Microsoft YaHei UI", 13, "bold")).pack(side=tk.LEFT)
        tk.Label(head, text="保存后需重新导入视频才会按新参数分析。",
                 bg=BG, fg=FG_MUTED, font=("Microsoft YaHei UI", 9)).pack(
            side=tk.LEFT, padx=(12, 0))

        # 底部操作条（与列表分开，避免挡住最后一项）
        btn_bar = tk.Frame(parent, bg=BG_PANEL, highlightthickness=1,
                           highlightbackground=BORDER)
        btn_bar.pack(side=tk.BOTTOM, fill=tk.X)
        # 按钮条与参数卡片同宽居中，避免全屏时「恢复/保存」贴在屏幕两端
        self._params_btn_inner = tk.Frame(btn_bar, bg=BG_PANEL)
        self._params_btn_inner.pack(fill=tk.X, padx=16, pady=10)
        self._make_btn(self._params_btn_inner, "恢复默认值", self._restore_param_defaults,
                       accent=False).pack(side=tk.LEFT)
        self._make_btn(self._params_btn_inner, "保存", self._save_params, accent=True).pack(
            side=tk.RIGHT)

        # 参数列表（Canvas + Scrollbar 放进同一容器，左右并排，可滚轮滚动）
        scroll_frame = tk.Frame(parent, bg=BG)
        scroll_frame.pack(fill=tk.BOTH, expand=True, padx=(0, 0), pady=(0, 10))

        sbar = ttk.Scrollbar(scroll_frame, orient=tk.VERTICAL)
        sbar.pack(side=tk.RIGHT, fill=tk.Y)

        scroll = tk.Canvas(scroll_frame, bg=BG, highlightthickness=0,
                           yscrollcommand=sbar.set)
        scroll.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sbar.configure(command=scroll.yview)
        self._params_canvas = scroll
        self._params_sbar = sbar

        wrap = tk.Frame(scroll, bg=BG)
        self._params_window = scroll.create_window((0, 0), window=wrap, anchor="nw")
        wrap.bind("<Configure>", self._sync_params_scroll)
        scroll.bind("<Configure>", self._sync_params_scroll)
        # 鼠标滚轮滚动（内容不足一屏时不滚动，避免全屏空滚）
        scroll.bind("<Enter>", lambda e: scroll.bind_all(
            "<MouseWheel>", self._on_params_mousewheel))
        scroll.bind("<Leave>", lambda e: scroll.unbind_all("<MouseWheel>"))

        # 当前生效参数值：按 PARAM_DEFS 从 settings 实时读取，新增参数无需再手写一份键列表
        current = {p["key"]: getattr(cfg, p["key"]) for p in PARAM_DEFS}
        self._param_vars = {}
        self._param_bool_btns = {}   # 布尔参数的「开/关」按钮引用（恢复默认值时同步样式）
        self._param_choice_val2label = {}  # choice 参数的 (label2val, val2label) 映射
        self._param_defs = PARAM_DEFS

        for p in PARAM_DEFS:
            key = p["key"]
            row = tk.Frame(wrap, bg=BG_CARD, highlightthickness=1,
                           highlightbackground=BORDER)
            row.pack(fill=tk.X, pady=2, padx=(0, 8))

            left = tk.Frame(row, bg=BG_CARD)
            left.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(16, 8), pady=8)
            tk.Label(left, text=p["label"], bg=BG_CARD, fg=FG,
                     font=("Microsoft YaHei UI", 10)).pack(anchor="w")
            help_lbl = tk.Label(left, text=p["help"], bg=BG_CARD, fg=FG_FAINT,
                                font=("Microsoft YaHei UI", 8), wraplength=560,
                                justify="left")
            help_lbl.pack(anchor="w", pady=(2, 0))
            left.bind(
                "<Configure>",
                lambda e, lbl=help_lbl: lbl.config(
                    wraplength=max(240, e.width - 8)))

            if p["type"] == "bool":
                var = tk.BooleanVar(value=bool(current[key]))
                self._param_vars[key] = var
                # 用「开/关」切换按钮代替勾选框，选中/未选中对比明显
                btn = tk.Button(row, text="开" if var.get() else "关",
                                width=4,
                                bg=ACCENT_GREEN if var.get() else BG_HOVER,
                                fg="#04110a" if var.get() else FG_MUTED,
                                activebackground=ACCENT_HOVER,
                                activeforeground="#ffffff",
                                relief=tk.FLAT, cursor="hand2",
                                font=("Microsoft YaHei UI", 9, "bold"),
                                bd=0, highlightthickness=1,
                                highlightbackground=BTN_GREEN_BORDER if var.get() else BTN_NORMAL_BORDER,
                                highlightcolor=BTN_GREEN_BORDER if var.get() else BTN_NORMAL_BORDER)
                btn.config(command=lambda v=var, b=btn: self._toggle_bool(v, b))
                btn.pack(side=tk.RIGHT, padx=16)
                self._param_bool_btns[key] = btn
            elif p["type"] == "int":
                var = tk.StringVar(value=str(int(current[key])))
                self._make_param_spinbox(
                    row, var, p.get("min", 0), p.get("max", 1000),
                    p.get("step", 1)).pack(side=tk.RIGHT, padx=16, pady=10)
                self._param_vars[key] = var
            elif p["type"] == "choice":
                # options 可能是 [(显示文本, 值)] 或 [值]
                opts = p.get("options", [])
                if opts and isinstance(opts[0], (tuple, list)):
                    # (显示文本, 值) 形式：用 Combobox 显示文本，内部存值
                    label2val = {str(t): v for t, v in opts}
                    val2label = {str(v): t for t, v in opts}
                    labels = [str(t) for t, _ in opts]
                    # 当前值对应的显示文本
                    cur_label = val2label.get(str(int(current[key])), labels[0])
                    var = tk.StringVar(value=cur_label)
                    cb = ttk.Combobox(row, textvariable=var, values=labels,
                                      state="readonly", width=18)
                    cb.pack(side=tk.RIGHT, padx=16, pady=10)
                    self._param_vars[key] = var
                    self._param_choice_val2label[key] = (label2val, val2label)
                else:
                    # 纯值列表：同样用深色 Combobox，避免 OptionMenu 系统默认样式
                    var = tk.StringVar(value=str(int(current[key])))
                    options = [str(o) for o in opts]
                    cb = ttk.Combobox(row, textvariable=var, values=options,
                                      state="readonly", width=18)
                    cb.pack(side=tk.RIGHT, padx=16, pady=10)
                    self._param_vars[key] = var
            else:
                # 浮点参数
                var = tk.StringVar(value=f"{float(current[key]):.2f}")
                self._make_param_spinbox(
                    row, var, p.get("min", 0.0), p.get("max", 1.0),
                    p.get("step", 0.1)).pack(side=tk.RIGHT, padx=16, pady=10)
                self._param_vars[key] = var

    def _sync_params_scroll(self, event=None):
        """按视口与内容高度同步参数列表滚动区域。

        内容不超过一屏时把 scrollregion 锁成视口大小并回到顶部，
        避免全屏时到顶仍能空滚。
        """
        canvas = getattr(self, "_params_canvas", None)
        if canvas is None:
            return
        if not canvas.winfo_exists():
            return
        view_w = canvas.winfo_width()
        view_h = canvas.winfo_height()
        if view_w < 10 or view_h < 10:
            return
        # 视口很宽时卡片居中限宽，小窗口仍铺满
        if view_w > _PARAMS_CARD_MAX_WIDTH:
            content_w = _PARAMS_CARD_MAX_WIDTH
            origin_x = (view_w - content_w) // 2
        else:
            content_w = view_w
            origin_x = 0
        canvas.itemconfigure(self._params_window, width=content_w)
        canvas.coords(self._params_window, origin_x, 0)
        inner = getattr(self, "_params_btn_inner", None)
        # 底部按钮跟随卡片左右边，全屏时不要贴在屏幕两端
        if inner is not None and inner.winfo_exists():
            inner.pack_configure(padx=max(16, origin_x))
        bbox = canvas.bbox("all")
        if bbox is None:
            return
        content_h = bbox[3] - bbox[1]
        # 内容能完整放下：滚动区等于视口，锁在顶部
        if content_h <= view_h:
            canvas.configure(scrollregion=(0, 0, view_w, view_h))
            canvas.yview_moveto(0)
        else:
            canvas.configure(scrollregion=(0, 0, view_w, content_h))
        return

    def _on_params_mousewheel(self, event):
        """参数列表滚轮：仅当内容超出视口时滚动。"""
        canvas = getattr(self, "_params_canvas", None)
        if canvas is None:
            return
        bbox = canvas.bbox("all")
        if bbox is None:
            return
        content_h = bbox[3] - bbox[1]
        view_h = canvas.winfo_height()
        # 一屏能显示完则不滚动
        if content_h <= view_h:
            canvas.yview_moveto(0)
        else:
            canvas.yview_scroll(int(-event.delta / 120), "units")
        return

    def _make_param_spinbox(self, parent, var, from_, to, increment):
        """参数页数值输入框：深色 ttk.Spinbox，与下拉框视觉一致。"""
        box = ttk.Spinbox(
            parent, from_=from_, to=to, increment=increment,
            textvariable=var, width=10)
        return box

    def _save_params(self):
        """收集参数输入、校验、应用、持久化。"""
        new_params = {}
        err = None
        try:
            for p in self._param_defs:
                key = p["key"]
                var = self._param_vars[key]
                # 布尔开关直接取当前按钮状态
                if p["type"] == "bool":
                    new_params[key] = bool(var.get())
                elif p["type"] == "int":
                    val = int(var.get())
                    if "min" in p and val < p["min"]:
                        raise ValueError(f"{p['label']} 不能小于 {p['min']}")
                    if "max" in p and val > p["max"]:
                        raise ValueError(f"{p['label']} 不能大于 {p['max']}")
                    new_params[key] = val
                elif p["type"] == "choice":
                    mapping = getattr(self, "_param_choice_val2label", {}).get(key)
                    # 有显示文本映射时从 Combobox 文案转回实际数值
                    if mapping:
                        label2val, _ = mapping
                        label = var.get()
                        new_params[key] = label2val.get(label, None)
                    else:
                        new_params[key] = int(var.get())
                else:
                    # 浮点参数
                    val = float(var.get())
                    if "min" in p and val < p["min"]:
                        raise ValueError(f"{p['label']} 不能小于 {p['min']}")
                    if "max" in p and val > p["max"]:
                        raise ValueError(f"{p['label']} 不能大于 {p['max']}")
                    new_params[key] = val
        except ValueError as e:
            err = str(e)
        # 校验失败只提示错误，不写配置
        if err is not None:
            messagebox.showerror("参数错误", err, parent=self.root)
        else:
            apply_params(new_params)
            persist = load_config()
            persist.update(new_params)
            save_config(persist)
            self._sync_skin_btn()
            # 涂抹开关变化时，脱敏视频的马赛克框按钮立刻变成可设 / 禁用
            if hasattr(self, "view_dst"):
                self.view_dst._sync_mosaic_btn()
                self.view_dst._refresh_overlay()
            self._clear_videos()   # 参数已变，清空旧视频数据，让用户用新参数重新分析
            messagebox.showinfo("成功", "参数已保存，请重新导入视频进行分析。",
                                parent=self.root)
        return

    def _clear_videos(self):
        """清空已导入的视频及其分析结果（参数变化后旧结果已失效）。"""
        # 清空预处理结果
        self.src_info = None
        self.dst_info = None
        self._desens_progress_src = 0
        self._desens_progress_dst = 0
        self._desens_done_src = 0
        self._desens_done_dst = 0
        self._desens_total_src = 0
        self._desens_total_dst = 0
        self._desens_gen_src += 1   # 让旧的预处理线程退出
        self._desens_gen_dst += 1

        # 释放两个视频窗口
        if hasattr(self, "view_src"):
            self.view_src._release()
            self.view_src.video_path = None
            self.view_src.total_frames = 0
            self.view_src.face_boxes_by_frame = {}
            self.view_src.btn_play.config(state=tk.DISABLED, text="播放", bg=BG_HOVER, fg=FG)
            self.view_src._paint_canvas_bg()
            self.view_src.lbl_info.config(text="未导入视频")
        if hasattr(self, "view_dst"):
            self.view_dst._release()
            self.view_dst.video_path = None
            self.view_dst.total_frames = 0
            self.view_dst.face_boxes_by_frame = {}
            self.view_dst.mosaic_rects_by_frame = {}
            self.view_dst.btn_play.config(state=tk.DISABLED, text="播放", bg=BG_HOVER, fg=FG)
            self.view_dst._paint_canvas_bg()
            self.view_dst.lbl_info.config(text="未导入视频")

        # 重置右侧面板状态
        self.lbl_src_state.config(text="原视频：未导入")
        self.lbl_dst_state.config(text="脱敏视频：未导入")
        self.src_progress.config(value=0)
        self.dst_progress.config(value=0)
        self.check_progress.config(value=0)
        self.lbl_check_state.config(text="检测进度：未开始")
        self._set_desens_result("")
        self._drop_desens_report()

    def _restore_param_defaults(self):
        """把参数控件填回默认值（不立即保存，等用户点保存）。"""
        defaults = get_default_params()
        for p in self._param_defs:
            key = p["key"]
            if p["type"] == "bool":
                self._param_vars[key].set(bool(defaults[key]))
                # 同步开关按钮样式
                btn = self._param_bool_btns.get(key)
                if btn:
                    if defaults[key]:
                        btn.config(text="开", bg=ACCENT_GREEN, fg="#04110a",
                                   highlightbackground=BTN_GREEN_BORDER,
                                   highlightcolor=BTN_GREEN_BORDER)
                    else:
                        btn.config(text="关", bg=BG_HOVER, fg=FG_MUTED,
                                   highlightbackground=BTN_NORMAL_BORDER,
                                   highlightcolor=BTN_NORMAL_BORDER)
            elif p["type"] == "int":
                self._param_vars[key].set(str(int(defaults[key])))
            elif p["type"] == "choice":
                mapping = getattr(self, "_param_choice_val2label", {}).get(key)
                if mapping:
                    _, val2label = mapping
                    label = val2label.get(str(int(defaults[key])))
                    self._param_vars[key].set(label if label else str(int(defaults[key])))
                else:
                    self._param_vars[key].set(str(int(defaults[key])))
            else:
                self._param_vars[key].set(f"{float(defaults[key]):.2f}")

    def _toggle_bool(self, var, btn):
        """切换布尔参数的开/关状态，并同步按钮样式。"""
        var.set(not var.get())
        if var.get():
            btn.config(text="开", bg=ACCENT_GREEN, fg="#04110a",
                       highlightbackground=BTN_GREEN_BORDER,
                       highlightcolor=BTN_GREEN_BORDER)
        else:
            btn.config(text="关", bg=BG_HOVER, fg=FG_MUTED,
                       highlightbackground=BTN_NORMAL_BORDER,
                       highlightcolor=BTN_NORMAL_BORDER)

    def _sync_skin_btn(self):
        """同步主界面肤色按钮文字到当前 SKIN_FILTER_ENABLED 状态。"""
        if cfg.SKIN_FILTER_ENABLED:
            self.btn_skin.config(text="肤色过滤：开", bg=ACCENT_GREEN, fg="#04110a")
        else:
            self.btn_skin.config(text="肤色过滤：关", bg=BG_HOVER, fg=FG_MUTED)

    def toggle_skin_filter(self):
        """切换肤色校验开关（运行时动态切换，并持久化到配置）。"""
        cfg.SKIN_FILTER_ENABLED = not cfg.SKIN_FILTER_ENABLED
        if cfg.SKIN_FILTER_ENABLED:
            self.btn_skin.config(text="肤色过滤：开", bg=ACCENT_GREEN, fg="#04110a")
        else:
            self.btn_skin.config(text="肤色过滤：关", bg=BG_HOVER, fg=FG_MUTED)
        persist = load_config()
        persist["SKIN_FILTER_ENABLED"] = cfg.SKIN_FILTER_ENABLED
        save_config(persist)

    # ==================== 参数设置对话框 ====================
