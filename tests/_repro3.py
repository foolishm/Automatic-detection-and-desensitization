import tkinter as tk, os, time, threading

import _bootstrap
import face_video_detector as f
if os.path.exists(f.CONFIG_PATH):
    open(f.CONFIG_PATH, "w", encoding="utf-8").write("{}")

root = tk.Tk()
app = f.FaceVideoApp(root)
root.geometry("1120x720")
root.update()

path = r"E:/Users/Administrator/Desktop/脱敏视频/脱敏视频_第2至4分钟.mp4"
app.view_src.load(path)
app.view_dst.load(path)
root.update()

# 启动两个预处理
app._desens_gen_src += 1; app._desens_gen_dst += 1
gs, gd = app._desens_gen_src, app._desens_gen_dst
threading.Thread(target=app._preprocess_video, args=(path, True, gs), daemon=True).start()
threading.Thread(target=app._preprocess_video, args=(path, False, gd), daemon=True).start()
time.sleep(1)

# 同时播放，检查画面帧是否真的在推
app.view_src.play()
app.view_dst.play()

# 记录 _display_pos 变化（画面是否在前进）
last_src, last_dst = app.view_src._display_pos, app.view_dst._display_pos
for i in range(6):
    root.update()
    time.sleep(0.5)
    cur_s, cur_d = app.view_src._display_pos, app.view_dst._display_pos
    moved = (cur_s != last_src) or (cur_d != last_dst)
    print(f'{i*0.5:.1f}s: src_pos={cur_s}, dst_pos={cur_d}, 画面移动={moved}')
    last_src, last_dst = cur_s, cur_d

app._on_close()
