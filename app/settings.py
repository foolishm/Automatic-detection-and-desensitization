# -*- coding: utf-8 -*-
"""检测参数、配置文件读写。"""

import os

import cv2

from app.paths import _app_dir, _resource_path


# ============================== 可配置项 ==============================
# 检测后端（三选一）：
#   "yunet"     —— 默认。OpenCV YuNet 深度学习检测器，抗遮挡最强（推荐）
#   "mediapipe" —— MediaPipe FaceLandmarker，精细人脸网格，但遮挡鲁棒性较差
#   "haar"      —— OpenCV Haar 级联，无需模型文件（注意：新版 opencv 可能已移除 xml）
DETECTOR = "yunet"

# YuNet 模型文件（与脚本同目录 / exe 内）
YUNET_MODEL = _resource_path("face_detection_yunet_2023mar.onnx")
YUNET_SCORE_THRESHOLD = 0.8   # 检测置信度阈值：越高越严格（少误检）。0.8 较严格，可显著减少误检；
                              # 若远距离小人脸漏检，可适当调低（但误检会增多）。
YUNET_NMS_THRESHOLD = 0.3     # 非极大值抑制阈值，抑制重叠框
YUNET_INPUT_SCALE = 1.0       # 输入帧缩放比例：1.0 = 不降分辨率（在原分辨率上检测，远处人脸最准）。
                              # <1.0 会先缩小帧再检测（更快/省 CPU，但远处小人脸更糊、更易漏检）。

# 预处理缩放（检测前是否把帧缩放到指定宽度，可加快检测/省 CPU）
PREPROCESS_RESIZE_ENABLED = True  # 是否缩放分辨率：True=缩放，False=用原分辨率检测
PREPROCESS_RESIZE_WIDTH = 640     # 缩放目标宽度（像素），高度按原图宽高比自动等比缩放。
                                  # 缩放会降低 CPU 占用、加快速度，但过小会导致远处小人脸更糊、更易漏检。

# 预处理：半透明棋盘格马赛克涂抹（检测前把马赛克区域涂成纯色，防止透出的人脸被检出）
MOSAIC_MASK_ENABLED = True        # 是否启用马赛克涂抹：True=启用，False=关闭
MOSAIC_MASK_COLOR = 255           # 涂抹颜色（灰度值）：255=全白，0=全黑
MOSAIC_MASK_THRESHOLD = 40        # 棋盘格响应阈值：越低越敏感（更容易把纹理当马赛克）
MOSAIC_MASK_PERIOD_THRESHOLD = 35 # 周期性校验阈值：排除字幕数字等单方向重复纹理
MOSAIC_MASK_CELLS = (2, 4, 6, 8)  # 候选方格边长（像素）。2px 覆盖实心细棋盘格，
                                  # 4/6/8 覆盖半透明叠加码；核对 ±1px 仍有响应
MOSAIC_MASK_MIN_SIDE = 6          # 马赛克连通域最短边（像素）。小于此值的块当噪点丢掉；
                                  # 6 = 原先「3 个最小方格」的默认值

# 人脸框平滑（消除相邻帧检测框抖动）
SMOOTH_ALPHA = 0.5            # 平滑系数 0~1：越小越平滑（越跟手越慢）；1 = 不平滑
MIN_FACE_SIZE = 20            # 最小人脸边长（像素）：保留远距离小人脸。误检交由轨迹稳定性过滤。

# 轨迹稳定性过滤（区分「真实人脸」与「阴影散点误检」）
CONFIRM_FRAMES = 3            # 连续出现多少帧才确认是真实人脸（阴影散点通常只出现 1~2 帧）
LOST_FRAMES = 5               # 确认后连续丢失多少帧才移除该轨迹

# 肤色校验（只对「中大型框」启用，用于挡轮胎/车辆配件等肤色≈0 的误检）
SKIN_FILTER_ENABLED = True    # 肤色校验开关：True=启用，False=关闭。
                              # 黑白/红外/夜视画面没有肤色信息，应设为 False，否则会误杀所有框。
SKIN_MIN_SIZE = 60            # 仅当框边长 ≥ 此值时，按 SKIN_RATIO_THRESHOLD 做完整肤色校验
                              # （远处小人脸较小、肤色弱，不用这条，以免误杀）
SKIN_RATIO_THRESHOLD = 0.10   # 中大框内肤色占比低于此值判定为非人脸（轮胎≈0，人脸通常 0.15+）
SKIN_DARK_RATIO = 0.02        # 小框只在肤色接近 0 时才继续看明暗
SKIN_DARK_MAX = 110           # 小框平均亮度（HSV 的 V）低于此值且几乎无肤色，视为轮胎等暗块
                              # 实测车轮 V≤106；马赛克仍透出的人脸 V≥127，不能用同一刀切掉

# 五官二次校验（用 SCRFD 检测框内是否有眼/鼻/嘴，挡「只有耳朵/后脑勺」的误检）
FACIAL_LANDMARK_CHECK = False  # 五官二次校验总开关：默认关闭。
                               # SCRFD 能检测小脸（低至 ~20px）并输出 5 关键点（双眼/鼻/两嘴角），
                               # 因此对远距离监控也能用（比 MediaPipe 的 ~100px 要求强很多）。
LANDMARK_MIN_POINTS = 1        # 框内需定位到的五官关键点(眼/鼻/嘴)最小数量，低于=判为「无五官」过滤掉。
                               # 默认 1 = 只要检测到眼睛/鼻子/嘴任意一个就算有效（侧脸/遮挡也保留）。
SCRFD_THRESHOLD = 0.3          # SCRFD 检测置信度阈值：越低越容易检出（少漏检，但可能多误检）。
                               # 漏检真脸时可调低到 0.2~0.25；误检「耳朵」仍多时可调高到 0.4~0.5。

HAAR_CASCADE = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
HAAR_PARAMS = {
    "scaleFactor": 1.1,
    "minNeighbors": 5,
    "minSize": (40, 40),
}

# MediaPipe 参数
# 说明：数值越低，越容易检测到人脸（对被遮挡/侧面/模糊更鲁棒），
#       但误检（把非人脸当脸）的概率也会升高。遮挡严重时可按需继续调低。
MP_MIN_DETECTION_CONFIDENCE = 0.3   # 人脸检测置信度（默认 0.5）
MP_MIN_PRESENCE_CONFIDENCE = 0.3    # 人脸存在置信度（默认 0.5，遮挡时主因）
MP_MIN_TRACKING_CONFIDENCE = 0.3    # 追踪置信度（默认 0.5）

BOX_COLOR = (0, 255, 0)   # 人脸框颜色（BGR：绿色）
BOX_THICKNESS = 2
LABEL_COLOR = (255, 255, 255)

# 人脸聚类（跨帧追踪同一张人脸）参数
TRACK_IOU_THRESHOLD = 0.3     # 交并比阈值，超过则认为相邻帧是同一张脸

# 流水线队列上限（防止内存无限增长）
QUEUE_MAXSIZE = 64
# ============================== 配置持久化 ==============================
CONFIG_PATH = os.path.join(_app_dir(), "config.json")


def load_config():
    """读取配置文件（JSON），文件不存在或损坏时返回空 dict。"""
    try:
        if os.path.exists(CONFIG_PATH):
            import json
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_config(data):
    """把配置写入配置文件（JSON）。"""
    try:
        import json
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ============================== 检测参数元数据 ==============================
# 每个参数：label=中文名, type=float/int/bool, default=默认值, min/max=数值范围(可选), step=步进, help=说明
PARAM_DEFS = [
    {"key": "YUNET_SCORE_THRESHOLD", "label": "检测置信度阈值", "type": "float",
     "default": 0.8, "min": 0.1, "max": 0.99, "step": 0.05,
     "help": "越高越严格（少误检）。0.8 较严格，可显著减少误检；调低可减少远处小人脸漏检。"},
    {"key": "MIN_FACE_SIZE", "label": "最小人脸边长(px)", "type": "int",
     "default": 20, "min": 5, "max": 200, "step": 5,
     "help": "过滤小于该边长的检测框（阴影/噪点）。"},
    {"key": "SKIN_FILTER_ENABLED", "label": "肤色过滤", "type": "bool",
     "default": True,
     "help": "挡轮胎/车辆配件等肤色≈0 的误检。黑白/红外画面应关闭。"},
    {"key": "SKIN_MIN_SIZE", "label": "肤色校验最小边长(px)", "type": "int",
     "default": 60, "min": 20, "max": 300, "step": 10,
     "help": "仅当框边长≥此值才做肤色校验（远处小人脸肤色弱，跳过以免误杀）。"},
    {"key": "SKIN_RATIO_THRESHOLD", "label": "肤色占比阈值", "type": "float",
     "default": 0.10, "min": 0.01, "max": 0.5, "step": 0.01,
     "help": "框内肤色占比低于此值判为非人脸（轮胎≈0，人脸通常 0.15+）。"},
    {"key": "CONFIRM_FRAMES", "label": "轨迹确认帧数", "type": "int",
     "default": 3, "min": 1, "max": 20, "step": 1,
     "help": "连续出现多少帧才确认真实人脸（阴影散点通常只出现 1~2 帧）。"},
    {"key": "LOST_FRAMES", "label": "轨迹丢失容忍帧数", "type": "int",
     "default": 5, "min": 1, "max": 30, "step": 1,
     "help": "确认后连续丢失多少帧才移除该轨迹。"},
    {"key": "FACIAL_LANDMARK_CHECK", "label": "五官二次校验", "type": "bool",
     "default": False,
     "help": "检测到人脸框后，再用 SCRFD 判断框内是否有眼/鼻/嘴(挡「只有耳朵/后脑勺」误检)。"
          "SCRFD 能检测小脸(低至约20px)，远距离监控也可用。"},
    {"key": "LANDMARK_MIN_POINTS", "label": "五官关键点最小数量", "type": "int",
     "default": 1, "min": 1, "max": 5, "step": 1,
     "help": "框内需定位到的眼/鼻/嘴关键点下限(SCRFD共5点)，低于此数判为「无五官」过滤掉。"
          "默认1=只要有一个五官(侧脸/遮挡)就保留。"},
    {"key": "SCRFD_THRESHOLD", "label": "SCRFD检测阈值", "type": "float",
     "default": 0.3, "min": 0.1, "max": 0.9, "step": 0.05,
     "help": "SCRFD 检测置信度阈值：越低越容易检出(少漏检)、越高越严格(挡更多误检)。"
          "漏真脸时调低(0.2~0.25)，误检仍多时调高(0.4~0.5)。"},
    {"key": "PREPROCESS_RESIZE_ENABLED", "label": "预处理缩放分辨率", "type": "bool",
     "default": True,
     "help": "开启后，检测前把帧缩放到指定分辨率(只缩小不放大)，可加快检测、降低 CPU 占用；"
          "但缩放过小会让远处小人脸更糊、更易漏检。"},
    {"key": "PREPROCESS_RESIZE_WIDTH", "label": "缩放目标分辨率", "type": "choice",
     "default": 640, "options": [
         ("360p (640×360)", 640),
         ("480p (854×480)", 854),
         ("720p (1280×720)", 1280),
         ("1080p (1920×1080)", 1920),
         ("2K (2560×1440)", 2560),
         ("4K (3840×2160)", 3840),
     ],
     "help": "预处理缩放的目标分辨率(以宽度为准，高度等比)。只缩小不放大："
          "原视频比目标小则保持原样。"},
    {"key": "MOSAIC_MASK_ENABLED", "label": "预处理涂抹马赛克", "type": "bool",
     "default": True,
     "help": "打开时：脱敏视频预处理会定位马赛克并涂成纯色再检人脸，并可显示马赛克框。"
          "关闭时：不跑马赛克检测，马赛克框不可设置。"},
    {"key": "MOSAIC_MASK_COLOR", "label": "马赛克涂抹颜色", "type": "choice",
     "default": 255, "options": [
         ("全白", 255),
         ("全黑", 0),
     ],
     "help": "马赛克区域涂成的纯色。"},
    {"key": "MOSAIC_MASK_THRESHOLD", "label": "马赛克识别阈值", "type": "int",
     "default": 40, "min": 10, "max": 120, "step": 5,
     "help": "棋盘格响应阈值：越低越敏感(更容易把普通纹理当成马赛克)，越高越严格(漏掉淡的马赛克)。"},
    {"key": "MOSAIC_MASK_MIN_SIDE", "label": "最小马赛克边长(px)", "type": "int",
     "default": 6, "min": 4, "max": 80, "step": 2,
     "help": "连通域最短边低于此值不当马赛克（字幕、碎点）。调大挡小误报，调小保留更细的码。"},
]


def get_default_params():
    """返回所有参数的默认值 dict。"""
    return {p["key"]: p["default"] for p in PARAM_DEFS}


def apply_params(params):
    """把参数 dict 应用到模块全局变量，使检测逻辑立即（或重新载入后）生效。"""
    global YUNET_SCORE_THRESHOLD, MIN_FACE_SIZE, SKIN_FILTER_ENABLED
    global SKIN_MIN_SIZE, SKIN_RATIO_THRESHOLD, CONFIRM_FRAMES, LOST_FRAMES
    global FACIAL_LANDMARK_CHECK, LANDMARK_MIN_POINTS, SCRFD_THRESHOLD
    global PREPROCESS_RESIZE_ENABLED, PREPROCESS_RESIZE_WIDTH
    global MOSAIC_MASK_ENABLED, MOSAIC_MASK_COLOR, MOSAIC_MASK_THRESHOLD
    global MOSAIC_MASK_MIN_SIDE
    if "YUNET_SCORE_THRESHOLD" in params:
        YUNET_SCORE_THRESHOLD = float(params["YUNET_SCORE_THRESHOLD"])
    if "MIN_FACE_SIZE" in params:
        MIN_FACE_SIZE = int(params["MIN_FACE_SIZE"])
    if "SKIN_FILTER_ENABLED" in params:
        SKIN_FILTER_ENABLED = bool(params["SKIN_FILTER_ENABLED"])
    if "SKIN_MIN_SIZE" in params:
        SKIN_MIN_SIZE = int(params["SKIN_MIN_SIZE"])
    if "SKIN_RATIO_THRESHOLD" in params:
        SKIN_RATIO_THRESHOLD = float(params["SKIN_RATIO_THRESHOLD"])
    if "CONFIRM_FRAMES" in params:
        CONFIRM_FRAMES = int(params["CONFIRM_FRAMES"])
    if "LOST_FRAMES" in params:
        LOST_FRAMES = int(params["LOST_FRAMES"])
    if "FACIAL_LANDMARK_CHECK" in params:
        FACIAL_LANDMARK_CHECK = bool(params["FACIAL_LANDMARK_CHECK"])
    if "LANDMARK_MIN_POINTS" in params:
        LANDMARK_MIN_POINTS = int(params["LANDMARK_MIN_POINTS"])
    if "SCRFD_THRESHOLD" in params:
        SCRFD_THRESHOLD = float(params["SCRFD_THRESHOLD"])
    if "PREPROCESS_RESIZE_ENABLED" in params:
        PREPROCESS_RESIZE_ENABLED = bool(params["PREPROCESS_RESIZE_ENABLED"])
    if "PREPROCESS_RESIZE_WIDTH" in params:
        PREPROCESS_RESIZE_WIDTH = int(params["PREPROCESS_RESIZE_WIDTH"])
    if "MOSAIC_MASK_ENABLED" in params:
        MOSAIC_MASK_ENABLED = bool(params["MOSAIC_MASK_ENABLED"])
    if "MOSAIC_MASK_COLOR" in params:
        MOSAIC_MASK_COLOR = int(params["MOSAIC_MASK_COLOR"])
    if "MOSAIC_MASK_THRESHOLD" in params:
        MOSAIC_MASK_THRESHOLD = int(params["MOSAIC_MASK_THRESHOLD"])
    if "MOSAIC_MASK_MIN_SIDE" in params:
        MOSAIC_MASK_MIN_SIDE = int(params["MOSAIC_MASK_MIN_SIDE"])


def load_params():
    """从配置文件读取检测参数，缺失项用默认值补齐，并应用到全局。"""
    cfg = load_config()
    merged = get_default_params()
    merged.update({k: v for k, v in cfg.items() if k in merged})
    apply_params(merged)
    # 把合并后的检测参数写回配置（补齐缺失项），但保留原配置里的其它键
    # （如 show_boxes_src / show_boxes_dst 等检测框开关），避免覆盖丢失。
    save_cfg = dict(cfg)          # 先保留原有全部键
    save_cfg.update(merged)       # 再覆盖/补齐检测参数
    save_config(save_cfg)
    return merged

# MediaPipe FaceLandmarker 模型文件路径（与脚本同目录 / exe 内）
MODEL_PATH = _resource_path("face_landmarker.task")

# SCRFD 检测模型（带5关键点：双眼/鼻/两嘴角），用于「五官二次校验」
SCRFD_MODEL = _resource_path(os.path.join("models", "det_10g.onnx"))
