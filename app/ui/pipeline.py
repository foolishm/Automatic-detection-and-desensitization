# -*- coding: utf-8 -*-
"""单路视频检测流水线（旧播放器路径）。"""

import csv
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog

import cv2

from app.detect.detector import FaceDetector
from app.detect.track import FaceTracker, TrackGate
from app.settings import BOX_COLOR, BOX_THICKNESS, DETECTOR, LABEL_COLOR
from app.theme import ACCENT_RED, BG_CARD, BG_HOVER, FG
from app.ui import dialogs as messagebox
from app.video.formats import (
    decode_seek, duration_seconds, format_frame_count, normalize_frame_count,
    probe_frame_count, video_open_filetypes,
)


class PipelineMixin(object):
    def _set_state(self, no_video=True):
        for btn in (self.btn_play, self.btn_export, self.btn_save_stats):
            if no_video:
                btn.config(state=tk.DISABLED, bg=BG_CARD)
            else:
                btn.config(state=tk.NORMAL, bg=BG_HOVER)
        if no_video:
            self.btn_play.config(text="播放")

    # ---------- 检测器加载 ----------
    def _load_detector(self):
        try:
            self.detector = FaceDetector()
            self._detector_ready = True
            self._detector_name = {"yunet": "YuNet", "mediapipe": "MediaPipe",
                                   "haar": "Haar"}.get(DETECTOR, DETECTOR)
            self._detector_label_pending = True
        except Exception as e:
            self._detector_ready = False
            self._detector_error = str(e)
            self._detector_label_pending = True

    # ---------- 视频载入 ----------
    def open_video(self):
        path = filedialog.askopenfilename(
            title="选择视频文件",
            filetypes=video_open_filetypes(),
        )
        if not path:
            return
        self._load_video(path)

    def _load_video(self, path):
        # 停止旧流水线
        self._stop_pipeline()
        if self.detector is not None:
            self.detector.close()
        self.detector = None
        self._detector_ready = False
        threading.Thread(target=self._load_detector, daemon=True).start()

        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            messagebox.showerror("错误", "无法打开视频文件：\n%s" % path,
                                 parent=self.root)
            cap.release()
            return
        self.video_path = path
        reported = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        self._linear_seek = normalize_frame_count(reported) <= 0
        self.total_frames = probe_frame_count(path, reported)
        self.fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

        # 重置状态
        self.playing = False
        self._ended = False
        self._play_pos = 0
        self._frame_cache = {}
        self._frames_done = set()
        self.faces_frames = []
        self.frame_face_counts = {}
        self.face_tracks = []
        self._tracker = FaceTracker()
        self._smoother = TrackGate()
        self._stats_ready = False
        self._analyze_done = 0
        self._scan_finished = False
        self._stats_applied = False
        self._last_progress_ui = -1
        self._stop_play.clear()
        # 清空显示队列
        try:
            while True:
                self._display_q.get_nowait()
        except queue.Empty:
            pass

        name = os.path.basename(path)
        self.lbl_info.config(
            text=f"{name}  ·  {self.width}x{self.height}  ·  {self.fps:.1f} fps  ·  {format_frame_count(self.total_frames)} 帧"
        )
        self.lbl_total.config(text=format_frame_count(self.total_frames))
        self.lbl_face_frames.config(text="…")
        self.lbl_face_count.config(text="…")
        self.lbl_scan_state.config(text="分析中…")
        self.scan_progress.config(value=0)
        self._update_time_label(0)
        self.progress.set(0)
        self._set_state(no_video=False)
        self.btn_play.config(text="播放", bg=BG_HOVER, fg=FG)

        # 启动三级流水线
        self._start_pipeline()

    def _annotate_frame(self, frame):
        """对一帧做检测并标注，返回 (标注帧, 人脸框列表)。"""
        if not self._detector_ready or self.detector is None:
            return frame, []
        try:
            return self.detector.detect_and_draw(frame)
        except Exception:
            return frame, []

    # ---------- 流水线 ----------
    def _start_pipeline(self):
        self._pipeline_gen += 1
        gen = self._pipeline_gen
        self._pipeline_stop.clear()
        self._reader_thread = threading.Thread(target=self._reader_loop, args=(gen,), daemon=True)
        self._detect_thread = threading.Thread(target=self._detect_loop, args=(gen,), daemon=True)
        self._reader_thread.start()
        self._detect_thread.start()

    def _stop_pipeline(self):
        self.playing = False
        self._pipeline_gen += 1       # 递增代次，让旧线程立刻识别自己已过时
        self._pipeline_stop.set()
        self._stop_play.set()
        # 清空队列，让阻塞在 get/put 的线程尽快结束
        try:
            while True:
                self._raw_q.get_nowait()
        except queue.Empty:
            pass
        try:
            while True:
                self._display_q.get_nowait()
        except queue.Empty:
            pass
        # 等待旧线程退出（配合代次检查，最坏也很快返回）
        for t in (self._reader_thread, self._detect_thread, self._play_thread):
            if t is not None and t.is_alive() and t is not threading.current_thread():
                t.join(timeout=1.0)

    def _alive(self, gen):
        """判断当前线程是否仍是「活跃代次」（未被重新导入顶替）。"""
        return gen == self._pipeline_gen and not self._pipeline_stop.is_set()

    def _reader_loop(self, gen):
        """生产者线程：顺序读原始帧放入 raw_q。"""
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            self._raw_q.put(None)
            return
        idx = 0
        while self._alive(gen):
            ok, frame = cap.read()
            if not ok:
                break
            try:
                self._raw_q.put((idx, frame), timeout=0.5)
                idx += 1
            except queue.Full:
                continue
        cap.release()
        if self._alive(gen):
            self._raw_q.put(None)  # 结束信号（仅当前代次仍活跃时才发）

    def _detect_loop(self, gen):
        """检测线程：消费原始帧，检测+轨迹门控+统计，填充结果缓存。"""
        while self._alive(gen):
            try:
                item = self._raw_q.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is None:
                break
            idx, frame = item

            if not self._alive(gen):
                break
            if idx in self._frame_cache:
                pass
            else:
                annotated, raw_boxes = self._annotate_frame(frame)
                # 轨迹门控：只保留连续多帧确认的真实人脸，过滤阴影散点，并平滑抖动
                if self.backend_is_yunet():
                    boxes = self._smoother.step(raw_boxes)
                else:
                    boxes = raw_boxes
                annotated = self._redraw_boxes(frame, boxes)
                if not self._alive(gen):
                    break
                self._frame_cache[idx] = (annotated, boxes)
                self._frames_done.add(idx)
                if boxes:
                    self.faces_frames.append(idx)
                    self.frame_face_counts[idx] = len(boxes)
                    self._tracker.update(idx, boxes)

            # 进度只写共享状态，由主线程轮询刷新界面
            self._analyze_done = len(self._frames_done)

        # 扫描结束：提交统计（仅当前代次仍活跃时才提交，避免污染新视频）
        if self._alive(gen):
            self.face_tracks = self._tracker.flush()
            self._stats_ready = True
            self._scan_finished = True
            # 裸码流扫描结束后才知道真实总帧
            if self.total_frames <= 0:
                self.total_frames = len(self._frames_done)

    def backend_is_yunet(self):
        return DETECTOR == "yunet"

    def _redraw_boxes(self, frame, boxes):
        """在原始帧上按给定框列表重画标注（用于平滑后更新框位置）。"""
        out = frame.copy()
        for i, (cx, cy, cw, ch) in enumerate(boxes, start=1):
            cv2.rectangle(out, (cx, cy), (cx + cw, cy + ch), BOX_COLOR, BOX_THICKNESS)
            cv2.putText(out, f"Face {i}", (cx, max(cy - 10, 15)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, LABEL_COLOR, 2, cv2.LINE_AA)
        return out

    def _update_analyze_progress(self):
        """主线程轮询：刷新分析进度（已检测帧数 / 总帧数）。"""
        done = self._analyze_done
        if done == self._last_progress_ui and not self._scan_finished:
            return
        self._last_progress_ui = done
        if self.total_frames > 0:
            total = self.total_frames
            pct = min(done / total * 100, 100)
            total_txt = str(total)
        else:
            # 未知总帧：不按 1 当总分母，避免第 1 帧就显示 100%
            total = done
            pct = 100 if self._scan_finished else 0
            total_txt = "未知"
        self.scan_progress.config(value=pct)
        if self._scan_finished:
            ffc = len(self.faces_frames)
            fc = len(self.face_tracks)
            self.lbl_scan_state.config(
                text=f"分析完成 · 已检测 {done}/{total} 帧 · 人脸帧 {ffc} · 人脸 {fc} 张")
        elif self.total_frames > 0:
            self.lbl_scan_state.config(
                text=f"分析中… 已检测 {done} / {total_txt} 帧 ({pct:.0f}%)")
        else:
            self.lbl_scan_state.config(
                text=f"分析中… 已检测 {done} 帧")
    def _play_loop(self):
        """独立播放线程：按播放位置从缓存顺序取帧，推入显示队列（不直接碰 Tk）。"""
        delay = 1.0 / self.fps if self.fps > 0 else 0.04
        while self.playing and not self._stop_play.is_set():
            idx = self._play_pos
            if idx in self._frame_cache:
                annotated, _ = self._frame_cache[idx]
                # 只保留最新一帧，丢弃旧帧（背压控制）
                try:
                    self._display_q.put_nowait((idx, annotated))
                except queue.Full:
                    try:
                        self._display_q.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self._display_q.put_nowait((idx, annotated))
                    except queue.Full:
                        pass
                self._play_pos += 1
                # 已知总帧：播到末尾结束；未知总帧：扫描结束且缓存没有这一帧才结束
                if self.total_frames > 0:
                    ended = self._play_pos >= self.total_frames
                else:
                    ended = self._scan_finished and self._play_pos not in self._frame_cache
                if ended:
                    self._ended = True
                    self.playing = False
                    break
                self._stop_play.wait(delay)
            else:
                # 该帧还没检测到（检测节奏落后），小睡等待
                time.sleep(0.005)

    def _finish_scan(self):
        total = self.total_frames
        face_frame_count = len(self.faces_frames)
        face_count = len(self.face_tracks)

        self.lbl_total.config(text=format_frame_count(total))
        self.lbl_face_frames.config(
            text=f"{face_frame_count}（{face_frame_count / max(total, 1) * 100:.1f}%）")
        self.lbl_face_count.config(text=str(face_count))
        self._render_frames_text()

    def _render_frames_text(self):
        """把帧号统计写入右侧文本框。"""
        lines = [f"人脸帧号（共 {len(self.faces_frames)}）："]
        for seg in self._ranges(self.faces_frames):
            lines.append("  " + seg)
        lines.append("")
        if self.face_tracks:
            lines.append("按人脸分列：")
            for i, tr in enumerate(self.face_tracks, start=1):
                fr = tr["frames"]
                lines.append(f"  人脸 #{i} · {len(fr)} 帧 · {self._ranges(fr)[0]}")
                for seg in self._ranges(fr)[1:]:
                    lines.append("      " + seg)

        self.txt_frames.config(state=tk.NORMAL)
        self.txt_frames.delete("1.0", tk.END)
        self.txt_frames.insert("1.0", "\n".join(lines))
        self.txt_frames.config(state=tk.DISABLED)

    @staticmethod
    def _ranges(frame_list):
        """把帧号列表压缩为区间字符串，如 [1,2,3,5,6] -> ['1-3', '5-6']。"""
        if not frame_list:
            return ["无"]
        result = []
        start = prev = frame_list[0]
        for f in frame_list[1:]:
            if f == prev + 1:
                prev = f
            else:
                result.append(str(start) if start == prev else f"{start}-{prev}")
                start = prev = f
        result.append(str(start) if start == prev else f"{start}-{prev}")
        return result

    def save_stats(self):
        """导出统计结果到 txt 文件。"""
        if not self._stats_ready:
            messagebox.showwarning("提示", "统计尚未完成，请稍候。",
                                   parent=self.root)
            return
        default_name = os.path.splitext(os.path.basename(self.video_path))[0] + "_人脸统计.txt"
        out_path = filedialog.asksaveasfilename(
            title="保存统计报告",
            defaultextension=".txt",
            initialfile=default_name,
            filetypes=[("文本文件", "*.txt"), ("CSV 文件", "*.csv")],
        )
        if not out_path:
            return

        total = self.total_frames
        face_frame_count = len(self.faces_frames)
        face_count = len(self.face_tracks)

        if out_path.lower().endswith(".csv"):
            # CSV 格式：每张人脸一行的帧号列表
            import csv
            with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["人脸编号", "出现帧数", "出现帧号（逗号分隔）"])
                for i, tr in enumerate(self.face_tracks, start=1):
                    writer.writerow([f"人脸 #{i}", len(tr["frames"]),
                                     ",".join(str(x) for x in tr["frames"])])
                writer.writerow([])
                writer.writerow(["总帧数", total])
                writer.writerow(["检测到人脸的帧数", face_frame_count])
                writer.writerow(["检测到的人脸张数", face_count])
            messagebox.showinfo("完成", "统计已保存为 CSV：\n%s" % out_path,
                                parent=self.root)
        else:
            lines = []
            lines.append(f"视频文件：{self.video_path}")
            lines.append(f"总帧数：{total}")
            lines.append(f"检测到人脸的帧数：{face_frame_count}"
                         f"（{face_frame_count / max(total, 1) * 100:.1f}%）")
            lines.append(f"检测到的人脸张数：{face_count}")
            lines.append("")
            lines.append(f"检测到人脸的帧号（共 {face_frame_count} 帧）：")
            for seg in self._ranges(self.faces_frames):
                lines.append("  " + seg)
            lines.append("")
            lines.append("按人脸分列：")
            for i, tr in enumerate(self.face_tracks, start=1):
                fr = tr["frames"]
                lines.append(f"人脸 #{i}：共 {len(fr)} 帧")
                for seg in self._ranges(fr):
                    lines.append("  " + seg)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            messagebox.showinfo("完成", "统计已保存：\n%s" % out_path,
                                parent=self.root)


    # ---------- 播放逻辑 ----------
    def toggle_play(self):
        if self.playing:
            self._pause()
        else:
            self._play()
    def _play(self):
        if not self.video_path:
            return
        if self._ended:
            self._restart_playback()
            return
        self.playing = True
        self._stop_play.clear()
        self.btn_play.config(text="暂停", bg=ACCENT_RED, fg="#ffffff")
        # 启动独立的播放线程（按缓存顺序取帧显示）
        self._play_thread = threading.Thread(target=self._play_loop, daemon=True)
        self._play_thread.start()

    def _pause(self):
        self.playing = False
        self._stop_play.set()
        self.btn_play.config(text="播放", bg=BG_HOVER, fg=FG)

    def _on_video_end(self):
        self._ended = True
        self._pause()
        self.lbl_scan_state.config(text="播放结束 · 点击播放可重新播放")

    def _restart_playback(self):
        """重新从开头播放：重置播放位置（检测结果已缓存，无需重新检测）。"""
        self._stop_pipeline()
        self.playing = False
        self._ended = False
        self._stop_play.clear()
        self._play_pos = 0
        self.progress.set(0)
        self._update_time_label(0)
        # 若缓存不完整则重启检测流水线补全（通常已完整）
        if len(self._frames_done) < self.total_frames:
            self._start_pipeline()
        self._play()

    # ---------- 进度拖动 ----------
    def _on_scrub(self, val):
        if not self.video_path:
            return
        if getattr(self, "_updating_progress", False):
            return  # 程序更新进度条触发的回调，忽略（避免与播放位置冲突）
        # 裸码流没有可靠总帧数，拖进度条无法换算目标帧
        if self.total_frames <= 1:
            return
        ratio = float(val) / 1000.0
        target = int(ratio * max(self.total_frames - 1, 0))
        self._play_pos = target   # 同步播放位置，让播放从该帧继续
        self._seek_to(target)

    def _seek_to(self, idx):
        """跳转到指定帧：优先从缓存取，未缓存则临时读帧检测。"""
        self._update_time_label(idx)
        if idx in self._frame_cache:
            annotated, _ = self._frame_cache[idx]
            self._show_frame(annotated)
            return
        cap = cv2.VideoCapture(self.video_path)
        linear = bool(getattr(self, "_linear_seek", False))
        # 裸 H.264 禁止 cap.set，从文件头顺序抓到 idx
        cap, _, ok, frame = decode_seek(cap, self.video_path, -1, idx, linear)
        cap.release()
        if ok:
            annotated, boxes = self._annotate_frame(frame)
            self._frame_cache[idx] = (annotated, boxes)
            self._show_frame(annotated)

    # ---------- 导出 ----------
    def export_video(self):
        if not self.video_path:
            return
        if not self._detector_ready:
            messagebox.showwarning("提示", "检测器尚未就绪，请稍候再试。",
                                   parent=self.root)
            return

        default_name = os.path.splitext(os.path.basename(self.video_path))[0] + "_人脸标注.mp4"
        out_path = filedialog.asksaveasfilename(
            title="保存标注后的视频",
            defaultextension=".mp4",
            initialfile=default_name,
            filetypes=[("MP4 视频", "*.mp4")],
        )
        if not out_path:
            return

        self._pause()
        self.btn_export.config(state=tk.DISABLED)
        self.lbl_info.config(text="正在导出……请耐心等待（可看进度）")
        self._export_done_flag = False
        self._export_result = None
        self._export_progress = None

        threading.Thread(target=self._export_worker, args=(out_path,), daemon=True).start()

    def _export_worker(self, out_path):
        try:
            self._do_export(out_path)
            self._export_result = ("ok", out_path)
        except Exception as e:
            self._export_result = ("fail", str(e))
        finally:
            self._export_done_flag = True

    def _do_export(self, out_path):
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            raise RuntimeError("无法打开视频进行导出。")

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total = probe_frame_count(
            self.video_path, cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total <= 0:
            total = 1

        writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"),
                                 fps, (width, height))
        if not writer.isOpened():
            cap.release()
            raise RuntimeError("无法创建输出文件，可能编码器不受支持。")

        frame_idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_idx in self._frame_cache:
                annotated, _ = self._frame_cache[frame_idx]
            else:
                annotated, _ = self._annotate_frame(frame)
                self._frame_cache[frame_idx] = (annotated, _)
            writer.write(annotated)

            frame_idx += 1
            if frame_idx % 10 == 0:
                # 进度写共享状态，由主线程轮询刷新
                self._export_progress = (frame_idx, total)

        cap.release()
        writer.release()

        cap.release()
        writer.release()

    def _export_done(self):
        self.btn_export.config(state=tk.NORMAL, bg=BG_HOVER)
        self.lbl_info.config(text="导出完成")
    # ---------- 显示辅助 ----------
    def _show_frame(self, frame_bgr):
        # 保持宽高比缩放至画布
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw < 10 or ch < 10:
            cw, ch = 940, 520
        h, w = frame_bgr.shape[:2]
        scale = min(cw / w, ch / h)
        nw, nh = int(w * scale), int(h * scale)
        resized = cv2.resize(frame_bgr, (nw, nh), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        self._tk_image = self._to_tk_image(rgb)
        self.canvas.delete("all")
        self.canvas.create_image(cw // 2, ch // 2, image=self._tk_image, anchor=tk.CENTER)

    def _to_tk_image(self, rgb):
        import PIL.Image
        import PIL.ImageTk
        img = PIL.Image.fromarray(rgb)
        return PIL.ImageTk.PhotoImage(img)

    def _update_progress(self, pos):
        if self.total_frames > 1:
            ratio = pos / (self.total_frames - 1)
            self._updating_progress = True
            try:
                self.progress.set(ratio * 1000.0)
            finally:
                self._updating_progress = False

    def _update_time_label(self, pos):
        cur_sec = duration_seconds(pos, self.fps)
        if self.total_frames > 0:
            total_txt = self._fmt(duration_seconds(self.total_frames, self.fps))
        else:
            total_txt = "--:--"
        self.lbl_time.config(text=f"{self._fmt(cur_sec)} / {total_txt}")

    @staticmethod
    def _fmt(seconds):
        seconds = max(0, int(seconds))
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

