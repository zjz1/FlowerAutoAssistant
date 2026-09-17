# FlowerAutoAssistant (FAA) 项目进度与任务

> **用法（重要）**：这是项目的"活文档"。**每次运行/开始新任务前，先读本文件**了解当前状态与未完成任务；每次里程碑完成后更新它并勾选任务。保持本文件为当前真实进度的唯一权威来源。

***

> ## 🔖 接手声明（2026-09-18，接手方：TraeCode）
>
> - **产出与修改都在新工作区**：`E:\my_project\trae project\FAA_2026-9-18\FlowerAutoAssistant\`（由 `FlowerAutoAssistant_handoff.zip` 解压 69 文件 + 从原目录只读复制 `resource/template/` 16 个模板）。原目录 `E:\my_project\trae project\6a87d545e1df38ada361ca1c\FlowerAutoAssistant` 仅作**基线只读**，本轮不改写。
> - **运行环境仍用原项目**：解释器 `...\6a87d545e1df38ada361ca1c\FlowerAutoAssistant\.venv\Scripts\python.exe`（Python 3.13.15 / cv2 5.0.0 / maafw）；实机 `127.0.0.1:16384`、`adb=D:\Program Files\Netease\MuMu\nx_main\adb.exe`。已实测从新工作区可直连截图（`py_compile` 0 错、`--list` 9 流程、`debug/_ws_env_check.png` 有效）。
> - **数据分叉约定**：新工作区的 `data/`（`click_log.json` / `config.json` / `close_buttons.json` / `tplt_annotations.jsonl` / `water_count*`）是 **2026-09-17 基线副本**，之后只在**新工作区**增长。**交接期内请勿再从原目录跑自动化或 WebUI**，否则两边知识库各涨一份；端口 8765 同时只允许一个实例（当前无监听）。
> - **回写方式**：原目录对当前 Agent 不可写 → 确认后的改动由用户拷贝回原目录（或授权后由 Agent 合并）。每次交付附「待回写文件清单 + SHA256」。
> - **本轮负责范围**：①文档与代码对齐；②好友采粉并入 `flow_social.json` + WebUI 子面板；③交接期发现的问题修复。**不主动改动** `legacy/`、MaaCore 引擎本体；**不擅自** `git commit/push`。
> - **并行协作提醒**：前序开发方可能继续参与同一目标 —— 双方按本文档顶部声明各自范围，不改对方正在写的文件（见 `HANDOFF.md` §8）。

***

> ## ✅ 开发流程约束（重要，自"从好友采粉"功能开发开始生效）
>
> **所有未经用户确认的新开发内容，一律暂存于临时工作区（如项目下新建 `workbench/` 或 `dev_work/` 目录），不直接更改主体项目（`flows/`、`webui/`、`webui.py`、`ocr_engine.py`、`daily.json` 等）。** 这样可避免新内容开发造成功能顺序混乱；只有用户确认了该新功能/逻辑后，才将其合并进主体项目（含对应 flow、开关、WebUI 子面板）。
>
> **开发工具沉淀规则**：开发过程中创建的新临时脚本，**尝试提取其可通用部分做成通用脚本**，存放在项目中专门的**开发工具部分**（`dev_tools/`，按类别分目录）。之后有需求时**先检索开发工具内是否已有相似功能脚本**再复用，而不是重复新建一次性临时脚本，以减少重复开销。

***

## 1. 项目目标

为页游《小花仙》实现一键挂机（收获/种植/浇水等）。长期对标 MAA 质量，但**技术路线已切换**（见下）。

### 📌 技术路线（2026-08-22 确定，已弃用 MAA 模板匹配路线）

**改为 "OCR 文字定位 + 相对坐标" 数据驱动方案**，与 MAA 模板匹配区分：

- **核心思想**：每次运行时用 OCR 识别界面文字 → 定位文字中心坐标 → 归一化为**相对坐标**（×屏宽高 / 屏高）。**相对位置不受屏幕尺寸变化影响**。定点时 `相对 × 当前屏尺寸` → 点击。

- **三通道回退**：`click_text()` 依次尝试 **① OCR 文字定位 → ② 颜色特征定位（无文字图形按钮）→ ③ 坐标锚点（click\_log 知识库）**。

- **知识库自积累**：每次点击成功后自动把「按钮名 → 相对坐标/绝对坐标 → 界面/场景 → 类别」写入 `data/click_log.json`（version2 按场景两层嵌套，同场景同名按钮只保留最新，跨场景互不覆盖）

### 技术栈

- Python 3.11+ / **MaaFw（新版 maa Python 接口，spawn+tasker）** / OpenCV / RapidOCR / MuMu 模拟器 12

- 当前模拟器：`127.0.0.1:16384`

- 画面坐标系：**1280×720 横屏**；截图 `shape=(720,1280,3)`；点击 `x∈[0,1280), y∈[0,720)`；相对坐标归一化 0\~1

***

## 2. 当前进度（AS OF 2026-09-18，历史里程碑自 2026-08-22 起累加）

### ✅ 已完成

1. **连接与截图链路**：Tasker 连接 `127.0.0.1:16384` 成功，截图 1280×720 成功。

2. **OCR 单例**（[ocr\_ui.py](ocr_ui.py)）：RapidOCR 引擎**进程内只初始化一次**（单例复用），避免每次调用重复加载模型/触发权限。

3. **核心引擎**（[ocr\_engine.py](ocr_engine.py)）：连接/截图/`ocr_image`/`find_text`/`locate`/`locate_color`/`click_abs`/`click_rel`/`click_text`(三通道回退)/`collect_ui`/流程执行(`--flow`)。

4. **三通道识别全部验证成功**：

   - OCR 定位并点击「家园」「一键种植」（种植箱→一键种植两按钮已靠坐标锚点正确区分）

   - **关闭按钮**（右上角粉色四瓣花形，**无文字**）→ 用**颜色特征**（HSV 粉色过滤 + 连通区域）定位点击成功，界面从种植面板返回家园 ✅

   - 坐标锚点回退：OCR 漏识别"一键种植"的"一"时，靠 click\_log 相对坐标仍稳定点击 ✅

5. **知识库自动采集**：`collect_ui()` 一键采集当前界面所有文字块（相对坐标）写入 `data/click_log.json`（当前含种植界面 50+ 按钮）。

6. **界面采集进度**：已进入家园、种植操作界面，识别到核心作业按钮（见第 3 节）。

7. **主循环** **`main.py`** **已构建并端到端验证成功**：

   - 连接 → 执行流程 → 多轮循环（`--loop 0`=无限）→ Ctrl+C 中断 → 断线自动重连

   - 每日挂机单轮实测跑通：**进家园→一键种植→浇水→施肥→收花→关闭**，退出码 0

   - 三通道识别（OCR/颜色/坐标锚点）在实机全部生效，点击日志自动积累

8. **✅ 模块化编排（六大模块）构建并端到端跑通**（AS OF 2026-08-22）：

   - `daily.json` 按序调度：启动 → 签到 → 种植 → 社交 → 挂机 → 领取奖励；核心模块 `on_fail=stop_round`，可选模块 `on_fail=skip`。

   - `ocr_engine.run_daily()/run_module()` 已实现编排；`main.py` 检测到 `modules` 键自动走编排（`main.py:84`）。

   - 单轮实机运行：**6/6 模块完成、退出码 0**，容错链路（顺序执行/失败终止/失败跳过）验证有效。

   - 新采集坐标：社交(0.331,0.949)、在线礼包(0.821,0.217)、家园快捷条「种植箱一键种植」(0.784,0.950)、「快捷操作」(0.692,0.950)。

9. **✅ 关闭按钮-特殊逻辑注册表**（AS OF 2026-08-22）：

   - 新增 `data/close_buttons.json`，以"关闭按钮-特殊逻辑"方式注册两种已知关闭按钮：

     - `anchor_color`：「提示」锚点右侧按颜色找关闭（弹窗式）

     - `corner`：整体画面右上角按颜色找关闭（种植面板式，region\_rel 相对区域）

   - `find_close_button()` 遍历注册表返回首个命中的关闭按钮；`close_dialog()` 改为调用它（`--flow`/`loop` 步骤 `close_dialog` 自动生效）。

   - CLI 扩展：`--close-test`（仅定位打印不点击）、`--add-close <名称> <corner|anchor_color>`（后续新增关闭按钮用）。

   - 实测：`--close-test` 当前画面右上角逻辑命中候选 (1265,107) rel(0.988,0.149)，是否真实关闭按钮需种植面板内肉眼复核。

10. **✅ 体力任务模块首链跑通**（AS OF 2026-08-22）：

- `--flow 体力任务 --loop 1` 实测（用 `-u` 无缓冲）：6 次 `close_dialog` 未命中弹窗（无「提示」，符合预期）；`if_text 闪耀变身 → HIT`，OCR 定位 (134,450) rel(0.1047,0.625) 并点击成功，流程退出码 0。

- 注意：进程无输出多为 Python 输出缓冲所致，命令需加 `-u`。

1. **✅ 新增步骤类型** **`if_fraction`** **+ 体力任务逻辑4**（AS OF 2026-08-22）：

- 引擎新增 `parse_fraction_at()`（OCR 找距 `region_rel` 最近的 `a/b` 数字块）/ `eval_fraction()`（用变量 a=分子、b=分母 求值 condition，如 `a<b`、`a>=20`），`run_step` 支持 `if_fraction` 分支。

- `flow_energy.json` 逻辑4：①顶栏 `(0.598,0.038)` 读到 `a/b`，`a<b` 才继续；②顶栏 `(0.860,0.038)` 读到 `c/d`，`c>=20` 才继续；③两项都满足则点「光偶像」(fallback\_rel \[0.0508,0.5417])。

- 实测：当前闪耀变身页 `(0.598,0.038)=342/600`→`a<b` TRUE、`(0.860,0.038)=100/100`→`a>=20` TRUE。

1. **✅ OCR 扫描开发工具** **`--ocr-screen`** **+ 区域文本判断 + 体力任务逻辑5**（AS OF 2026-08-22）：

- 新增 CLI `--ocr-screen`：连接→截图→一次OCR→打印当前画面**所有字符及相对坐标**（不写入知识库），替代临时脚本，供开发采集坐标用。

- `find_text()`/`locate()`/`if_text` 支持 `region_rel=[x1,y1,x2,y2]`：只在指定区域做文本判断（避免全局同名误命中）。

- `flow_energy.json` 逻辑5：①区域 `(0.05,0.86,0.18,0.94)` 含「成为最闪耀明星」则点 (0.817,0.893)「速通」；②点「确定」；③\*\*`wait_text` 等「确认/确定」出现后再点\*\*。

- ✅ 坐标已校准（实测 速通→确定→结算）：第②个「确定」=速通弹窗 `[0.497,0.644]`；第③个＝结算页「确认」`[0.638,0.858]`（OCR 文本是「确认」非「确定」，故 text 用 \["确认","确定"]）。点结算「确认」后回到星光偶像选择界面。

- ✅ 时序已修复：点「速通」弹窗确定后挑战进行数秒，第③部已用 `wait_text`（timeout 25s）等「确认」出现再点，避免在挑战界面过早误点。

1. **✅ 新增步骤类型** **`loop_fraction`：体力任务按需循环**（AS OF 2026-08-22）：

- 引擎新增 `_calc_int()`（受信公式安全求值，支持 a/b/ceil()/floor() 四则）与 `run_loop_fraction()`（读多个分数区域→各按公式算整数→取 min/max→夹到 max\_loop→重复执行 do）。

- `flow_energy.json` 重构：顶栏 `(0.598,0.038)` 算 `n=ceil((b-a)/57)`、`(0.860,0.038)` 算 `m=floor(a/20)`，`combine=min` 得循环次数，重复 do= \[点光偶像→若区域有「成为最闪耀明星」则点速通→点确定→等结算确认→点确认]。均<=0 则不循环（天然充当条件闸门）。

- 公式实测：`ceil((600-399)/57)=4`、`floor(52/20)=2`；现场画面 `342/600→n=5`、`62/100→m=3`、`min=3`。

1. **✅ 锚点偏移定位法 + 登录界面「切换账号」按钮知识库**（AS OF 2026-08-22）：

- **背景**：小花仙登录界面为**固定尺寸**（不随设备分辨率缩放），整体画面相对坐标(0\~1)在启动就绪/登录功能中**失效**；改用「锚点 + 像素偏移」法，偏移恒定不随分辨率变化。

- 引擎新增 [`locate_anchor_offset()`](ocr_engine.py)：按 `text_contains`（子串，如账号 `abc****de` 中的 `****`）或 `text`（关键字）找锚点块 → 锚点中心 + 像素偏移 → 目标点，支持多锚点依次回退。

- `click_text()` 回退链升级为四通道：**OCR → 锚点偏移 → 颜色特征 → 坐标缓存**（知识库条目含 `anchor` 字段即走锚点通道）。

- `_log_click()` 改为合并式写入：保留旧条目人工标注的 `anchor/color/scene/note` 扩展字段，不被自动日志覆盖。

- 「切换账号」按钮（灰色向下折角，无文字）已写入 `data/click_log.json`，三种方法实测均命中 (991,287)：

  1. 主锚点=账号文本 `****` + 偏移 (+351,+1)
  2. 次锚点=「登录」按钮 + 偏移 (+237,-107)
  3. 颜色特征：账号右侧 dy±20 / dx 150~~380 区域内浅灰块（HSV V 205~~245, S≤30, 面积 60\~100；收窄后唯一命中，排除干扰块 area 125/475）

- CLI 新增开发工具 `--ocr-anchor <锚点> [--exact]`：以指定文字为锚点打印各文字块像素偏移（固定尺寸界面采集用）。

- 登录界面其它锚点偏移（锚点=登录按钮）：切换(+475,-282)、公告(+474,-212)、登录其他账号(-1,+85)、账号文本(-114,-108)。

- **✅「切换账号」模块实机跑通**：`flow_switch.json`（可选模块，`daily.json` 已插到「启动就绪」之前，on\_fail=skip）→ ①`click_text("切换账号")` 锚点通道点折角图标展开列表(实机 992,287) ②新增步骤 `click_account_tail` 按账号文本尾部数字点目标账号(实机命中 195\*\*\*\*89 at 652,361)。目标账号用尾部数字识别（如 89），region\_rel 限定账号列表区避免误点底部数字。引擎新增 [click\_account\_tail()](ocr_engine.py)：OCR 在 region 内找 `****` 账号块且尾部==tail → 点击中心。（注：点击账号后回到目标账号登录页，由「启动就绪」后续点「登录」进游戏。）目标账号尾部已改为**可配置项**：`data/config.json` 的 `target_tail` 字段（默认 89），flow 步骤 `tail` 用 `${target_tail}` 占位符引用；引擎新增 `_load_config()`/`resolve()` 支持 `data/config.json` 加载与 `${key}` 占位符解析（仅替换 config 中非 `_` 开头字段）；CLI 可用 `--tail <数字>` 临时覆盖（`ocr_engine.py --flow 切换账号 --tail 61` / `main.py --tail 61`）。**切换账号已做成可选功能（UI 开关）**：`data/config.json` 增加 `enable_switch`（默认 false）；`run_daily` 在模块循环中，id=='switch' 且未启用时直接 skip；引擎新增 `_save_config()`/`update_config(**kw)` 持久化；Web UI「运行流程」面板新增「可选功能」区（勾选切换账号 + 目标尾部输入 + 保存），新增 API `GET /api/config` / `POST /api/set_config`。

1. **✅ 本地 Web UI（自测/使用模式）**（AS OF 2026-08-22）：

- [`webui.py`](webui.py)：标准库 `http.server` 实现，无第三方依赖；`python webui.py [--port 8765]` 启动，浏览器开 `http://127.0.0.1:8765/`。

- [`webui.html`](webui.html)：内嵌单页前端，功能齐全：

  - **实时画面 + OCR 标注**：每 1.5s 自动刷新，粉色框标出 OCR 文字块并显示相对坐标；点击画面任意位置即对模拟器发点击（转相对坐标）。

  - **连接 / 返回键 / 模式切换**：ADB「连接」、送「返回键」；「使用」/「测试」模式（测试周期切 `debug_click` 存点击截图到 `data/click_debug`）。

  - **运行流程**：下拉选 8 个 flow（含「每日挂机编排」）+ 一键运行，后台线程执行，日志经环形缓冲实时增量滚动（`/api/log?after=`）。

  - **流程/知识库浏览**：下方面板展示 `flows/*.json` 与 `data/click_log.json` / `data/close_buttons.json`（知识库按**场景树形分组**展示，可折叠，带类别标签）。

- API 一览：`/api/status` `/api/flows` `/api/kb` `/api/connect` `/api/set_mode` `/api/screen` `/api/click` `/api/back` `/api/run` `/api/log`。

- 已修复：[webui.html](webui.html) `refreshStatus()` 里未定义的 `rank()` 改为 `!!s.connected`（原先会抛 ReferenceError 致连接徽标刷新崩溃）。

1. **✅ Web UI 重构：使用 / 测试双界面（MAA 风格）**（AS OF 2026-08-22）：

- **拆分为两个界面，右上角「切换界面」按钮互切**：

  - **使用界面**（新，仿 MAA 主界面）：左栏「每日挂机任务」勾选列表（全选/清空/反选）+「完成后」下拉 +「开始一轮」大按钮；右栏「账号切换」（启用开关 + 目标账号下拉 + 立即切换）、“连接设置”（连接配置/ADB/地址/连接状态按钮）。**去除任何「必选」标记**——任务全部可由用户勾选决定是否执行。

  - **测试界面**（原单页能力全部保留）：实时画面 + OCR 标注、点击、运行流程、可选功能、运行日志、流程/知识库浏览。

- 前端 [webui.html](webui.html)：两视图容器 `#use-view` / `#test-view` 用 `.hidden` 切换，右上角 `#view-toggle` 切换按钮；共用同一条 `/api/log` 日志流。

- 后端 [webui.py](webui.py) 新增接口：

  - `GET /api/daily`：读 `flows/daily.json` 返回模块列表（id→中文名映射）+ config/enable\_switch/target\_tail。

  - `POST /api/run_daily`：接收勾选模块 id 列表，从 daily.json 过滤构造编排后跑，「开始一轮」使用；会**去掉必选标记**（统一 `on_fail=skip`）、空选择返回 400。

- 实机验证：页面 200、`/api/daily` 返回正确中文映射、`/api/run_daily` 空选择返回 400「未勾选任何任务」。

- **注意：端口 8765 曾被未关闭的旧 webui 进程（系统 Python313）占用**，导致新接口返回旧逻辑；用 `Stop-Process` 清掉旧进程、以 `.venv` 重启后一切正常。启动脚本 [start\_webui.bat](start_webui.bat) 仍适用（会优先用 `.venv`）。

1. **✅ 启动脚本增强 + UI 关闭服务按钮**（AS OF 2026-08-22）：

- [start\_webui.bat](start_webui.bat)：双击即用，启动后约 2 秒**自动打开浏览器**（内嵌 PowerShell `Start-Process`）；支持 `start_webui.bat [port] [--address xxx] [--adb xxx]`，沿用 `.venv` 优先；进程退出后自动关窗（`timeout 3s`）。

- 后端 [webui.py](webui.py) 新增 `POST /api/shutdown`：记录日志后用独立线程调用 `srv.shutdown()`+`server_close()`，优雅退出并释放端口（`main()` 里把 server 实例存入模块级 `_SERVER`）。

- 前端 [webui.html](webui.html)：header 右上角新增红色「⏻ 关闭服务」按钮（确认弹窗 → 请求 `/api/shutdown` → 页面提示已关闭）。为避免改变 `.view-link` 布局，`shutdown` 不加 `margin-left:auto`（`view-link` 上的 auto 已生效，默认间距不变）。

- 实测：POST `/api/shutdown` 返回 `{"ok":true,"message":"服务已关闭"}`，监听进程退出、端口释放（`LISTENERS_LEFT=0`）。

1. **✅ 架构调整：启动就绪→开始启动，切换账号并入作为可选功能**（AS OF 2026-08-22）：

- **「启动就绪」更名为「开始启动」**；**「切换账号」合并进开始启动**（不再是独立模块），作为启动内的可选功能存在。

- 引擎 [ocr\_engine.py](ocr_engine.py) 新增步骤类型 **`if_config`**（`eval_config()`）：流程内按 `data/config.json` 键值做条件分支（`key`/`value`/`op` ∈ == != >= <= > <；value 支持 `${key}` 占位符与 bool/int 自动转换）。

- [flow\_startup.json](flows/flow_startup.json)：更名为「开始启动」；步骤前方包一层 `if_config`（`enable_switch=true` 才执行：点切换账号 → `click_account_tail` 点目标账号），随后点「登录」→「点击进入游戏」。

- `flow_switch.json` **已删除**（逻辑并入 startup，不再独立）。

- [daily.json](flows/daily.json)：编排从 **9 → 8 模块**，移除独立 `switch` 模块；`startup` 描述为「开始启动(登录进游戏, 含可选切换账号)」。

- 后端 [webui.py](webui.py)：`id2name` 移除 `switch`、`startup` 改名「开始启动」，使用界面任务列表同步更新。

- `run_daily()` 中原先针对 `switch` 的 `enable_switch` 特判已删除（开关判断下沉到 startup 流程内部 `if_config`，逻辑等价的职责内聚）。

- 验证：daily 8 模块无 switch、startup 首步 if\_config、flow\_switch 已删、`eval_config` 对 enable\_switch true/false 判断正确。

1. **✅ 签到功能开发 + 新增右上角白色圆形关闭按钮类型**（AS OF 2026-08-22）：

- **签到面板**：游戏自动弹出（仅当日未签时）；「兔尔电波/双生签到」日历，8/23 位置 `点击签到(abs(624,327))`，21/22 已显示「已签到」，累计 9/41→10/41。

- [flow\_signin.json](flows/flow_signin.json)（`signin` 模块）：① `if_text` 全屏 OCR 找「点击签到」→ 命中才执行（不留存坐标，位置随日历每日变化）②点「点击签到」③点「点击任意处关闭」关『恭喜获得』弹窗 ④ `close_dialog only_types=["corner","corner_white"]` 退出签到面板。当日已签则不弹、OCR 找不到「点击签到」自动跳过（天然兼容）。

- 实测：签到+关弹窗成功、累计 10/41。

- **🔴 修复：签到面板右上角关闭按钮未能退出**——它是**白色圆形**（中心 abs(1228,71)，边缘粉色描边 HSV(172,42%,96%)），而旧逻辑用摇钱树坐标 `click_rel(0.938,0.125)=(1200,90)` 点到背景色，退不出。

  - `data/close_buttons.json` 新增第 3 种关闭类型 **`corner_white`**：右上角 rel 区域 `(0.9,0,1.0,0.16)` 内找白色块（HSV V>200,S<30,面积600\~3000），精确命中 (1228,71)。

  - `ocr_engine.py`：`_locate_close_by_entry` 支持 `corner_white`（与 `corner` 同走 region\_rel+color）；`close_dialog()`/`run_step` 新增 **`only_types`** 参数（按类型过滤遍历，退出整屏面板时避免误点「提示」锚点弹窗）。

  - 实测：`corner`→(1228,66)、`corner_white`→(1228,71) 双命中；`close_dialog(only_types=["corner","corner_white"])` 成功退出签到界面 → 回到主界面（寻梦童话/手账/在线礼包等）。

1. **✅ 新增功能2「花灵派对」独立流程（AS OF 2026-08-23）**：

- [`flow_party.json`](flows/flow_party.json)（`party` 候选，独立流程）参照「闪耀变身」进入结构，但**入口走「菜单」**（非更多活动）：①关弹窗(loop 6×close\_dialog anchor=提示) ②`if_text` 就近直达「花灵派对」→点 ③否则回主界面(点菜单, 若只有家园先点家园再点菜单) ④从菜单 OCR 找「花灵派对」→点。

- `--list` 已识别「花灵派对」流程；**暂未挂载 daily.json**（先独立测试，实机校准菜单内「花灵派对」坐标后再决定是否挂载）。

- ⚠️「花灵派对」在菜单内的相对坐标未校准，`fallback_rel` 暂用 \[0.105,0.625] 占位，需实机 `--ocr-screen` 校准。

1. **✅ 花灵派对·领取奖励（时长礼包）实机跑通（AS OF 2026-08-23）**：

- `flow_party.json` 扩展为完整领取流程：进花灵派对 → 点「派对时长礼包」rel(0.0539,0.4250) → 顺序领取6个在线时长礼包 → 关面板。

- **派对时长礼包面板校准**：6礼包分两行3列，标题「派对时长礼包」rel(0.5,0.0806)；第1行「1分钟/5分钟/15分钟在线礼包」(y=0.2167)，各「领取」按钮 rel(0.2750,0.4694)/(0.5000,0.4694)/(0.7242,0.4694)；第2行「30/60/90分钟在线礼包」(y=0.5806)，领取 rel(0.2758,0.8333)/(0.5000,0.8333)/(0.7242,0.8333)。

- **领取机制**：点「领取」→ 弹「恭喜获得」窗 → 点「点击任意处关闭」(0.5,0.9375)→ 该礼包「领取」按钮消失。已领的按钮消失后，固定坐标点击无效（自然跳过，流程健壮）。

- 实测领完1/5/15/30分钟，弹窗+关闭全程正常。

- **面板关闭**：派对时长礼包/爱心记录面板的关闭按钮 = `corner_pink_small` 类型，命中 (1108,80)。**注意每日任务/爱心记录面板被覆盖时** **`corner`/`corner_white`** **也测过无效，只有** **`corner_pink_small`** **有效**。

- 花灵派对场景：进入他人派对时顶部有「点赞」、左侧功能栏(时长礼包/每白任务/排行榜/爱心记录)；`corner_pink_small` 关闭面板回到派对场景。

- test flow JSON 23 步，`json.load` 合法。

- **✅ 已挂载为「领取奖励」功能2**：花灵派对领取流程合并进 [`flow_claim.json`](flows/flow_claim.json)（27步），在功能1在线礼包后顺序执行；`daily.json` 的 claim 模块不变，自动继承。`flow_party.json` 保留为独立流程便于单独测试。

1. **✅ 领取奖励·功能1/功能2 可选开关 + Web UI 模块 ⚙ 设置面板（AS OF 2026-08-23）**：

- **config.json** 新增 `claim_online`、`claim_party` 布尔开关(默认 true)，`_comment` 已说明。

- **flow\_claim.json** 重构为 2 个 `if_config` 块：`claim_online`(功能1, then=4步) 与 `claim_party`(功能2, then=23步)；任一关 skip 该整段。引擎已支持 `if_config`(见课内 eval\_config/run\_step if\_config)。

- **webui.py**：`/api/config` GET 新增返回 `claim_online`/`claim_party`；`/api/set_config` POST 支持写这两个开关并写日志；`/api/daily` 每个模块新增 `settings` meta——`claim` 模块含功能1/2 的 switch、`startup` 模块含 enable\_switch/target\_tail，其它模块为空数组。

- **webui.html**：使用界面改三栏布局(任务|设置|账号连接提示)；左栏任务行加 `⚙` 键(无独立设置的模块置灰禁用)；点击 ⚙ 展开该模块「模块设置」面板(在左栏面板内)，渲 switch/text 设置项，"保存设置"调 `/api/set_config`。

- **已验证**：`/api/daily` 返回 claim/startup settings、`/api/config` 含新字段、`set_config` 写回 config.json 正常；测试后已将 claim\_party 恢复为 true。

1. **✅ 新增** **`retry_loop`** **原语：把「批量关弹窗」改为「脱困式重试」**（AS OF 2026-08-23）：

- **问题背景**：旧流程一律在核心步骤前 `loop_times 6 × close_dialog(提示)` 批量连关弹窗。关闭按钮可能误识别/误触，且连点次数多易产生误触。优化目标：关弹窗不再是"开场必做"，而是"核心步骤无法进行时的最后一招脱困"。

- **引擎新增** **`retry_loop`** **步骤类型**（[ocr\_engine.py](ocr_engine.py) `run_step`）：`max_rounds`(默认3)+ `do`(每轮内容) + 可选 `fail_do`(脱困动作；不写则自动 `close_dialog()` 尝试**全部类型**关闭按钮)。

- **命中机制**：`click_text` 支持 `mark:true` 标记"目标命中"。retry\_loop 每轮开始把 `self._rr_hit` 置 False，执行 `run_steps(do)`；仅 when do 内**真实点击成功且该点击带** **`mark:true`** 时置 `_rr_hit=True`。轮末：`_rr_hit=True` → 本轮成功退出；`False` → 脱困(关全部类型弹窗) → 进入下一轮。跑满 `max_rounds` 仍无命中 → 放弃，继续流程后续步骤（不抛错）。

- **语义（方案B/A 融合）**：进入目标的**候选序列定位为前段**，只有"点到目标(带 mark)"才算本轮成功；「菜单/家园/社交/家族」等**导航层不 mark**，点它们后继续向下层探测；**后段核心步骤(领礼包/速通/浇水)不参与成败判定**，进门命中即本轮成功 → 避免"当日无事可做(如已领/次数已满)"时被误判失败而空转脱困。

- **四个流程统一改造**（删掉开头 `loop_times 6 × 关提示`，改由 retry\_loop 轮末脱困触发）：

  - [`flow_party.json`](flows/flow_party.json)：目标=「花灵派对」(mark)，导航=菜单/家园；后段领6礼包。

  - [`flow_energy.json`](flows/flow_energy.json)：目标=「闪耀变身」(mark)，导航=菜单/家园；后段 loop\_fraction 速通循环。

  - [`flow_social.json`](flows/flow_social.json)：目标=「家族活动」(mark)，导航=社交/家族(嵌套)；后段摇钱树浇水。

  - [`flow_claim.json`](flows/flow_claim.json)：功能2 花灵派对的`if_config claim_party` then 内，用同一 retry\_loop 结构替换原 loop\_times+if\_text 链（功能1在线礼包不变）。

- **模拟验证**（无设备，`locate`/`click_text` 打桩）：场景1(目标全 MISS)→3轮各脱困1次=3次、无异常退出；场景2(首轮命中)→0次脱困、首轮即退出。`json.load` 校验 4 流程合法。

1. **✅ 花灵派对·时长礼包领取改为** **`loop_text`** **动态循环（AS OF 2026-08-23）**：

- **问题背景**：花灵派对「时长礼包」面板内礼包分成两行三列（1/5/15 + 30/60/90 分钟）。旧版用**固定 6 个相对坐标**逐个点击领取（如 (0.275,0.47)/(0.5,0.47)/(0.724,0.47) 等）。实机发现：**这些坐标落在每张卡片的"种植/经验"作物区，不是"领取"按钮** → 点 6 次全程无「恭喜获得」、礼包面板也关不掉。

- **关键规则（用户确认）**：礼包一经领取，"领取"按钮即消失。因此：**能否识别到"领取"文字 == 是否还有可领的礼包**。

- **处理方案**：`领取`按钮相对坐标虽固定，但以**OCR 判定有无**为准更可靠 → 两者结合。

- **引擎新增** **`loop_text`** **步骤类型**（[ocr\_engine.py](ocr_engine.py) `run_step`）：只要还能识别到 `text`（如"领取"）就重复执行 `do`；识别不到即退出。参数 `text`/`min_score`/`max_loop`(守卫上限,默认20)/可选 `region_rel`。用于"有'领取'就点、领完按钮消失即自然停止"的领取循环。

- **[`flow_party.json`](flows/flow_party.json)** **/** **[`flow_claim.json`](flows/flow_claim.json)** **功能2 改造**：原 6 个固定领取坐标 → `loop_text(text=["领取"])` do=\[ `click_text("领取")` → 等1.2s → if\_text(「恭喜获得」)→点(0.5,0.9375)关闭 ]。面板内识别到"领取"就点，全部领完按钮消失即停，随后 `close_dialog` 关面板。

- **实机已确认**：`--ocr-screen` 验证点左侧栏「时长礼包」rel(0.0539,0.4250) 确实进入「派对时长礼包」面板（标题出现），面板内可识别到"领取"按钮（如 (0.5,0.8333)/(0.7242,0.8333)）。`json.load` 校验两流程合法。

- **注意（本次实机遗留）**：因当日在面板外截图时"领取"按钮已部分消失（领完即隐藏），实际"点进入面板→loop\_text 领取"的连贯性需下次整流程 `--flow 花灵派对 --loop 1` 复核；正常路径应全程零脱困，仅目标被挡时触发 retry\_loop 脱困。

1. **✅ 花灵派对·整流程实机跑通 + 「时长礼包」入口改为 OCR 驱动（AS OF 2026-08-23，未提交）**：

- **问题（用户指出，此前已确认）**：进入花灵派对后流程**没有点「时长礼包」按钮**，导致 `loop_text('领取')` 一开始就找不到按钮而直接结束。

- **实机定位**：`--ocr-screen` 确认登录「花灵派对」主面板左侧栏有「时长礼包」tab `rel(0.0531,0.425)=(68,306)`；点它进入「派对时长礼包」面板（标题 rel0.5,0.079），面板内当时有 **2 个「领取」按钮** `(0.499,0.833)`/`(0.723,0.833)`（其余已领完即消失）。

- **修复**（原 `flow_party.json` 步骤47-55，已合一进 [`flow_claim.json`](flows/flow_claim.json) 功能2）：把裸 `click_rel(0.0539,0.425)` 改为 **`if_text('时长礼包')`** **→** **`click_text('时长礼包')`（OCR 定位点）+ else 兜底** **`click_rel(0.0531,0.425)`**。

- **实机验证**（`--flow 花灵派对` 完整跑通）：retry\_loop 第3轮从脱困恢复→识别「菜单」(68,59)→点「花灵派对」(237,542)→mark 命中；`if_text('时长礼包')` 本轮 **MISS**（文字未识别到），靠**兜底坐标** `click_rel(67,306)` 点中面板；`loop_text('领取')` 连续点 2 次 `(639,600)/(926,600)`，每次→`if_text('恭喜获得')`→点 `(0.5,0.9375)` 关闭，直到按钮消失结束；最后 `close_dialog(corner_pink_small)` 关面板。**全程领取+关弹窗正常**。

- **残留注意**：①`if_text('时长礼包')` 实机有 MISS，当前靠兜底坐标救回的，OCR 对该字样识别不稳定，后续可再加强；② OCR 精度修复（`det_use_dilation=False`，见第 6 节）本次实机有效——`菜单` 干净识别 `(68,59)`，未误点「奇妙花宝」。

1. **✅ 领取奖励←合一 + 功能1 补 retry\_loop（AS OF 2026-08-23，未提交）**：

- **纠偏概念**：花灵派对 ≡ 领取奖励·功能2，是**同一实体**。原先 `flow_party.json` 与 `flow_claim.json` 功能2 各持一份几乎相同的代码 → 重复且易漂移（今日 flow\_party 的「时长礼包 OCR 驱动」修复就未同步到功能2）。

- **合一**：删除 `flow_party.json`（无任何引用），权威副本收敛到 `flow_claim.json` 功能2；将今日「时长礼包 OCR 驱动入口(`if_text('时长礼包')→click_text`+兜底 `(0.0531,0.425)`)+sleep」同步进功能2，坐标统一。

- **功能1 claim\_online 补 retry\_loop（入口脱困化）**：原开场直接 `click_rel(0.8258,0.2167)` 点「在线礼包」，可能停留在其它页面而点空。改为 `retry_loop=max3`：每轮 `if_text('在线礼包')` → `click_text mark:true`(fallback 0.8258,0.2167)，**无导航层**（功能1 入口固定可见）；未命中→失败→`close_dialog`(corner\_pink\_small/corner/corner\_white)脱困→下轮。后段(抽奖 loop×3 / 时间礼包 50→30→10 / 关面板)原样保留。

- flow\_claim.json `json.load` 校验通过。**待实机验证**（见待办 🟠）。

1. **⚠️ retry\_loop 改造点，仅「花灵派对/功能2」实机验证，其余待验证（AS OF 2026-08-23）**：

- 「retry\_loop 脱困式重试」（里程碑 23）改造的 retry\_loop 位置现共 **3 处**：`flow_claim` 功能1（在线礼包，本轮新增）、`flow_claim` 功能2（花灵派对，原 flow\_party 已合一）、`flow_energy`（闪耀变身）、`flow_social`（家族活动/摇钱树浇水）。

- **目前实机验证通过的仅「花灵派对」（功能2，原 flow\_party）**；功能1（本轮改造）、`flow_energy`、`flow_social` 均**尚未真机实测**，需逐一验证（见待办 🟠）。

1. **✅ 领取奖励功能1+功能2 端到端实机跑通（AS OF 2026-08-23，未提交）**：

- 配置：`config.claim_online` 从脱敏态 false 临时置 true 施测（`claim_party` 本就 true），`--flow 领取奖励` 全程一次跑通，退出码 0。

- **功能1 claim\_online**：retry\_loop 第1轮 mark 命中「在线礼包」(1058,155)→抽奖 `N:3→2→1`(每次 wait\_text『点击任意处关闭』→点(0.5,0.9375)关恭喜获得)→`count_text('已领取')=0<threshold=3`→if\_text「50分钟」HIT→点(0.166,0.692)领取→wait\_text→关闭→关面板 corner\_pink\_small(1105,97)。

- **功能2 claim\_party（合一后回归）**：retry\_loop 直达/脱困——首轮花灵派对MISS、菜单MISS→家园HIT(1115,684)→菜单(68,58)→花灵派对(237,542) mark命中；`if_text('时长礼包')` **MISS→兜底** click\_rel(67,306) 进时长礼包面板；`loop_text('领取')` 本轮 6 档全未领：连续领 6 个 `(352,337)/(639,338)/(926,338)/(351,600)/(639,600)/(926,600)`，每项 `if_text('恭喜获得')`→点(0.5,0.9375)关闭，**全部领完按钮消失**→loop\_text 自然退出→关面板 corner\_pink\_small(1108,80)。

- **结论**：功能1（新增 retry\_loop 入口脱困）、功能2（合一+时长礼包兜底+loop\_text 动态领取）均实测通过；retry\_loop 脱困式进入、抽奖耗尽、时间礼包按档领取、恭喜获得弹窗关闭、关面板各环节正常。剩 `flow_energy`/`flow_social` 待验证（见待办 🟠）。

1. **✅ 知识库/按钮库分类分组改造（两层嵌套）**（AS OF 2026-08-27）：

- **背景**：旧 `data/click_log.json` 为扁平 `{按钮名: 记录}`，同名按钮跨界面互相覆盖、无分类、难维护。按用户要求按「界面/场景」+「功能类别」两维度分组，磁盘采用**两层嵌套**。

- **磁盘格式（version 2）**：`{"version":2, "scenes": {场景名: {按钮名: {记录, "category": 类别}}}}`。记录内 `category` ∈ 导航/作业/活动/账号/弹窗/关闭按钮/状态/其他。

- **引擎改造**（[ocr\_engine.py](ocr_engine.py)）：

  - `_load_click_log()` 兼容**新嵌套 + 旧扁平**两种格式（旧格式自动归入「未分类」，带 `scene` 字段的按字段归组）；`_save_click_log()` 写 version2 嵌套。

  - 内存维护两级状态：`click_log_scenes`（场景→按钮→记录，权威）+ `click_log`（**扁平索引**，跨场景同名取最后一个，供既有查找回退链零改动使用）。

  - `_log_click()`/`collect_ui()` 按 `self._scene` 分组写入并自动打 `category`（`auto_category()` 按按钮名语义推断）；保留了旧条目人工标注的 anchor/color/scene/note/category 字段不被覆盖。

  - **场景声明**：流程步骤/流程顶层可写 `"scene"` 字段（如 `"scene": "家园主界面"`）声明当前界面，默认「未分类」；计划长期结合界面感知自动识别。

- **数据迁移**：旧 80+ 条记录按语义映射到 12 个场景（登录界面/家园主界面/种植界面/家族界面/家族活动界面/在线礼包界面/签到界面等）并逐个打类别；含「浇水」等跨场景同名示例（扁平索引按设计只留其一，分组不覆盖）。

- **close\_buttons.json**：4 条关闭按钮特殊逻辑全部补 `scene`+`category` 字段。

- **Web UI**（[webui.html](webui.html) 知识库面板）：按 **场景树形分组**展示（可折叠），每场景显示按钮数与类别标签（按类别着色），附关闭按钮库分组，旧扁平格式自动回退展示。

- **自测**：临时自测脚本验证——所有 JSON 解析正常（click\_log 为 version2+scenes）、新格式加载场景数=12、扁平索引条数=唯一按钮名数(106，107 条中含 1 个跨场景同名)、旧格式兼容归「未分类」、`_log_click` 分组写入+自动类别、关闭按钮全部带 scene/category。全部通过后临时脚本已删。

- **当前分布**：12 场景 / 107 按钮（唯一名 106）；类别：其他 37、状态 25、作业 20、活动 10、导航 5、关闭按钮 4、弹窗 3、账号 3。

1. **✅ 中优先-方案②：点击位置"立体化分级 + 均值 + 偏差复核"加固定位**（AS OF 2026-08-27）：

- **目标**：缓解 OCR 定位抖动/合并块中心偏移导致点偏（如「种植箱一键种植」合并块宽 148 把命中点带偏），让位置"越用越稳"。

- **立体化分级**：定位方式已由记录 `method` 分级——`ocr`/`color`=整体相对坐标（可跨分辨率复用）、`anchor`=锚点-像素偏移（固定尺寸界面如登录页，整体相对坐标不可比）、`fallback`=缓存回退（不产生新位置证据）。**分级的目的：均值样本只按"同类可比"累积，不混用**。

- **均值累积**（[ocr\_engine.py](ocr_engine.py) `_log_click`）：仅 `ocr`/`color` 命中时按场景更新记录 `mean_rel`+`sample_n`（运行均值，免存全量样本；与旧数据的 `rel` 字段独立，`rel` 保持"最近一次命中"）。anchor/fallback 不写入均值。

- **偏差复核**（`click_text` OCR 命中路径）：命中点与该按钮**当前场景**均值偏差 > `BIAS_MAX_PX=60px` 判为可疑 → 二次精细处理 `_refine_hit()`：以命中点为中心局部截取 60×40 区域放大 2x 重识别关键字子块；更靠近均值的子块**校准采用**，否则沿用原命中并仅打日志（不静默改点）。场景条目用 `_entry_for()` 优先当前场景、无则扁平索引。

- **均值点补齐**：OCR/锚点/颜色全 miss 的回退链顺序改为 **均值点(mean\_rel) → 进程缓存(last\_rel) → 知识库 rel**。

- **Web UI**：知识库面板相对坐标列显示样本数（`· 均N`），位置信任度可视化。

- **自测**：临时脚本验证 6 项全部通过——均值累积收敛、sample\_n 递增、anchor/fallback 不入样本、场景优先条目、偏差触发复核并点击校准点、回退优先均值点。临时脚本已删未入库。

- **生效方式**：无需配置，历史无 `mean_rel` 的条目在下次 `ocr`/`color` 命中时自动补齐首样本；后续每次成功点击自动累积。

1. **✅ 方案A·公共「进入目标界面」导航能力** **`navigate`（AS OF 2026-08-27）**：

- **背景**：`flow_energy`/`flow_social`/`flow_claim`(功能2) 各自内嵌一套几乎相同的 `retry_loop` 进入链（归位→导航→mark 命中→脱困重试），坐标各自硬编码、改一处不同步即漂移；且无"进入某界面"可复用子流程，新活动只能复制链或塞进现有 flow 越写越臃肿。

- **新增导航注册表** `flows/common/entries.json`：`{"targets": {目标名: {scene, mark_text, mark_fallback_rel, max_rounds, nav}}}`。已登记 **家族活动 / 闪耀变身 / 花灵派对** 三 target（nav 用引擎标准步骤 schema，内层点到目标的 `click_text` 带 `mark:true`）。子目录不被 `load_flows()` 扫入主流程（只 glob 顶层 \*.json）。

- **引擎新增** **`navigate`** **步骤类型**（[ocr\_engine.py](ocr_engine.py)）：`{"type":"navigate","target":"家族活动"}` —— `run_navigate()` 从注册表取进入链，复用 retry\_loop 语义：每轮 do=「顶层 mark\_text 探测点击」+「nav 导航链」；任一带 mark 的 `click_text` 真实命中即本轮成功并把 `self._scene` 切到 target 场景；未命中 `close_dialog()` 脱困、最多 `max_rounds` 轮（默认3，注册表可配）；target 缺失打印跳过、不抛错。

- **保留旧** **`retry_loop`** **不删**（向后兼容，已验证流程零改动）；三处进入链为**增量迁移**。

- **自测**（临时脚本打桩 locate/click\_text/close\_dialog，跑完即删）：四场景全过——A 顶层直接命中(脱困0次, scene切换)；B 全 miss→脱困 max\_rounds 次→放弃；C target 缺失→跳过不脱困；D 顶层看不到目标→走 nav 逐层(社交→家族→家族活动)点击后 mark 命中(scene=家族活动界面)。`py_compile` 通过，`--list` 不受影响（common/ 不列为主流程）。

- **✅ 迁移①/3** **`flow_energy`**（AS OF 2026-08-30）：`flow_energy.json` 原 43 行 retry\_loop 进入链压缩为单步 `{"type":"navigate","target":"闪耀变身","max_rounds":3}`；老链（顶层闪耀变身→菜单→家园 分支 + mark 命中）与注册表「闪耀变身」nav+顶层探测语义一致。`json.load`/`py_compile` 通过，`--list` 正常。✅ **实机回归通过**（退出码0）：selftest 后 `--flow 体力任务 --loop 1`——navigate 第1轮顶层 MISS→走 nav「家园→菜单→闪耀变身」mark 命中、0 脱困、`scene=体力界面` 切换；后段 loop\_fraction 5 次速通循环 1/5\~5/5 全跑完，点击记录正确归属体力界面。

- **✅ 迁移②/3** **`flow_social`**（AS OF 2026-08-30）：`flow_social.json` 原 47 行 retry\_loop 进入链压缩为单步 `{"type":"navigate","target":"家族活动","max_rounds":3}`；老链（顶层家族活动→社交→家族 分支 + mark 命中）与注册表「家族活动」nav+顶层探测语义一致。✅ **实机回归通过**（退出码0）：`--flow 社交任务 --loop 1`——navigate 第1/2轮全 MISS 各脱困一次(点右上角关闭)、第3轮经 nav「社交→家族→家族活动」逐层命中、`scene=家族活动界面` 切换；后段 if\_fraction 0/3→浇水→store\_fraction water\_count=1→右上角关闭 全跑通（脱困/逐层导航/scene 切换均验证）。

- **✅ 迁移③/3** **`flow_claim`** **功能2** **`claim_party`**（AS OF 2026-08-30）：`flow_claim.json` 功能2（花灵派对）原 43 行 retry\_loop 进入链压缩为单步 `{"type":"navigate","target":"花灵派对","max_rounds":3}`；老链（顶层花灵派对→菜单→家园 分支 + mark 命中）与注册表「花灵派对」nav+顶层探测语义一致。功能1 `claim_online`（在线礼包）为直接文本点击、无导航层，保持原样不变。✅ **实机回归通过**（退出码0）：`--flow 领取奖励 --loop 1`——功能2 navigate 第1轮全 MISS 脱困、第2轮经 nav「菜单→花灵派对」mark 命中、`scene=花灵派对界面` 切换；后段 时长礼包入口→loop\_text 依「领取」逐档领取6次(2×3)→领完按钮消失即停→关闭面板，点击记录正确归属花灵派对界面。

- **✅ 方案A 待办① 全部完成**：`flow_energy`(闪耀变身)/`flow_social`(家族活动)/`flow_claim`(功能2 花灵派对) 三处 retry\_loop 进入链均已迁移为 `navigate` 步骤并实机回归通过。旧 `retry_loop` 保留（向后兼容），公共进入能力收敛至 `flows/common/entries.json`。

- **待办**（见中优先级）：①后续「家族活动」下多活动子界面（浇水/矿洞/闪耀/守望）统一先进家族活动界面(`navigate` 复用)，不再重进。

1. **✅ 临时脚本归档约定（AS OF 2026-08-30）**：

- **原则**：临时/一次性脚本不再留在项目根（避免 `_tmp_*.py`/`_selftest_*.py` 堆积），**创建后即备份归档**到 `dev_tools/`，按功能分类子目录命名，按需检索复用、减少重复开发开销。

- **目录约定** `dev_tools/<类别>/<描述性文件名>.py`：

  - `self_test/` —— 离线引擎自测（不连设备，打桩）。例：`test_navigate.py`（navigate 四场景回归）。

  - `calibrate/` —— 实机坐标/按钮校准（需连模拟器）。例：`cal_quick_dialog_qd.py`（速通/确定 按钮相对坐标采集）。

  - 新类别出现时按功能新增子目录，在本文档登记。

- **归档脚本均自带 sys.path 引导**（`sys.path.insert(0, str(Path(__file__).resolve().parents[2]))`），确保从项目根任意位置 `python dev_tools/...` 可运行、`import ocr_engine` 生效；用法注释写在文件头。

- **已归档**：`_selftest_nav.py`→`dev_tools/self_test/test_navigate.py`（离线自测通过）；`_tmp_cal_qd.py`→`dev_tools/calibrate/cal_quick_dialog_qd.py`。原临时脚本与 `_probe*.png` 已删除。`dev_tools/` 不在 .gitignore，作为常驻开发工具可被版本跟踪。

1. **✅ 社交任务·家族活动·「闪耀委托挑战」功能（AS OF 2026-08-30，未提交）**：

- **目标**：家族活动下「闪耀委托挑战」挑战刷分，复用方案A的 `navigate` 公共导航进入「家族活动」。

- **config 开关**：`data/config.json` 新增 `enable_shine`（默认 false）；流程内用 `if_config` 读取，false 时整段跳过。

- **每日编排挂载**：`daily.json` modules 新增 `{id:"shine", flow:"flow_shine.json", required:false, on_fail:"skip"}`，与社交模块互不影响。

- **[`flows/flow_shine.json`](flows/flow_shine.json)** 流程（`if_config enable_shine` 包裹）：

  1. `navigate target=家族活动`（复用注册表公共进入链）；
  2. `click_text("闪耀委托挑战")`（fallback \[0.2727,0.8986]）进子面板；
  3. **`loop_text("参与挑战")`**（min\_score 0.4, max\_loop 8）主循环：

     - `click_text("参与挑战")`（fallback \[0.6828,0.8181]）发起挑战（**关键规则：家族满级分≠个人满分，点「参与挑战」即可继续个人挑战**）；

     - `wait_text("我换好了")` 等服装搭配界面出现 → `click_text("推荐/推荐搭配")`（fallback \[0.0523,0.8778]）**自动填装**服装（否则无可穿服装「我换好了」提交无效）→ `click_text("我换好了")`（\[0.2664,0.9181]）提交；

     - `wait_text("确认/确定")` 等结算 → `click_text("确认/确定")`（\[0.6383,0.8583]）确认返回挑战面板；`sleep 1s`。
  4. `click_rel([0.9375,0.125])` 右上角关闭返回主界面。

- **实测状态**：✅ **整轮闭环实机回归通过**（AS OF 2026-08-30，`config.enable_shine=true` → `--flow 闪耀委托挑战 --loop 1`，退出码0）：navigate 第1轮经 nav「社交→家族→家族活动」mark 命中（0 脱困）→点「闪耀委托挑战」(349,647)→loop\_text「参与挑战」**连刷 8 整轮全通**（参与→推荐搭配自动填装→我换好了提交→等/点确认→循环），每轮 mean\_rel 均值样本正常累积（参与挑战样本8）；达 `max_loop=8` 上限后 loop\_text 自然退出→右上角关闭 (1200,90)→流程完成。**注意**：本次 8 轮是触达 max\_loop 守卫上限而停（第8轮后「参与挑战」仍存在），非按钮消失；当日委托次数未耗尽即会一直刷到上限，若需耗尽当日次数可调大 max\_loop。

- **说明**：`loop_text("参与挑战")` 天然处理"服装部件耗尽/当日挑战上限时按钮消失即停"；家族"满分"显示不影响个人继续挑战，只要有「参与挑战」即可持续刷。

1. **✅ 全局「停止当前所有流程（不关闭服务）」功能（AS OF 2026-09-03）**：

- **需求**：Web UI 提供停止按钮，点击后**立即中断当前正在进行的所有流程/编排，但服务进程保持运行**，可再点「开始一轮」继续。也可由 CLI(main.py `--loop 0`) 复用同一机制。

- **停止机制（[`ocr_engine.py`](ocr_engine.py)** **模块级）**：新增 `_STOP_EV`(threading.Event) + `request_stop()/clear_stop()/stop_requested()`；`StopRequested(BaseException)` 异常（**继承 BaseException 而非 Exception**，从而穿透 `run_module` 的 `except Exception` 容错，直达顶层）。

- **检查点**：`run_step` 入口、`wait_text/wait_text_gone` 轮询循环内各 `_check_stop()`（命中即抛 `StopRequested`）；`run_flow`/`run_daily` **入口** **`clear_stop()`**（新一轮自动复位旧请求），并用 `try/except StopRequested` 统一打印"已由停止请求中断"后正常返回（不抛异常、不退出）。

- **Web UI**：新增 `/api/stop`(POST `-> request_stop()`, 不关服务) +「使用界面」`⏹ 停止当前流程` 按钮与 onlick 提示；与已有关闭服务按钮(`_shutdown`)区分。

- **main.py**：`_on_signal`(Ctrl+C) 同时 `request_stop()`；主循环条件改 `while _RUNNING and not stop_requested()`，`--loop 0` 亦响应停止。

- **验证**：`dev_tools/self_test/test_stop.py` 离线自测通过——sleep 流程运行中 `request_stop` 在步骤边界被中断（线程正常结束、标志仍置位），`clear_stop` 后可再运行。三个文件 `py_compile` 通过。

- **说明**：中断粒度为"当前步骤执行完后、下一个步骤/等待/模块边界"（最坏等一个 `wait_text` 的 timeout 或一次长 screenshot），非线程强杀，故不会中途破坏模拟器/知识库状态。

35. **✅ 新增模板匹配通道 `click_template` + 模板标注开发工具（WebUI）（补充，AS OF 2026-09-16）**：（上接445行里程碑35 底部）
   - **引擎**（[`ocr_engine.py`](ocr_engine.py)）：`locate_template()`（多尺度 0.7~1.0、`TM_SQDIFF_NORMED`、支持 `region_rel`）+ `click_template()`。
   - **模板标注工具（WebUI）**：独立页 [`/tpltool`](tpltool.html)（入口见 [`webui.html`](webui.html) 头部「模板标注」链接）。后端 [`webui.py`](webui.py) 新增 `tpl_init`(连接+截图+模板列表) / `tpl_probe`(区域内前景颜色连通域探测候选框→回填) / `tpl_save`(按框裁模板 + 可选画笔蒙版生成 `<name>.mask.png`)；前端载图、拖动/8角调框、自由画笔蒙版、橡皮、保存。**实机端到端验证通过**（截图→探测回填→保存模板+蒙版落盘正确）。
   - **实机采集落地**：A1 `close_corner_pink`、A3 `close_online_small`、A4 `close_family`、**B1 切换账号灰色折角** `b1_switch_down.png`（36×21px，箭头 bbox x975~1007·y279~296；`click_template` 实测登录界命中中心 abs(991,287)/rel(0.774,0.399)，score=1.000，已定稿）。
   - **动机**：纯图形/无文字按钮（关闭钮、切换账号灰色折角等）此前靠颜色特征/锚点偏移识别，稳定性有限；借鉴 MAA 增加**模板匹配**，增强图形识别，同时**有文字按钮仍保留 OCR**（`click_text` 不变）。
   - **引擎**（[`ocr_engine.py`](ocr_engine.py)）：`TEMPLATE_DIR = resource/template/`；`locate_template()`（**多尺度**模板缩放 0.7~1.0、`TM_SQDIFF_NORMED`（同源抠图最稳）、`score=1-sqdiff`、支持 `region_rel` 限定、返回模板中心 Point）+ `click_template()`（命中击点并记 `click_log` method=template；未命中可回退 `fallback_rel`）。
   - **步骤类型**：`{ type:"click_template", template:"xxx.png/g", threshold:0.8, region_rel:[..], scale_range:[..], fallback_rel:[..], delay:1.0 }`，支持 `mark`（嵌套在 retry_loop 内作成功标记）。
   - **采集工具**（[`dev_tools/explore/capture_template.py`](dev_tools/explore/capture_template.py)）：实机截图→相对中心±半宽高裁剪→存 `resource/template/<名称>.png`。
   - **自测**（[`dev_tools/self_test/test_template.py`](dev_tools/self_test/test_template.py)）：带噪背景合成图，多尺度命中模板中心≈(325,205)、不存在模板返回 None，通过。
   - **实现要点/坑**：① 多尺度应缩放**模板**去匹配原图（而非缩放截图）；② CCOEFF_NORMED 对近纯色/低方差模板退化，改用 SQDIFF_NORMED（同源自匹配 sqdiff=0）；③ 大片纯色背景在多尺度下可与模板背景误匹配，故真实采集模板应**尽量贴按钮本体**并配合 `region_rel` 收窄；④ Point 尺寸用 img 自身宽高（勿依赖可能为 0 的 self.screen_w/h）。
   - **接入与实机回归（✅ 完成）**：`close_buttons.json` 给 A1(通用corner)/A3(corner_pink_small)/A4(新增家族活动corner) 注册项加 `template` 字段，`_locate_close_by_entry` **模板优先**、未命中回退原颜色。`flow_claim.json` 在线礼包关闭重构为 `click_template close_online_small` 前置 + `close_dialog only_types=corner_pink_small` 兜底。实机回归：**A3 score=1.000→(1104,96)、A4 close_family score=0.946→(1245,27)；`--flow 领取奖励 --loop 1` 退出码 0**，在线礼包/花灵派对关闭均模板命中稳定生效。
   - **待办**：A2 签到白色圆关闭待下次登录签到弹窗补采；B2 删除按钮/B3 右上灰钮需多账号展开界面定位（规避用）。

#### 📥 纯图形按钮·拟采集清单（开发工具 `dev_tools/explore/capture_template.py` + `confirm_capture.py` 用，**非日程模块**）
- **A. 关闭按钮类**（程序化 `find_close_button` 定位 → 已采模板）：
  - ✅ A1 右上角花形粉色关闭｜种植面板｜**rel(0.9578,0.0458)**｜→ `close_corner_pink.png`(66×64px)
  - ⏳ A2 签到面板白色圆形关闭(corner_white)｜签到界面｜区(0.9,0~1,0.16) 采时定位｜待下次登录签到弹窗补采
  - ✅ A3 在线礼包小白色关闭块｜在线礼包界面｜**rel(0.8633,0.1347)**｜→ `close_online_small.png`(21×17px)｜**已实机验证：面板内模板 score=1.000 命中(1104,96)，`close_dialog(corner_pink_small)` 点击成功回主界面**
  - ✅ A4 家族活动右上角关闭｜家族活动面板｜**rel(0.9727,0.0361)**（原 hardcode 0.9375,0.125 已纠正）｜→ `close_family.png`｜**已实机验证：面板内模板 score=0.946 命中(1245,27)，点击关闭回主界面**
- **B. 登录/切换账号图形按钮**（登录界面固定尺寸、rel 失效 → 锚点采集）：
  - ✅ B1 切换账号灰色折角图标｜登录界面｜**rel(0.774,0.399)** 箭头中心｜→ `b1_switch_down.png`(36×21px, 已定稿+模板匹配实测命中)
  - ⏳ B2 删除账号按钮（条目右侧）｜登录界面｜仅作**规避定位**（防误触）⚠️
  - ⏳ B3 账号列表右上角灰色按钮｜登录界面｜仅作**规避定位**（防误触）⚠️
- **C. 面板功能按钮**（✅ 全部实机确认**均含文字标签→保留 OCR，无需模板**）：
  - ✅ C1 在线礼包抽奖按钮｜含"抽奖"文字｜**rel(0.6094,0.5681)**(原0.6102微调)
  - ✅ C2 花灵派对时长礼包入口｜含"时长礼包"文字｜rel(0.0531,0.4250)
  - ✅ C3 摇钱树入口卡｜含"摇钱树"文字｜rel(0.27,0.30)(树图形区)
  - ✅ C4 浇水按钮｜含"浇水"文字｜rel(0.845,0.685)(摇钱树子界面)
- 备注1：在线礼包/花灵派对「点击任意处关闭」(0.5,0.9375) 为文字提示保留 OCR，不采。
- 备注2：**模板匹配仅适用于纯图形按钮**（A组关闭钮、B组折角图标）；凡含文字标签的按钮一律保留 OCR 定位，采集结论与"有文字保留文字"原则一致。

36. **✅ tpltool 2.0 人机协同标注重构 + 三项 UI 修复 + 好友采粉模板标注（AS OF 2026-09-17）**：
   - **定位转变**：工具只产出**坐标标注 JSON**（`data/tplt_annotations.jsonl`），不直接保存模板；框选=缩小范围、画笔=重点提示层（不改像素）、描边=有序闭合点列供生成 mask。
   - **重构内容**：独立页 `/tpltool`（[`tpltool.html`](tpltool.html)）+ 后端 [`webui.py`](webui.py) 新增 `/api/tplt_init`(复用主界面全局单例 `get_engine()` 截图, 未连接返回503) / `/api/tplt_load` / `/api/tplt_submit`(追加 jsonl)；旧 `tpl_init/tpl_probe/tpl_save` 已删除。
   - **标记交互**：框选+画笔+描边可同标记内叠加后点「保存标记」进本地列表；列表可改 id/备注（备注 bug 已修：`card.onclick` 加 `if(ev.target.closest('input,button')) return` 守卫，输入不再被重建列表打断）、删除、复制 id、选中高亮。
   - **观察能力**：缩放 0.1~64（滚轮/±/重置），最高放大到可见单像素；**笔刷像素级**可调 `min=1 max=16`（默认2）；**裁剪功能**：`裁剪` 模式拖矩形确认 → 画面缩到裁剪区、已存标注整体平移、`offsetX/offsetY` 累计偏移，提交时绝对坐标加回偏移、相对坐标按原图完整尺寸 `fullW/fullH` 计算；新截图(`showShot`)自动把裁剪平移坐标加回并复位完整画面。
   - **好友采粉模板标注（进行中）**：用户已提交标注 `ann_1_63180`（1 rect + 25点 contour，可采粉图标）。`workbench/contour_to_tpl.py` 生成模板 `workbench/template/ann_1_63180.png` + mask + 复核图 `debug/contour_ann_1_63180.png`。**复核结论：黄线轮廓仍未完整包住图标顶部花簇（贴合约40~45%，顶部偏左内缩/花簇顶点遗漏）** → 待用户用改进后的工具（裁剪+单像素缩放+描边轮廓）重描 contour 后再次生成。
   - **开发规则**：本次起所有未经确认的新开发内容暂存 `workbench/`，确认后再并入主体（见顶部「开发流程约束」）。

37. **✅ 好友采粉可采粉图标轮廓重描 + tpltool 生成连续轮廓闭环（AS OF 2026-09-17）**：
   - **连续轮廓重描**：用户改用裁剪+单像素缩放+「描边轮廓」模式提交闭合轮廓 `ann_1_30541`（48点，约25×23px，原图 rel(0.76,0.66~0.695)）。`workbench/contour_to_tpl.py` 生成模板 `workbench/template/ann_1_30541.png` + mask + 复核图 `debug/contour_ann_1_30541.png`。**复核：贴合约70~75%（较上次40%明显更好），仍三处可完善——顶部花簇右侧削顶、右下角向内折返路径、顶部直线段偏锯齿**。
   - **新增「生成轮廓」闭环**（工具功能，非主体流程）：
     - 后端 [`webui.py`](webui.py) 新增 `/api/tplt_contour`（POST）：复用 `get_engine()` 截图，在指定矩形(绝对像素)内均值漂移+OTSU+形态闭合找最大外轮廓，`approxPolyDP` 简化后返回有序闭合点列。
     - 前端 [`tpltool.html`](tpltool.html)：header 加「生成轮廓」按钮 → 基于当前 `working.rect`(+offset 转绝对) 请求后端 → 回填 `working.contour`(画面坐标) 显示黄线底稿 → 用户仍可「描边轮廓」重画覆盖微调 → 保存/提交。
     - 界面交互闭环：框选 → 生成连续轮廓 → 微调 → 保存 → 提交。
   - **🔴 复核图空白根因（重要）**：`contour_to_tpl.py` 用固定旧源图 `debug/friend_friend_list.png`(0:08) 裁剪，其 y≈474~502 是"念菱世殇(无图标)"行；而用户标注时该行是"悠清水(绿色图标)" → **同一坐标不同画面，裁剪必然空白/错位**。tpltool 提交只存坐标、未存当时截图，源图与标注画面无法对齐。
   - **✅ 方案A：提交自动存截图（已实现）**：tpltool「提交」时前端把**原始完整截图**（jpeg dataURL）随 payload 附带，后端 [`webui.py`](webui.py) `_tplt_submit` 解码保存到 `data/annot_shots/{annotation_id}.png` 并把相对路径写入 jsonl 的 `shot` 字段 → 坐标与画面严格绑定，后续模板/复核均用该截图，不再错位。
   - **核心设计理念（重要，后续贯彻）**：**tpltool 的核心产物始终是坐标标注**；**捕捉/采集脚本在真实截图上完成模板截取**。捕捉脚本**本身要有原生识别能力**（OCR/颜色/模板三通道），同时能**借助 tpltool 提供的人工确认坐标做强化**——即把"人工框选的正确位置"当作监督样本反馈给捕捉脚本/知识库，类似大模型的监督微调(SFT)：识别正确→强化当前特征分；识别错误→依据人工标注纠正阈值/锚点/特征，逐步逼近精确。tpltool 定位角色是"强化学习的标注接口"，不是去取代捕捉脚本的自动识别。
   - **开发工具沉淀（按新规则）**：新增 `dev_tools/explore/overlay_annotation.py`，把 jsonl 标注的矩形/轮廓叠加到任一源图生成整幅复核图(用法 `overlay_annotation.py [annotation_id] [src]`)。

### 🚧 进行中 / 待确认（实机作业校准）

- **种植模块作业未真正执行**：每日编排里对"一键种植/种植箱"MISS（8s 超时）→ 未进花田 → 浇水/施肥/授粉/收花循环全部空转。编排框架 OK，实机作业动作需校准。

- **离线诊断为有效线索**：`after_home.png` 上 OCR 把「种植箱一键种植」识别为**单一合并块**（box \[930,672,1078,698]，宽 148>90，score 0.82）；`ocr_find` 用严格方式能命中。**MISS 根因疑似与** **`find_text()`** **中"过宽块放大重识别"（宽>90 触发）有关**，需下个会话重点排查（见待办 🔴-1）。

### 🐛 本次会话发现的问题（待修复）

- **（记录，非重点）体力任务右上角误点**：某次测试开局停留在「世界聊天」界面时，清弹窗阶段 `corner` 右上角关闭逻辑连点 (1252,9)/(1245,26)/(1226,33) 5 次（该处为世界聊天入口小圆点），把画面带到世界聊天导致后续找不到「闪耀变身」、循环=0 提前结束。但**未能稳定复现**（另一次开局在齐他界面时全程干净），判断依赖开局画面状态，暂不作为重点任务，仅记录备查。corner 区域见 close\_buttons.json。

- **流程名关键字歧义**：`--flow 种植` 命中先载入的「进入种植界面」(enter\_garden.json) 而非「种植任务」(flow\_plant.json)。`main.py/ocr_engine.main` 用 `key in name` 取第一个，名称重合会选错流程 → 需改"精确名优先"匹配。

- **过期回退坐标**：enter\_garden.json 里「一键种植」回退缓存 (0.7508,0.9514)=(961,685)，已被新采集 (0.784,0.950)=(1004,684) 取代 → 应更新 click\_log / 流程 fallback\_rel。

- **旧流程与测试残留**：`flows/` 混有 `enter_garden/enter_home/login_verify/test_close.json` 与 `diag.py`、`validate_daily.py`、`debug/` 截图，与新的 `flow_*.json` 并存且会干扰 `--flow` 关键字匹配。

### ✅ GitHub 已同步（2026-08-22）

- 仓库：`https://github.com/zjz1/FlowerAutoAssistant`（Public）

- 已推送白名单：`main.py`、`ocr_engine.py`、`ocr_ui.py`、`requirements.txt`、`PROGRESS.md`、`flows/*.json`、`data/click_log.json`、`.gitignore`

- 因规避个人信息/IP风险，仓库级 `.gitignore` 排除了：`.venv/`、`debug/`（游戏截图）、`legacy/`（Unity 解包脚本）、`resource/`（旧模板/素材图）、`__pycache__/`

### 📤 提交 GitHub 方法（知识库 / MAA 工作流）

> 在本目录（`FlowerAutoAssistant/`）用 PowerShell 执行。所有命令不会改动全局/本地 git 配置。

1. **扫描是否含敏感信息**（提交前必做）：

   - 🔴 **2026-09-18 复核：脱敏曾失守，已重写历史清除**（详见本章末尾「2026-09-18 敏感数据清除记录」）：`data/config.json` 与 `data/click_log.json` **都是受版本控制的文件**，且 `HEAD=0e61c34`（= `origin/main`）中曾含**真实账号尾号 / `enable_switch` 为开 / 浇水计数**，以及 2 条**以真实账号文本为键**的知识库条目 → 该内容**曾推送到公开仓库**；`webui.html` 还硬编码了账号下拉框。
   - **处置结论（用户明确授权）**：采用 **方案②——重写全部历史 + force push 彻底清除**；同时**取消跟踪 `data/config.json`**（改为 `.gitignore` + 提供 `data/config.example.json` 模板），并修掉泄露源头（`webui.html` 硬编码账号下拉框 → 文本框、`ocr_engine.py` 写库键名不再含真实账号文本）。记录与验证证据见本章末尾。
   - 检查 `data/config.json` 是否内置了真实账号数据（如 `target_tail` 应为空 `""` 或由用户自行填写，不内置真实账号尾号）。

   - 检查 `data/click_log.json` 是否有账号类条目（键名或内容含 `195`/`186`/手机号模式/账号 `****` 尾号）。如发现，先脱敏（置空/删除该条目）再提交。

   - 检查是否混入临时/调试产物：`git status` 应只见真正要提交的文件；`data/click_debug/`、`_probe*.png`、`_tmp_*.py` 已被 `.gitignore` 排除。

2. **查看待提交状态**：

   ```powershell
   git status               # 看改动文件
   git diff data/config.json   # 逐一核对 config 差异, 确认无账号
   git log --oneline -3     # 看历史 commit 风格
   git branch -vv           # 确认分支与远程领先/落后
   ```

3. **暂存 + 提交**（身份用 `-c` 内联临时指定，与历史一致 `zjz1 <zjz1@users.noreply.github.com>`；本仓库未落盘全局/本地 user.name/email，直接 `git commit` 会报 `Author identity unknown`）：

   ```powershell
   git add PROGRESS.md webui.py webui.html start_webui.bat data/config.json data/click_log.json
   git -c user.name="zjz1" -c user.email="zjz1@users.noreply.github.com" commit -m "feat: <一句话主题>

   <（可选）详细说明, 分点列出改动, 用空行分隔正文>"
   ```

   - 出现 `LF will be replaced by CRLF` 仅是换行符提示，无害，可忽略。

   - 提交失败时先停下排查：报 `Author identity unknown` 就补上面的 `-c`。

4. **推送**：

   ```powershell
   git push origin main
   ```

   - 推送成功尾部见               `  <旧hash>..<新hash>  main -> main`。

   - 若报 `Recv failure: Connection was reset`（多为临时网络/代理抖动）：提交已在本地（不丢），稍后重跑 `git push origin main` 即可。

   - **绝不** **`git push --force`**，不 `--force-with-lease`，不直接改 `git config`。

5. **验证**：

   ```powershell
   git status              # 工作树干净
   git log --oneline -1    # 最新 commit
   git branch -vv          # main 应显示 up to date
   ```

   - 仓库不纳入版本管理的文件：`.venv/`、`debug/`、`legacy/`、`resource/`、`__pycache__/`（已在 `.gitignore`）。

> ⚠️ 注意：`data/config.json` 的 `target_tail`、`data/click_log.json` 属坐标/配置数据，提交前严格筛查账号类信息；不能确定时先脱敏或暂不提交（讨论后再定）。

***

## 3. 关键按钮相对坐标（来自 click\_log / OCR 采集）

> 相对坐标 = 绝对坐标 ÷ 屏尺寸。屏幕尺寸变化时，`相对×新尺寸` 仍定位正确。

### 家园 / 世界界面

| 按钮       | 绝对          | 相对             |
| -------- | ----------- | -------------- |
| 家园(底部导航) | (1116, 684) | (0.872, 0.950) |
| 种植箱一键种植  | (1004, 684) | (0.784, 0.950) |
| 快捷操作     | (886, 684)  | (0.692, 0.950) |
| 离开       | (1117, 686) | (0.873, 0.953) |
| 园艺店      | (216, 59)   | (0.169, 0.082) |
| 菜单       | (69, 58)    | (0.054, 0.081) |
| 社交(底部导航) | (424, 683)  | (0.331, 0.949) |
| 在线礼包     | (1058, 157) | (0.827, 0.218) |
| 世界(底部导航) | (505, 679)  | (0.398, 0.943) |
| 勇气国花园    | (68, 688)   | (0.053, 0.956) |

### 种植操作界面（点「一键种植」后进入）

| 按钮     | 绝对          | 相对             |
| ------ | ----------- | -------------- |
| 种植(左栏) | (87, 165)   | (0.068, 0.229) |
| 照料(左栏) | (90, 255)   | (0.070, 0.354) |
| 授粉(左栏) | (90, 342)   | (0.070, 0.475) |
| 浇水(右栏) | (1233, 127) | (0.963, 0.176) |
| 施肥(右栏) | (1233, 212) | (0.963, 0.294) |
| 收花(右栏) | (1233, 297) | (0.963, 0.413) |
| 清理(右栏) | (1231, 382) | (0.962, 0.531) |
| 开花(右栏) | (1233, 466) | (0.963, 0.647) |
| 造型种植   | (843, 633)  | (0.658, 0.879) |
| 随机种植   | (1054, 633) | (0.823, 0.879) |

### 无文字图形按钮（颜色特征识别）

- **关闭按钮有"特殊逻辑"注册表**（[data/close\_buttons.json](data/close_buttons.json)），目前**四种**：①「提示」锚点右侧（弹窗式）；②整体画面右上角（种植面板式，region\_rel=\[0.93,0,1.0,0.1]）；③右上角白色圆形（签到面板 `corner_white`）；④在线礼包右上角粉色小圆（`corner_pink_small`）。每条已标注 `scene`/`category`。找关闭按钮时遍历注册表，可后续扩展。

- 原 `corner` 区域 \[0.82,0,1.0,0.18] 过宽会扫到中间偏右的其它粉色图标（如 (1100,89) 处误报、被循环连点），已收窄至 \[0.93,0,1.0,0.1] 消除误报。真实关闭按钮约 (0.973,0.036)。

- 原有"关闭"条目：右上角粉色四瓣花形，绝对 (1245,26)，相对 (0.973, 0.036)。颜色 `hsv_lower=[150,100,100], hsv_upper=[175,255,255], area 100~1000`（该坐标属旧采集，注册表 `corner` 逻辑为当前优先）。

***

## 4. 待办任务（按优先级）

### 🔴 高优先级（下一步）

- [ ] **修复「一键种植」MISS 根因**：排查 `find_text()` 的"过宽块放大重识别"逻辑（宽>90 触发）对合并块「种植箱一键种植」的处理。离线证据：`after_home.png` 上该块 score0.82、`ocr_find`严格能命中，但补点后仍 MISS。可临时把 90 阈值调大 / 关闭合并块重识别 / 改用 exact 匹配验证。

- [ ] **修正流程名匹配歧义**：`main.py` 与 `ocr_engine.main` 用 `key in name` 取第一个，`--flow 种植` 误选「进入种植界面」。改为"先精确名匹配，再关键字子串匹配"。

- [ ] **更新过期回退坐标**：click\_log 与 flow 里「一键种植」回退 (0.7508)→(0.784)；同步旧流程 enter\_garden.json。

- [x] **清理干扰文件**：`flows/` 已确认仅剩 `daily.json`+`flow_*.json`（enter\_garden/enter\_home/login\_verify/test\_close 早前已删）；根目录 `diag.py`/`validate_daily.py`/`debug/` 已不存在；本次删除根目录残留临时调试截图 `debug_menu_frame.png`、`debug_now.png`。`git status` 工作树干净。

- [ ] 校准后重跑 `main.py --flow 每日` 验证种植作业真实执行（浇水/施肥/收花）。

### 🟠 中优先级

- [ ] **优化「切换账号」按钮识别 + 减少误触右上角灰色按钮与删除账号按钮**（`flow_startup.json` 可选切换账号，见里程碑1）：
  - **① 切换账号按钮识别优化**：该钮为"灰色向下折角、无文字"，当前靠锚点偏移 + HSV 颜色特征定位（[`locate_anchor_color()`](ocr_engine.py) + 账号文本 `****` 锚点 +351px）。需优化其识别稳定性（颜色阈值/锚点偏移的容差、region 收窄防干扰块），减少脱敏/截断账号块导致的定位偏移。

  - **② 减少误触右上角灰色按钮**：点击「切换账号」展开账号列表后，列表/界面右上角可能存在灰色功能按钮（关闭列表/账号管理类）；`click_rel`/`click_text` 定位偏右时可能误触。建议在点击前或展开后用 `region_rel` 明确避开右上角区域，或对这类"无文字灰色按钮"做专项规避。

  - **③ 减少误触「删除账号」按钮**：`click_account_tail` 目前 `region_rel=[0.45,0.35,0.58,0.56]` 圈定账号列表，但①账号条目可能被 OCR 成"账号文本 + 删除按钮"的合并块，`best["center"]` 点整块中心会落在删除钮上；②region 若偏大致带进右侧删除列。建议：账号块匹配时排除含"删除/删"字样块、点击点取账号文本左侧/中部而非整块中心、并把 region 进一步收窄避让删除列与右上角。**（误触删除有账号风险，需谨慎处理）**

- [x] **闪耀委托挑战·完整整轮实机回归**（原 `flow_shine.json` → **已并入 `flow_social.json`**，见里程碑33）：📌 **2026-09-18 更新**：独立 `flow_shine.json` 与 `daily.json` 的 `shine` 模块已**移除**，整段并入 [`flow_social.json`](flows/flow_social.json) 的 `if_config enable_shine` 块，命令改为 `--flow 社交任务`（此前为 `--flow 闪耀委托挑战`，该流程名已不存在）。✅ 2026-08-30 实测 `config.enable_shine=true` + `--flow 闪耀委托挑战 --loop 1` 退出码0——navigate 进家族活动→闪耀委托挑战→loop\_text「参与挑战」连刷 **8 轮全通**（参与→推荐搭配→我换好了→确认→循环），达 max\_loop=8 上限后自然退出→右上角关闭。测试后已恢复 enable\_shine=false。⚠️ 注意 8 轮为 max\_loop 守卫上限而非按钮消失，若需耗尽当日次数可调大 max\_loop。

- [ ] **实机验证 retry\_loop 其余 2 处**（里程碑 26/里程碑28 记录；功能1、功能2 已验证）：逐一跑 `--flow` 复核 `${mark}` 目标命中 / 脱困重试 / 后段逻辑。
  - [x] **领取奖励·功能1 claim\_online**（`flow_claim.json` 功能1，本轮新增 retry\_loop）：`--flow 领取奖励` 实机跑通——retry\_loop 第1轮命中「在线礼包」(1058,155)→抽奖耗尽 N:3→2→1→时间礼包领取 50分钟档(cur (0.166,0.692))→关面板 corner\_pink\_small(1105,97)。✅ 2026-08-23

  - [x] **领取奖励·功能2 claim\_party**：`--flow 领取奖励` 实机跑通（合一后回归）——retry\_loop 家园(1115,684)→菜单(68,58)→`花灵派对`(237,542) mark命中；`if_text('时长礼包')` MISS→兜底(67,306)；`loop_text('领取')` 连续领 **6 个**(352,337/639,338/926,338/351,600/639,600/926,600)，每项→恭喜获得→关闭，全部领完按钮消失→关面板 corner\_pink\_small(1108,80)。✅ 2026-08-23（验证时 config.claim\_online 已置 true 实机测试）

  - [x] **体力·闪耀变身**（`flow_energy.json`）目标=「闪耀变身」(mark)，导航=菜单/家园，后段 loop\_fraction 速通循环。`--flow 体力` 实机跑通——从随机页面起跑，retry\_loop 第3轮命中「闪耀变身」(134,449) mark（前2轮菜单弹窗内无该钮，脱困后回到能见左侧快捷栏画面）；loop\_fraction 读数 a=570/600→1、a=47/100→2、取 min=1；once 光偶像(65,390)→速通(1046,643)→确定(636,464)→结算确认(817,618)。✅ 2026-08-24

  - [x] **社交·家族活动/摇钱树浇水**（`flow_social.json`）目标=「家族活动」(mark)，导航=社交/家族(嵌套)，后段摇钱树浇水（含 10 分钟冷却 + store\_fraction 计次）。`--flow 社交` 实机跑通——从体力任务残留画面起跑，前2轮全 MISS 脱困 close 回主界面，第3轮 社交(423,683)→家族(422,595)→家族活动(98,329) mark 命中→进入；if\_fraction 读「0/3」a\<b TRUE→浇水(1085,495)→关奖励(640,676)→store\_fraction water\_count=1→右上关闭(1200,90)。✅ 2026-08-24

- [ ] **每日礼包（在线礼包）进入方式重构**（2026-08-24 实机确认）：每日礼包**已领取时主界面不显示「在线礼包」按钮**，现行 `flow_claim` 功能1 retry\_loop 对此盲跳——3 轮「在线礼包」MISS 后仍脱困连点 close(corner/corner\_white/corner\_pink\_small)，既白白点改知识库，又把画面带离主界面，累及后续功能2（连「菜单」都 MISS）。现行逻辑"够用"，**暂不改动**；重构思路：入口不可见 → 判定"今日已领完" → 直接跳过该功能，不脱困、不点 close。

- [x] **✅ 方案②：点击位置"立体化分级 + 均值 + 偏差复核"加固定位**（2026-08-27 已实现，见里程碑 30）：按钮按定位方式分级（`method`: ocr/color 整体相对坐标 / anchor 锚点-像素偏移 / fallback），`_log_click` 仅对 ocr/color 命中按场景累积位置样本求运行均值（`mean_rel`+`sample_n`，anchor/fallback 不混入）；`click_text` OCR 命中与该场景均值偏差 > `BIAS_MAX_PX=60px` 判为可疑 → 二次精细处理（局部放大 2x 重识别校准子块）；OCR 全 miss 回退时优先**均值点补齐**。

- [ ] `main.py` 主程序入口：参数化（adb 地址、流程选择、循环次数/无限）、日志、状态反馈

- [ ] 循环机制：流程结束后自动回到起点反复执行至手动停止

- [ ] 界面状态感知：识别当前所处界面（家园/种植/登录），决定下一动作

### 🟢 低优先级 / 后续扩展

- [ ] 更多任务：施肥、领奖、社交、收花批量（跨模块动作深度联动）

- [ ] 颜色特征按钮扩展：如登录页"点击进入游戏"等无/弱文字元素

- [x] ~~安装 git 做正式版本控制~~（已同步 GitHub，见第 2 节）

- [ ] README.md 完善（补模块化编排说明）

***

## 5. 关键文件清单

| 文件                        | 作用                                                                                                                                               |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `ocr_ui.py`               | RapidOCR 单例：`ocr_image` / `ocr_find`（文字→块，含 center/score）                                                                                        |
| `ocr_engine.py`           | 核心引擎：连接/截图/OCR定位/颜色定位/点击/相对坐标/知识库回退/界面采集/关闭按钮遍历/区域文本判断/流程执行（CLI: `--flow`, `--collect`, `--list`, `--close-test`, `--add-close`, `--ocr-screen`） |
| `data/click_log.json`     | **按钮知识库**（version2 两层嵌套 `scenes: {场景: {按钮: {记录, category}}}`）：按钮名→相对/绝对坐标、识别方式(ocr/color/fallback)、类别与场景分组（自动积累，兼容旧扁平格式加载）                       |
| `data/close_buttons.json` | **关闭按钮-特殊逻辑注册表**：`corner`/`anchor_color`/`corner_white`/`corner_pink_small` 关闭按钮定位逻辑（带 scene/category），可扩展                                       |
| `flows/*.json`            | 数据驱动流程定义。**步骤类型全集**（[`ocr_engine.py`](ocr_engine.py) `run_step`）：`wait_text` / `click_text` / `click_template` / `click_account_tail` / `click_rel` / `sleep` / `close_dialog` / `if_text` / `if_fraction` / `if_greater` / `if_config` / `count_text` / `store_fraction` / `loop_text` / `loop_fraction` / `loop_times` / `retry_loop` / `navigate`（共 18 种；`wait_text_gone()` 仅为引擎方法，暂无同名步骤类型）                  |
| `flows/daily.json`        | **编排**：按序调度 **8 大模块**（startup→signin→plant→social→energy→daily→claim→idle）。📌 2026-09-18 现状：**8 个模块全部 `required:false` + `on_fail:skip`**（单模块失败只跳过、不终止整轮）；原独立 `shine` 模块已并入 `social`。                                       |
| `flows/flow_*.json`       | 各模块流程：startup(开始启动, 含可选切换账号) / signin / plant / social(**含闪耀委托挑战**) / energy / daily\_task / claim / idle。⚠️ `flow_party.json`、`flow_shine.json` 均已删除（分别并入 `flow_claim` 功能2、`flow_social`） |
| `flows/common/entries.json` | **公共导航注册表**：`navigate` 步骤引用，已登记 3 个 target —— 家族活动 / 闪耀变身 / 花灵派对（各含 scene / mark\_text / mark\_fallback\_rel / max\_rounds / nav 链）。`common/` 子目录不被 `load_flows()` 扫入主流程 |
| `webui.py` + `webui.html` + `tpltool.html` | 本地 WebUI（`http.server`，无第三方依赖）：使用/测试双界面、实时画面+OCR 标注、知识库场景树、模块 ⚙ 设置、停止当前流程(不关服务)、关闭服务；`/tpltool` 人机协同标注页（只产坐标标注） |
| `data/tplt_annotations.jsonl` + `data/annot_shots/` | tpltool 标注产物：jsonl 追加写坐标标注；方案A —— 提交时前端附带原始截图，后端存 `annot_shots/{annotation_id}.png` 并把路径写入 `shot` 字段，保证坐标与画面严格绑定 |
| `resource/template/*.png` | **模板匹配**模板（`click_template` 用，`TEMPLATE_DIR`）：close\_corner\_pink / close\_online\_small / close\_family / b1\_switch\_down 等。⚠️ 已被 `.gitignore` 排除，不入版本控制 |
| `workbench/`              | **未确认功能的暂存区**（当前：好友采粉捕捉脚本 + 模板 + tpltool 设计稿）。用户确认后才并入主体 |
| `legacy/`                 | 已弃用的旧 MAA 模板路线 & Unity 解包脚本**备份**（不参与运行）                                                                                                         |
| `.gitignore`（项目根）         | 已忽略 `.venv/`、`debug/`、`legacy/`、`__pycache__/` 等                                                                                                 |
| ✅ `flows/` 已清理            | 仅剩 `daily.json`+`flow_*.json`，无旧流程残留（enter\_garden\~test\_close 等已删，diag.py/validate\_daily.py/debug/ 已不存在，根目录临时调试截图已清）                          |

### 运行环境（务必用 venv）

- 系统 `python`(3.13) 无依赖 → **必须用** **`.\.venv\Scripts\python.exe`**。

- 实机模拟器：`127.0.0.1:16384`，adb=`D:\Program Files\Netease\MuMu\nx_main\adb.exe`。

- 常用命令（`cwd`=FlowerAutoAssistant/）：`.\.venv\Scripts\python.exe main.py --flow 每日 --loop 1`（单轮）`/ --list`（列流程）/ `--collect`（采集界面写知识库，在 ocr\_engine.py）。

***

## 6. 技术要点 / 避坑记录

- **MaaFw 是全新 API**（`maa` 包），非老版 `maa-core`。新版用 `Spawn → Future → tasker = Asst(role=App)`，连接、截图通过 `tasker.controller` / Toolkit。

- **关 OCREngine 单例**：`OCR_ENGINE` 实例全局复用，避免多进程反复加载模型（每次新进程 still 触发权限，应尽量同一进程内循环）。

- **相对坐标是核心**：所有定位最终转归一化相对坐标，屏幕尺寸变化不失效。

- **颜色识别**用于无文字图形按钮（如关闭）：HSV 过滤 + 连通区域取最大连通块。

- **点击即记录**：`click_text` 成功后自动 `_log_click` 写回 click\_log，知识库随使用增长。

- **合并文字块 <-> find\_text 冲突**：OCR 常把相邻按钮合并成一个块（如「种植箱一键种植」宽 148>90），`find_text()` 会触发"过宽块放大 2x 重识别"，可能反而丢命中 → 这是「一键种植」MISS 的疑似根因，改造后务必回归测试。

- **OCR 合并「菜单/奇妙花宝」⚠️（2026-08-23 已查根因）**：记录帧 `debug_menu_frame.png` 在任意参数下本就能分开两块；实时帧偶发合并是因**半透明按钮背后的背景变化**导致检测框粘为一个宽块，而 `ocr_find` 用**子串匹配**(`"菜单" in "菜单奇妙花宝"`)+**点整块中心** → 误点邻钮。**第 1 层修复已落地**：`ocr_ui.get_engine()` 单例初始化改为 `det_use_dilation=False` + `det_thresh=0.2`+`det_box_thresh=0.3`+`det_unclip_ratio=1.4`，从检测源减少膨胀粘连（传 `det_*` 参数时该库强制读 `det_model_path`，须显式传 `None` 沿用默认模型路径）。**第 2 层待实机验证**：若仍粘连，`click_text` 对"过宽合并块"按横轴分段分别重识别、取真正含关键字的子段点击，而非点整块中心。勿用"字符在块内占比"估算位置（不可靠）。

- **`--flow`** **名称匹配歧义**：`key in name` 取第一个会选错同名流程 → 应"精确名优先，子串次之"。

- **运行依赖在 venv**：系统 python 无 numpy/maa → 一律用 `.\.venv\Scripts\python.exe`（其他终端也一样）。

- **PowerShell 重定向会破坏二进制 PNG**：`exec-out screencap` 输出必须用 Python `subprocess` 捕获原始字节，勿用 `>` 或管道。

- ~~MAA 模板匹配路线已废弃~~：原 4 个模板（quick\_ops/plant\_box/one\_click/map）与 `daily.json` 属旧方案，不再使用（备份在 legacy）。

---
## 2026-09-17 · 好友采粉-捕捉脚本三通道（workbench 暂存）
- **(恢复)好友采粉捕捉脚本** `workbench/capture_friend_pollin.py`：三通道①颜色(HSV 绿圈, 实测 HSV≈(47,82,170), x≈985)②模板(MAA 多尺度 `TM_CCOEFF_NORMED`+mask)③OCR(一键采粉/快捷操作)。含 SFT 监督比对接口(`load_gt_rect` 读 jsonl 人工 rect→命中率)。
- **实测结论**：纯颜色通道在粉紫 UI 上不可靠(图标白芯使绿成"环"、圆度<0.45 枚举卡掉；背景海滩绿噪)，已降为回退通道；**主打模板通道**。
- **MAA 匹配实测退化 inf**：当前模板 `friend_pollin.png` 是旧源误裁(尺寸 37×37 掩膜有效区过小→CCOEFF 除零 inf)，**必须用方案A新提交的绑定截图重裁模板**才能验证算法。
- **WebUI 8765 曾堆 4 个旧实例**导致方案A(shot 落盘)不生效；已清掉全部 PID 统一以当前 `webui.py` 单实例重启(PID 41792)。方案A现在会 `data/annot_shots/{annotation_id}.png` 落盘。
- **tpltool 画笔 UX 修**：画笔由"散点"改为**连续半透明红色粗描边**(线宽=brushR 图元px、随缩放放大、圆头圆角、远距自动断笔)；`addPtTo` 采样间距阈值放宽(1.0/brushR*0.4)；描边轮廓拖动实时细绿线。F5 生效。
- **MAA 模板通道验证通过**：修复 `maa_match()` NMS 的 `all()`空真 bug → 改用 `any()` 并过滤非有限(inf/nan)分数；用方案A绑定截图 `data/annot_shots/ann_1_44654.png` 生成的**干净模板/mask(30×28)** 复跑，检出 **3 个绿色可采粉图标**(score 0.92~1.0，abs(987,196)/abs(987,293)/abs(987,488))，叠加图 `debug/pollin_detect.png` 确认无漏检无误检(无敌莉莉丝/ノ姒淡洳夢/伊一) → **验证通过可并入 `flow_social.json`**。
- **tpltool 画笔"大像素"根因+修复（第3轮）**：根因是在高分屏(Windows显示缩放>100%, devicePixelRatio>1)下画布背板未乘 DPR，浏览器把整幅位图(含半透明矢量笔触)+`image-rendering:pixelated` 就近放大成"几个大方块像素"。修复：`applyZoom` 背板尺寸乘 `DPR`、绘制 `setTransform(scale*DPR,...)`、`brushPoly` 每顶点补画等径圆点保证圆头笔触、笔径仍按截图分辨率归一化 `brushIm()=round(brushR*fullH/720)`；删除死代码 `dot()`。node --check 通过。用户 Ctrl+F5 硬刷后试画验证。
- **待办(进行中)**：用户 Ctrl+F5 后按方案A 用新画笔重描校验(可采粉/进家园/一键采粉键) → 若可采粉图标定位达标识可并 `flow_social.json` → 再并 WebUI 子面板。勿忘挂账项:种植"一键种植/种植箱"MISS、在线礼包 A2 关闭钮补采。

---
## 2026-09-18 · 交接接手（TraeCode）— 基线核对 + 文档-代码对齐 + 环境验证

### A. 交接物与工作区
- 交接物：`FlowerAutoAssistant_handoff.zip`(69 文件) + [`HANDOFF.md`](HANDOFF.md)；权威原目录 `E:\my_project\trae project\6a87d545e1df38ada361ca1c\FlowerAutoAssistant`（另含 .venv / data / resource / debug / legacy）。
- **核对结果**：新工作区 28 个关键文件（引擎/前端/流程/数据/workbench）与**原目录工作树逐文件 SHA256 完全一致** → 交接包已包含当前**全部未提交改动**，基线无漂移。
- 新工作区（本轮产出地）：`E:\my_project\trae project\FAA_2026-9-18\FlowerAutoAssistant\` = 解压 69 文件 + 只读复制 `resource/template/`(16) + `debug/friend_friend_list.png`。原目录保持**只读**。注：`6a87d545...\_stage_faa\` 是原目录的重复副本（5 个核心文件哈希相同），可忽略/删除。

### B. 环境验证（用原项目 venv，从新工作区执行）
- `python -m py_compile ocr_engine.py ocr_ui.py webui.py main.py` → exit 0。
- `main.py --list` → 正确列出 **9 个流程**，且路径解析到新工作区（脚本 `BASE = parents[1]` 自动跟随，**无需改代码**）。
- 实机链路：`dev_tools/explore/snap.py` 连接 `127.0.0.1:16384` 成功，截图 720×1280 落盘 `debug/_ws_env_check.png`(351KB，有效)。MaaCore 会打印一条 `settings get secure android_id` 的 `[ERR]`，属既有无害噪声。

### C. 离线复核「好友采粉模板通道」结论 —— ✅ 复现一致
用方案A绑定截图 `data/annot_shots/ann_1_44654.png` + `workbench/template/friend_pollin.png`(28×30)+mask 跑 `maa_match()`：命中 **3 个绿色可采粉图标**，score **1.000 / 0.965 / 0.919**，abs(987,196)/(987,488)/(987,293)——与 HANDOFF §3 记录一致，无漏检无误检。对照组：同画面纯颜色通道 `detect_pollen_green()` 只出 1 个 (986,491) → 再次印证"颜色不可靠、模板为主"。（纯内存复算，未改脚本、未覆盖 `debug/pollin_detect.png`）

### D. ⚠️ 交接期发现「文档落后于代码」5 处（已在本文件就地对齐）
1. **`flow_shine.json` 已删除**，整段并入 [`flow_social.json`](flows/flow_social.json) 的 `if_config enable_shine` 块，`daily.json` 的 `shine` 模块同步移除 → 命令由 `--flow 闪耀委托挑战` 改为 `--flow 社交任务`（里程碑33 与 §4 待办已加注）。
2. [`flows/daily.json`](flows/daily.json) 现为 **8 模块且全部 `required:false` + `on_fail:skip`**（原文档记"核心模块 stop_round"）→ 单模块失败只跳过、不终止整轮。
3. §5 文件清单补全：`flows/*.json` **步骤类型全集 18 种**、`flows/common/entries.json`、`webui.*`/`tpltool.html`、`data/tplt_annotations.jsonl`+`annot_shots/`、`resource/template/`、`workbench/`。
4. 🔴 **脱敏曾失守 → 已按用户授权重写历史清除**：`data/config.json` 与 `data/click_log.json` **都受版本控制**，`0e61c34`(= `origin/main`) 中曾含真实账号尾号 / `enable_switch` 为开 / 浇水计数，以及 2 条以真实账号文本为键的知识库条目 → **曾推送到公开仓库**。2026-09-18 已用 `git filter-repo` 重写全部历史 + `push --force-with-lease`，并取消跟踪 `data/config.json`、修正泄露源头。详见 §2 末尾「2026-09-18 敏感数据清除记录」。
5. 本轮纳入基线的未提交改动：`PROGRESS.md`、`flows/daily.json`、`flows/flow_social.json`、**删除** `flows/flow_shine.json`、`tpltool.html`(+560 行)、`webui.html`(+120 行)、`webui.py`(+233 行)。

### E. 交接期约定
见本文件顶部「🔖 接手声明」：数据分叉（交接期勿从原目录跑自动化/WebUI，8765 单实例）、回写方式（用户拷贝或授权后合并，交付附 SHA256 清单）、不改对方正在写的文件。

### F. 本轮待办
- [x] **同步文档 + 固化未提交改动**（本节 + 顶部声明 + README 刷新）
- [ ] **好友采粉并入** `flow_social.json` + WebUI 子面板 —— 前置：用户 Ctrl+F5 后用新画笔重描「可采粉图标」→ 校准达标（模板/mask + 离线在绑定截图上验证命中）后并入
- [ ] 🔴-1 「一键种植/种植箱」MISS 根因排查（`find_text()` 过宽块逻辑）；🔴-2 签到面板 A2 白色圆关闭钮补采
- [ ] 交接期遗留（沿用旧待办）：流程名匹配"精确优先"、`click_log` 过期回退坐标更新

