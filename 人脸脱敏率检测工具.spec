# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('face_detection_yunet_2023mar.onnx', '.'), ('face_landmarker.task', '.'), ('models/det_10g.onnx', 'models')]
binaries = []
hiddenimports = [
    'pystray', 'PIL.ImageTk', 'desensitization_checker',
    'app', 'app.main', 'app.paths', 'app.settings', 'app.theme',
    'app.video', 'app.video.formats',
    'app.detect', 'app.detect.detector', 'app.detect.track',
    'app.ui', 'app.ui.app', 'app.ui.video_view', 'app.ui.drop',
    'app.ui.titlebar', 'app.ui.params', 'app.ui.desens', 'app.ui.pipeline',
    'app.ui.dialogs',
]
tmp_ret = collect_all('mediapipe')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['face_video_detector.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='人脸脱敏率检测工具',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
