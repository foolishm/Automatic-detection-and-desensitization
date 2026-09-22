# -*- coding: utf-8 -*-
"""把工程根加入 sys.path，便于从 tests/ 直接运行脚本。"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 直接 python tests/xxx.py 时 path 只有 tests/，需要工程根才能 import face_video_detector
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
