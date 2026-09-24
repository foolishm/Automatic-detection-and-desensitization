## Context

脱敏率在 `DesensMixin._compute_desensitization` 里用预处理人脸记录对齐后算出，只把一段纯文本交给右侧 `desens_result`。文件名、每帧人脸数、参数和全量漏帧仍留在 `src_info` / `dst_info`，没有一份与这次点击绑定的结果对象。旧单路 `PipelineMixin.save_stats` 导出的是单视频人脸轨迹 txt/csv，不是这份双路脱敏结论。

约束：实现落在 `app/`，`face_video_detector.py` 只再导出公开名字；UI 不写检测算法，报告拼装不引用 tkinter；弹窗走 `app.ui.dialogs`；运行时参数读 `app.settings` 当前值；新 `app.*` 写入 spec `hiddenimports`；测试经 `face_video_detector` 入口。

## Goals / Non-Goals

**Goals:**

- 检测成功后可另存为 `.docx` 正式报告。
- 文档五节与界面上的应脱敏 / 已脱敏 / 脱敏率一致，漏帧全量。
- 导出使用检测完成时冻结的结果和参数，不重读视频。
- 确认路径后显示「正在保存」，完成前可取消；取消时删除本次已经生成的文件。

**Non-Goals:**

- 不判断是否达标，不采集检测人、签名或备注。
- 不导出 PDF、HTML 或 CSV。
- 不改变脱敏率公式，不把马赛克覆盖重新纳入成败判定。
- 不复用 `save_stats`。

## Decisions

### 1. 格式用 python-docx 生成 .docx

Word / WPS 是归档和转发的默认打开方式。HTML 不像正式文件；PDF 需要嵌入中文字体，和现有 PyInstaller 单文件打包容易冲突。

备选：只写 txt —— 用户已明确不要纯文本。备选：HTML 再打印 PDF —— 多一步，且对方拿到的是网页。

### 2. 检测结束时冻结 `last_desens_report`

`_compute_desensitization` 在组装界面文本的同时写入一份 dict：两路文件与元数据、scale、offset、应/已/漏/率/skipped、全量逐帧结果（含人脸数）、以及当时从 `app.settings` 读出的参数快照。导出只读这份 dict。

备选：导出时再扫 `src_info` —— 期间若参数已改但视频未清，方法节会和本次检测不一致。界面文本另存为同样不够，因为没有时间和全量明细。

零人脸帧的 N/A 结果同样冻结，允许导出。

### 3. 拼文档放在 `app/report/desens_docx.py`

公开函数接收报告 dict、输出路径，以及一个可查询的取消标记，返回是否写成功。拼表时每写入一批漏帧行就看一次取消标记，取消则停笔。模块禁止 import tkinter。`DesensMixin` 只负责按钮状态、`filedialog.asksaveasfilename` 和主题弹窗。

确认路径后立刻弹出与现有深色弹窗同一套样式的「正在保存检测报告…」，带「取消」。生成放在后台线程，避免卡住主界面点不到取消。文档先写到目标旁边的临时文件，全部写完且未被取消时再替换成目标路径；替换成功后关闭「正在保存」，再用 `showinfo` 弹出「保存完成」并写上路径。用户在「保存完成」出现前点取消：停止写入，删除本次临时文件；若本次已经替换到目标路径，把该目标文件也删掉。更早一次成功保存、本次还没覆盖的旧文件不删。失败同样删除本次已写出的文件，不弹完成。`Document.save` 这一下本身切不开，取消落到「删掉已经写出的文件」，而不是留着半份。

按钮由 `app/ui/app.py` 创建，放在「开始检测脱敏率」下方、公式框上方，回调进 `DesensMixin`。默认文件名：`原视频主名_vs_脱敏视频主名_脱敏检测报告.docx`。

`python-docx` 与新模块 `app.report`、`app.report.desens_docx` 写入 `人脸脱敏率检测工具.spec` 的 `hiddenimports`。兼容入口再导出拼文档函数，测试不直接 `import app.report`。

### 4. 按钮状态跟检测生命周期

初始禁用。`check_desensitization_ui` 开始时禁用。`_on_desens_computed` 启用。`_on_desens_failed`、导入视频、`_clear_videos` 禁用并丢掉 `last_desens_report`。

### 5. 文档结构

标题、生成时间，然后五节表格/段落：

1. 检测对象：两路文件名、时长、分辨率、帧率、总帧、人脸帧数。
2. 检测方法：口径、对齐公式、换算比、帧偏移、参数快照。
3. 检测结论：应脱敏、已脱敏、漏脱敏、脱敏率；越界跳过数仅在大于 0 时写出。无人脸时结论为不适用，不写百分比。
4. 漏脱敏明细：全量；无漏帧时一段说明。
5. 说明：帧级统计；涂抹开关影响能否检出人脸。

时间显示为 `分:秒`，由帧号 / fps 得到。

## Risks / Trade-offs

- [python-docx 未装或打包漏 hiddenimports] → 开发环境写入依赖说明；spec 同步 hiddenimports；保存失败走 `showerror`，不留半截文件。
- [漏帧上万行导致 docx 偏大、界面卡住] → 仍全量写入；生成放后台线程，主线程只留「正在保存」和取消。
- [取消时留下半截 docx] → 取消或失败时删除本次临时文件；若已经替换到目标路径，连目标文件一起删。
- [中文字体] → docx 不嵌入字体，由 Word / WPS 用系统字体打开，避免 PDF 路线的缺字问题。

## Migration Plan

无数据迁移。未检测过的会话没有报告可导出。回退时去掉按钮与 `app/report`，不影响已有检测结果框。

## Open Questions

无。达标线与检测人已明确排除。
