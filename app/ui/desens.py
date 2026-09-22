# -*- coding: utf-8 -*-
"""脱敏率导入、预处理与检测。"""

import os
import threading
import tkinter as tk
from tkinter import filedialog

import cv2

from app.detect.detector import FaceDetector
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
        self.dst_info = None
        self._desens_progress_dst = 0
        self._desens_done_dst = 0
        self.dst_progress.config(value=0)
        self.lbl_dst_state.config(text=f"脱敏视频：{os.path.basename(path)} 分析中… 0%")
        threading.Thread(target=self._preprocess_video, args=(path, False, gen), daemon=True).start()

    def _preprocess_video(self, path, is_src, gen):
        """后台预处理：逐帧检测人脸，记录帧号+人脸框，供脱敏率检测使用。

        gen 为代次标记，若在运行期间被重新导入（gen 已过期），立即退出。
        """
        try:
            import desensitization_checker as dc
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                raise RuntimeError("无法打开视频")
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            total = probe_frame_count(
                path, cap.get(cv2.CAP_PROP_FRAME_COUNT))
            det = FaceDetector()
            faces = []   # (frame_idx, boxes)
            idx = 0
            # 记录总帧数
            if is_src:
                self._desens_total_src = total
            else:
                self._desens_total_dst = total

            def _still_alive():
                return gen == (self._desens_gen_src if is_src else self._desens_gen_dst)

            while True:
                if not _still_alive():
                    # 已被重新导入顶替，退出
                    break
                ok, frame = cap.read()
                if not ok:
                    break
                _, boxes = det.detect_and_draw(frame)
                if boxes:
                    faces.append((idx, boxes))
                    # 实时注入框数据，让播放到该帧时能立即显示检测框（边检测边显示）
                    view = self.view_src if is_src else self.view_dst
                    if hasattr(view, "face_boxes_by_frame"):
                        view.face_boxes_by_frame[idx] = boxes
                idx += 1
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
            cap.release()
            det.close()

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
            info = {"path": path, "fps": fps, "total": total, "faces": faces, "done": True}
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
            self.lbl_src_state.config(text=f"原视频：{os.path.basename(info['path'])} 完成（{n} 人脸帧）")
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
            self.lbl_dst_state.config(text=f"脱敏视频：{os.path.basename(info['path'])} 完成（{n} 人脸帧）")
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
        """后台计算：用两份预处理信息 + 重新读脱敏视频做马赛克检测。"""
        try:
            import desensitization_checker as dc
            src = self.src_info
            dst = self.dst_info

            s_fps = src["fps"]
            d_fps = dst["fps"]
            s_total = src["total"]
            d_total = dst["total"]
            src_face_count = len(src["faces"])

            # 原视频未检出人脸 → 无需脱敏，直接返回（不打开脱敏视频）
            if src_face_count == 0:
                lines = []
                lines.append(f"原视频: {s_fps:.2f} fps · {s_total} 帧 · 0 人脸帧")
                lines.append(f"脱敏视频: {d_fps:.2f} fps · {d_total} 帧")
                lines.append("应脱敏帧: 0 · 已脱敏帧: 0")
                lines.append("脱敏率: 无需脱敏 / N/A（原视频未检测到人脸）")
                self.root.after(0, self._on_desens_computed, "\n".join(lines))
                return

            dst_face_frames = {fr for fr, _ in dst["faces"]}  # 脱敏视频有人脸的帧号集合

            dst_cap = cv2.VideoCapture(dst["path"])
            if not dst_cap.isOpened():
                raise RuntimeError("无法重新打开脱敏视频")

            results = []
            skipped = 0   # 越界跳过的帧数（脱敏视频里没有对应的时长）
            self._check_total = src_face_count
            self._check_progress = 0
            for idx, (s_frame, s_boxes) in enumerate(src["faces"]):
                # 更新检测进度（主线程轮询刷新）
                self._check_progress = (idx + 1) / max(src_face_count, 1)
                # 时间对齐
                t = s_frame / s_fps
                d_frame = int(round(t * d_fps))
                # 边界保护：对齐结果越界（脱敏视频没有该时间点），跳过不计入分母
                if d_frame < 0 or d_frame >= d_total:
                    skipped += 1
                    continue
                dst_cap.set(cv2.CAP_PROP_POS_FRAMES, d_frame)
                ok, dst_img = dst_cap.read()
                if not ok:
                    skipped += 1
                    continue

                # (a) 该帧是否还能检出人脸
                face_still_there = d_frame in dst_face_frames

                # (b) 在原人脸框位置检查马赛克
                mosaic_found = False
                dh, dw = dst_img.shape[:2]
                for (x, y, w, h) in s_boxes:
                    cx = max(0, x); cy = max(0, y)
                    cw = min(w, dw - cx); ch = min(h, dh - cy)
                    if cw <= 0 or ch <= 0:
                        continue
                    region = dst_img[cy:cy + ch, cx:cx + cw]
                    if dc.is_mosaic(region):
                        mosaic_found = True
                        break

                desensitized = (not face_still_there) and mosaic_found
                if not face_still_there and mosaic_found:
                    status = "已脱敏"
                elif face_still_there:
                    status = "未脱敏(仍检出人脸)"
                else:
                    status = "未脱敏(无马赛克)"
                results.append((status, s_frame, d_frame, desensitized))

            dst_cap.release()

            dst_cap.release()

            total_should = len(results)          # 有效对齐、参与判定的帧数
            total_done = sum(1 for r in results if r[3])
            missed = [r for r in results if not r[3]]
            rate = (total_done / total_should * 100) if total_should else 0.0

            # 组装报告文本（公式已常显，这里只放数据与结果）
            lines = []
            lines.append(f"原视频: {s_fps:.2f} fps · {s_total} 帧 · {src_face_count} 人脸帧")
            lines.append(f"脱敏视频: {d_fps:.2f} fps · {d_total} 帧")
            lines.append(f"应脱敏帧: {total_should} · 已脱敏帧: {total_done}")
            lines.append(f"脱敏率: {rate:.2f}%")
            if skipped:
                lines.append(f"（{skipped} 帧对齐越界跳过，不计入）")
            lines.append("")
            if missed:
                lines.append(f"漏脱敏帧（{len(missed)}）:")
                for st, sf, df, _ in missed[:20]:
                    lines.append(f"  原帧{sf}→脱敏帧{df}: {st}")
            else:
                lines.append("全部人脸帧均已脱敏。")
            report_text = "\n".join(lines)

            self.root.after(0, self._on_desens_computed, report_text)
        except Exception as e:
            err_msg = str(e)
            self.root.after(0, self._on_desens_failed, err_msg)

    def _on_desens_failed(self, err_msg):
        self._set_desens_result(f"检测失败：{err_msg}\n")
        self.btn_check_desens.config(state=tk.NORMAL)
        self.lbl_check_state.config(text="检测进度：失败")

    def _on_desens_computed(self, report_text):
        self._set_desens_result(report_text)
        self.btn_check_desens.config(state=tk.NORMAL)
        self.check_progress.config(value=100)
        self.lbl_check_state.config(text="检测进度：完成")
