# -*- coding: utf-8 -*-
"""脱敏率导入、预处理与检测。"""

import os
import threading
import tkinter as tk
from tkinter import filedialog, ttk

import cv2

from app import settings as cfg
from app.detect.analyze import FrameAnalyzerPool
from app.report.desens_docx import capture_param_snapshot, write_desens_docx
from app.theme import (
    ACCENT, BG_CARD, BG_HOVER, BG_PANEL, BORDER, BTN_NORMAL_BORDER, FG, FG_FAINT,
    FG_MUTED,
)
from app.ui import dialogs as messagebox
from app.video.formats import (
    format_frame_count, probe_frame_count, video_open_filetypes,
)


class DesensMixin(object):
    def _refresh_check_progress(self):
        """主线程轮询：刷新脱敏率计算进度条。"""
        if self._check_total > 0:
            pct = min(self._check_progress * 100, 100)
            self.check_progress.config(value=pct)
            done = int(self._check_progress * self._check_total)
            self.lbl_check_state.config(
                text=f"检测进度：{done}/{self._check_total} 帧 ({pct:.0f}%)")
    def import_src_video(self, path=None):
        # 无路径：点按钮弹对话框；有路径：拖入画面区直接导入
        if not path:
            path = filedialog.askopenfilename(
                title="选择原视频",
                filetypes=video_open_filetypes())
        if not path:
            return
        # 递增代次，让旧的预处理线程退出
        self._desens_gen_src += 1
        gen = self._desens_gen_src
        # 载入预览窗口
        if not self.view_src.load(path):
            messagebox.showerror("错误", "无法打开原视频：\n%s" % path,
                                 parent=self.root)
            return
        self.view_src.face_boxes_by_frame = {}   # 清空旧框数据，边检测边重建
        self.src_info = None
        self._drop_desens_report()
        self._desens_progress_src = 0
        self._desens_done_src = 0
        self.src_progress.config(value=0)
        self.lbl_src_state.config(text=f"原视频：{os.path.basename(path)} 分析中… 0%")
        threading.Thread(target=self._preprocess_video, args=(path, True, gen), daemon=True).start()

    def import_dst_video(self, path=None):
        # 无路径：点按钮弹对话框；有路径：拖入画面区直接导入
        if not path:
            path = filedialog.askopenfilename(
                title="选择脱敏视频",
                filetypes=video_open_filetypes())
        if not path:
            return
        # 递增代次，让旧的预处理线程退出
        self._desens_gen_dst += 1
        gen = self._desens_gen_dst
        # 载入预览窗口
        if not self.view_dst.load(path):
            messagebox.showerror("错误", "无法打开脱敏视频：\n%s" % path,
                                 parent=self.root)
            return
        self.view_dst.face_boxes_by_frame = {}   # 清空旧框数据，边检测边重建
        self.view_dst.mosaic_rects_by_frame = {}
        self.dst_info = None
        self._drop_desens_report()
        self._desens_progress_dst = 0
        self._desens_done_dst = 0
        self.dst_progress.config(value=0)
        self.lbl_dst_state.config(text=f"脱敏视频：{os.path.basename(path)} 分析中… 0%")
        threading.Thread(target=self._preprocess_video, args=(path, False, gen), daemon=True).start()

    def _preprocess_video(self, path, is_src, gen):
        """后台预处理：逐帧检测人脸（脱敏视频同时记马赛克，供画面画框）。

        gen 为代次标记，若在运行期间被重新导入（gen 已过期），立即退出。
        """
        try:
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                raise RuntimeError("无法打开视频")
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            total = probe_frame_count(
                path, cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            faces = []     # (frame_idx, boxes)
            mosaics = {}   # frame_idx -> {"checker": [...], "solid": [...]}，只有脱敏视频记录、只记有马赛克的帧
            idx = 0
            view = self.view_src if is_src else self.view_dst
            # 记录总帧数
            if is_src:
                self._desens_total_src = total
            else:
                self._desens_total_dst = total

            def _still_alive():
                return gen == (self._desens_gen_src if is_src else self._desens_gen_dst)

            def _frames():
                """顺序解码，读完或被顶替即停。"""
                while _still_alive():
                    ok, frame = cap.read()
                    if not ok:
                        break
                    yield frame

            # 原视频不检测马赛克；脱敏视频与参数页「预处理涂抹马赛克」一致
            pool = FrameAnalyzerPool(with_mosaic=(not is_src) and cfg.MOSAIC_MASK_ENABLED)
            try:
                for frame_idx, result in pool.run(_frames(), _still_alive):
                    if result.record is not None:
                        mosaics[frame_idx] = result.record
                        # 实时注入马赛克框，让播放到该帧时能立即显示（边检测边显示）
                        view.mosaic_rects_by_frame[frame_idx] = result.display_rects
                    if result.boxes:
                        faces.append((frame_idx, result.boxes))
                        # 实时注入框数据，让播放到该帧时能立即显示检测框（边检测边显示）
                        view.face_boxes_by_frame[frame_idx] = result.boxes
                    idx = frame_idx + 1   # 已完成帧数
                    # 进度（写共享变量，轮询刷新）；未知总帧时不按 1 当总分母，避免第 1 帧就显示 100%
                    if total > 0:
                        pct = idx / total * 100
                    else:
                        pct = 0
                    if is_src:
                        self._desens_progress_src = pct
                        self._desens_done_src = idx
                    else:
                        self._desens_progress_dst = pct
                        self._desens_done_dst = idx
            finally:
                # 出错或被顶替也要释放解码器、线程池并恢复 OpenCV 线程设置
                cap.release()
                pool.close()

            if not _still_alive():
                return  # 已被顶替，不提交结果
            # 裸码流读完后才知道真实帧数
            if total <= 0:
                total = idx
            if is_src:
                self._desens_total_src = total
                self._desens_progress_src = 100
                self._desens_done_src = idx
            else:
                self._desens_total_dst = total
                self._desens_progress_dst = 100
                self._desens_done_dst = idx
            info = {"path": path, "fps": fps, "total": total, "faces": faces,
                    "width": width, "height": height,
                    "mosaics": mosaics, "done": True}
            # 结果写入共享变量（主线程轮询读取，避免子线程直接碰 Tk）
            self._preprocess_results[is_src] = ("ok", info)
        except Exception as e:
            # 被顶替的线程不报错（避免覆盖新线程状态）
            if is_src and gen == self._desens_gen_src:
                self._preprocess_results[is_src] = ("error", str(e))
            elif not is_src and gen == self._desens_gen_dst:
                self._preprocess_results[is_src] = ("error", str(e))

    def _on_preprocess_done(self, info, is_src):
        if is_src:
            self.src_info = info
            n = len(info["faces"])
            self.lbl_src_state.config(
                text=f"原视频：{os.path.basename(info['path'])} 完成（{n} 人脸帧）")
            self.src_progress.config(value=100)
            # 注入人脸框数据到原视频窗口（供显示检测框）
            if hasattr(self, "view_src"):
                self.view_src.face_boxes_by_frame = {fr: boxes for fr, boxes in info["faces"]}
                # 裸码流导入时 load() 的总帧是未知，分析完后补上真实帧数
                if info.get("total"):
                    self.view_src.total_frames = info["total"]
                self.view_src._refresh_overlay()
        else:
            self.dst_info = info
            n = len(info["faces"])
            m = len(info.get("mosaics", {}))
            self.lbl_dst_state.config(
                text=f"脱敏视频：{os.path.basename(info['path'])} 完成（{n} 人脸帧 · {m} 马赛克帧）")
            self.dst_progress.config(value=100)
            # 注入人脸框数据到脱敏视频窗口
            if hasattr(self, "view_dst"):
                self.view_dst.face_boxes_by_frame = {fr: boxes for fr, boxes in info["faces"]}
                if info.get("total"):
                    self.view_dst.total_frames = info["total"]  # 与原视频相同：分析完后补真实帧数
                self.view_dst._refresh_overlay()

    def _on_preprocess_error(self, err, is_src):
        if is_src:
            self.lbl_src_state.config(text=f"原视频分析失败：{err}")
        else:
            self.lbl_dst_state.config(text=f"脱敏视频分析失败：{err}")

    def _refresh_desens_progress(self):
        """主线程轮询：刷新脱敏分析进度（右侧进度条 + 帧数进度 + 各窗口下方进度条）。"""
        src_pct = min(self._desens_progress_src, 100)
        dst_pct = min(self._desens_progress_dst, 100)
        self.src_progress.config(value=src_pct)
        self.dst_progress.config(value=dst_pct)
        # 右侧状态标签：显示「已分析 X/Y 帧」帧数进度
        if self.src_info is not None:
            self.lbl_src_state.config(
                text=f"原视频：分析完成 {self._desens_done_src}/{self._desens_total_src} 帧")
        elif self._desens_total_src > 0:
            self.lbl_src_state.config(
                text=f"原视频：分析中 {self._desens_done_src}/{self._desens_total_src} 帧 ({src_pct:.0f}%)")
        elif self._desens_done_src > 0:
            # 裸码流尚无总帧数：只显示已读帧
            self.lbl_src_state.config(
                text=f"原视频：分析中 {self._desens_done_src} 帧")
        if self.dst_info is not None:
            self.lbl_dst_state.config(
                text=f"脱敏视频：分析完成 {self._desens_done_dst}/{self._desens_total_dst} 帧")
        elif self._desens_total_dst > 0:
            self.lbl_dst_state.config(
                text=f"脱敏视频：分析中 {self._desens_done_dst}/{self._desens_total_dst} 帧 ({dst_pct:.0f}%)")
        elif self._desens_done_dst > 0:
            self.lbl_dst_state.config(
                text=f"脱敏视频：分析中 {self._desens_done_dst} 帧")
        # 同步到各视频窗口下方的进度条和标签（显示 已分析帧数/总帧数）
        if hasattr(self, "view_src"):
            self.view_src.analyze_progress.config(value=src_pct)
            self._update_view_analyze_label(
                self.view_src, src_pct, self._desens_done_src, self._desens_total_src, self.src_info)
        if hasattr(self, "view_dst"):
            self.view_dst.analyze_progress.config(value=dst_pct)
            self._update_view_analyze_label(
                self.view_dst, dst_pct, self._desens_done_dst, self._desens_total_dst, self.dst_info)

    def _update_view_analyze_label(self, view, pct, done, total, info):
        """更新视频窗口下方的脱敏计算相关数据标签（帧数进度 + 脱敏数据行常显）。"""
        name = os.path.basename(view.video_path) if view.video_path else ""
        header = (f"文件：{name}\n"
                  f"分辨率：{view.width}×{view.height} · 帧率：{view.fps:.1f} fps\n"
                  f"总帧数：{format_frame_count(view.total_frames)}\n")
        # 帧数进度行
        if pct >= 100 and info is not None:
            progress = f"分析完成 · {done}/{total} 帧"
        elif total > 0 and pct > 0:
            progress = f"分析中… {done}/{total} 帧 ({pct:.0f}%)"
        elif done > 0:
            progress = f"分析中… {done} 帧"
        else:
            progress = "待分析…"
        # 脱敏数据行（常显）
        if pct >= 100 and info is not None:
            data = f"▶ 检出人脸帧：{len(info['faces'])} 帧（脱敏率检测用）"
            # 马赛克记录只给画面画框，不再参与脱敏率判定
            if view is getattr(self, "view_dst", None):
                data += f" · 马赛克帧：{len(info.get('mosaics', {}))} 帧"
        elif pct > 0:
            data = "▶ 检出人脸帧：分析中…"
        else:
            data = "▶ 检出人脸帧：-- 帧"
        view.lbl_info.config(text=header + progress + "\n" + data)

    def check_desensitization_ui(self):
        """点击「开始检测脱敏率」：检查数据是否就绪，就绪则计算。"""
        if self.src_info is None or not self.src_info.get("done"):
            messagebox.showinfo("提示", "原视频数据还未收集完成，无法进行检测。",
                                parent=self.root)
            return
        if self.dst_info is None or not self.dst_info.get("done"):
            messagebox.showinfo("提示", "脱敏视频数据还未收集完成，无法进行检测。",
                                parent=self.root)
            return
        self.btn_check_desens.config(state=tk.DISABLED)
        self._drop_desens_report()
        self._set_desens_result("正在计算脱敏率，请稍候…\n")
        self._check_progress = 0
        self._check_total = 0
        self.lbl_check_state.config(text="检测进度：开始…")
        self.check_progress.config(value=0)
        threading.Thread(target=self._compute_desensitization, daemon=True).start()

    def _set_desens_result(self, text):
        self.desens_result.config(state=tk.NORMAL)
        self.desens_result.delete("1.0", tk.END)
        self.desens_result.insert("1.0", text)
        self.desens_result.config(state=tk.DISABLED)

    def _compute_desensitization(self):
        """后台计算：只用两份预处理人脸记录做对齐比对，不再重新读视频、不用马赛克判定。"""
        try:
            import desensitization_checker as dc
            src = self.src_info
            dst = self.dst_info

            s_fps = src["fps"]
            d_fps = dst["fps"]
            s_total = src["total"]
            d_total = dst["total"]
            src_face_count = len(src["faces"])

            # 两路分辨率可能不同；无人脸时也记下，报告方法节要写换算比
            scale = dc.box_scale(src.get("width"), src.get("height"),
                                 dst.get("width"), dst.get("height"))
            report_gen = self._desens_report_gen

            # 原视频未检出人脸 → 无需脱敏，直接返回（不打开脱敏视频）
            if src_face_count == 0:
                lines = []
                lines.append(f"原视频: {s_fps:.2f} fps · {s_total} 帧 · 0 人脸帧")
                lines.append(f"脱敏视频: {d_fps:.2f} fps · {d_total} 帧")
                lines.append("换算公式: 脱敏帧号 = round(原帧号 ÷ 原帧率 × 脱敏帧率) + 帧偏移")
                lines.append("原视频人脸数: 0 · 脱敏视频人脸数: %d" % sum(
                    len(boxes) for _frame, boxes in dst["faces"]))
                lines.append("帧率换算后原视频应脱敏人脸数: 0 · 帧率换算后脱敏视频检测出人脸数: 0")
                lines.append("脱敏率: 无需脱敏 / N/A（原视频未检测到人脸）")
                lines.append("原视频人脸帧数: 0 · 脱敏视频人脸帧数: %d" % len(dst["faces"]))
                lines.append("帧率换算后原视频应脱敏帧数: 0 · 帧率换算后脱敏视频检测出帧数: 0")
                frozen = self._pack_desens_report(
                    src, dst, scale, 0, 0, [], True, 0, 0, None, dc.tally_aligned_faces([]))
                self._publish_desens_report(report_gen, frozen, "\n".join(lines))
                return

            dst_face_count = {}
            for fr, boxes in dst["faces"]:
                dst_face_count[fr] = len(boxes)
            dst_face_frames = set(dst_face_count)           # 脱敏视频有人脸的帧号集合
            dst_mosaics = dst.get("mosaics", {})             # 仅用于估计转码帧偏移，不参与成败判定
            # 脱敏设备转码有固定延迟，按时间戳对齐后仍差几帧；用马赛克位置估计偏移，判定本身只看人脸
            offset = dc.estimate_frame_offset(src["faces"], s_fps, dst_mosaics, d_fps,
                                              d_total, scale)

            rows = []
            skipped = 0   # 越界跳过的帧数（脱敏视频里没有对应的时长）
            self._check_total = src_face_count
            self._check_progress = 0
            for idx, (s_frame, s_boxes) in enumerate(src["faces"]):
                # 更新检测进度（主线程轮询刷新）
                self._check_progress = (idx + 1) / max(src_face_count, 1)
                # 时间对齐 + 帧偏移
                t = s_frame / s_fps
                d_frame = int(round(t * d_fps)) + offset
                # 边界保护：对齐结果越界（脱敏视频没有该时间点），跳过不计入分母
                if d_frame < 0 or d_frame >= d_total:
                    skipped += 1
                    continue

                # 已脱敏 = 原视频该时刻有人脸，对齐后的脱敏视频检不出人脸
                face_still_there = d_frame in dst_face_frames
                desensitized = not face_still_there
                if face_still_there:
                    status = "未脱敏(仍检出人脸)"
                else:
                    status = "已脱敏"
                rows.append({
                    "status": status,
                    "src_frame": s_frame,
                    "dst_frame": d_frame,
                    "src_faces": len(s_boxes),
                    "dst_faces": dst_face_count.get(d_frame, 0),
                    "desensitized": desensitized,
                })

            total_should = len(rows)          # 有效对齐、参与判定的帧数
            total_done = sum(1 for row in rows if row["desensitized"])
            tally = dc.tally_aligned_faces(rows)
            rate = tally["rate"]

            # 组装报告文本（公式已常显，这里只放数据与结果）
            lines = []
            lines.append(f"原视频: {s_fps:.2f} fps · {s_total} 帧 · "
                         f"{src.get('width', '?')}×{src.get('height', '?')} · {src_face_count} 人脸帧")
            lines.append(f"脱敏视频: {d_fps:.2f} fps · {d_total} 帧 · "
                         f"{dst.get('width', '?')}×{dst.get('height', '?')}")
            # 分辨率不同或存在帧偏移时把对齐参数写出来，便于核对
            if scale != (1.0, 1.0):
                lines.append(f"坐标换算: ×{scale[0]:.3f} / ×{scale[1]:.3f}")
            if offset:
                lines.append(f"帧偏移: {offset:+d} 帧（脱敏视频延迟 {offset / d_fps:.2f} s）")
            src_faces_n = 0
            for _frame, boxes in src["faces"]:
                src_faces_n += len(boxes)
            dst_faces_n = 0
            for count in dst_face_count.values():
                dst_faces_n += count
            lines.append("换算公式: 脱敏帧号 = round(原帧号 ÷ 原帧率 × 脱敏帧率) + 帧偏移")
            lines.append("原视频人脸数: %d · 脱敏视频人脸数: %d" % (src_faces_n, dst_faces_n))
            lines.append("帧率换算后原视频应脱敏人脸数: %d · 帧率换算后脱敏视频检测出人脸数: %d" % (
                tally["faces_should"], tally["faces_unique_dst"]))
            lines.append("已脱敏人脸数: %d · 脱敏率: %.2f%%" % (tally["faces_done"], rate))
            lines.append("原视频人脸帧数: %d · 脱敏视频人脸帧数: %d" % (
                len(src["faces"]), len(dst["faces"])))
            lines.append("帧率换算后原视频应脱敏帧数: %d · 帧率换算后脱敏视频检测出帧数: %d" % (
                total_should, tally["detected_dst_frames"]))
            if skipped:
                lines.append(f"（{skipped} 帧对齐越界跳过，不计入）")
            report_text = "\n".join(lines)
            frozen = self._pack_desens_report(
                src, dst, scale, offset, skipped, rows, False,
                total_should, total_done, rate, tally)
            self._publish_desens_report(report_gen, frozen, report_text)
        except Exception as e:
            err_msg = str(e)
            self.root.after(0, self._on_desens_failed, err_msg)

    def _pack_desens_report(self, src, dst, scale, offset, skipped, rows,
                            na, should, done, rate, tally):
        """把这一次比对收成导出用的字典。参数取检测结束时的值，不拖到点导出。"""
        missed = 0
        if not na:
            missed = should - done
        # 无人脸时不写百分比
        face_rate = None
        if not na:
            face_rate = tally["rate"]
        report = {
            "na": na,
            "src": self._report_side(src),
            "dst": self._report_side(dst),
            "scale": scale,
            "offset": offset,
            "should": should,
            "done": done,
            "missed": missed,
            "rate": face_rate if face_rate is not None else rate,
            "faces_should": tally["faces_should"],
            "faces_done": tally["faces_done"],
            "faces_paired_dst": tally["faces_paired_dst"],
            "faces_unique_dst": tally["faces_unique_dst"],
            "aligned_dst_frames": tally["aligned_dst_frames"],
            "detected_dst_frames": tally["detected_dst_frames"],
            "skipped": skipped,
            "rows": rows,
            "params": capture_param_snapshot(),
        }
        return report

    def _report_side(self, info):
        """一路视频在报告里要写的身份和规模。"""
        faces = info.get("faces") or []
        face_count = 0
        for _frame, boxes in faces:
            face_count += len(boxes)
        side = {
            "path": info.get("path", ""),
            "fps": info.get("fps") or 0,
            "total": info.get("total") or 0,
            "width": info.get("width"),
            "height": info.get("height"),
            "face_frames": len(faces),
            "face_count": face_count,
        }
        return side

    def _publish_desens_report(self, report_gen, frozen, report_text):
        """代次没变才留下冻结结果，再回到主线程刷新文字和按钮。"""
        # 计算过程中重新导入或清空过，这次结果作废，不再刷回界面
        if report_gen == self._desens_report_gen:
            self.last_desens_report = frozen
            self.root.after(0, self._on_desens_computed, report_text)
        return

    def _drop_desens_report(self):
        """丢掉冻结结果并禁用「生成检测报告」。"""
        self.last_desens_report = None
        self._desens_report_gen += 1
        self._set_export_report_enabled(False)
        self._clear_miss_list()
        return

    def _set_export_report_enabled(self, enabled):
        """生成报告按钮的可点状态。控件还没建好时直接跳过。"""
        btn = getattr(self, "btn_export_report", None)
        if btn is not None:
            # 可点时恢复普通按钮配色；禁用时改成灰底，避免看起来还能按
            if enabled:
                btn.config(state=tk.NORMAL, bg=BG_HOVER, fg=FG,
                           highlightbackground=BTN_NORMAL_BORDER)
            else:
                btn.config(state=tk.DISABLED, disabledforeground=FG_FAINT,
                           bg=BG_CARD, highlightbackground=BORDER)
        return

    def _report_default_name(self):
        """另存为的默认文件名：原视频主名_vs_脱敏视频主名_脱敏检测报告.docx。"""
        src = os.path.splitext(os.path.basename(self.last_desens_report["src"]["path"]))[0]
        dst = os.path.splitext(os.path.basename(self.last_desens_report["dst"]["path"]))[0]
        name = "%s_vs_%s_脱敏检测报告.docx" % (src, dst)
        return name

    def export_desens_report(self):
        """弹出另存为，确认后在后台写 docx，并可在写完前取消。"""
        report = self.last_desens_report
        path = ""
        # 没有成功的检测结果，或用户关掉另存为：什么都不写
        if report is not None:
            path = filedialog.asksaveasfilename(
                parent=self.root,
                title="保存检测报告",
                defaultextension=".docx",
                filetypes=[("Word 文档", "*.docx")],
                initialfile=self._report_default_name(),
            ) or ""
            if path and not path.lower().endswith(".docx"):
                path = path + ".docx"
        if report is not None and path:
            self._start_report_save(report, path)
        return

    def _start_report_save(self, report, path):
        """弹出正在保存，并在后台把报告写到 path。完成结果由主线程轮询取回。"""
        cancel_event = threading.Event()
        dialog = messagebox.open_saving(self.root, cancel_event.set)
        self._set_export_report_enabled(False)
        self._report_save_gen += 1
        gen = self._report_save_gen
        self._report_save_box = None

        def work():
            outcome = "fail"
            err = ""
            try:
                outcome = write_desens_docx(report, path, cancel_event.is_set)
            except Exception as exc:
                # 写盘异常：拼文档函数已删本次生成物，这里只把原因带回主线程
                outcome = "fail"
                err = str(exc)
            # 只写普通属性，不在子线程调用 Tk
            if gen == self._report_save_gen:
                self._report_save_box = (dialog, path, outcome, err)
            return

        threading.Thread(target=work, daemon=True).start()
        self._poll_report_save(gen)
        return

    def _poll_report_save(self, gen):
        """主线程查看后台是否写完。写完才关「正在保存」并决定要不要提示完成。"""
        # 又开始了一次新的保存，这次轮询作废
        if gen == self._report_save_gen and self.root.winfo_exists():
            box = self._report_save_box
            if box is None:
                self.root.after(50, lambda g=gen: self._poll_report_save(g))
            else:
                self._report_save_box = None
                dialog, path, outcome, err = box
                self._on_report_saved(dialog, path, outcome, err)
        return

    def _on_report_saved(self, dialog, path, outcome, err):
        """关掉「正在保存」。只有成功才接着弹「保存完成」。"""
        dialog.close()
        # 冻结结果还在，按钮重新可点
        if self.last_desens_report is not None:
            self._set_export_report_enabled(True)
        # 成功：单独的完成提示，正文带路径
        if outcome == "ok":
            messagebox.showinfo("保存完成", "检测报告已保存：\n%s" % path, parent=self.root)
        elif outcome == "fail":
            messagebox.showerror("保存失败", err or "检测报告未能保存。", parent=self.root)
        return

    def _on_desens_failed(self, err_msg):
        self._set_desens_result(f"检测失败：{err_msg}\n")
        self.btn_check_desens.config(state=tk.NORMAL)
        self.lbl_check_state.config(text="检测进度：失败")
        self._drop_desens_report()

    def _on_desens_computed(self, report_text):
        self._set_desens_result(report_text)
        self._fill_miss_list(self.last_desens_report)
        self.btn_check_desens.config(state=tk.NORMAL)
        self.check_progress.config(value=100)
        self.lbl_check_state.config(text="检测进度：完成")
        # 主线程再确认一次：计算期间被清空则保持禁用
        if self.last_desens_report is not None:
            self._set_export_report_enabled(True)
        return

    def _build_miss_list(self, parent):
        """右侧栏底部的漏脱敏列表。自己滚动，不放进上方 Canvas。"""
        self._miss_rows = []
        self._miss_host = parent
        self.lbl_miss_title = tk.Label(
            parent, text="漏脱敏帧", bg=BG_CARD, fg=FG,
            font=("Microsoft YaHei UI", 10, "bold"), anchor="w")
        self.lbl_miss_title.pack(fill=tk.X, padx=16, pady=(0, 6))
        box = tk.Frame(parent, bg=BG_CARD)
        box.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))
        scroll = ttk.Scrollbar(box, orient=tk.VERTICAL)
        self.miss_list = tk.Listbox(
            box, bg=BG_PANEL, fg=FG, selectbackground=ACCENT,
            selectforeground="#ffffff", activestyle="none",
            relief=tk.FLAT, highlightthickness=1, highlightbackground=BORDER,
            font=("Microsoft YaHei UI", 9), yscrollcommand=scroll.set)
        scroll.config(command=self.miss_list.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.miss_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.lbl_miss_empty = tk.Label(
            box, text="未发现漏脱敏帧", bg=BG_PANEL, fg=FG_MUTED,
            font=("Microsoft YaHei UI", 9))
        self.lbl_miss_empty.place(relx=0.5, rely=0.5, anchor="center")
        self.miss_list.bind("<<ListboxSelect>>", self._on_miss_pick)
        # 列表获得焦点时，控件自己的滚轮绑定会先于全局绑定；这里滚列表并拦住，避免滚两次
        self.miss_list.bind("<MouseWheel>", self._on_right_mousewheel)
        return

    def _clear_miss_list(self):
        """清空漏帧列表，并停掉两边还没完成的跳转。"""
        self._miss_rows = []
        miss_list = getattr(self, "miss_list", None)
        # 控件还没建好（初始化早期）时只停跳转
        if miss_list is not None:
            miss_list.delete(0, tk.END)
            self.lbl_miss_title.config(text="漏脱敏帧")
            self.lbl_miss_empty.place(relx=0.5, rely=0.5, anchor="center")
        for view in (getattr(self, "view_src", None), getattr(self, "view_dst", None)):
            if view is not None:
                view.cancel_show_frame()
        return

    def _fill_miss_list(self, report):
        """把本次漏脱敏帧写入列表。越界记录不在 rows 里，不会出现。"""
        rows = []
        src_fps = 0
        dst_fps = 0
        if report is not None:
            src_fps = report["src"]["fps"]
            dst_fps = report["dst"]["fps"]
            for row in report.get("rows") or []:
                # 仍检出人脸的才是漏脱敏
                if not row.get("desensitized"):
                    rows.append(row)
            rows.sort(key=lambda item: item["src_frame"])
        self._miss_rows = rows
        self.miss_list.delete(0, tk.END)
        for row in rows:
            self.miss_list.insert(tk.END, self._miss_line(row, src_fps, dst_fps))
        if rows:
            self.lbl_miss_title.config(text="漏脱敏帧（%d）" % len(rows))
            self.lbl_miss_empty.place_forget()
        else:
            self.lbl_miss_title.config(text="漏脱敏帧")
            self.lbl_miss_empty.place(relx=0.5, rely=0.5, anchor="center")
        return

    def _on_miss_pick(self, event=None):
        """单击一行：两边暂停并精确跳到这一行的帧号。"""
        picked = self.miss_list.curselection()
        if picked:
            row = self._miss_rows[picked[0]]
            self.view_src.show_frame(row["src_frame"])
            self.view_dst.show_frame(row["dst_frame"])
        return

    @staticmethod
    def _miss_clock(frame, fps):
        """帧号对应的时间。超过一小时才带小时。"""
        sec = 0
        if fps:
            sec = int(round(frame / float(fps)))
        if sec < 0:
            sec = 0
        hours, rem = divmod(sec, 3600)
        minutes, secs = divmod(rem, 60)
        text = "%02d:%02d" % (minutes, secs)
        if hours:
            text = "%d:%02d:%02d" % (hours, minutes, secs)
        return text

    def _miss_line(self, row, src_fps, dst_fps):
        """列表一行：时间、帧号、该帧两边人脸数。"""
        text = "%s 原帧%d → %s 脱敏帧%d  %d/%d" % (
            self._miss_clock(row["src_frame"], src_fps),
            row["src_frame"],
            self._miss_clock(row["dst_frame"], dst_fps),
            row["dst_frame"],
            row["src_faces"],
            row["dst_faces"],
        )
        return text
