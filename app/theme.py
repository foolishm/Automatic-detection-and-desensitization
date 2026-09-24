# -*- coding: utf-8 -*-
"""界面配色与标题栏图标。"""


BG = "#0f1117"           # 主背景
BG_PANEL = "#161a24"     # 顶/底栏背景
BG_CARD = "#1c2230"      # 面板卡片
BG_HOVER = "#242c3d"     # 按钮悬停/常态
BG_VIDEO = "#05070b"     # 视频区底色
BG_CHIP = "#143028"      # 检测器徽标底
FG = "#e6e9f0"           # 主文字
FG_MUTED = "#8a93a6"     # 次要文字
FG_FAINT = "#5b6474"     # 弱化文字
ACCENT = "#4f8cff"       # 主强调蓝
ACCENT_HOVER = "#6aa1ff"
ACCENT_GREEN = "#2ee6a8" # 成功绿
ACCENT_RED = "#ff5c5c"   # 暂停/错误红
ACCENT_WARN = "#e6a23c"
MOSAIC_BOX_COLOR = (60, 160, 255)   # 马赛克框颜色（BGR：橙色，与绿色人脸框区分）  # 警告橙（弹窗模板 warning）
BORDER = "#2a3244"       # 边框
CHIP_BORDER = "#1e5c48"  # 检测器徽标描边

# 按钮精修配色（层次感：主按钮蓝底+亮描边；普通按钮深灰底+浅灰描边）
BTN_ACCENT_BORDER = "#7cb0ff"   # 主按钮描边（比底色亮的蓝）
BTN_ACCENT_PRESS = "#3d72d6"    # 主按钮按下（更深的蓝）
BTN_NORMAL_BORDER = "#394357"   # 普通按钮描边
BTN_NORMAL_HOVER = "#2d3648"    # 普通按钮悬停
BTN_NORMAL_PRESS = "#1a2130"    # 普通按钮按下
BTN_GREEN_BORDER = "#5ef0bb"    # 绿色开按钮描边
BTN_GREEN_PRESS = "#24c78d"     # 绿色开按钮按下

# 标题栏窗口按钮（Segoe MDL2 Assets，与 Windows 10 系统按钮同款线框）
TB_MDL2_FONT = ("Segoe MDL2 Assets", 9)
TB_ICON_MAXIMIZE = "\uE922"     # 小窗口：最大化（圆角方框）
TB_ICON_RESTORE = "\uE923"      # 已最大化：还原（重叠方框）
