import tkinter as tk, os
from tkinter import ttk

import _bootstrap
import face_video_detector as f

if os.path.exists(f.CONFIG_PATH):
    open(f.CONFIG_PATH, "w", encoding="utf-8").write("{}")

root = tk.Tk()
app = f.FaceVideoApp(root)
root.geometry("1120x720")
root.update_idletasks(); root.update()
app.show_params_page(); root.update_idletasks(); root.update()

# 找参数页里的 Canvas 和 Scrollbar
def find_widgets(w, cls, out):
    for c in w.winfo_children():
        if c.winfo_class() == cls:
            out.append(c)
        find_widgets(c, cls, out)

canvases = []
scrollbars = []
find_widgets(app.page_params, 'Canvas', canvases)
find_widgets(app.page_params, 'Scrollbar', scrollbars)

print(f'Canvas数量: {len(canvases)}, Scrollbar数量: {len(scrollbars
