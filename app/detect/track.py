# -*- coding: utf-8 -*-
"""跨帧轨迹聚类与门控。"""

from app import settings as cfg


def _iou(a, b):
    """计算两个矩形 (x, y, w, h) 的交并比 IoU。"""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    ix1 = max(ax, bx)
    iy1 = max(ay, by)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    area_a = aw * ah
    area_b = bw * bh
    union = area_a + area_b - inter
    if union <= 0:
        return 0.0
    return inter / union


class FaceTracker:
    """跨帧聚类：把逐帧检测到的人脸矩形，按空间相似度归并成"同一个人脸"的轨迹。

    每个人脸轨迹记录它出现过的所有帧号。
    """

    def __init__(self, iou_threshold=None):
        # 构造时读当前配置，避免默认参数在 import 时快照到旧值
        if iou_threshold is None:
            iou_threshold = cfg.TRACK_IOU_THRESHOLD
        self.iou_threshold = iou_threshold
        self.tracks = []   # 每条 track = {"last_box": (x,y,w,h), "frames": [帧号...]}

    def update(self, frame_idx, boxes):
        """输入当前帧号与该帧检测到的人脸框列表，更新轨迹。"""
        available = set(range(len(self.tracks)))
        for box in boxes:
            best_iou = 0.0
            best_track = None
            for t in available:
                iou = _iou(box, self.tracks[t]["last_box"])
                if iou > best_iou:
                    best_iou = iou
                    best_track = t
            if best_track is not None and best_iou >= self.iou_threshold:
                # 归入已有轨迹
                tr = self.tracks[best_track]
                tr["last_box"] = box
                tr["frames"].append(frame_idx)
                available.discard(best_track)
            else:
                # 新出现的人脸
                self.tracks.append({"last_box": box, "frames": [frame_idx]})

    def flush(self):
        """清理，返回按首次出现帧号排序的人脸轨迹列表。"""
        result = sorted(self.tracks, key=lambda t: t["frames"][0])
        return result


class TrackGate:
    """轨迹门控：把逐帧检测框归并成「带确认状态的轨迹」，只输出已确认的真实人脸框。

    解决「阴影散点误检」与「远距离小人脸」无法用尺寸/单帧 score 区分的矛盾：
      - 真实人脸连续多帧出现 → hits 累积到 cfg.CONFIRM_FRAMES 即「确认」并输出
      - 阴影散点只出现 1~2 帧 → 永远达不到确认阈值，被丢弃
      - 确认后短暂漏检（遮挡/离开）靠 cfg.LOST_FRAMES 容忍，不立刻消失

    输出的框同时做了指数平滑，消除抖动。
    """

    def __init__(self, alpha=None, confirm=None, lost=None, iou_threshold=None):
        # 构造时读当前配置，避免默认参数在 import 时快照到旧值
        if alpha is None:
            alpha = cfg.SMOOTH_ALPHA
        if confirm is None:
            confirm = cfg.CONFIRM_FRAMES
        if lost is None:
            lost = cfg.LOST_FRAMES
        if iou_threshold is None:
            iou_threshold = cfg.TRACK_IOU_THRESHOLD
        self.alpha = alpha
        self.confirm = confirm
        self.lost = lost
        self.iou_threshold = iou_threshold
        # 每条轨迹: {box, smooth_box, hits, misses, confirmed}
        self.tracks = []

    def step(self, boxes):
        """输入本帧检测框，返回「已确认轨迹」的平滑框列表。"""
        if not boxes:
            # 本帧无检测：所有轨迹累加 miss，移除超阈值的
            for tr in self.tracks:
                tr["misses"] += 1
            self.tracks = [t for t in self.tracks if t["misses"] < self.lost]
            return [t["smooth_box"] for t in self.tracks if t["confirmed"]]

        matched = [False] * len(self.tracks)
        for box in boxes:
            # 找最近邻轨迹
            best_i, best_iou = -1, 0.0
            for j, tr in enumerate(self.tracks):
                if matched[j]:
                    continue
                iou = _iou(box, tr["box"])
                if iou > best_iou:
                    best_iou, best_i = iou, j
            if best_i >= 0 and best_iou >= self.iou_threshold:
                tr = self.tracks[best_i]
                matched[best_i] = True
                tr["box"] = box
                tr["hits"] += 1
                tr["misses"] = 0
                # 平滑
                sb = tr["smooth_box"]
                tr["smooth_box"] = (
                    int(self.alpha * box[0] + (1 - self.alpha) * sb[0]),
                    int(self.alpha * box[1] + (1 - self.alpha) * sb[1]),
                    int(self.alpha * box[2] + (1 - self.alpha) * sb[2]),
                    int(self.alpha * box[3] + (1 - self.alpha) * sb[3]),
                )
                if tr["hits"] >= self.confirm:
                    tr["confirmed"] = True
            else:
                # 新候选框
                self.tracks.append({
                    "box": box, "smooth_box": box,
                    "hits": 1, "misses": 0, "confirmed": False,
                })
                matched.append(True)  # 新框已匹配，不计为 miss

        # 未匹配到的轨迹累加 miss
        for j, tr in enumerate(self.tracks):
            if not matched[j]:
                tr["misses"] += 1
        self.tracks = [t for t in self.tracks if t["misses"] < self.lost]

        return [t["smooth_box"] for t in self.tracks if t["confirmed"]]

    def reset(self):
        self.tracks = []
