# -*- coding: utf-8 -*-
"""程序入口。"""

import tkinter as tk

from app.ui.app import FaceVideoApp


def main():
    root = tk.Tk()
    FaceVideoApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
