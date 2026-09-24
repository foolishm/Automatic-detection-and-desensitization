# -*- coding: utf-8 -*-
"""
人脸脱敏率检测工具
==================
功能：给定「原视频」（25fps）和「脱敏后视频」（15fps，帧率可不同），
计算脱敏率 —— 即原视频中「应脱敏的人脸帧」里，有多少在脱敏后视频对应时刻检不出人脸。

原理：
  1. 用 YuNet 逐帧检测原视频，得到「应脱敏帧」列表（帧号 + 人脸框）。
  2. 按时间戳把原视频帧号对齐到脱敏视频（因为两视频帧率不同）：
        时间 t = 原帧号 / 原fps = 脱敏帧号 / 脱敏fps
        → 脱敏帧号 = round(原帧号 * 脱敏fps / 原fps)
  3. 对每个「应脱敏时间点」查脱敏视频对应帧是否还能检出人脸：
       检不出 = 已脱敏；仍能检出 = 未脱敏。不看马赛克纹理。
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
    checker_mosaic_mask, rect_coverage,
)

# ============================== 可配置项 ==============================
# 马赛克块检测参数
MOSAIC_BLOCK = 8                 # 马赛克块边长（像素），常见 8~16
MOSAIC_GRID = 3                  # 采样网格点数（在每个方向上取多少块）
MOSAIC_VAR_THRESHOLD = 15.0      # 块内颜色方差的判定阈值（低于=颜色统一=马赛克块）
MOSAIC_BLOCK_RATIO = 0.5         # 判定为马赛克所需「统一色块」占比
MOSAIC_CHECKER_RATIO = 0.3       # 半透明棋盘格：棋盘格覆盖人脸框面积达到此占比即判为已打码
                                 # （原视频框与脱敏视频马赛克位置略有偏差，不要求全覆盖）


def _block_variance(gray_block):
    """计算一个图像块内部的灰度方差（越小越像马赛克统一色块）。"""
    if gray_block.size == 0:
        return 0.0
    return float(gray_block.var())


def _is_solid_mosaic(region_bgr):
    """实心马赛克：区域被划成等大色块 → 块内方差小。低方差块占比高即判定为马赛克。"""
    h, w = region_bgr.shape[:2]
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
    return total > 0 and (uniform / total) >= MOSAIC_BLOCK_RATIO


def _is_checker_mosaic(region_bgr):
    """半透明棋盘格马赛克：深浅方格交替叠在人脸上，块内方差不小，
    改用棋盘格定位（与检测预处理同一算法，但不受「预处理涂抹」开关影响），
    按棋盘格在区域内的覆盖占比判定。"""
    mask = checker_mosaic_mask(region_bgr)
    return float((mask > 0).mean()) >= MOSAIC_CHECKER_RATIO


def box_scale(src_w, src_h, dst_w, dst_h):
    """原视频 → 脱敏视频的坐标缩放比 (sx, sy)。任一边尺寸未知或为 0 时按同尺寸处理（1, 1）。"""
    sx = 1.0
    sy = 1.0
    if src_w and src_h and dst_w and dst_h:
        sx = float(dst_w) / float(src_w)
        sy = float(dst_h) / float(src_h)
    return sx, sy


def scale_box(box, scale):
    """把 (x, y, w, h) 按 (sx, sy) 换算到另一路视频的坐标系。"""
    sx, sy = scale
    x, y, w, h = box
    result = box
    # 同尺寸时不动，避免整数取整抖动
    if sx != 1.0 or sy != 1.0:
        result = (int(round(x * sx)), int(round(y * sy)),
                  max(1, int(round(w * sx))), max(1, int(round(h * sy))))
    return result


def _box_iou(a, b):
    """两个 (x, y, w, h) 的交并比。"""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    iw = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    ih = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = iw * ih
    return inter / float(aw * ah + bw * bh - inter + 1e-6)


def estimate_frame_offset(src_faces, src_fps, dst_mosaics, dst_fps, dst_total, scale,
                          max_shift_s=1.0, sample_step=10):
    """估计脱敏视频相对原视频的帧偏移（脱敏帧号 = 时间对齐帧号 + offset）。

    脱敏设备转码有固定延迟，两路视频按时间戳对齐后仍会差几帧；人在走动时几帧就能让
    人脸框和马赛克错开。这里在 ±max_shift_s 秒范围内逐个偏移试算「原视频人脸框（换算后）
    与脱敏视频棋盘格矩形的平均 IoU」，取最大者。相同得分时取绝对值更小的偏移。
    src_faces 按 sample_step 抽样，几千个人脸帧也只需几十毫秒。
    """
    best_offset = 0
    best_score = -1.0
    max_shift = int(round(max_shift_s * dst_fps))
    sampled = src_faces[::max(1, sample_step)]
    # 没有可比对的数据时保持 0 偏移
    if sampled and dst_mosaics:
        for offset in sorted(range(-max_shift, max_shift + 1), key=abs):
            total = 0.0
            count = 0
            for s_frame, boxes in sampled:
                d_frame = int(round(s_frame / src_fps * dst_fps)) + offset
                record = dst_mosaics.get(d_frame) if 0 <= d_frame < dst_total else None
                # 该帧没有棋盘格记录就不计分
                if not record or not record.get("checker"):
                    continue
                for box in boxes:
                    sb = scale_box(box, scale)
                    total += max(_box_iou(sb, r) for r in record["checker"])
                    count += 1
            score = total / count if count else 0.0
            # 严格大于才更新：得分相同时保留先遍历到的、|offset| 更小的那个
            if score > best_score:
                best_score = score
                best_offset = offset
    return best_offset


def box_is_mosaic(box, record):
    """用预处理阶段记录的马赛克矩形判断 box 位置是否已打码（不再读帧）。

    record 为 `frame_mosaic_record` 的返回值：{"checker": [...], "solid": [...]}，None 表示该帧没有马赛克。
    判定口径与 is_mosaic 一致：实心矩形覆盖 ≥ MOSAIC_BLOCK_RATIO，或棋盘格覆盖 ≥ MOSAIC_CHECKER_RATIO。
    """
    result = False
    if record:
        # 先看实心马赛克覆盖，不够再看棋盘格
        if rect_coverage(box, record.get("solid", ())) >= MOSAIC_BLOCK_RATIO:
            result = True
        elif rect_coverage(box, record.get("checker", ())) >= MOSAIC_CHECKER_RATIO:
            result = True
    return result


def is_mosaic(region_bgr):
    """判断一个图像区域是否已打马赛克。

    同时识别两类马赛克：
      1. 实心马赛克（等大色块、块内颜色统一）
      2. 半透明棋盘格马赛克（深浅方格交替，人脸仍透出）
    """
    result = False
    if region_bgr is not None and region_bgr.size > 0:
        h, w = region_bgr.shape[:2]
        # 区域太小放不下两个块，无法判定
        if h >= MOSAIC_BLOCK * 2 and w >= MOSAIC_BLOCK * 2:
            result = _is_solid_mosaic(region_bgr)
            # 实心判定不成立时再看是不是棋盘格
            if not result:
                result = _is_checker_mosaic(region_bgr)
    return result


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


def tally_aligned_faces(rows):
    """按每次时间对齐汇总人脸数。

    已脱敏人头 = max(0, 原帧人脸数 - 该次对齐到的脱敏帧人脸数)。
    脱敏帧人脸数同时给出按对齐次数累加、以及同一脱敏帧只计一次的两个数。
    """
    should = 0
    done = 0
    paired_dst = 0
    by_dst = {}
    for row in rows:
        src_n = int(row["src_faces"])
        dst_n = int(row["dst_faces"])
        should += src_n
        paired_dst += dst_n
        # 脱敏帧检出更多时，多出来的不记成负的已脱敏
        if src_n > dst_n:
            done += src_n - dst_n
        by_dst[row["dst_frame"]] = dst_n
    unique_dst = 0
    detected_dst_frames = 0
    for count in by_dst.values():
        unique_dst += count
        # 这一张脱敏帧上确实检出了人脸，帧数才计一次
        if count > 0:
            detected_dst_frames += 1
    rate = 0.0
    if should:
        rate = done / float(should) * 100
    tally = {
        "faces_should": should,
        "faces_done": done,
        "faces_paired_dst": paired_dst,
        "faces_unique_dst": unique_dst,
        "aligned_dst_frames": len(by_dst),
        "detected_dst_frames": detected_dst_frames,
        "rate": rate,
    }
    return tally


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

    # 3. 只取脱敏视频总帧，用于对齐越界判断（判定不再读像素、不看马赛克）
    dst_cap = cv2.VideoCapture(dst_path)
    if not dst_cap.isOpened():
        raise RuntimeError("无法打开脱敏视频：%s" % dst_path)
    d_total = int(dst_cap.get(cv2.CAP_PROP_FRAME_COUNT))
    dst_cap.release()

    # 4. 对齐 + 判定：原视频有人脸、对齐后脱敏视频没有人脸即已脱敏
    results = []
    for s_frame, _s_boxes in src_faces:
        t = s_frame / s_fps
        d_frame = int(round(t * d_fps))
        # 帧越界，视为未脱敏（无法验证）
        if d_frame < 0 or d_frame >= d_total:
            results.append({
                "src_frame": s_frame, "dst_frame": d_frame,
                "status": "out_of_range", "desensitized": False,
            })
            continue

        face_still_there = d_frame in dst_face_frames
        dst_boxes = dst_face_frames.get(d_frame, [])
        desensitized = not face_still_there
        if face_still_there:
            status = "未脱敏(仍检出人脸)"
        else:
            status = "已脱敏"
        results.append({
            "src_frame": s_frame, "dst_frame": d_frame,
            "src_faces": len(_s_boxes), "dst_faces": len(dst_boxes),
            "status": status, "desensitized": desensitized,
        })

    # 5. 汇总：帧数仍保留，脱敏率按对齐后的人脸数
    in_range = [r for r in results if r["status"] != "out_of_range"]
    total_should = len(in_range)
    total_done = sum(1 for r in in_range if r["desensitized"])
    tally = tally_aligned_faces(in_range)
    rate = tally["rate"]

    # 漏脱敏帧列表
    missed = [r for r in results if not r["desensitized"]]

    return {
        "src_fps": s_fps,
        "dst_fps": d_fps,
        "src_face_frames": total_should,
        "desensitized": total_done,
        "faces_should": tally["faces_should"],
        "faces_done": tally["faces_done"],
        "faces_unique_dst": tally["faces_unique_dst"],
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
    print("换算公式: 脱敏帧号 = round(原帧号 ÷ 原帧率 × 脱敏帧率) + 帧偏移")
    print(f"帧率换算后原视频应脱敏帧数: {report['src_face_frames']}")
    print(f"帧率换算后原视频应脱敏人脸数: {report['faces_should']}")
    print(f"帧率换算后脱敏视频检测出人脸数: {report['faces_unique_dst']}")
    print(f"已脱敏人脸数: {report['faces_done']}")
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
