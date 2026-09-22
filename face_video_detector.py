# -*- coding: utf-8 -*-
"""兼容入口：实现按模块拆到 app/，此处再导出原公开名字。

启动、测试、打包脚本仍可 `import face_video_detector` 或直接运行本文件。
"""

from tkinter import filedialog
from app.ui import dialogs as messagebox

from app.detect.detector import FaceDetector, skin_ratio
from app.detect.track import FaceTracker, TrackGate, _iou
from app.main import main
from app.paths import _app_dir, _resource_path
from app.settings import (
    BOX_COLOR, BOX_THICKNESS, CONFIG_PATH, CONFIRM_FRAMES, DETECTOR,
    FACIAL_LANDMARK_CHECK, HAAR_CASCADE, HAAR_PARAMS, LABEL_COLOR,
    LANDMARK_MIN_POINTS, LOST_FRAMES, MIN_FACE_SIZE, MODEL_PATH,
    MP_MIN_DETECTION_CONFIDENCE, MP_MIN_PRESENCE_CONFIDENCE,
    MP_MIN_TRACKING_CONFIDENCE, PARAM_DEFS, PREPROCESS_RESIZE_ENABLED,
    PREPROCESS_RESIZE_WIDTH, QUEUE_MAXSIZE, SCRFD_MODEL, SCRFD_THRESHOLD,
    SKIN_FILTER_ENABLED, SKIN_MIN_SIZE, SKIN_RATIO_THRESHOLD, SMOOTH_ALPHA,
    TRACK_IOU_THRESHOLD, YUNET_INPUT_SCALE, YUNET_MODEL, YUNET_NMS_THRESHOLD,
    YUNET_SCORE_THRESHOLD, apply_params, get_default_params, load_config,
    load_params, save_config,
)
from app.ui.app import FaceVideoApp
from app.ui.drop import _hdrop_paths, _warn_drop_not_video, pick_dropped_video
from app.ui.video_view import VideoView
from app.video.formats import (
    VIDEO_EXTS, count_annexb_pictures, decode_seek, duration_seconds,
    format_frame_count, normalize_frame_count, probe_frame_count,
    video_open_filetypes,
)

# 历史测试与调用方使用下划线类名
_VideoView = VideoView


if __name__ == "__main__":
    main()
