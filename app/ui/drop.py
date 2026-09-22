# -*- coding: utf-8 -*-
"""Windows 拖放路径解析。"""

import os
import tkinter as tk

from app.ui import dialogs as messagebox
from app.video.formats import VIDEO_EXTS


def pick_dropped_video(paths):
    """从拖入的路径里选出第一个视频文件；没有则返回 None。"""
    chosen = None
    for p in paths:
        # 忽略空项、不存在的路径、文件夹
        if not p or not os.path.isfile(p):
            continue
        ext = os.path.splitext(p)[1].lower()
        if ext in VIDEO_EXTS:
            chosen = os.path.abspath(p)
            break
    return chosen


def _hdrop_paths(hdrop):
    """从 Windows HDROP 句柄取出拖入的全部路径，并释放句柄。"""
    import ctypes
    from ctypes import wintypes
    shell32 = ctypes.windll.shell32
    # 64 位 HDROP 是指针，默认 c_int/c_long 会 OverflowError
    shell32.DragQueryFileW.argtypes = [
        ctypes.c_void_p, wintypes.UINT, ctypes.c_wchar_p, wintypes.UINT]
    shell32.DragQueryFileW.restype = wintypes.UINT
    shell32.DragFinish.argtypes = [ctypes.c_void_p]
    handle = ctypes.c_void_p(int(hdrop))
    paths = []
    count = int(shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0))
    for i in range(count):
        nchar = int(shell32.DragQueryFileW(handle, i, None, 0))
        buf = ctypes.create_unicode_buffer(nchar + 1)
        shell32.DragQueryFileW(handle, i, buf, nchar + 1)
        paths.append(buf.value)
    shell32.DragFinish(handle)
    return paths


def _warn_drop_not_video():
    """拖入的不是支持的视频文件时给出提示。"""
    messagebox.showerror("错误", "请拖入视频文件（mp4 / avi / mov / mkv 等）")
    return
