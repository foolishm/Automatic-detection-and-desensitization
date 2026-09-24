# -*- coding: utf-8 -*-
"""逐帧分析（人脸 + 马赛克）与多线程有序流水线。

预处理原本是单线程逐帧串行；OpenCV 调用会释放 GIL，用几个工作线程同时处理不同帧
可以接近线性提速。`FrameAnalyzerPool.run` 负责投递、限制在飞帧数、并按帧号顺序吐出结果，
调用方拿到的顺序与单线程时完全一致。
"""

import os
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import cv2

from app.detect.detector import FaceDetector
from app.detect.mosaic import (
    checker_mosaic_masks_kind, coarse_mosaic_cells, fine_mosaic_cells,
    frame_mosaic_record, record_display_rects,
)


class FrameResult(object):
    """一帧的分析结果。"""

    __slots__ = ("boxes", "record", "display_rects", "mosaic_kind")

    def __init__(self, boxes, record, display_rects, mosaic_kind=""):
        self.boxes = boxes                  # 人脸框 [(x, y, w, h), ...]
        self.record = record                # 马赛克记录 {"checker": [...], "solid": [...]} 或 None
        self.display_rects = display_rects  # 供播放窗口画的马赛克框
        self.mosaic_kind = mosaic_kind      # fine / coarse / 空：本帧命中的格子档


def analyze_frame(det, frame, with_mosaic, cells=None):
    """分析一帧：with_mosaic=True 时先定位马赛克（供涂抹与记录），再检测人脸。

    cells：覆盖默认 MOSAIC_MASK_CELLS；预处理池在锁定视频格子档后只传其中一档。
    """
    record = None
    display_rects = []
    mosaic_kind = ""
    if with_mosaic:
        # 脱敏视频：棋盘格掩码只算一次，既交给检测器做涂抹预处理，也拆成矩形记下来
        paint, tight, mosaic_kind = checker_mosaic_masks_kind(frame, cells=cells)
        record = frame_mosaic_record(frame, checker_mask=tight)
        if record is not None:
            display_rects = record_display_rects(record)
        _, boxes = det.detect_and_draw(frame, mosaic_mask=paint)
    else:
        # 原视频，或参数关掉涂抹：只检测人脸，不跑马赛克
        _, boxes = det.detect_and_draw(frame, skip_mosaic=True)
    return FrameResult(boxes, record, display_rects, mosaic_kind)


def default_workers():
    """工作线程数：留两个核给解码 / UI，最多 6 个（实测 6 个之后收益已很小）。"""
    return max(1, min(6, (os.cpu_count() or 2) - 2))


# OpenCV 自己的算子级多线程会和帧级多线程抢核，池子运行期间把它关掉，全部结束后恢复。
# 用计数器处理原视频 / 脱敏视频两个池子同时在跑的情况。
_cv_threads_lock = threading.Lock()
_cv_threads_active = 0
_cv_threads_saved = None


def _cv_single_thread_enter():
    global _cv_threads_active, _cv_threads_saved
    with _cv_threads_lock:
        # 第一个池子进来时保存原设置并切到单线程
        if _cv_threads_active == 0:
            _cv_threads_saved = cv2.getNumThreads()
            cv2.setNumThreads(1)
        _cv_threads_active += 1


def _cv_single_thread_exit():
    global _cv_threads_active, _cv_threads_saved
    with _cv_threads_lock:
        _cv_threads_active = max(0, _cv_threads_active - 1)
        # 最后一个池子退出时恢复
        if _cv_threads_active == 0 and _cv_threads_saved is not None:
            cv2.setNumThreads(_cv_threads_saved)
            _cv_threads_saved = None


# 连续多少帧只命中同一档格子后，后面只跑这一档（空镜帧不再两档都扫）
_STYLE_LOCK_HITS = 8


class FrameAnalyzerPool(object):
    """多线程有序帧分析池。每个工作线程持有自己的 FaceDetector（YuNet 会话不跨线程共用）。"""

    def __init__(self, with_mosaic, workers=None):
        self.with_mosaic = with_mosaic
        self.workers = workers or default_workers()
        self._local = threading.local()
        self._detectors = []            # 所有线程创建过的检测器，close 时统一释放
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=self.workers)
        self._closed = False
        self._style = "unknown"         # unknown / fine / coarse
        self._fine_hits = 0
        self._coarse_hits = 0
        _cv_single_thread_enter()

    def _detector(self):
        """当前工作线程专属的检测器，首次使用时创建。"""
        det = getattr(self._local, "det", None)
        if det is None:
            det = FaceDetector()
            self._local.det = det
            with self._lock:
                self._detectors.append(det)
        return det

    def _cells(self):
        """锁定格子档之后只跑对应一档；未锁定返回 None 用默认两档。"""
        cells = None
        style = self._style
        # 已锁定：空镜也不再扫另一档
        if style == "fine":
            cells = fine_mosaic_cells() or (2,)
        elif style == "coarse":
            cells = coarse_mosaic_cells() or (4, 6, 8)
        return cells

    def _observe_style(self, kind):
        """统计命中档；同一档攒够 _STYLE_LOCK_HITS 且另一档为 0 就锁定。"""
        if kind and self._style == "unknown":
            with self._lock:
                # 锁定后并发观察不再改
                if self._style == "unknown":
                    if kind == "fine":
                        self._fine_hits += 1
                    elif kind == "coarse":
                        self._coarse_hits += 1
                    if self._fine_hits >= _STYLE_LOCK_HITS and self._coarse_hits == 0:
                        self._style = "fine"
                    elif self._coarse_hits >= _STYLE_LOCK_HITS and self._fine_hits == 0:
                        self._style = "coarse"

    def _task(self, frame):
        result = analyze_frame(self._detector(), frame, self.with_mosaic,
                               cells=self._cells() if self.with_mosaic else None)
        # 脱敏视频才根据命中档锁定，原视频不跑马赛克
        if self.with_mosaic:
            self._observe_style(result.mosaic_kind)
        return result

    def run(self, frames, still_alive):
        """按顺序消费 frames 迭代器（产出 frame），按同样顺序产出 (idx, FrameResult)。

        在飞帧数限制为 2 × 工作线程数，避免解码跑得太快把内存吃满。
        still_alive() 返回 False 时停止投递并丢弃未取回的结果。
        """
        pending = deque()
        limit = 2 * self.workers
        idx = 0
        for frame in frames:
            if not still_alive():
                break
            pending.append((idx, self._pool.submit(self._task, frame)))
            idx += 1
            # 在飞帧数达到上限：先把最早的一帧结果吐出去
            if len(pending) >= limit:
                done_idx, fut = pending.popleft()
                yield done_idx, fut.result()
        # 解码结束或被顶替：把剩余结果按序吐完（被顶替时调用方会自行忽略）
        while pending:
            done_idx, fut = pending.popleft()
            yield done_idx, fut.result()

    def close(self):
        """关闭线程池、释放各线程的检测器，并恢复 OpenCV 线程设置。重复调用无副作用。"""
        if not self._closed:
            self._closed = True
            self._pool.shutdown(wait=True)
            for det in self._detectors:
                det.close()
            self._detectors = []
            _cv_single_thread_exit()
