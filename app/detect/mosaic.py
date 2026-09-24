# -*- coding: utf-8 -*-
"""半透明棋盘格马赛克的定位与涂抹预处理。

部分脱敏设备打的马赛克是「半透明棋盘格」：深浅方格交替叠在人脸上，
但人脸轮廓仍透出来，YuNet 照样能检出，导致脱敏率判为「仍检出人脸」。
本模块在检测前找出这类棋盘格区域并涂成纯白 / 纯黑，让检测器看不到人脸，
同时纯色块也能被 `desensitization_checker.is_mosaic` 判为已打码。

识别原理：
  1. 棋盘格核卷积：2c×2c 的 [[+1,-1],[-1,+1]] 核，对深浅交替的方格响应强，
     自然图像几乎不会出现这种二维精确交替。
  2. 周期性校验：平移 2c 像素应与原图相似、平移 c 像素应明显不同，
     排除只在一个方向重复的字幕数字等叠加文字。
  3. 连通域过滤：过小 / 过扁的区域丢弃，只保留能覆盖人脸的块。
"""

import cv2
import numpy as np

from app import settings as cfg


def _shift_absdiff(img, dx, dy):
    """|img - img 平移 (dx, dy)|，越界部分与边缘像素比较（不做环绕）。"""
    h, w = img.shape[:2]
    padded = cv2.copyMakeBorder(img, 0, dy, 0, dx, cv2.BORDER_REPLICATE)
    return cv2.absdiff(img, padded[dy:dy + h, dx:dx + w])


def _select_labels(labels, count, flags):
    """按 flags（长度 count 的 bool 数组）把选中的连通域标成 255，其余为 0。"""
    lut = np.zeros(max(count, 1), np.uint8)
    lut[np.asarray(flags, dtype=bool)] = 255
    lut[0] = 0
    return lut[labels]


def checker_mosaic_mask(frame_bgr, cells=None, resp_thresh=None, period_thresh=None):
    """返回与帧同尺寸的 uint8 涂抹掩码（255 = 棋盘格马赛克区域，含外扩边）。"""
    paint, _tight = checker_mosaic_masks(frame_bgr, cells, resp_thresh, period_thresh)
    return paint


def checker_mosaic_masks(frame_bgr, cells=None, resp_thresh=None, period_thresh=None):
    """定位棋盘格马赛克，返回 (涂抹掩码, 紧掩码)。"""
    paint, tight, _kind = checker_mosaic_masks_kind(
        frame_bgr, cells, resp_thresh, period_thresh)
    return paint, tight


def checker_mosaic_masks_kind(frame_bgr, cells=None, resp_thresh=None, period_thresh=None):
    """定位棋盘格马赛克，返回 (涂抹掩码, 紧掩码, kind)。

    kind 为 fine / coarse / 空串，供预处理池判断本视频打的是哪一档格子。

    涂抹掩码向外多盖一圈，保证方格边缘透出的人脸轮廓被涂掉；
    紧掩码把棋盘核 c×c 铺满带来的外溢收回去，边界贴合真实马赛克，用于画框和记录位置。
    cells：候选方格边长列表；resp_thresh：棋盘核响应阈值（越低越敏感）；
    period_thresh：周期性校验阈值。缺省均取 `app.settings` 的当前值。

    4px 及以上走粗到精：先在 1/2 缩小图上（方格尺寸同步减半、阈值放宽）找候选区域，
    再只在候选外接框（外扩一圈）内按全分辨率精定位。2~3px 实心棋盘格不能走这条路——
    INTER_AREA 缩一半会把黑白格平均成灰，必须整帧全分辨率定位。
    两档都开时先找 2~3px；已经命中就不再跑 4/6/8（同一帧不会混打两种格子）。
    """
    if cells is None:
        cells = cfg.MOSAIC_MASK_CELLS
    if resp_thresh is None:
        resp_thresh = cfg.MOSAIC_MASK_THRESHOLD
    if period_thresh is None:
        period_thresh = cfg.MOSAIC_MASK_PERIOD_THRESHOLD
    h, w = frame_bgr.shape[:2]
    paint = np.zeros((h, w), np.uint8)
    tight = np.zeros((h, w), np.uint8)
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    cell_list = list(cells)
    fine_cells = [c for c in cell_list if c < 4]
    coarse_cells = [c for c in cell_list if c >= 4]
    kind = ""
    # 2~3px：半分辨率会把细格抹掉，整帧全分辨率找
    if fine_cells:
        p, t = _locate_checker(gray, fine_cells, resp_thresh, period_thresh)
        paint = cv2.max(paint, p)
        tight = cv2.max(tight, t)
        # 细格已经盖住码块，粗格路径不会再给出另一类码
        if p.any():
            kind = "fine"
    # 4px 及以上：缩小一半粗定位，只在候选框里精修
    if coarse_cells and not paint.any():
        small = cv2.resize(gray, (max(1, w // 2), max(1, h // 2)), interpolation=cv2.INTER_AREA)
        small_cells = sorted(set(max(2, c // 2) for c in coarse_cells))
        coarse, _ = _locate_checker(small, small_cells, resp_thresh * 0.4, 0.0)
        # 有候选才做精定位
        if coarse.any():
            margin = 2 * max(coarse_cells) + 8
            cand = cv2.resize(coarse, (w, h), interpolation=cv2.INTER_NEAREST)
            cand = cv2.dilate(cand, np.ones((2 * margin + 1, 2 * margin + 1), np.uint8))
            count, _labels, stats, _ = cv2.connectedComponentsWithStats(cand)
            for i in range(1, count):
                x, y, cw, ch, _area = stats[i]
                x0, y0, x1, y1 = int(x), int(y), int(x + cw), int(y + ch)
                # 只在候选外接框里按全分辩率精定位，结果贴回整帧
                p, t = _locate_checker(gray[y0:y1, x0:x1], coarse_cells, resp_thresh, period_thresh)
                paint[y0:y1, x0:x1] = cv2.max(paint[y0:y1, x0:x1], p)
                tight[y0:y1, x0:x1] = cv2.max(tight[y0:y1, x0:x1], t)
                if p.any():
                    kind = "coarse"
    return paint, tight, kind


def fine_mosaic_cells(cells=None):
    """小于 4px 的方格档（必须全分辨率找）。"""
    if cells is None:
        cells = cfg.MOSAIC_MASK_CELLS
    return tuple(c for c in cells if c < 4)


def coarse_mosaic_cells(cells=None):
    """4px 及以上的方格档（可走半分辨率粗到精）。"""
    if cells is None:
        cells = cfg.MOSAIC_MASK_CELLS
    return tuple(c for c in cells if c >= 4)


def mosaic_min_side():
    """马赛克连通域最短边下限（像素），读参数页当前值。"""
    return max(1, int(cfg.MOSAIC_MASK_MIN_SIDE))


def _locate_checker(gray, cells, resp_thresh, period_thresh):
    """在 float32 灰度图上定位棋盘格，返回 (涂抹掩码, 核心掩码)。参数含义见 checker_mosaic_masks。"""
    h, w = gray.shape[:2]
    result = np.zeros((h, w), np.uint8)
    tight = np.zeros((h, w), np.uint8)
    min_side = mosaic_min_side()
    # 图比最短边还小，放不下一块合格马赛克，直接返回全零掩码
    if h >= min_side and w >= min_side:
        best = np.zeros(gray.shape, np.float32)      # 严格周期性校验的响应（用于找种子）
        best_weak = np.zeros(gray.shape, np.float32) # 放宽校验的响应（用于从种子向外生长）
        for c in cells:
            # 棋盘格核：左上/右下 +1，右上/左下 -1。该核可分离为 u·uᵀ（u = c 个 +1 接 c 个 -1），
            # 用 sepFilter2D 代替二维卷积，速度快一个量级
            u = np.ones(2 * c, np.float32)
            u[c:] = -1.0
            u /= float(2 * c)
            resp = cv2.sepFilter2D(gray, -1, u, u, borderType=cv2.BORDER_REFLECT)
            resp = cv2.absdiff(resp, 0.0)
            # 周期性校验：同相平移 2c 应相似（same 小），反相平移 c 应差异大（half 大）
            same = cv2.add(_shift_absdiff(gray, 2 * c, 0), _shift_absdiff(gray, 0, 2 * c))
            half = cv2.add(_shift_absdiff(gray, c, 0), _shift_absdiff(gray, 0, c))
            period = cv2.blur(cv2.addWeighted(half, 1.0, same, -1.5, 0.0), (2 * c, 2 * c))
            # 严格 / 放宽两档周期性门限，分别用于找种子和向外生长
            strict_gate = cv2.threshold(period, period_thresh, 1.0, cv2.THRESH_BINARY)[1]
            weak_gate = cv2.threshold(period, period_thresh * 0.5, 1.0, cv2.THRESH_BINARY)[1]
            gated = cv2.multiply(resp, strict_gate)
            weak = cv2.multiply(resp, weak_gate)
            # 核只在与方格对齐处响应，用 c×c 最大值滤波把响应铺满整块方格
            box = np.ones((c, c), np.uint8)
            gated = cv2.dilate(gated, box)
            weak = cv2.dilate(weak, box)
            best = cv2.max(best, gated)
            best_weak = cv2.max(best_weak, weak)
        mask = cv2.threshold(best, resp_thresh, 255, cv2.THRESH_BINARY)[1].astype(np.uint8)
        # 闭运算补上方格间缝隙（核取小，避免把相邻两块马赛克连成一块），开运算去掉孤立噪点
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
        # 只保留短边和面积都达到 mosaic_min_side 的连通域，过滤字幕等细长误报
        big = ((stats[:, cv2.CC_STAT_WIDTH] >= min_side)
               & (stats[:, cv2.CC_STAT_HEIGHT] >= min_side)
               & (stats[:, cv2.CC_STAT_AREA] >= min_side * min_side))
        keep = _select_labels(labels, count, big)
        # 大块附近的小碎块（马赛克边缘被浅色背景冲淡的残片）也并入，避免残留半张脸。
        # 邻域只取半个 min_side，免得把旁边另一块马赛克的碎片也吸进来
        near_r = max(1, min_side // 2)
        near = cv2.dilate(keep, np.ones((2 * near_r + 1, 2 * near_r + 1), np.uint8))
        touched = np.zeros(count, bool)
        touched[np.unique(labels[near > 0])] = True
        keep = _select_labels(labels, count, big | touched)
        # 滞后阈值：以强响应块为种子，向相连的弱响应区生长。
        # 人脸亮部（额头/面颊）上的浅色格几乎与皮肤同色，响应只有一半，
        # 单一阈值会只涂掉半张脸，剩下的下巴仍会被检出。
        # 生长只允许在种子外接框向四周各扩一倍的范围内进行，防止顺着衣物纹理无限蔓延。
        low = (best_weak > resp_thresh * 0.5).astype(np.uint8) * 255
        low = cv2.morphologyEx(low, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        seed_count, seed_labels, seed_stats, _ = cv2.connectedComponentsWithStats(keep)
        for i in range(1, seed_count):
            sx, sy, sw, sh, _area = seed_stats[i]
            # 允许生长的窗口：种子框四周各扩一个种子尺寸
            wx0 = max(0, sx - sw)
            wy0 = max(0, sy - sh)
            wx1 = min(w, sx + 2 * sw)
            wy1 = min(h, sy + 2 * sh)
            window = low[wy0:wy1, wx0:wx1]
            seed_win = (seed_labels[wy0:wy1, wx0:wx1] == i)
            grown = seed_win.copy()
            low_count, low_labels, low_stats, _ = cv2.connectedComponentsWithStats(window)
            for j in range(1, low_count):
                comp = (low_labels == j)
                # 弱响应连通域里含有本种子才并入，孤立的弱纹理不算马赛克
                if (comp & seed_win).any():
                    grown |= comp
            # 按生长结果的实际形状涂掉，不取外接矩形：相邻两块马赛克之间的空隙保留原样，
            # 不会被合成一块大的
            result[wy0:wy1, wx0:wx1][grown] = 255
        # 核心掩码：未外扩的生长结果，供 mask_rects 取框（框再按 rect_shrink() 收边）
        tight = result
        # 涂抹掩码：整体外扩一小圈，盖住方格边缘残留的人脸轮廓（发际线 / 下巴）
        result = cv2.dilate(result, np.ones((5, 5), np.uint8))
    return result, tight


def rect_shrink(cells=None):
    """棋盘核响应用 c×c 最大值滤波铺满方格时会向外溢出约半个方格，
    画框 / 记录位置时每边应收回的像素数（按候选方格平均边长的一半）。"""
    if cells is None:
        cells = cfg.MOSAIC_MASK_CELLS
    return max(1, int(round(sum(cells) / len(cells) / 2.0)))


def mask_mosaic(frame_bgr, enabled=None, color=None, mask=None):
    """按配置把帧内棋盘格马赛克涂成纯色，返回 (处理后的帧, 掩码)。

    关闭时原样返回输入帧（不复制）与全零掩码；开启时返回新副本，不改动入参。
    mask 可传入已算好的棋盘格掩码（预处理阶段已算过一次时复用，避免重复计算）。
    """
    if enabled is None:
        enabled = cfg.MOSAIC_MASK_ENABLED
    if color is None:
        color = cfg.MOSAIC_MASK_COLOR
    out = frame_bgr
    if enabled:
        # 没有现成掩码才现算
        if mask is None:
            mask = checker_mosaic_mask(frame_bgr)
        # 命中区域才复制并涂色，没命中直接复用原帧省一次拷贝
        if mask.any():
            out = frame_bgr.copy()
            gray_val = int(color)
            out[mask > 0] = (gray_val, gray_val, gray_val)
    else:
        mask = np.zeros(frame_bgr.shape[:2], np.uint8)
    return out, mask


def _largest_rectangle(mask):
    """bool 矩阵里全为 True 的最大面积轴对齐矩形，返回 (x, y, w, h)；没有则 (0, 0, 0, 0)。

    经典「柱状图最大矩形」逐行扫描：heights[c] = 第 c 列到当前行为止连续 True 的高度。
    """
    best = (0, 0, 0, 0)
    best_area = 0
    h, w = mask.shape
    heights = np.zeros(w + 1, np.int32)
    for row in range(h):
        heights[:w] = np.where(mask[row], heights[:w] + 1, 0)
        stack = []
        for col in range(w + 1):
            start = col
            # 弹出比当前柱高的柱，结算它们能撑起的矩形
            while stack and heights[stack[-1][0]] > heights[col]:
                idx, s = stack.pop()
                area = int(heights[idx]) * (col - s)
                if area > best_area:
                    best_area = area
                    best = (s, row - int(heights[idx]) + 1, col - s, int(heights[idx]))
                start = s
            stack.append((col, start))
    return best


def _expand_rect(rect, comp):
    """把 rect 向四边扩张，只要新扩进来的整行 / 整列都在 comp 内就继续，返回扩张后的 rect。

    并集里被先取走的部分会让第二块只剩残缺的一截，扩回去才能恢复它原本的完整矩形。
    """
    x, y, w, h = rect
    ch, cw = comp.shape
    grow = True
    while grow:
        grow = False
        # 向左
        if x > 0 and comp[y:y + h, x - 1].all():
            x -= 1
            w += 1
            grow = True
        # 向右
        if x + w < cw and comp[y:y + h, x + w].all():
            w += 1
            grow = True
        # 向上
        if y > 0 and comp[y - 1, x:x + w].all():
            y -= 1
            h += 1
            grow = True
        # 向下
        if y + h < ch and comp[y + h, x:x + w].all():
            h += 1
            grow = True
    return (x, y, w, h)


def _split_rect_union(comp, min_side, fill_ok=0.75, part_ratio=0.25, max_parts=4):
    """把一个连通域（bool 数组）拆成若干可以互相重叠的轴对齐矩形，返回相对坐标 [(x, y, w, h), ...]。

    设备打的马赛克都是矩形，两块接触 / 部分重叠会连成 L 形、T 形或十字形，
    连通域面积 / 外接框面积（填充率）明显小于 1。此时反复「取最大内接矩形 →
    向四边扩到贴合连通域边界 → 从剩余区域里抠掉」，每一轮恢复出一块原始矩形。

    单块马赛克在人脸亮部会缺角（实测填充率 0.80~0.96、缺口短边 ≤ 3 个方格），
    所以只有填充率明显偏低、且拆出的第二块本身够大时才认定是多块；否则整块按外接框返回。
    """
    h, w = comp.shape
    fill = int(comp.sum()) / float(max(1, h * w))
    parts = []
    # 填充率够高或尺寸太小：不可能是两块，跳过拆分
    if fill < fill_ok and min(h, w) >= 2 * min_side:
        remaining = comp.copy()
        while len(parts) < max_parts:
            x, y, rw, rh = _largest_rectangle(remaining)
            # 第二块起要求短边 ≥ 2 个 min_side 且面积不小于首块的 part_ratio，
            # 头发 / 遮挡造成的缺角、边缘凸起不算另一块
            if parts:
                first_area = parts[0][2] * parts[0][3]
                if rw < 2 * min_side or rh < 2 * min_side or rw * rh < first_area * part_ratio:
                    break
            elif rw < min_side or rh < min_side:
                break
            x, y, rw, rh = _expand_rect((x, y, rw, rh), comp)
            parts.append((x, y, rw, rh))
            remaining[y:y + rh, x:x + rw] = False
    # 拆出 ≥ 2 块才算多块马赛克；否则是一块带缺角的马赛克，用完整外接框
    if len(parts) >= 2:
        rects = parts
    else:
        rects = [(0, 0, w, h)]
    return rects


def _aligned_and_close(a, b, gap, overlap_ratio=0.7):
    """两个矩形是否「同一块马赛克被断成两截」：一个方向上投影重叠 ≥ overlap_ratio，
    另一个方向上间距 ≤ gap（允许略微相交）。"""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x_overlap = min(ax + aw, bx + bw) - max(ax, bx)
    y_overlap = min(ay + ah, by + bh) - max(ay, by)
    x_gap = max(ax, bx) - min(ax + aw, bx + bw)
    y_gap = max(ay, by) - min(ay + ah, by + bh)
    # 上下断开：x 方向对齐，y 方向留有小缝
    stacked = x_overlap >= overlap_ratio * min(aw, bw) and -gap <= y_gap <= gap
    # 左右断开：y 方向对齐，x 方向留有小缝
    side_by_side = y_overlap >= overlap_ratio * min(ah, bh) and -gap <= x_gap <= gap
    return stacked or side_by_side


def _merge_aligned_rects(rects, gap):
    """把对齐且相近的矩形合成一个外接框，反复直到没有可合并的对。

    人脸亮部一整条方格褪色时，一块马赛克的掩码会被断成上下（或左右）两截连通域，
    按外接框合回去；两张不同的脸即便挨着，投影也对不齐，不会被误合。
    """
    merged = list(rects)
    changed = True
    while changed:
        changed = False
        for i in range(len(merged)):
            for j in range(i + 1, len(merged)):
                if _aligned_and_close(merged[i], merged[j], gap):
                    ax, ay, aw, ah = merged[i]
                    bx, by, bw, bh = merged[j]
                    x0 = min(ax, bx)
                    y0 = min(ay, by)
                    x1 = max(ax + aw, bx + bw)
                    y1 = max(ay + ah, by + bh)
                    merged[i] = (x0, y0, x1 - x0, y1 - y0)
                    del merged[j]
                    changed = True
                    break
            # 合并过一次后列表变了，从头再扫
            if changed:
                break
    return merged


def mask_rects(mask, split=True, min_side=None, shrink=0):
    """把二值掩码拆成矩形列表 [(x, y, w, h), ...]，用于画框和紧凑记录马赛克位置。

    split=True 时，接触 / 部分重叠而连成一片的多块矩形马赛克会按形状拆开，各自成框。
    shrink：每边向内收的像素数（抵消棋盘核铺满带来的外溢，让框贴合真实马赛克）。
    """
    rects = []
    if min_side is None:
        min_side = mosaic_min_side()
    if mask is not None and mask.any():
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
        # 拆分前先在连通域自己的外接框内做一次闭运算：单块马赛克在人脸亮部会缺一角、
        # 边缘参差，先把这些小凹口补平，免得被当成两块的并集切碎；
        # 两块 ≥ min_side 的矩形并成的 L 形凹口比核大，补不平，仍会被拆开
        close_k = np.ones((min_side, min_side), np.uint8)
        found = []
        for i in range(1, count):
            x, y, w, h, _area = stats[i]
            if split:
                comp = (labels[y:y + h, x:x + w] == i).astype(np.uint8)
                comp = cv2.morphologyEx(comp, cv2.MORPH_CLOSE, close_k) > 0
                for (px, py, pw, ph) in _split_rect_union(comp, min_side):
                    found.append((int(x) + px, int(y) + py, pw, ph))
            else:
                found.append((int(x), int(y), int(w), int(h)))
        # 同一块马赛克被弱响应带断成两截连通域的，按外接框合回去
        if split:
            found = _merge_aligned_rects(found, min_side)
        for (rx, ry, rw, rh) in found:
            # 每边收 shrink 像素；收完仍要留下至少一个 min_side 的块
            s = min(shrink, max(0, (min(rw, rh) - min_side) // 2))
            rects.append((rx + s, ry + s, rw - 2 * s, rh - 2 * s))
    return rects


def solid_mosaic_rects(frame_bgr, block=8, var_thresh=15.0):
    """实心马赛克位置：按 block×block 网格算块内灰度方差，低方差块（颜色统一）
    按网格行连成「行程」矩形，返回 int16 数组 (N, 4)，每行 (x, y, w, h)。

    与 desensitization_checker._is_solid_mosaic 用同一套块尺寸 / 方差阈值，
    只是把「逐区域现算」改成「整帧一次算完、记录矩形」，供脱敏率检测直接查表。
    自然画面里纯色墙面 / 天空到处都是，每帧几百条行程，用紧凑数组而不是 tuple 列表存，
    一万帧的视频才不会吃掉几百 MB。
    """
    rects = np.zeros((0, 4), np.int16)
    h, w = frame_bgr.shape[:2]
    gh = h // block
    gw = w // block
    # 帧比一个块还小时没有可判定的网格
    if gh > 0 and gw > 0:
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
        gray = gray[:gh * block, :gw * block]
        blocks = gray.reshape(gh, block, gw, block)
        var = blocks.var(axis=(1, 3))
        uniform = var < var_thresh
        # 按网格行取连续低方差块的「行程」作矩形，精确等价于逐块统计，
        # 不用连通域外接框（L 形区域的外接框会把中间非统一块也算进去）
        padded = np.zeros((gh, gw + 2), bool)
        padded[:, 1:-1] = uniform
        edges = np.diff(padded.astype(np.int8), axis=1)
        rows_s, starts = np.where(edges == 1)
        _rows_e, ends = np.where(edges == -1)
        # 同一行里 start / end 成对出现且顺序一致，可以直接按位置配对
        if starts.size:
            rects = np.stack([
                starts * block,
                rows_s * block,
                (ends - starts) * block,
                np.full(starts.shape, block, starts.dtype),
            ], axis=1).astype(np.int16)
    return rects


def rect_coverage(box, rects):
    """矩形列表（tuple 列表或 (N, 4) 数组）在 box 内的覆盖占比（0~1，矩形重叠部分只算一次）。

    先用向量化运算把与 box 相交的矩形筛出来（实心行程每帧几百条，逐条 Python 循环
    会长时间占住 GIL，让界面卡顿），再只对相交的少数几条做栅格并集。
    """
    x, y, w, h = box
    ratio = 0.0
    if w > 0 and h > 0 and len(rects) > 0:
        arr = np.asarray(rects, dtype=np.int32).reshape(-1, 4)
        x0 = np.maximum(arr[:, 0] - x, 0)
        y0 = np.maximum(arr[:, 1] - y, 0)
        x1 = np.minimum(arr[:, 0] + arr[:, 2] - x, w)
        y1 = np.minimum(arr[:, 1] + arr[:, 3] - y, h)
        inter = (x1 > x0) & (y1 > y0)
        # 有相交的矩形才栅格化统计
        if inter.any():
            hit = np.zeros((h, w), np.uint8)
            for a, b, c, d in zip(x0[inter], y0[inter], x1[inter], y1[inter]):
                hit[b:d, a:c] = 1
            ratio = float(hit.mean())
    return ratio


def record_display_rects(record):
    """把一帧的马赛克记录转成画在画面上的矩形列表 [(x, y, w, h), ...]。

    只画棋盘格矩形。实心「低方差块」记录在自然画面里到处都是（墙面、天空、衣服），
    只作脱敏率判定的兜底口径，画出来是一屏噪声，不显示。
    """
    rects = []
    if record:
        rects.extend(record.get("checker", ()))
    return rects


def frame_mosaic_record(frame_bgr, checker_mask=None):
    """一帧的马赛克记录：{"checker": 棋盘格矩形, "solid": 实心马赛克矩形}。

    checker_mask 可传入已算好的棋盘格**紧**掩码（`checker_mosaic_masks` 的第二个返回值），
    None 则内部现算；两类矩形都为空时返回 None，便于只记录有马赛克的帧。
    """
    if checker_mask is None:
        _paint, checker_mask = checker_mosaic_masks(frame_bgr)
    record = {
        "checker": mask_rects(checker_mask, shrink=rect_shrink()),
        "solid": solid_mosaic_rects(frame_bgr),
    }
    # 两类都没命中就不记录，省内存
    if not record["checker"] and len(record["solid"]) == 0:
        record = None
    return record
