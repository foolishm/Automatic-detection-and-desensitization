# 已知 Bug 台账

本文件由 `.cursor/rules/bug-save.mdc` 约束。改代码前先读；确认缺陷后按模板追加；修复后更新状态。新条目放在「条目列表」最上方。

## 条目模板

```
## BUG-YYYYMMDD-NN 一句话标题

- 状态: 未修复 | 已修复
- 发现日期: YYYY-MM-DD
- 修复日期: YYYY-MM-DD 或 —
- 相关文件: 路径
- 现象:
- 根因:
- 修复方式:
- 避免再犯:
```

## 条目列表

## BUG-20260921-07 全屏参数行拉满宽、右侧结果区大量留白

- 状态: 已修复
- 发现日期: 2026-09-21
- 修复日期: 2026-09-21
- 相关文件: app/ui/params.py, app/ui/app.py, tests/test_fullscreen_layout.py
- 现象: 2560×1440 最大化后，参数页每一行从最左拉到最右，说明和输入框隔很远；检测页右侧「检测结果」框只有约 200px 高，下面空出约 750px
- 根因: `_sync_params_scroll` 把卡片宽度设成 Canvas 全宽。右侧面板用 Canvas 包内容，内框高度等于内容请求高度（约 615），`desens_result` 的 `expand` 没有可分配的剩余空间
- 修复方式: 参数卡片最大 960px 并水平居中。右侧内框高度至少等于视口，让结果框吃掉底部空白
- 避免再犯: 全屏表单禁止拉满整屏宽；Canvas 内可伸展控件必须把内框高度撑到视口

## BUG-20260921-06 最大化按整屏尺寸铺开会盖住任务栏

- 状态: 已修复
- 发现日期: 2026-09-21
- 修复日期: 2026-09-21
- 相关文件: app/ui/titlebar.py, tests/test_fullscreen_layout.py
- 现象: 点最大化后窗口变成整屏宽高（实测约 2576×1460，屏幕 2560×1440），任务栏被盖住，边缘还会弹出 Windows 贴靠布局
- 根因: `_toggle_maximize` 用 `winfo_screenwidth/height` 和 `+0+0`，等于铺满显示器而不是工作区
- 修复方式: 按 `SPI_GETWORKAREA` 最大化到去掉任务栏后的工作区
- 避免再犯: 自绘标题栏最大化禁止用整屏宽高；必须用工作区。自绘窗口本来就要保留任务栏可见

## BUG-20260921-05 参数页点保存后没有成功弹窗

- 状态: 已修复
- 发现日期: 2026-09-21
- 修复日期: 2026-09-21
- 相关文件: app/ui/params.py, tests/test_save_params_dialog.py
- 现象: 参数设置页点击「保存」后配置会写上，但不弹出「参数已保存」提示
- 根因: 拆模块时 `_save_params` 仍调用 `messagebox.showinfo` / `showerror`，但 `params.py` 只导入了 `tk` 和 `ttk`。Tk 按钮回调把 `NameError: messagebox is not defined` 吞掉，弹窗语句位于 `_clear_videos()` 之后，所以看起来像「保存成功但没弹窗」
- 修复方式: `from tkinter import ttk, messagebox`。校验失败走 `showerror`，成功走 `showinfo`
- 避免再犯: 拆模块后凡是弹窗必须在本文件显式导入 `messagebox`；禁止依赖原先单文件里的隐式全局名

## BUG-20260921-04 播放时按住进度条会被拽回播放位置

- 状态: 已修复
- 发现日期: 2026-09-21
- 修复日期: 2026-09-21
- 相关文件: app/ui/video_view.py, tests/test_scrub_hold.py
- 现象: 播放中长时间拖着进度条不松手，滑块会跳回当前播放位置
- 根因: `_on_scrub` 在每次拖动后 `after(180)` 调用 `_on_scrub_release`。按住停顿超过 180ms（ttk.Scale 本来就不会连续触发 command）就会把 `_scrubbing` 清掉，`_render_tick` 的 `_update_progress` 按播放帧把滑块拽回去
- 修复方式: 只有鼠标按下到松开才算拖动；停顿不再结束拖动。按下时 `bind_all` 松手，拖出进度条再松也能结束。按住期间播放不刷新滑块和时间
- 避免再犯: 禁止用 command 停顿定时器当「松手」；`_scrubbing` 必须覆盖整个按住过程

## BUG-20260921-03 裸 H.264 拖进度条只会快进且对不齐

- 状态: 已修复
- 发现日期: 2026-09-21
- 修复日期: 2026-09-21
- 相关文件: app/video/formats.py, app/ui/video_view.py, tests/test_h264_seek.py
- 现象: `.h264` 来回拖进度条时画面只能往前「快进」，快进幅度和拖到的位置对不上
- 根因: 裸 Annex-B 没有索引。`_on_scrub` / `_play_loop` 用 `cap.set(CAP_PROP_POS_FRAMES)`。该调用返回 True，但不会跳到目标帧，每次 set+read 大约只前进一个 GOP（本流约 30 帧）。进度条/时间却按拖动目标更新，所以画面和滑块错位，也无法真正后退
- 修复方式: OpenCV 给不出总帧时走 `decode_seek`：后退重开文件，前进 `grab` 到目标帧。拖动中只改时间，松手或停顿后再解码。顺序跳到的帧号可信，检测框可再用缓存
- 避免再犯: 无容器索引的码流禁止用 `cap.set` 当随机访问；进度条 command 里禁止边拖边 set/read

## BUG-20260921-02 裸 H.264 导入后总时长显示 --:--

- 状态: 已修复
- 发现日期: 2026-09-21
- 修复日期: 2026-09-21
- 相关文件: app/video/formats.py, app/ui/video_view.py, tests/test_h264_import.py
- 现象: 导入 `.h264` 后进度条右侧总时长是 `--:--`，总帧数显示「未知」
- 根因: 裸 Annex-B 没有容器时长/帧索引，OpenCV `CAP_PROP_FRAME_COUNT` 不可信，上一轮用 `normalize_frame_count` 直接当成未知。时长只在人脸预处理逐帧读完后才有机会补上，导入当下解析不出来
- 修复方式: OpenCV 总帧不可信时，扫描起始码统计 type 1/5 且 `first_mb_in_slice==0` 的图像 NAL，用帧数/帧率算出时长。`Video_Chnl09.h264` 实测 10806 帧、25fps、界面 `00:00 / 07:12`
- 避免再犯: 裸 H.264 禁止只依赖 `CAP_PROP_FRAME_COUNT`/`CAP_PROP_POS_MSEC` 显示总时长；没有容器索引时必须扫码流计帧

## BUG-20260921-01 裸 H.264 码流无法导入

- 状态: 已修复
- 发现日期: 2026-09-21
- 修复日期: 2026-09-21
- 相关文件: app/video/formats.py, app/ui/drop.py, tests/test_h264_import.py
- 现象: 拖入或用导入对话框选择 `.h264` / `.264`（如桌面 `Video_Chnl09.h264`）时不被当成视频；即便用「所有文件」打开，总帧数也会显示成离谱负数，分析进度第一帧就到 100%
- 根因: `VIDEO_EXTS` 和文件对话框只有容器后缀（mp4/mkv 等），不含裸 Annex-B。解码本身走 OpenCV FFmpeg，`VideoCapture` 能打开该文件并读出 704x576 帧。裸流没有容器索引，`CAP_PROP_FRAME_COUNT` 返回约 `-1.92e14`，`int()` 后仍被当总帧数用
- 修复方式: 后缀加入 `.h264`/`.264`；`normalize_frame_count` 把 <=0 或过大的 FRAME_COUNT 视为未知；分析读完后再回写真实帧数；未知总帧时不拖进度条、进度不按 1 当总分母
- 避免再犯: 导入白名单必须覆盖 FFmpeg 能解的裸码流后缀；禁止把 OpenCV 的 FRAME_COUNT 在未校验时直接当进度分母或跳转上限

## BUG-20260920-06 拖视频到画面区无法导入

- 状态: 已修复
- 发现日期: 2026-09-20
- 修复日期: 2026-09-20
- 相关文件: app/ui/drop.py, app/ui/video_view.py, app/ui/titlebar.py
- 现象: 把视频拖到「将视频拖到此处导入」区域后没有导入
- 根因: 画面区能收到 `WM_DROPFILES`（消息 563），但 `_hdrop_paths` 调用 `DragQueryFileW` 时未按 64 位指针传 HDROP，抛出 `OverflowError` 后被吞掉。WndProc 里再调 Tk `after()` 还会打乱 GIL。去掉系统标题栏后顶层窗口是 `WS_EX_LAYERED` 且未允许拖放，资源管理器命中父窗口时也会禁止放下。
- 修复方式: `DragQueryFileW`/`DragFinish` 使用 `c_void_p`；WndProc 只记路径，由 `_render_tick` 再导入；顶层窗口 `DragAcceptFiles`。
- 避免再犯: 64 位 HDROP 必须按指针传递；禁止在 WndProc 里调用 Tk；分层顶层窗口必须单独允许拖放。

## BUG-20260920-05 原视频播放时检测框与人脸错位

- 状态: 已修复
- 发现日期: 2026-09-20
- 修复日期: 2026-09-20
- 相关文件: app/ui/video_view.py, app/detect/detector.py
- 现象: 原视频打开「检测框」播放时，绿框和画面里的人脸对不齐（拖进度条后尤其明显）
- 根因: 预处理按顺序 `read()` 记帧号；播放器用 `cap.set(CAP_PROP_POS_FRAMES)` 跳转。OpenCV/FFmpeg 跳转常落到邻近关键帧，但 `POS_FRAMES` 仍回报目标号。`_draw_boxes` 用这个号去取预处理框，等于把 A 帧的框画到 B 帧上。缩放检测的 rx/ry 映射是对的，不是框坐标没还原。
- 修复方式: 增加 `_index_trusted`。顺序解码可信用预处理缓存；一旦 `cap.set` 就把标志关掉，按当前画面现场检测画框。暂停拖动也会画框。
- 避免再犯: 禁止用 `cap.set` 之后的 `CAP_PROP_POS_FRAMES` 去索引另一路顺序解码得到的框；跳转后要么现场检测，要么顺序读到目标帧。

## BUG-20260920-04 参数页全屏时到顶仍能继续向下滚动

- 状态: 已修复
- 发现日期: 2026-09-20
- 修复日期: 2026-09-20
- 相关文件: app/ui/params.py
- 现象: 小窗口参数列表滚动正常；全屏时内容顶部已对齐，仍能再向下滚动
- 根因: `_build_params_page` 用 Canvas `bbox("all")` 直接当 scrollregion，且滚轮无条件 `yview_scroll`。卡片间距使内容高约 972px，1080p 全屏视口约 893px，到顶后仍有一段可滚；视口大于内容时也未把 yview 锁在 0。
- 修复方式: `_sync_params_scroll` 在内容不超过视口时把 scrollregion 锁成视口并 `yview_moveto(0)`；滚轮在一屏能显示完时不滚动；略减卡片 pady。
- 避免再犯: Canvas 列表必须按「内容高 vs 视口高」同步 scrollregion，禁止无条件 yview_scroll。

## BUG-20260920-03 最大化导入大图后再还原，其它控件被视频区挤出窗口

- 状态: 已修复
- 发现日期: 2026-09-20
- 修复日期: 2026-09-20
- 相关文件: app/ui/video_view.py
- 现象: 最大化窗口导入 1080p 画面后再缩回小窗口，视频几乎占满界面，进度条/信息/右侧面板等控件看不到
- 根因: `_VideoView` 用 `tk.Label` 显示 `PhotoImage`。Label 的请求尺寸等于图片尺寸；最大化时按大画布缩放出的图会把 `video_panel` 撑住。窗口还原后 pack 不会把 Label 收到分配区域以下，`lbl_info` 等仍按最大化时的 y 布局，被裁在窗口外。
- 修复方式: `video_panel.pack_propagate(False)`，画面按面板分配尺寸缩放，并在 Configure 时重绘。
- 避免再犯: 预览控件禁止让 PhotoImage 决定父布局请求尺寸；必须用 pack_propagate(False) 或 Canvas 贴图。

## BUG-20260920-02 去掉系统标题栏后视频区透视后面窗口

- 状态: 已修复
- 发现日期: 2026-09-20
- 修复日期: 2026-09-20
- 相关文件: app/ui/titlebar.py, app/ui/video_view.py
- 现象: 未导入视频时预览区能看到后面窗口的内容
- 根因: `_hide_native_titlebar` 去掉 `WS_CAPTION` 后 DWM 把未绘制客户区当玻璃；空 Canvas/Label 只有背景色、没有像素，会被透视。
- 修复方式: 去标题栏后调用 `DwmExtendFrameIntoClientArea(0)` 并设分层窗口 alpha=255；空视频区用实心位图铺满。
- 避免再犯: 去掉系统标题栏后必须处理 DWM 客户区玻璃，空画面不能只靠 widget 背景色。

## BUG-20260920-01 自绘标题栏拖动窗口产生残影

- 状态: 已修复
- 发现日期: 2026-09-20
- 修复日期: 2026-09-20
- 相关文件: app/ui/titlebar.py
- 现象: 按住自绘标题栏拖动窗口时，窗口内画面出现重重残影
- 根因: `_do_drag` 在每次 `<B1-Motion>` 里调用 `root.geometry("+x+y")` 逐帧改位置。去掉系统标题栏后 DWM 不会走原生移动合成，Tk Canvas/PhotoImage 来不及整窗重绘，留下残影。
- 修复方式: `_start_drag` 在 Windows 上对 TkTopLevel 发送 `WM_NCLBUTTONDOWN`+`HTCAPTION`，由系统整窗拖动；仅在原生拖动失败时才回退 `geometry`。
- 避免再犯: 无边框/自绘标题栏禁止用鼠标移动事件循环调用 `geometry()` 改位置，必须走系统标题栏拖动消息。

（此前无其它记录）
