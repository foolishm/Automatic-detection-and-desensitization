# -*- coding: utf-8 -*-
"""脱敏视频窗口的「马赛克框」开关：只有脱敏视频有按钮；开启时按预处理记录画橙色框；状态持久化。"""

import tkinter as tk

import _bootstrap  # noqa: F401
import cv2
import numpy as np

import face_video_detector as f
from app.theme import MOSAIC_BOX_COLOR


def _has_color(img, bgr):
    """图里是否出现指定颜色的像素。"""
    return bool(np.all(img.reshape(-1, 3) == np.array(bgr, np.uint8), axis=1).any())


def main():
    ok = True
    root = None
    app = None
    try:
        root = tk.Tk()
        root.withdraw()
        app = f.FaceVideoApp(root)
        root.update()
        # 1. 只有脱敏视频窗口有马赛克框按钮
        ok = ok and app.view_src.btn_mosaic is None
        ok = ok and app.view_dst.btn_mosaic is not None
        print("按钮: src", app.view_src.btn_mosaic is None, "dst", app.view_dst.btn_mosaic is not None)
        view = app.view_dst
        # 涂抹开关打开时按钮可点；先恢复可设置，再强制显示框（配置里可能是关）
        f.apply_params({"MOSAIC_MASK_ENABLED": True})
        view._sync_mosaic_btn()
        view.show_boxes = False
        view.show_mosaic = True
        view._sync_mosaic_btn()
        ok = ok and str(view.btn_mosaic["state"]) == "normal"
        # 2. 用一张灰底假帧 + 记录的矩形，开关开启时画出橙色框，关闭时不画
        raw = np.full((200, 300, 3), 90, np.uint8)
        view._index_trusted = True
        view.mosaic_rects_by_frame = {7: [(50, 40, 60, 80)]}
        drawn_on = view._draw_boxes(raw, 7)
        ok = ok and _has_color(drawn_on, MOSAIC_BOX_COLOR)
        ok = ok and not _has_color(raw, MOSAIC_BOX_COLOR)   # 原帧不能被污染
        view._on_mosaic_toggle()                            # 关
        drawn_off = view._draw_boxes(raw, 7)
        ok = ok and not _has_color(drawn_off, MOSAIC_BOX_COLOR)
        print("画框: 开", _has_color(drawn_on, MOSAIC_BOX_COLOR), "关", _has_color(drawn_off, MOSAIC_BOX_COLOR))
        # 3. 开关状态写进 config.json
        saved = f.load_config().get(view.mosaic_config_key)
        ok = ok and saved is False
        view._on_mosaic_toggle()                            # 复位为开
        ok = ok and f.load_config().get(view.mosaic_config_key) is True
        print("持久化键:", view.mosaic_config_key, "关闭时写入", saved)
        # 4. 没有记录的帧不画（预处理未到该帧时不做现算，保证播放不卡）
        drawn_none = view._draw_boxes(raw, 8)
        ok = ok and not _has_color(drawn_none, MOSAIC_BOX_COLOR)
        # 5. 参数页关掉涂抹后：按钮禁用、点不动、不画框
        f.apply_params({"MOSAIC_MASK_ENABLED": False})
        view._sync_mosaic_btn()
        ok = ok and str(view.btn_mosaic["state"]) == "disabled"
        ok = ok and view.show_mosaic is False
        view._on_mosaic_toggle()
        ok = ok and view.show_mosaic is False
        drawn_locked = view._draw_boxes(raw, 7)
        ok = ok and not _has_color(drawn_locked, MOSAIC_BOX_COLOR)
        print("涂抹关: state", view.btn_mosaic["state"], "show", view.show_mosaic)
    finally:
        if app is not None:
            try:
                app._on_close()
            except Exception:
                if root is not None:
                    root.destroy()
        elif root is not None:
            root.destroy()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
