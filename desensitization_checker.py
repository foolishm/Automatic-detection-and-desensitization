# -*- coding: utf-8 -*-
"""
人脸脱敏率检测工具
==================
功能：给定「原视频」（25fps）和「脱敏后视频」（15fps，帧率可不同），
计算脱敏率 —— 即原视频中「应脱敏的人脸帧」里，有多少在脱敏后视频中真正被打了马赛克。

原理：
  1. 用 YuNet 逐帧检测原视频，得到「应脱敏帧」列表（帧号 + 人脸框）。
  2. 按时间戳把原视频帧号对齐到脱敏视频（因为两视频帧率不同）：
        时间 t = 原帧号 / 原fps = 脱敏帧号 / 脱敏fps
        → 脱敏帧号 = round(原帧号 * 脱敏fps / 原fps)
  3. 对每个「应脱敏时间点」检查脱敏视频对应帧：
       (a) 人脸检测：该帧能否再检出人脸（能检出 = 未脱敏）
       (b) 马赛克纹理：在原人脸框位置，该区域是否呈马赛克块状（有 = 已脱敏）
       两者结合：已脱敏 = (检不出人脸) 且/或 (存在马赛克块)。
  4. 输出脱敏率 = 已脱敏帧数 / 应脱敏帧数，以及详细报告（哪些帧漏脱敏）。

运行：
  python desensitization_checker.py --src 原视频.mp4 --dst 脱敏视频.mp4
  （也可作为模块 import 后调用 check_desensitization()）

依赖：opencv-python（含 YuNet 模型 face_detection_yunet_2023mar.onnx）
作者：Generated
"""

import os
import cv2
import numpy as np

# 复用同目录下的人脸检测器与配置
from face_video_detector import (
    FaceDetector, YUNET_MODEL, YUNET_SCORE_THRESHOLD,
    MIN_FACE_SIZE, SKIN_FILTER_ENABLED, SKIN_MIN_SIZE, skin_ratio,
)

# ============================== 可配置项 ==============================
# 马赛克块检测参数
MOSAIC_BLOCK = 8                 # 马赛克块边长（像素），常见 8~16
MOSAIC_GRID = 3                  # 采样网格点数（在每个方向上取多少块）
MOSAIC_VAR_THRESHOLD = 15.0      # 块内颜色方差的判定阈值（低于=颜色统一=马赛克块）
MOSAIC_BLOCK_RATIO = 0.5         # 判定为马赛克所需「统一色块」占比


def _block_variance(gray_block):
    """计算一个图像块内部的灰度方差（越小越像马赛克统一色块）。"""
    if gray_block.size == 0:
        return 0.0
    return float(gray_block.var())


def is_mosaic(region_bgr):
    """判断一个图像区域是否呈现「马赛克块状」纹理。

    原理：马赛克把图像划分成若干等大块并统一颜色 → 块内方差小、块间差异大。
    对区域内多个采样块计算块内方差，若「低方差块」占比高，判定为马赛克。
    """
    if region_bgr is None or region_bgr.size == 0:
        return False
    h, w = region_bgr.shape[:2]
    if h < MOSAIC_BLOCK * 2 or w < MOSAIC_BLOCK * 2:
        return False
    gray = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2GRAY)

    uniform = 0
    total = 0
    # 在区域内网格采样块
    for y in range(0, h - MOSAIC_BLOCK + 1, MOSAIC_BLOCK):
        for x in range(0, w - MOSAIC_BLOCK + 1, MOSAIC_BLOCK):
            block = gray[y:y + MOSAIC_BLOCK, x:x + MOSAIC_BLOCK]
            if _block_variance(block) < MOSAIC_VAR_THRESHOLD:
                uniform += 1
            total += 1
    if total == 0:
        return False
    return (uniform / total) >= MOSAIC_BLOCK_RATIO


def detect_faces_in_video(video_path, fps=None, max_frames=None, step=1):
    """逐帧（或按 step 采样）检测视频中的人脸，返回 (fps, [(frame_idx, face_boxes)...])。

    face_boxes 为 [(x, y, w, h), ...]。
    step: 采样步长（>1 时每 step 帧检测一次，用于加速；默认 1 逐帧）。
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError("无法打开视频：%s" % video_path)
    real_fps = fps or cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    det = FaceDetector()
    faces = []   # (frame_idx, boxes)
    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if max_frames is not None and frame_idx >= max_frames:
            break
        if frame_idx % step == 0:
            detected, boxes = det.detect_and_draw(frame)
            if boxes:
                faces.append((frame_idx, boxes))
        frame_idx += 1

    cap.release()
    det.close()
    return real_fps, faces


def check_desensitization(src_path, dst_path, src_fps=None, dst_fps=None, step=3):
    """计算脱敏率。返回 dict 报告。

    参数：
      src_path: 原视频路径（25fps）
      dst_path: 脱敏后视频路径（15fps）
      src_fps / dst_fps: 手动指定帧率（None 则从视频读取）
      step: 采样步长（>1 则每 step 帧检测一次，大幅提速；脱敏率是抽样估算，默认 3）
    """
    # 1. 检测原视频人脸帧（采样）
    s_fps, src_faces = detect_faces_in_video(src_path, fps=src_fps, step=step)

    # 2. 检测脱敏视频（也检测人脸，用于「未脱敏」判定，采样）
    d_fps, dst_faces = detect_faces_in_video(dst_path, fps=dst_fps, step=step)
    dst_face_frames = {fr: boxes for fr, boxes in dst_faces}  # 脱敏视频：帧号 -> 人脸框

    # 3. 打开脱敏视频用于「马赛克检测」
    dst_cap = cv2.VideoCapture(dst_path)
    if not dst_cap.isOpened():
        raise RuntimeError("无法打开脱敏视频：%s" % dst_path)
    d_total = int(dst_cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # 帧率比例
    ratio = d_fps / s_fps   # 15/25 = 0.6

    # 4. 对齐 + 判定
    results = []
    for s_frame, s_boxes in src_faces:
        # 时间对齐
        t = s_frame / s_fps
        d_frame = int(round(t * d_fps))

        # 读取脱敏视频对应帧
        dst_cap.set(cv2.CAP_PROP_POS_FRAMES, d_frame)
        ok, dst_img = dst_cap.read()
        if not ok:
            # 帧越界，视为未脱敏（无法验证）
            results.append({
                "src_frame": s_frame, "dst_frame": d_frame,
                "status": "out_of_range", "desensitized": False,
            })
            continue

        # (a) 该帧是否还能检出人脸
        face_still_there = d_frame in dst_face_frames

        # (b) 在原人脸框位置检查马赛克
        mosaic_found = False
        dh, dw = dst_img.shape[:2]
        for (x, y, w, h) in s_boxes:
            # 原视频框坐标可能和脱敏视频尺寸不同，这里假设同尺寸（通常一致）
            cx = max(0, x); cy = max(0, y)
            cw = min(w, dw - cx); ch = min(h, dh - cy)
            if cw <= 0 or ch <= 0:
                continue
            region = dst_img[cy:cy + ch, cx:cx + cw]
            if is_mosaic(region):
                mosaic_found = True
                break

        # 综合判定：已脱敏 = 检不出人脸 且/或 存在马赛克（两者结合，取更严：两者都满足才最可靠）
        # 最准确：既检不出人脸，又在该位置发现马赛克 → 确凿已打码
        desensitized = (not face_still_there) and mosaic_found

        # 记录详细状态
        if not face_still_there and mosaic_found:
            status = "已脱敏"
        elif face_still_there:
            status = "未脱敏(仍检出人脸)"
        elif not mosaic_found:
            status = "未脱敏(无马赛克)"
        else:
            status = "部分"

        results.append({
            "src_frame": s_frame, "dst_frame": d_frame,
            "status": status, "desensitized": desensitized,
        })

    dst_cap.release()

    # 5. 汇总
    total_should = len(results)
    total_done = sum(1 for r in results if r["desensitized"])
    rate = (total_done / total_should * 100) if total_should else 0.0

    # 漏脱敏帧列表
    missed = [r for r in results if not r["desensitized"]]

    return {
        "src_fps": s_fps,
        "dst_fps": d_fps,
        "src_face_frames": total_should,
        "desensitized": total_done,
        "rate": rate,
        "missed": missed,
        "results": results,
    }


def print_report(report):
    """打印脱敏率报告。"""
    print("=" * 50)
    print("人脸脱敏率检测报告")
    print("=" * 50)
    print(f"原视频帧率: {report['src_fps']:.2f} fps")
    print(f"脱敏视频帧率: {report['dst_fps']:.2f} fps")
    print(f"应脱敏人脸帧: {report['src_face_frames']} 帧")
    print(f"已脱敏帧: {report['desensitized']} 帧")
    print(f"脱敏率: {report['rate']:.2f}%")
    print("-" * 50)
    if report["missed"]:
        print(f"漏脱敏的帧（{len(report['missed'])} 帧）:")
        for r in report["missed"][:20]:
            print(f"  原帧 {r['src_frame']} → 脱敏帧 {r['dst_frame']}: {r['status']}")
    else:
        print("全部人脸帧均已脱敏。")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="人脸脱敏率检测")
    parser.add_argument("--src", required=True, help="原视频路径")
    parser.add_argument("--dst", required=True, help="脱敏后视频路径")
    parser.add_argument("--src-fps", type=float, default=None, help="原视频帧率（默认自动读取）")
    parser.add_argument("--dst-fps", type=float, default=None, help="脱敏视频帧率（默认自动读取）")
    args = parser.parse_args()

    report = check_desensitization(args.src, args.dst, args.src_fps, args.dst_fps)
    print_report(report)


if __name__ == "__main__":
    main()
