# -*- coding: utf-8 -*-
"""播放中按住进度条时，停顿不得把滑块拽回当前播放位置。"""

import tkinter as tk

import _bootstrap
import face_video_detector as f


def test_scrub_command_does_not_end_hold():
    """_on_scrub 不得用 after 去调松手逻辑，否则长时间按住会结束拖动。"""
    root = tk.Tk()
    root.withdraw()
    view = f._VideoView(root, "原视频", lambda: None, config_key="show_boxes_src")
    view.cap = object()
    view.total_frames = 1001
    view._on_scrub_press()
    view.progress.set(400)
    view._on_scrub("400")
    still = bool(view._scrubbing)
    no_timer = view._scrub_after is None
    view._update_progress(0)
    thumb = float(view.progress.get())
    stayed = abs(thumb - 400) < 1.0
    try:
        view._release()
        root.destroy()
    except Exception:
        try:
            root.destroy()
        except Exception:
            pass
    ok = still and no_timer and stayed
    return ok, still, no_timer, stayed, thumb


def main():
    exit_code = 1
    ok, still, no_timer, stayed, thumb = test_scrub_command_does_not_end_hold()
    if ok:
        print("PASS: hold scrub keeps slider")
        exit_code = 0
    else:
        print(
            f"FAIL: still={still} no_timer={no_timer} stayed={stayed} thumb={thumb}"
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
