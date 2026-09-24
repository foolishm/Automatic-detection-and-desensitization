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

## BUG-20260923-05 右侧滚动区域滚轮无效

- 状态: 已修复
- 发现日期: 2026-09-23
- 修复日期: 2026-09-23
- 相关文件: app/ui/app.py, app/ui/desens.py, tests/test_desens_wheel.py
- 现象: 检测页右侧统计区和漏脱敏列表出现滚动条后，鼠标滚轮不能滚动
- 根因: 参数页在指针进入时用 `bind_all` 接了 `<MouseWheel>`，检测页的 Canvas 和漏帧列表没有接。Windows 上滚轮默认只发给当前焦点控件，停在标签或未点中的列表上就不会滚
- 修复方式: 指针在右侧栏内时接上滚轮。落在漏帧列表上滚列表，落在上方统计区滚那一块 Canvas。内容不超过一屏时不滚动
- 避免再犯: 新增 Canvas 或列表时，必须在指针进入该区域时绑定滚轮，不能只加滚动条。一屏放得下时禁止空滚

## BUG-20260923-04 报告里人脸数和帧数指代不清

- 状态: 已修复
- 发现日期: 2026-09-23
- 修复日期: 2026-09-23
- 相关文件: app/ui/desens.py, app/ui/app.py, app/report/desens_docx.py, desensitization_checker.py
- 现象: 结论里「应脱敏人脸」和「帧率换算后」用了同一数字，读不出发换算前总数、换算后应脱敏数、换算后检出数分别是哪一个；帧数也没有对应说法
- 根因: `faces_should` 被写成两行；`faces_unique_dst` 的标签像「换算后的应脱敏人脸」，实际是对齐落到的脱敏帧上检出的人脸，同一帧只计一次
- 修复方式: 人脸固定四项：原视频人脸数、脱敏视频人脸数、帧率换算后原视频应脱敏人脸数、帧率换算后脱敏视频检测出人脸数。帧数用同一套四项。结论和结果框写明换算公式 `脱敏帧号 = round(原帧号 ÷ 原帧率 × 脱敏帧率) + 帧偏移`。漏帧表列名改成「该帧原视频人脸数」「该帧脱敏视频人脸数」，避免和全片总数撞名
- 避免再犯: 不要再用「应脱敏人脸」「帧率换算后对应人脸」这类省略说法。换算前总数和换算后应脱敏数必须分开写，即使两个数字碰巧相同

## BUG-20260923-03 第十秒车轮被检成人脸

- 状态: 已修复
- 发现日期: 2026-09-23
- 修复日期: 2026-09-23
- 相关文件: app/detect/detector.py, app/settings.py, tests/test_tire_skin.py
- 现象: `Video_Chnl09_15fps.mp4` 第 10 秒附近，停着的车轮反复被画成人脸框
- 根因: 车轮框约 20×24 到 30×44 像素，肤色占比为 0，置信度 0.61–0.76。肤色过滤只在边长 ≥ `SKIN_MIN_SIZE`（60）时生效，这个框被跳过。把阈值调到 0.8 也挡不住 0.76 的那次
- 修复方式: 肤色开关打开时，边长不足 60 的框只有「肤色占比 < 0.02 且平均亮度 V < 110」才丢。实测车轮 V≤106；仍被检出的马赛克人脸 V≥127，第 47 秒、第 331 秒的人脸框还在
- 避免再犯: 小框不能整段跳过肤色过滤，也不能按中大框的 0.1/0.2 阈值一刀切。远处真人脸仍有肤色，轮胎是又黑又没有肤色

## BUG-20260923-02 最小化后点任务栏图标无法恢复窗口

- 状态: 已修复
- 发现日期: 2026-09-23
- 修复日期: 2026-09-23
- 相关文件: app/ui/titlebar.py
- 现象: 点最小化之后，再点任务栏上的程序图标，窗口不出来
- 根因: `_minimize` 调用 `root.withdraw()`，窗口从任务栏消失而不是变成最小化；托盘「显示窗口」又在 pystray 线程里直接 `deiconify`，没有回到 Tk 主线程。无标题栏窗口收到任务栏的 `SC_RESTORE` 时，Tk 也经常停在 iconic
- 修复方式: 最小化改为 `iconify()`，任务栏按钮还在。托盘恢复改成 `root.after` 回到主线程。父窗口过程里收到 `SC_RESTORE` 时再排一次 `_restore_main_window`
- 避免再犯: 最小化禁止 `withdraw()`。托盘、保存线程里禁止直接调用 Tk，必须回到主线程

## BUG-20260923-01 生成检测报告时主界面卡死

- 状态: 已修复
- 发现日期: 2026-09-23
- 修复日期: 2026-09-23
- 相关文件: app/ui/dialogs.py, app/ui/desens.py, app/report/desens_docx.py
- 现象: 一点「生成检测报告」整窗就卡住，取消和任务栏都没反应；卡住时再最小化，任务栏点不开
- 根因: 「正在保存」用了 `grab_set`。实测此时对顶层窗口发 `SC_MINIMIZE`，`IsIconic` 仍是 0，任务栏无法最小化。漏帧表在子线程里用 python-docx 连续写单元格，长时间占住 GIL，主线程进不了消息循环。写完后子线程又直接 `root.after`，和父窗口的 Python 窗口过程抢 Tcl 锁
- 修复方式: 保存提示不再 `grab_set`。写表每 20 行 `sleep` 让出 GIL，并在让出时检查取消。保存结果只写入普通属性，由主线程轮询后关窗、弹「保存完成」
- 避免再犯: 耗时保存不要用模态 grab。子线程禁止调用 `root.after` / 控件方法。大表写入必须分批让出 GIL

## BUG-20260922-08 2px 实心棋盘格认不出来，脱敏率被判成「无马赛克」

- 状态: 已修复
- 发现日期: 2026-09-22
- 修复日期: 2026-09-22
- 相关文件: app/detect/mosaic.py, app/settings.py, tests/test_mosaic_2px.py
- 现象: `原视频.mp4`（1920×1080）+ `脱敏视频.mp4`（1280×720）肉眼看人脸都打了细密棋盘格，脱敏率却极低，报告几乎全是「未脱敏(无马赛克)」
- 根因: 这路设备打的是约 2px 的实心黑白棋盘格。`MOSAIC_MASK_CELLS` 只有 (4, 6, 8)，核锁不住 2px 格；`checker_mosaic_masks` 又先把画面缩到 1/2 做粗定位，`INTER_AREA` 把黑白格平均成灰，粗定位候选落在字幕/底栏而不是脸上，精定位从未扫到真实码块。YuNet 对实心码检不出人脸，判定却要求「无人脸 且 框内有马赛克记录」，棋盘格记录为空就整段落成未脱敏
- 修复方式: 候选方格加入 2px；小于 4px 的档整帧全分辨率定位，4px 及以上仍走原来的粗到精。120s 处 5 张脸全部入记录，抽样 120/300s 换算后的原视频框与码块 5/5、4/4 命中；旧的半透明 6px 样本 `test_mosaic_mask.py` 仍通过
- 避免再犯: 半分辨率粗定位只能用于边长 ≥ 4px 的方格；更细的棋盘格必须全分辨率找。新增马赛克形态要先量格子边长和核响应，禁止默认「缩一半一定还能看见」

## BUG-20260922-07 计算脱敏率时界面卡顿

- 状态: 已修复
- 发现日期: 2026-09-22
- 修复日期: 2026-09-22
- 相关文件: app/detect/mosaic.py
- 现象: 点「开始检测脱敏率」后主界面明显卡顿
- 根因: `rect_coverage` 对每个原视频人脸框逐条 Python 循环遍历该帧全部实心行程（自然画面每帧约 680 条），15870 个人脸帧就是上千万次 Python 迭代，后台线程长时间占住 GIL，Tk 主线程拿不到时间片
- 修复方式: 先用 numpy 向量化算出与框相交的矩形，只对相交的少数几条栅格化；整段计算 1.4 s → 0.5 s，主线程最大停顿 20 ms
- 避免再犯: 后台线程里对「每帧几百条」级别的记录禁止逐条 Python 循环，先向量化筛选

## BUG-20260922-06 原视频与脱敏视频分辨率不同时脱敏率极低

- 状态: 已修复
- 发现日期: 2026-09-22
- 修复日期: 2026-09-22
- 相关文件: app/ui/desens.py, desensitization_checker.py
- 现象: `Video_Chnl09.mp4`（1280×720）+ `Video_Chnl09_15fps.mp4`（704×576）脱敏率只有 22.6%，报告里 74% 的帧是「未脱敏(无马赛克)」，而脱敏视频肉眼看几乎全部打了码
- 根因: 两处。1) `_compute_desensitization` 与 CLI `check_desensitization` 都把原视频人脸框坐标直接用在脱敏视频上（代码里注释「假设同尺寸」），x 方向差 0.55 倍、y 方向差 0.8 倍，框落在完全错误的位置；2) 脱敏设备转码有约 0.27 s 固定延迟，按时间戳对齐后脱敏帧比原视频晚 4 帧，人走动时框和马赛克错开
- 修复方式: 预处理记录 `width/height`，新增 `box_scale` / `scale_box` 把框换算到脱敏视频坐标（特征匹配验证两路就是纯拉伸，x×0.55、y×0.80、无偏移）；新增 `estimate_frame_offset` 在 ±1 s 内按「换算后人脸框与棋盘格矩形的平均 IoU」自动估计帧偏移；报告里打印分辨率、换算比与帧偏移。修后 96.25%，剩余 3.6% 是脱敏视频里确实没打码、仍能检出的人脸
- 避免再犯: 两路视频的任何坐标比对前必须先按各自分辨率换算，禁止「假设同尺寸」；帧对齐不能只信时间戳，要用画面内容校验偏移

## BUG-20260922-05 实心马赛克记录用 tuple 列表，长视频吃掉数百 MB

- 状态: 已修复
- 发现日期: 2026-09-22
- 修复日期: 2026-09-22
- 相关文件: app/detect/mosaic.py
- 现象: 脱敏视频预处理完成后 `info["mosaics"]` 覆盖全部 10800 帧（自然画面里纯色墙面 / 天空处处是「低方差块」），每帧约 680 条 `(x, y, w, h)` tuple，合计 700 万个 tuple，估算 600 MB 以上
- 根因: `solid_mosaic_rects` 逐行 Python 循环 `append` tuple；记录在 `_preprocess_video` 里按帧全量保留
- 修复方式: 改为 numpy 向量化生成 `int16 (N, 4)` 数组（每帧约 5 KB，一万帧约 60 MB），`rect_coverage` / `frame_mosaic_record` 同时接受 tuple 列表和数组
- 避免再犯: 按帧全量保留的记录必须先估算「条目数 × 帧数 × 单条开销」；上千条 / 帧的数据禁止用 Python 对象列表存

## BUG-20260922-04 关闭「预处理涂抹」后脱敏率判不出透明马赛克

- 状态: 已修复
- 发现日期: 2026-09-22
- 修复日期: 2026-09-22
- 相关文件: desensitization_checker.py, tests/test_mosaic_mask.py
- 现象: 参数页把「预处理涂抹马赛克」关掉后，脱敏率检测对棋盘格马赛克一律报「未脱敏(无马赛克)」
- 根因: BUG-20260922-01 的修法把棋盘格识别挂在 `mask_mosaic` 上，而 `mask_mosaic` 跟随 `cfg.MOSAIC_MASK_ENABLED`；开关关掉后 `is_mosaic` 只剩原来的「块内方差」实心马赛克判定，棋盘格块内方差很大，判否
- 修复方式: `is_mosaic` 拆成 `_is_solid_mosaic`（原实心判定）+ `_is_checker_mosaic`（直接对区域跑 `checker_mosaic_mask`，覆盖占比 ≥ `MOSAIC_CHECKER_RATIO` 即判真），两者任一成立即为已打码；棋盘格分支不看预处理开关。抽样 1007 个棋盘格块全部判真，墙面/衣物/未打码人脸/字幕判否
- 避免再犯: 「检测预处理开关」只能影响检测器输入，禁止让脱敏率判定依赖它；判定算法本身必须能识别全部已知马赛克形态

## BUG-20260922-03 参数页手写 current 字典，新增参数就 KeyError

- 状态: 已修复
- 发现日期: 2026-09-22
- 修复日期: 2026-09-22
- 相关文件: app/ui/params.py
- 现象: 往 `PARAM_DEFS` 加入马赛克涂抹参数后，打开参数页崩溃 `KeyError: 'MOSAIC_MASK_ENABLED'`，所有依赖主窗口的测试连带失败
- 根因: `_build_params_page` 里 `current` 是逐键手写的 dict，与 `PARAM_DEFS` 各维护一份；循环按 `PARAM_DEFS` 取 `current[key]`，新键没同步就越界
- 修复方式: 改为 `{p["key"]: getattr(cfg, p["key"]) for p in PARAM_DEFS}`，只以 `PARAM_DEFS` 为唯一来源
- 避免再犯: 参数页禁止再手写参数键列表；新增参数只改 `settings.py`（常量、`PARAM_DEFS`、`apply_params`）三处

## BUG-20260922-02 detector.py 缺 numpy 导入，五官二次校验一开就全部过滤

- 状态: 已修复
- 发现日期: 2026-09-22
- 修复日期: 2026-09-22
- 相关文件: app/detect/detector.py
- 现象: 打开「五官二次校验」后所有人脸框消失
- 根因: 拆模块时 `facial_landmark_points` 里的 `np.array` / `np.stack` 等没带上 `import numpy as np`，抛 `NameError` 被 `detect_and_draw` 的 `except Exception` 吞掉，`landmark_faces` 为空，随后每个框都因「无五官」被丢弃
- 修复方式: 补 `import numpy as np`
- 避免再犯: 拆出的模块必须逐一核对用到的顶层名字；被 `except Exception` 包住的调用要单独跑一次确认不是 NameError

## BUG-20260922-01 半透明棋盘格马赛克下的人脸仍被检出，脱敏率误判

- 状态: 已修复
- 发现日期: 2026-09-22
- 修复日期: 2026-09-22
- 相关文件: app/detect/mosaic.py, app/detect/detector.py, app/settings.py, app/ui/desens.py, desensitization_checker.py, tests/test_mosaic_mask.py
- 现象: `Video_Chnl09_15fps.mp4` 这类设备打的马赛克是半透明深浅方格叠加，人脸轮廓透出来，YuNet 仍能检出，脱敏率报「未脱敏(仍检出人脸)」；`is_mosaic` 按 8px 块方差判定也认不出 6px 棋盘格
- 根因: `detect_and_draw` 直接对原帧检测，没有针对透明马赛克的预处理；`is_mosaic` 只识别「块内颜色统一」的实心马赛克
- 修复方式: 新增 `app/detect/mosaic.py`：可分离棋盘格核 + 平移周期性校验找出棋盘格，连通域按尺寸过滤字幕数字，以强响应为种子在有限窗口内滞后生长，再按外接矩形涂成全白/全黑。`FaceDetector.detect_and_draw` 在涂抹后的副本上检测、仍在原帧上画框；`_compute_desensitization` 与 CLI 在 `is_mosaic` 前先涂抹，纯色块方差为 0 即判为已打码。参数页新增开关、颜色、阈值。抽样 270 帧：落在马赛克上的检出 7 → 0，其余检出数不变
- 避免再犯: 新预处理必须在检测副本上做、禁止改动预览原帧；涂抹区域的生长必须限定在种子邻域，禁止用低阈值连通域直接取外接矩形（会顺着衣物纹理吞掉半个画面）；新增 `app.*` 模块同步写 spec `hiddenimports` 与兼容入口再导出

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
