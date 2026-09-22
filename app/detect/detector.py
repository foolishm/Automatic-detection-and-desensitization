# -*- coding: utf-8 -*-
"""人脸检测后端封装。"""

import os

import cv2

from app import settings as cfg


class FaceDetector:
    """统一封装不同的人脸检测后端。"""

    def __init__(self):
        self.backend = cfg.DETECTOR
        self._yunet = None          # 惰性创建
        self._yunet_size = None     # (w, h) 记录 YuNet 已设定尺寸
        if self.backend == "haar":
            if not os.path.exists(cfg.HAAR_CASCADE):
                raise RuntimeError("未找到 Haar 级联文件：%s" % cfg.HAAR_CASCADE)
            self.cascade = cv2.CascadeClassifier(cfg.HAAR_CASCADE)
        elif self.backend == "yunet":
            if not os.path.exists(cfg.YUNET_MODEL):
                raise RuntimeError(
                    "未找到模型文件 face_detection_yunet_2023mar.onnx，"
                    "请把它放到脚本同目录。\n"
                    "下载地址：https://github.com/opencv/opencv_zoo/raw/main/models/"
                    "face_detection_yunet/face_detection_yunet_2023mar.onnx"
                )
        elif self.backend == "mediapipe":
            if not os.path.exists(cfg.MODEL_PATH):
                raise RuntimeError(
                    "未找到模型文件 face_landmarker.task，请把它放到脚本同目录。\n"
                    "下载地址：https://storage.googleapis.com/mediapipe-models/"
                    "face_landmarker/face_landmarker/float16/1/face_landmarker.task"
                )
            from mediapipe.tasks.python import BaseOptions
            from mediapipe.tasks.python.vision import (
                FaceLandmarker, FaceLandmarkerOptions, RunningMode
            )
            options = FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=cfg.MODEL_PATH),
                running_mode=RunningMode.IMAGE,
                num_faces=10,
                min_face_detection_confidence=cfg.MP_MIN_DETECTION_CONFIDENCE,
                min_face_presence_confidence=cfg.MP_MIN_PRESENCE_CONFIDENCE,
                min_tracking_confidence=cfg.MP_MIN_TRACKING_CONFIDENCE,
            )
            self.landmarker = FaceLandmarker.create_from_options(options)
        else:
            raise RuntimeError("未知 cfg.DETECTOR 类型：%s" % self.backend)

        # 五官二次校验用的 SCRFD 检测器（惰性创建，仅当 cfg.FACIAL_LANDMARK_CHECK 开启时使用）
        self._scrfd_session = None
        self._scrfd_ready = None   # True=可用，False=模型缺失导致不可用

    def _get_scrfd_session(self):
        """惰性创建「五官二次校验」用的 SCRFD 检测会话（onnxruntime + det_10g.onnx）。

        返回 onnxruntime.InferenceSession，或 None（模型文件缺失时）。
        """
        if self._scrfd_ready is None:
            self._scrfd_ready = False
            if os.path.exists(cfg.SCRFD_MODEL):
                try:
                    import onnxruntime as ort
                    self._scrfd_session = ort.InferenceSession(
                        cfg.SCRFD_MODEL, providers=["CPUExecutionProvider"])
                    self._scrfd_ready = True
                except Exception:
                    self._scrfd_session = None
        return self._scrfd_session if self._scrfd_ready else None

    # SCRFD 各检测尺度的 stride
    _SCRFD_STRIDES = [8, 16, 32]

    def facial_landmark_points(self, frame_bgr):
        """用 SCRFD 检测整帧，返回「每张脸的五官关键点像素坐标」，用于判断框内是否有五官。

        SCRFD 输出 5 个关键点：左眼、右眼、鼻子、左嘴角、右嘴角（各 (x,y)）。
        返回 [(bbox, [point, ...])]，bbox=(x,y,w,h) 为关键点外接框，point=(px,py)。
        「只有耳朵/后脑勺」SCRFD 检不出（无法回归五官），返回空列表。
        """
        session = self._get_scrfd_session()
        if session is None:
            return []
        import onnxruntime as ort
        ih, iw = frame_bgr.shape[:2]
        inp_name = session.get_inputs()[0].name
        blob = cv2.dnn.blobFromImage(
            frame_bgr.astype("float32"), 1.0 / 128.0, (640, 640),
            (127.5, 127.5, 127.5), swapRB=True)
        outs = session.run(None, {inp_name: blob})

        scores_list, bboxes_list, kpss_list = [], [], []
        for i, stride in enumerate(self._SCRFD_STRIDES):
            score = outs[i].ravel()
            mask = score > cfg.SCRFD_THRESHOLD
            if mask.sum() == 0:
                continue
            bbox = outs[i + 3].reshape(-1, 4)[mask] * stride
            kps = outs[i + 6].reshape(-1, 10)[mask] * stride

            feat = 640 // stride
            anchor_centers = np.array(
                [[fx * stride, fy * stride]
                 for fy in range(feat) for fx in range(feat) for _ in range(2)],
                dtype=np.float32)[mask]

            x1 = anchor_centers[:, 0] - bbox[:, 0]
            y1 = anchor_centers[:, 1] - bbox[:, 1]
            x2 = anchor_centers[:, 0] + bbox[:, 2]
            y2 = anchor_centers[:, 1] + bbox[:, 3]
            b = np.stack([x1, y1, x2, y2], axis=-1)

            kd = []
            for j in range(5):
                kd.append(anchor_centers[:, 0] + kps[:, j * 2])
                kd.append(anchor_centers[:, 1] + kps[:, j * 2 + 1])
            kd = np.stack(kd, axis=-1)

            # blobFromImage 直接拉伸到 640×640（非等比），所以 x/y 分别按宽高缩放回原图
            sx = iw / 640.0
            sy = ih / 640.0
            b[:, 0] *= sx
            b[:, 2] *= sx
            b[:, 1] *= sy
            b[:, 3] *= sy
            kd[:, 0::2] *= sx
            kd[:, 1::2] *= sy

            scores_list.append(score[mask])
            bboxes_list.append(b)
            kpss_list.append(kd)

        if not scores_list:
            return []
        scores = np.concatenate(scores_list)
        bboxes = np.concatenate(bboxes_list)
        kpss = np.concatenate(kpss_list)

        # NMS 去重
        order = scores.argsort()[::-1]
        keep = []
        while order.size > 0:
            i = order[0]
            keep.append(i)
            xx1 = np.maximum(bboxes[i, 0], bboxes[order[1:], 0])
            yy1 = np.maximum(bboxes[i, 1], bboxes[order[1:], 1])
            xx2 = np.minimum(bboxes[i, 2], bboxes[order[1:], 2])
            yy2 = np.minimum(bboxes[i, 3], bboxes[order[1:], 3])
            w = np.maximum(0.0, xx2 - xx1)
            h = np.maximum(0.0, yy2 - yy1)
            inter = w * h
            ai = (bboxes[i, 2] - bboxes[i, 0]) * (bboxes[i, 3] - bboxes[i, 1])
            ao = (bboxes[order[1:], 2] - bboxes[order[1:], 0]) * \
                 (bboxes[order[1:], 3] - bboxes[order[1:], 1])
            ovr = inter / (ai + ao - inter + 1e-6)
            order = order[np.where(ovr <= 0.4)[0] + 1]

        out = []
        for i in keep:
            kp = kpss[i]
            pts = [(float(kp[j * 2]), float(kp[j * 2 + 1])) for j in range(5)]
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            bbox = (int(min(xs)), int(min(ys)),
                    int(max(xs) - min(xs)), int(max(ys) - min(ys)))
            out.append((bbox, pts))
        return out

    @staticmethod
    def _box_has_landmark(yunet_box, landmark_faces, min_points):
        """判断 YuNet 框内是否包含 ≥min_points 个五官关键点（眼/鼻/嘴）。"""
        x, y, w, h = yunet_box
        for _bbox, pts in landmark_faces:
            inside = 0
            for px, py in pts:
                if x <= px <= x + w and y <= py <= y + h:
                    inside += 1
            if inside >= min_points:
                return True
        return False

    def _get_yunet(self, w, h):
        """按帧尺寸惰性创建/复用 YuNet 检测器。"""
        if self._yunet is None or self._yunet_size != (w, h):
            self._yunet = cv2.FaceDetectorYN.create(
                cfg.YUNET_MODEL, "", (w, h),
                cfg.YUNET_SCORE_THRESHOLD, cfg.YUNET_NMS_THRESHOLD, 5000)
            self._yunet_size = (w, h)
        return self._yunet

    def detect_and_draw(self, frame_bgr):
        """对一帧图像进行人脸检测并就地绘制标注。

        返回 (标注后的帧, 人脸框列表)。人脸框为 (x, y, w, h) 矩形。
        """
        if self.backend == "haar":
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
            faces = self.cascade.detectMultiScale(gray, **cfg.HAAR_PARAMS)
            boxes = [tuple(int(v) for v in (x, y, w, h)) for (x, y, w, h) in faces]
            for i, (x, y, w, h) in enumerate(boxes, start=1):
                cv2.rectangle(
                    frame_bgr, (x, y), (x + w, y + h), cfg.BOX_COLOR, cfg.BOX_THICKNESS
                )
                label = f"Face {i}"
                cv2.putText(
                    frame_bgr, label, (x, max(y - 10, 15)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, cfg.LABEL_COLOR, 2,
                    cv2.LINE_AA,
                )
            return frame_bgr, boxes

        if self.backend == "yunet":
            ih, iw = frame_bgr.shape[:2]
            # 预处理缩放：开启时把帧缩放到指定宽度（高度等比），可加快检测/省 CPU
            if cfg.PREPROCESS_RESIZE_ENABLED and iw > cfg.PREPROCESS_RESIZE_WIDTH:
                target_w = int(cfg.PREPROCESS_RESIZE_WIDTH)
                target_h = max(1, int(ih * target_w / iw))
                small = cv2.resize(frame_bgr, (target_w, target_h),
                                   interpolation=cv2.INTER_AREA)
                sw, sh = target_w, target_h
            else:
                small = frame_bgr
                sw, sh = iw, ih

            detector = self._get_yunet(sw, sh)
            _, faces = detector.detect(small)
            boxes = []
            # 五官二次校验：开启时，用 MediaPipe 检测整帧的眼/鼻/嘴关键点（仅大脸有效）
            landmark_faces = []
            if cfg.FACIAL_LANDMARK_CHECK and faces is not None:
                try:
                    landmark_faces = self.facial_landmark_points(frame_bgr)
                except Exception:
                    landmark_faces = []
            if faces is not None:
                # 把降采样坐标系映射回原图坐标系
                rx = iw / sw
                ry = ih / sh
                for i, f in enumerate(faces, start=1):
                    # YuNet 返回 [x, y, w, h, landmarks(10), score]
                    x = int(f[0] * rx); y = int(f[1] * ry)
                    w = int(f[2] * rx); h = int(f[3] * ry)
                    cx = max(0, x); cy = max(0, y)
                    cw = w; ch = h
                    # 过滤小面积误检（阴影/噪点/远距离极小脸）。cfg.MIN_FACE_SIZE 可在参数页调节。
                    if min(cw, ch) < cfg.MIN_FACE_SIZE:
                        continue
                    # 五官二次校验：开启时，框内必须有 ≥cfg.LANDMARK_MIN_POINTS 个眼/鼻/嘴关键点才保留
                    # （landmark_faces 为空表示 MediaPipe 整帧都没检出五官，此时所有框都会被过滤 ——
                    #   这正是「远距离小人脸」场景，用户不应开启本开关）
                    if cfg.FACIAL_LANDMARK_CHECK:
                        if not self._box_has_landmark((cx, cy, cw, ch),
                                                      landmark_faces, cfg.LANDMARK_MIN_POINTS):
                            continue
                    # 肤色校验（仅当开关开启 + 中大型框）：挡轮胎/车辆配件等肤色≈0 的误检；
                    # 黑白画面应关闭开关；远处小人脸较小、肤色弱，跳过以免误杀。
                    if cfg.SKIN_FILTER_ENABLED and min(cw, ch) >= cfg.SKIN_MIN_SIZE:
                        if skin_ratio(frame_bgr, (cx, cy, cw, ch)) < cfg.SKIN_RATIO_THRESHOLD:
                            continue
                    boxes.append((cx, cy, cw, ch))
                    cv2.rectangle(frame_bgr, (cx, cy), (cx + cw, cy + ch),
                                  cfg.BOX_COLOR, cfg.BOX_THICKNESS)
                    label = f"Face {len(boxes)}"
                    score = float(f[-1]) if f.size >= 15 else 0.0
                    cv2.putText(frame_bgr, f"{label} {score:.2f}",
                                (cx, max(cy - 10, 15)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, cfg.LABEL_COLOR, 2,
                                cv2.LINE_AA)
            return frame_bgr, boxes

        # mediapipe：绘制面部网格 + 外框
        import mediapipe as mp
        rgb_mp = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB),
        )
        result = self.landmarker.detect(rgb_mp)
        boxes = []
        ih, iw = frame_bgr.shape[:2]
        if result.face_landmarks:
            for face_landmarks in result.face_landmarks:
                # 计算关键点外接矩形
                xs = [lm.x * iw for lm in face_landmarks]
                ys = [lm.y * ih for lm in face_landmarks]
                x = max(0, int(min(xs)))
                y = max(0, int(min(ys)))
                w = int(max(xs)) - x
                h = int(max(ys)) - y
                boxes.append((x, y, w, h))

                # 绘制关键点 + 连线（简化：绘制所有关键点）
                for lm in face_landmarks:
                    px, py = int(lm.x * iw), int(lm.y * ih)
                    cv2.circle(frame_bgr, (px, py), 1, cfg.BOX_COLOR, -1)
                # 绘制外框
                cv2.rectangle(frame_bgr, (x, y), (x + w, y + h),
                              cfg.BOX_COLOR, cfg.BOX_THICKNESS)
        return frame_bgr, boxes

    def close(self):
        if self.backend == "mediapipe":
            try:
                self.landmarker.close()
            except Exception:
                pass
        if self._scrfd_session is not None:
            self._scrfd_session = None
            self._scrfd_ready = None


def skin_ratio(frame_bgr, box):
    """计算框内肤色像素占比（0~1）。

    用 HSV 肤色范围：H 0~25，S 20~180，V 80~255。
    用于区分「真实人脸」和「轮胎/阴影/车辆配件」等非人脸物体。
    """
    x, y, w, h = box
    if w <= 0 or h <= 0:
        return 0.0
    h_img = frame_bgr.shape[0]
    w_img = frame_bgr.shape[1]
    x, y = max(0, x), max(0, y)
    w = min(w, w_img - x)
    h = min(h, h_img - y)
    if w <= 0 or h <= 0:
        return 0.0
    roi = frame_bgr[y:y + h, x:x + w]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 0] <= 25) &
            (hsv[:, :, 1] >= 20) & (hsv[:, :, 1] <= 180) &
            (hsv[:, :, 2] >= 80))
    return float(mask.mean())

