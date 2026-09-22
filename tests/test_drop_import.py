# -*- coding: utf-8 -*-
"""拖入视频到画面区导入：路径筛选 + 带路径导入不弹对话框。"""

import os
import tempfile
import tkinter as tk

import _bootstrap
import face_video_detector as f


def _touch(path):
    with open(path, "wb") as fh:
        fh.write(b"")
    return path


def test_pick_dropped_video():
    tmp = tempfile.mkdtemp(prefix="dropvid_")
    txt = _touch(os.path.join(tmp, "note.txt"))
    folder = os.path.join(tmp, "dir")
    os.mkdir(folder)
    mp4 = _touch(os.path.join(tmp, "clip.mp4"))
    mkv = _touch(os.path.join(tmp, "clip.MKV"))
    first = f.pick_dropped_video([txt, folder, mp4, mkv])
    none = f.pick_dropped_video([txt, folder])
    case = f.pick_dropped_video([mkv])
    ok = (first == os.path.abspath(mp4)) and (none is None) and (
        case == os.path.abspath(mkv))
    return ok, first, none, case


def test_import_with_path_skips_dialog():
    asked = {"n": 0}

    def fake_ask(*_a, **_k):
        asked["n"] += 1
        return ""

    old = f.filedialog.askopenfilename
    f.filedialog.askopenfilename = fake_ask
    old_err = f.messagebox.showerror
    f.messagebox.showerror = lambda *_a, **_k: None
    exit_ok = False
    root = None
    try:
        tmp = tempfile.mkdtemp(prefix="dropimp_")
        dummy = _touch(os.path.join(tmp, "bad.mp4"))
        root = tk.Tk()
        root.withdraw()
        app = f.FaceVideoApp(root)
        root.update()
        app.import_src_video(path=dummy)
        app.import_dst_video(path=dummy)
        exit_ok = asked["n"] == 0
    finally:
        f.filedialog.askopenfilename = old
        f.messagebox.showerror = old_err
        if root is not None:
            try:
                app._on_close()
            except Exception:
                root.destroy()
    return exit_ok, asked["n"]


def test_drop_hook_on_video_panel():
    root = tk.Tk()
    root.withdraw()
    app = f.FaceVideoApp(root)
    root.update()
    app.view_src._enable_file_drop()
    hooked = len(getattr(app.view_src, "_drop_hooks", [])) >= 1
    try:
        app._on_close()
    except Exception:
        root.destroy()
    return hooked


def test_hdrop_paths_64bit():
    """64 位 HDROP 句柄必须能解析出路径，不能 OverflowError。"""
    import ctypes
    from ctypes import wintypes
    tmp = tempfile.mkdtemp(prefix="hdrop_")
    mp4 = _touch(os.path.join(tmp, "clip.mp4"))

    class DROPFILES(ctypes.Structure):
        _fields_ = [
            ("pFiles", wintypes.DWORD),
            ("pt", wintypes.POINT),
            ("fNC", wintypes.BOOL),
            ("fWide", wintypes.BOOL),
        ]

    payload = (os.path.abspath(mp4) + "\0\0").encode("utf-16-le")
    size = ctypes.sizeof(DROPFILES) + len(payload)
    buf = ctypes.create_string_buffer(size)
    df = DROPFILES.from_buffer(buf)
    df.pFiles = ctypes.sizeof(DROPFILES)
    df.fWide = True
    ctypes.memmove(ctypes.addressof(buf) + ctypes.sizeof(DROPFILES), payload, len(payload))
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    hmem = kernel32.GlobalAlloc(0x0042, size)
    ptr = kernel32.GlobalLock(hmem)
    ctypes.memmove(ptr, buf, size)
    kernel32.GlobalUnlock(hmem)
    paths = f._hdrop_paths(hmem)
    ok = os.path.abspath(mp4) in paths
    return ok, paths


def main():
    exit_code = 1
    pick_ok, first, none, case = test_pick_dropped_video()
    hdrop_ok, paths = test_hdrop_paths_64bit()
    skip_ok, asked = test_import_with_path_skips_dialog()
    hook_ok = test_drop_hook_on_video_panel()
    if pick_ok and hdrop_ok and skip_ok and hook_ok:
        print("PASS: drop pick + hdrop + import(path) + hook")
        exit_code = 0
    else:
        print(
            f"FAIL: pick_ok={pick_ok} first={first} none={none} case={case} "
            f"hdrop_ok={hdrop_ok} paths={paths} "
            f"skip_ok={skip_ok} asked={asked} hook_ok={hook_ok}"
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
