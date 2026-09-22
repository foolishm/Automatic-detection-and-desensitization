# -*- coding: utf-8 -*-
"""视频后缀、裸 H.264 计帧与顺序跳转。"""

import mmap
import os

import cv2



# 可导入的视频后缀（按钮选文件 / 拖入画面区共用）
# .h264/.264 是裸 Annex-B 码流，无 mp4 容器，OpenCV/FFmpeg 仍可顺序解码
VIDEO_EXTS = (
    ".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".webm", ".m4v",
    ".h264", ".264",
)
# 超过这个值的 FRAME_COUNT 视为元数据损坏（裸码流常见天文数字）
_MAX_SANE_FRAME_COUNT = 10_000_000


def video_open_filetypes():
    """文件对话框的视频过滤器，与 VIDEO_EXTS 同步。"""
    return [
        ("视频文件", " ".join("*" + e for e in VIDEO_EXTS)),
        ("所有文件", "*.*"),
    ]


def normalize_frame_count(raw):
    """把 OpenCV FRAME_COUNT 规整成可用总帧数；不可信则返回 0（未知）。

    裸 H.264 等无容器索引的码流常给出负数或天文数字，不能拿来做进度/跳转。
    """
    result = 0
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = 0
    # 裸码流 / 损坏元数据：<=0 或过大都不能当总帧数用
    if 1 <= n <= _MAX_SANE_FRAME_COUNT:
        result = n
    return result


def format_frame_count(n):
    """界面展示用：未知总帧显示「未知」。"""
    text = "未知"
    if n and n > 0:
        text = str(int(n))
    return text


def duration_seconds(frame_count, fps):
    """总时长（秒）= 帧数 / 帧率；缺一则 0。"""
    result = 0.0
    if frame_count and fps and fps > 0:
        result = float(frame_count) / float(fps)
    return result


def _rbsp_first_bit_one(buf, start, end):
    """去掉 00 00 03 防竞争字节后，RBSP 第一 bit 是否为 1（first_mb_in_slice==0）。"""
    result = False
    zeros = 0
    i = start
    while i < end:
        b = buf[i]
        # 防竞争字节：00 00 03 里的 03 要跳过
        if zeros >= 2 and b == 3:
            zeros = 0
            i += 1
            continue
        if b == 0:
            zeros += 1
        else:
            zeros = 0
        result = (b & 0x80) != 0
        break
    return result


def _count_annexb_pictures_buf(buf):
    """在 Annex-B 缓冲里数图像 NAL（type 1/5 且 first_mb_in_slice==0）。"""
    pictures = 0
    n = len(buf)
    annexb = False
    # 文件头必须是起始码，避免把 mp4 等容器当裸流整文件扫描
    if n >= 4 and bytes(buf[0:4]) == b"\x00\x00\x00\x01":
        annexb = True
    elif n >= 3 and bytes(buf[0:3]) == b"\x00\x00\x01":
        annexb = True
    if annexb:
        marker = b"\x00\x00\x01"
        i = 0
        while True:
            j = buf.find(marker, i)
            if j < 0:
                break
            hdr = j + 3
            if hdr >= n:
                break
            ntype = buf[hdr] & 0x1F
            nxt = buf.find(marker, hdr + 1)
            end = nxt if nxt >= 0 else n
            # 只计一帧的第一片；后续 slice 的 first_mb>0，不重复加
            if ntype in (1, 5) and _rbsp_first_bit_one(buf, hdr + 1, end):
                pictures += 1
            i = hdr + 1
    return pictures


def count_annexb_pictures(path):
    """扫描裸 H.264 Annex-B 码流，返回图像帧数；不是裸流则 0。"""
    result = 0
    try:
        size = os.path.getsize(path)
        if size <= 0:
            result = 0
        else:
            with open(path, "rb") as fh:
                mm = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
                try:
                    result = _count_annexb_pictures_buf(mm)
                finally:
                    mm.close()
    except (OSError, ValueError, TypeError):
        result = 0
    return result


def probe_frame_count(path, reported=None):
    """优先用 OpenCV 总帧；不可信时再扫裸 H.264 起始码计数。"""
    result = normalize_frame_count(reported)
    if result <= 0:
        result = count_annexb_pictures(path)
    return result


def decode_seek(cap, path, decode_idx, target, linear):
    """跳到 target 帧，返回 (cap, decode_idx, ok, frame)。

    linear=True：裸 H.264 等无索引码流禁止 cap.set（它只会前进约一个 GOP），
    后退则重开文件，前进用 grab 丢帧直到目标。
    """
    ok = False
    frame = None
    out_cap = cap
    out_idx = decode_idx
    if cap is None or target is None or target < 0:
        pass
    elif (not linear) and cap is not None:
        # 有容器索引：仍用 cap.set（关键帧误差由调用方按不可信帧号处理）
        cap.set(cv2.CAP_PROP_POS_FRAMES, target)
        ok, frame = cap.read()
        if ok:
            out_idx = target
    elif target == decode_idx:
        pass
    else:
        # 目标在当前帧之前：解码器不能回退，只能重开从第 0 帧再走
        if decode_idx is None or target < decode_idx:
            try:
                cap.release()
            except Exception:
                pass
            out_cap = cv2.VideoCapture(path)
            decode_idx = -1
        opened = out_cap is not None and out_cap.isOpened()
        if opened:
            skipped = True
            nskip = target - (decode_idx + 1)
            i = 0
            while i < nskip:
                if not out_cap.grab():
                    skipped = False
                    break
                i += 1
            if skipped:
                ok, frame = out_cap.read()
                if ok:
                    out_idx = target
    return out_cap, out_idx, ok, frame
