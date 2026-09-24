# -*- coding: utf-8 -*-
"""半透明棋盘格马赛克涂抹预处理：涂抹后检测器应检不出被打码的人脸。

用法：python tests/test_mosaic_mask.py [视频路径]
默认视频：e:\\Users\\Administrator\\Desktop\\Video_Chnl09_15fps.mp4
"""

import sys

import _bootstrap  # noqa: F401
import cv2
import numpy as np

import face_video_detector as f
from app import settings as cfg

DEFAULT_VIDEO = r"e:\Users\Administrator\Desktop\Video_Chnl09_15fps.mp4"


def _sample_frames(path, step=40):
    """每隔 step 帧抽一帧。"""
    frames = []
    cap = cv2.VideoCapture(path)
    if cap.isOpened():
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        for idx in range(0, total, step):
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            # 读失败的帧直接跳过
            if ok:
                frames.append(frame)
        cap.release()
    return frames


def _count_faces(frames, masks, enabled):
    """按开关统计所有抽样帧的检出框：返回 (总框数, 落在马赛克区域上的框数)。"""
    f.apply_params({"MOSAIC_MASK_ENABLED": enabled})
    det = f.FaceDetector()
    total = 0
    on_mosaic = 0
    for frame, mask in zip(frames, masks):
        _, boxes = det.detect_and_draw(frame.copy())
        total += len(boxes)
        for (x, y, w, h) in boxes:
            sub = mask[y:y + h, x:x + w]
            # 框内三成以上像素落在马赛克掩码里，就算「检出了被打码的人脸」
            if sub.size and (sub > 0).mean() > 0.3:
                on_mosaic += 1
    det.close()
    return total, on_mosaic


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_VIDEO
    ok = True
    # 与程序运行时一致：用 config.json 里的检测参数
    f.load_params()
    frames = _sample_frames(path)
    if not frames:
        print("SKIP: 无法读取视频", path)
    else:
        # 1. 掩码必须命中：多数抽样帧有马赛克区域（个别帧画面里没人是正常的）
        masks = [f.checker_mosaic_mask(fr) for fr in frames]
        hit = sum(1 for m in masks if m.any())
        print(f"掩码命中帧: {hit}/{len(frames)}")
        ok = ok and hit * 2 >= len(frames)
        # 掩码不能大面积误涂：平均覆盖面积应远小于整帧
        area = float(np.mean([(m > 0).mean() for m in masks]))
        print(f"掩码平均覆盖: {area:.3%}")
        ok = ok and area < 0.15
        # 2. 涂抹为纯白/纯黑后的像素值正确
        out_w, mask = f.mask_mosaic(frames[0], enabled=True, color=255)
        out_b, _ = f.mask_mosaic(frames[0], enabled=True, color=0)
        ok = ok and bool(np.all(out_w[mask > 0] == 255))
        ok = ok and bool(np.all(out_b[mask > 0] == 0))
        # 3. 关闭时不复制、不改动
        same, zero_mask = f.mask_mosaic(frames[0], enabled=False)
        ok = ok and same is frames[0] and not zero_mask.any()
        # 4. 每个纯白块都能被 is_mosaic 判为已打码
        import desensitization_checker as dc
        count, _labels, stats, _ = cv2.connectedComponentsWithStats(mask)
        blocks_ok = all(
            dc.is_mosaic(out_w[y:y + bh, x:x + bw])
            for x, y, bw, bh, _a in stats[1:])
        print(f"is_mosaic(涂白区域): {blocks_ok} ({count - 1} 块)")
        ok = ok and count > 1 and blocks_ok
        # 4b. 脱敏率用的 is_mosaic 必须能直接认出未涂抹的棋盘格，且不受「预处理涂抹」开关影响
        f.apply_params({"MOSAIC_MASK_ENABLED": False})
        checker_hit = 0
        checker_total = 0
        plain_false = True
        for fr, m in zip(frames, masks):
            count, _labels, stats, _ = cv2.connectedComponentsWithStats(m)
            for x, y, bw, bh, _a in stats[1:]:
                checker_total += 1
                # 掩码块即马赛克位置：直接在原帧（未涂抹）上判定
                if dc.is_mosaic(fr[y:y + bh, x:x + bw]):
                    checker_hit += 1
            # 右上墙面（无马赛克）棋盘格分支必须判否（实心分支对平坦区域本就会判真，此处不测它）
            plain_false = plain_false and not dc._is_checker_mosaic(fr[40:140, 480:560])
        print(f"is_mosaic(未涂抹棋盘格): {checker_hit}/{checker_total}，无马赛克区域判否: {plain_false}")
        ok = ok and checker_total > 0 and checker_hit >= checker_total * 0.9 and plain_false
        # 5. 关闭时会在马赛克上检出人脸（问题复现），开启后马赛克上的检出必须为 0
        off_total, off_mos = _count_faces(frames, masks, False)
        on_total, on_mos = _count_faces(frames, masks, True)
        print(f"关闭: 检出 {off_total} 框，其中落在马赛克上 {off_mos}")
        print(f"开启: 检出 {on_total} 框，其中落在马赛克上 {on_mos}")
        ok = ok and off_mos > 0 and on_mos == 0
        # 6. 参数页 / 配置能改颜色，检测器读到的是实时值
        f.apply_params({"MOSAIC_MASK_COLOR": 0})
        ok = ok and cfg.MOSAIC_MASK_COLOR == 0
        f.apply_params({"MOSAIC_MASK_COLOR": 255, "MOSAIC_MASK_ENABLED": True})
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
