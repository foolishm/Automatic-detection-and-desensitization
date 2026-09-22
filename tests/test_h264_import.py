# -*- coding: utf-8 -*-
"""裸 H.264 码流应能被识别为可导入视频，离谱 FRAME_COUNT 应视为未知。"""

import os
import tempfile

import _bootstrap
import face_video_detector as f


def _touch(path):
    with open(path, "wb") as fh:
        fh.write(b"")
    return path


def test_pick_dropped_h264():
    tmp = tempfile.mkdtemp(prefix="h264imp_")
    h264 = _touch(os.path.join(tmp, "Video_Chnl09.h264"))
    raw264 = _touch(os.path.join(tmp, "stream.264"))
    txt = _touch(os.path.join(tmp, "note.txt"))
    chosen = f.pick_dropped_video([txt, h264])
    raw = f.pick_dropped_video([raw264])
    none = f.pick_dropped_video([txt])
    ok = (chosen == os.path.abspath(h264)) and (
        raw == os.path.abspath(raw264)) and (none is None)
    return ok, chosen, raw, none


def test_dialog_lists_h264():
    types = f.video_open_filetypes()
    blob = " ".join(pat for _name, pat in types)
    ok = ("*.h264" in blob) and ("*.264" in blob) and ("*.mp4" in blob)
    return ok, blob


def test_normalize_frame_count():
    cases = [
        (1234, 1234),
        (0, 0),
        (-192153584101141.0, 0),
        (1, 1),
        (None, 0),
        ("bad", 0),
        (10_000_001, 0),
    ]
    got = []
    ok = True
    for raw, expect in cases:
        n = f.normalize_frame_count(raw)
        got.append(n)
        if n != expect:
            ok = False
    return ok, got


def _annexb_nal(nal_type, payload):
    """拼一条 Annex-B NAL：4 字节起始码 + 1 字节头 + payload。"""
    return b"\x00\x00\x00\x01" + bytes([0x60 | (nal_type & 0x1f)]) + payload


def test_count_annexb_pictures():
    tmp = tempfile.mkdtemp(prefix="h264nal_")
    # 3 帧：SPS/PPS + IDR + 两帧 P（first_mb_in_slice=0，payload 最高位为 1）
    three = (
        _annexb_nal(7, b"\x42") + _annexb_nal(8, b"\xce")
        + _annexb_nal(5, b"\x80") + _annexb_nal(1, b"\x80") + _annexb_nal(1, b"\x80")
    )
    p3 = os.path.join(tmp, "three.h264")
    with open(p3, "wb") as fh:
        fh.write(three)
    # 同一帧两片：第二片 first_mb>0（首 bit 为 0）
    sliced = _annexb_nal(5, b"\x80") + _annexb_nal(1, b"\x40")
    p1 = os.path.join(tmp, "sliced.h264")
    with open(p1, "wb") as fh:
        fh.write(sliced)
    mp4ish = os.path.join(tmp, "clip.mp4")
    with open(mp4ish, "wb") as fh:
        fh.write(b"\x00\x00\x00\x18ftypisom")
    n3 = f.count_annexb_pictures(p3)
    n1 = f.count_annexb_pictures(p1)
    nmp4 = f.count_annexb_pictures(mp4ish)
    dur = f.duration_seconds(n3, 25.0)
    ok = (n3 == 3) and (n1 == 1) and (nmp4 == 0) and abs(dur - 0.12) < 1e-6
    return ok, n3, n1, nmp4, dur


def test_probe_uses_annexb_when_opencv_count_bad():
    tmp = tempfile.mkdtemp(prefix="h264probe_")
    body = (
        _annexb_nal(7, b"\x42") + _annexb_nal(8, b"\xce")
        + _annexb_nal(5, b"\x80") + _annexb_nal(1, b"\x80")
    )
    path = os.path.join(tmp, "clip.h264")
    with open(path, "wb") as fh:
        fh.write(body)
    n = f.probe_frame_count(path, reported=-192153584101141.0)
    ok = n == 2
    return ok, n


def main():
    exit_code = 1
    pick_ok, chosen, raw, none = test_pick_dropped_h264()
    dlg_ok, blob = test_dialog_lists_h264()
    cnt_ok, got = test_normalize_frame_count()
    nal_ok, n3, n1, nmp4, dur = test_count_annexb_pictures()
    probe_ok, probed = test_probe_uses_annexb_when_opencv_count_bad()
    if pick_ok and dlg_ok and cnt_ok and nal_ok and probe_ok:
        print("PASS: h264 pick + dialog + frame_count + duration")
        exit_code = 0
    else:
        print(
            f"FAIL: pick_ok={pick_ok} first={chosen} raw={raw} none={none} "
            f"dlg_ok={dlg_ok} blob={blob} cnt_ok={cnt_ok} got={got} "
            f"nal_ok={nal_ok} n3={n3} n1={n1} nmp4={nmp4} dur={dur} "
            f"probe_ok={probe_ok} probed={probed}"
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
