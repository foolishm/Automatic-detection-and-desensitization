# -*- coding: utf-8 -*-
"""资源路径与可写目录。"""

import os
import sys


def _project_root():
    """源码运行时的工程根（app 包的上一级，模型/config 所在目录）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resource_path(rel):
    """返回资源文件的绝对路径。

    打包成 exe 后，资源(模型文件)会被解压到 PyInstaller 的临时目录 sys._MEIPASS；
    开发/源码运行时，用工程根目录。用于定位只读资源文件(模型等)。
    """
    # 打包后资源在 _MEIPASS；源码则在工程根，不在 app/ 包内
    if getattr(sys, "_MEIPASS", None):
        base = sys._MEIPASS
    else:
        base = _project_root()
    return os.path.join(base, rel)


def _app_dir():
    """返回应用的目录(exe 所在目录 或 工程根)，用于读写配置文件等可写文件。"""
    result = _project_root()
    # 打包后配置写在 exe 旁，不能写到临时解压目录
    if getattr(sys, "frozen", False):
        result = os.path.dirname(os.path.abspath(sys.executable))
    return result

