# FlowerAutoAssistant (FAA) 项目进度与任务

> **用法（重要）**：这是项目的"活文档"。**每次运行/开始新任务前，先读本文件**了解当前状态与未完成任务；每次里程碑完成后更新它并勾选任务。保持本文件为当前真实进度的唯一权威来源。

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

## 2. 当前进度（AS OF 2026-08-22）

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

37. **✅ 好友采粉可采粉图标轮廓重描 + tpltool 生成连续轮廓闭环（AS OF 2026-09-17）**
   - **连续轮廓重描**：用户改用裁剪+单像素缩放+「描边轮廓」模式提交闭合轮廓 `ann_1_30541`（48点，约25×23px，原图 rel(0.76,0.66~0.695)）。`workbench/contour_to_tpl.py` 生成模板 `workbench/template/ann_1_30541.png` + mask + 复核图 `debug/contour_ann_1_30541.png`。**复核：贴合约70~75%（较上次40%明显更好），仍三处可完善——顶部花簇右侧削顶、右下角向内折返路径、顶部直线段偏锯齿**。
   - **新增「生成轮廓」闭环**（工具功能，非主体流程）：
     - 后端 [`webui.py`](webui.py) 新增 `/api/tplt_contour`（POST）：复用 `get_engine()` 截图，在指定矩形(绝对像素)内均值漂移+OTSU+形态闭合找最大外轮廓，`approxPolyDP` 简化后返回有序闭合点列。
     - 前端 [`tpltool.html`](tpltool.html)：header 加「生成轮廓」按钮 → 基于当前 `working.rect`(+offset 转绝对) 请求后端 → 回填 `working.contour`(画面坐标) 显示黄线底稿 → 用户仍可「描边轮廓」重画覆盖微调 → 保存/提交。
     - 界面交互闭环：框选 → 生成连续轮廓 → 微调 → 保存 → 提交。
   - **🔴 复核图空白根因（重要）**：`contour_to_tpl.py` 用固定旧源图 `debug/friend_friend_list.png`(0:08) 裁剪，其 y≈474~502 是"念菱世殇(无图标)"行；而用户标注时该行是"悠清水(绿色图标)" → **同一坐标不同画面，裁剪必然空白/错位**。tpltool 提交只存坐标、未存当时截图，源图与标注画面无法对齐。
   - **✅ 方案A：提交自动存截图（已实现）**：tpltool「提交」时前端把**原始完整截图**（jpeg dataURL）随 payload 附带，后端 [`webui.py`](webui.py) `_tplt_submit` 解码保存到 `data/annot_shots/{annotation_id}.png` 并把相对路径写入 jsonl 的 `shot` 字段 → 坐标与画面严格绑定，后续模板/复核均用该截图，不再错位。
   - **核心设计理念（重要，后续贯彻）**：**tpltool 的核心产物始终是坐标标注**；**捕捉/采集脚本在真实截图上完成模板截取**。捕捉脚本**本身要有原生识别能力**（OCR/颜色/模板三通道），同时能**借助 tpltool 提供的人工确认坐标做强化**——即把"人工框选的正确位置"当作监督样本反馈给捕捉脚本/知识库，类似大模型的监督微调(SFT)：识别正确→强化当前特征分；识别错误→依据人工标注纠正阈值/锚点/特征，逐步逼近精确。tpltool 定位角色是"强化学习的标注接口"，不是去取代捕捉脚本的自动识别。
   - **开发工具沉淀（按新规则）**：新增 `dev_tools/explore/overlay_annotation.py`，把 jsonl 标注的矩形/轮廓叠加到任一源图生成整幅复核图(用法 `overlay_annotation.py [annotation_id] [src]`)。

38. **✅ 新增全项目「文字版流程手册」docs/FLOWS.md（AS OF 2026-09-19）**：
   - 新建 [`docs/FLOWS.md`](docs/FLOWS.md)，把全部模块/功能的**文字版流程**一次性沉淀为本地权威文档。
   - 覆盖：全局编排(daily)、开始启动/登录+可选切号、签到、种植/花田、社交(家族浇水+闪耀委托挑战+好友采粉完整闭环)、体力、每日任务、领取奖励(在线礼包+花灵派对)、挂机、公共导航系统(navigate+entries.json)、识别与关闭按钮兜底机制；并含引擎步骤类型全集。
   - **重要约定（写入文档开头）**：今后项目**新增任何功能，必须在本文档对应模块下追加一条文字版流程**，与代码、PROGRESS.md、JSON 任务链同步更新。`FLOWS.md` 记各功能文字版流程，`PROGRESS.md` 记进度/决策/踩坑，双文档同步维护。

39. **✅ 并入接管版（FAA_2026-9-18）开发内容：好友采粉功能 + 全套代码改动（AS OF 2026-09-21，合并前备份于 `_backup_premerge_20260921.zip`）**：
   - **新增**：`pollin.py`（好友采粉闭环）、`resource/template/friend_pollin.png`、`resource/template/friend_page_jump.png`、`data/config.example.json`、`dev_tools/review/weekly_review.ps1`、客户端 `data/annot_shots/`（ann_1_44994/15768）及各 `workbench/` 采粉调试脚本。
   - **修改**：`flows/flow_social.json`（新增 `enable_pollin` 采粉段 + 浇水改 OCR 点「摇钱树/浇水」）、`flows/common/entries.json`（家族导航 exact/region 优化）、`ocr_engine.py`（新增 `friend_pollin` 步骤 + OCR 合并块纠偏 `_narrow_merged` + 采粉误命中硬阈值 `BIAS_HARD_PX` + 账号条目标记脱敏）、`webui.py`（`enable_pollin` 配置 + POST 白名单 `_POST_ROUTES` 安全修复）、`webui.html`（社交子面板「好友采粉」开关 `mp-social-pollin`）、`ocr_ui.py`/`tpltool.html`/`README.md`/`.gitignore`/`HANDOFF.md` 及 `dev_tools/`、`workbench/` 若干脚本。
   - **验证**：两版 `data/config.json` 运行态按用户确认保留——`enable_pollin=true`、`enable_shine=true`、`enable_switch=true`、`target_tail="61"`；`ocr_engine.py`/`pollin.py`/`webui.py`/`ocr_ui.py` 编译通过；新增模板落位于 `resource/template/`；flow_social 引用 `friend_pollin`、ocr_engine 引用 `run_friend_pollin`、webui 含 `enable_pollin`+`_POST_ROUTES` 均一致；WebUI「好友采粉」开关已挂接。
   - **实机全流程验证**（AS OF 2026-09-22，模拟器实机）：startup(登录成功，切号 tail=61 未命中账号条目但登录成功)→signin(签到成功，`BIAS_HARD_PX` 生效弃用 200px 偏差)→plant→social(浇水 if_fraction 未识别跳过、闪耀无「参与挑战」直接退出、好友采粉**端到端成功**：模板命中 0.994 进园→快捷操作→静默采粉成功，逐页扫描/连续失败跳页/ensure_home 兜底均工作)。发现**采粉过慢**，待办优化（见里程碑 40）。

40. **✅ 好友采粉提速优化：多命中模板匹配一次扫描 + 缩短固定等待（AS OF 2026-09-22）**：
   - **问题**：`pollin.scan_marks` 逐带(y 步进 0.03，约 30 次)调用 `locate_template`，而引擎每次做 4 尺度全图 matchTemplate → 一次扫描=120 次全图匹配；好友 30 页 × 每页一次，极慢。且多处固定 sleep 偏大。
   - **改动**：① `ocr_engine.py` 新增 `locate_template_all()`（一次匹配返回全部过阈值局部峰值，跨尺度 NMS 去重，返回 `list[Point]`，region/scale 语义同 locate_template）；② `pollin.py` `scan_marks` 改用 `locate_template_all` 一次取全（保留 y 聚类去重）；③ 缩短固定 sleep：wait_until 轮询 1.5→1.0、back 后 2.5→1.5、切页签 2.5→1.5、关对话框 2.5→1.5、跳页输入 4/2/2→2.5/1.5/1.5、采集收尾 1.5/2.0→1.0/1.5。
   - **验证**：`dev_tools/self_test/test_scan_marks.py` 离线对比新旧逻辑（用真实好友列表截图 `debug/friend_friend_list.png`）——**结果完全一致** `[(987,99),(987,196),(987,391)]`，耗时 **7.53s→0.25s（提速 29.6x）**；`test_template.py` 引擎回归通过；`pollin.py`/`ocr_engine.py` 编译通过。

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

- [x] **修正流程名匹配歧义**（**已修** — 2026-10-01 复核）：`select_flow`（[`ocr_engine.py`](ocr_engine.py#L1820-L1833)）现为“先精确名匹配（`name == key`），再关键字子串匹配”，`--flow 种植` 不再误选「进入种植界面」。`main.py` 与 `ocr_engine.main` 共用该函数。原 2026-09-23「仍未修」结论已过期。

- [ ] **修复「一键种植」MISS 根因**（影响面已收窄）：排查 `find_text()` 的"过宽块放大重识别"逻辑（宽>90 触发）对合并块「种植箱一键种植」的处理。离线证据：`after_home.png` 上该块 score0.82、`ocr_find`严格能命中，但补点后仍 MISS。可临时把 90 阈值调大 / 关闭合并块重识别 / 改用 exact 匹配验证。**注**：当前 [`flow_plant.json`](flows/flow_plant.json) 只点「家园」，一键种植已不在编排路径上，该 bug 只影响手动单跑，可与「花田作业」开发一起处理。

- [x] **更新过期回退坐标**（2026-09-23 核对完成）：全项目已无 `0.7508`；`data/click_log.json` 已是 (0.784, …)；旧流程 `enter_garden.json` 早已删除，无需同步。

- [x] **清理干扰文件**：`flows/` 已确认仅剩 `daily.json`+`flow_*.json`（enter\_garden/enter\_home/login\_verify/test\_close 早前已删）；根目录 `diag.py`/`validate_daily.py`/`debug/` 已不存在；本次删除根目录残留临时调试截图 `debug_menu_frame.png`、`debug_now.png`。`git status` 工作树干净。

- [ ] **种植花田作业（浇水/施肥/授粉/收花）待开发**：`flow_plant.json` 现仅"点家园"，[`docs/FLOWS.md`](docs/FLOWS.md) §3 已记为待开发。原「校准后重跑 `main.py --flow 每日` 验证种植作业真实执行（浇水/施肥/收花）」与实况不符（编排中无该作业），已按此更正。

### 🟠 中优先级

- [ ] **优化「切换账号」按钮识别 + 减少误触右上角灰色按钮与删除账号按钮**（`flow_startup.json` 可选切换账号，见里程碑1）：
  - **① 切换账号按钮识别优化**：该钮为"灰色向下折角、无文字"，当前靠锚点偏移 + HSV 颜色特征定位（[`locate_anchor_color()`](ocr_engine.py) + 账号文本 `****` 锚点 +351px）。需优化其识别稳定性（颜色阈值/锚点偏移的容差、region 收窄防干扰块），减少脱敏/截断账号块导致的定位偏移。

  - **② 减少误触右上角灰色按钮**：点击「切换账号」展开账号列表后，列表/界面右上角可能存在灰色功能按钮（关闭列表/账号管理类）；`click_rel`/`click_text` 定位偏右时可能误触。建议在点击前或展开后用 `region_rel` 明确避开右上角区域，或对这类"无文字灰色按钮"做专项规避。

  - **③ 减少误触「删除账号」按钮**：`click_account_tail` 目前 `region_rel=[0.45,0.35,0.58,0.56]` 圈定账号列表，但①账号条目可能被 OCR 成"账号文本 + 删除按钮"的合并块，`best["center"]` 点整块中心会落在删除钮上；②region 若偏大致带进右侧删除列。建议：账号块匹配时排除含"删除/删"字样块、点击点取账号文本左侧/中部而非整块中心、并把 region 进一步收窄避让删除列与右上角。**（误触删除有账号风险，需谨慎处理）**

- [x] **闪耀委托挑战·完整整轮实机回归**（原 `flow_shine.json`，里程碑33）：✅ 2026-08-30 实测 `config.enable_shine=true` + `--flow 闪耀委托挑战 --loop 1` 退出码0——navigate 进家族活动→闪耀委托挑战→loop\_text「参与挑战」连刷 **8 轮全通**（参与→推荐搭配→我换好了→确认→循环），达 max\_loop=8 上限后自然退出→右上角关闭。测试后已恢复 enable\_shine=false。⚠️ 注意 8 轮为 max\_loop 守卫上限而非按钮消失，若需耗尽当日次数可调大 max\_loop。**归属变更（里程碑44）**：`flow_shine.json` 已删除，该功能并入 [`flows/flow_social.json`](flows/flow_social.json) §4.1.2，复现命令改为 `--flow 社交`。

- [x] **实机验证 retry\_loop 其余 2 处**（里程碑 26/里程碑28 记录；功能1、功能2 已验证）：逐一跑 `--flow` 复核 `${mark}` 目标命中 / 脱困重试 / 后段逻辑。**2026-09-23 复核：4/4 全部实机通过，本项关闭。**
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
| `flows/*.json`            | 数据驱动流程定义（`type: wait_text/click_text/click_rel/sleep/close_dialog/if_text/if_fraction/loop_fraction/loop_times`）                                 |
| `flows/daily.json`        | **编排**：按序调度 8 大模块（**startup→signin→plant→social→energy→daily→claim→idle**，2026-09-23 按文件实况校正），全部 `required:false`+`on_fail:skip`（单模块失败只跳过，不终止整轮）                                           |
| `flows/flow_*.json`       | 各模块流程：startup/signin/plant/**energy**/daily\_task/social/idle/claim。**已废止**：`flow_shine.json`（里程碑44 删除，闪耀委托挑战并入 `flow_social.json` §4.1.2）、`flow_party.json`（早前合一进 `flow_claim.json` 功能2）                                                                        |
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

- **`--flow`** **名称匹配歧义**（**已修**，见 §4）：`select_flow` 已改为“精确名优先（`name == key`），子串次之”（`ocr_engine.py` L1820）。

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
## 2026-09-22 · 好友采粉实机校验 + 复核污染修复（里程碑 41）
- **if_time 时间窗口（补录上会话实现）**：`ocr_engine.py` 新增 `if_time` 步骤类型（1376-1388 行，按本地小时判断窗口，支持跨天）；`flows/flow_social.json` 闪耀委托挑战段外包 `if_time {from:10,to:21}`。**实机验证（3 时）**：不在 [10,21] → 闪耀段整体跳过，不影响其它模块。
- **🔴 复核场景污染根因（本会话最核心 bug）**：好友"岁岁"花园内完成家族活动后，close_family 关面板但 `_scene` 仍为「家族活动界面」；该场景 `scenes["家族活动界面"]["离开"]` 被误录到左上角 rel [0.2071,0.1778]（2026-09-22 01:31 录得），`_entry_for("离开")` 取到该条目，把正确 OCR 命中 (1115,686)（rel 0.871,0.953）判为**误命中** → 回退点 (265,128) 错位 → ensure_home 死循环卡 75s。
  - **修复①（数据清理）**：删除 click_log.json 中 `scenes["家族活动界面"]["离开"]` 误录条目。
  - **修复②（代码加固）**：`pollin.py:leave_garden` 主路径改为**底部栏区域限定**直接定位「离开」（region [0.70,0.88,1.0,1.0]）并 `click_abs`，不依赖场景缓存复核；`click_text` 仅作兜底。
- **`家族` mean_rel 污染重置**：`scenes["家族活动界面"]["家族"]` 均值被 4 个坏样本污染为 [0.1176,0.2785]（曾致复核偏差 479px）→ 重置为 rel 本身 [0.3297,0.825]（sample_n 1）。
- **pollin.py 三处修复（全部实机验证通过）**：
  ① **进园「点-等-重试」**（`collect_one` 376-412 行）：模拟器输入延迟/积压可达数十秒，单次点击常被吞（实测多次 75s 超时）→ 改为 3 次循环「点→wait_until 45s→2s 宽限→复查」，点后若仍在列表视为点击被吞继续重试；未进园未在列表则存诊断图 `debug/_enter_garden_fail.png` 并退出由外层重开列表。
  ② **离开底部栏定位**（`leave_garden` 171-189 行）：见上「修复②」。
  ③ **假标记槽位跳过**（`run_category` 484-518 行）：进园失败/无粉的行 `failed.add(target[2])` 本页不再重采只继续看其它标记，避免整页被跳过丢真实标记；删除死变量 `retried`。
- **假标记根因确认**：绿花模板 `friend_pollin.png` 会**误匹配绿色家园图标本身**（绿色圆底+白色房屋图案，score 0.994，出现在每页底部槽位如 (987,585)）；点其偏移坐标 (965,615) 无效。实机：假标记一次 fail 后直接翻页，不再整页二次重试。
- **系统邮件对话框阻塞处理**：第二轮跑时弹出「花香垂钓返还结算」邮件（未读邮件通知），ensure_home 无法识别（back 关不掉整屏）→ `dev_tools/explore/probe_close_mail.py` 白色连通块定位：右上角 X (1030,67) 关详情、(1128,81) 关列表。
- **端到端验证结果**：`编排结束: ok=1 skip=0 fail=0`；好友采粉**采到 4 次**（第7页1个+第8页3个），密友 0；假标记快速跳过；翻页全流程（跳转对话框+数字键盘）正常；if_time 3 时→闪耀跳过。收尾瑕疵：模拟器停在好友列表（`回自己家园 -> False`），下次运行 ensure_home 自动处理，不影响 ok 结果。

## 2026-09-22 · 停用返回键 + 项目清理（里程碑 42）
- **停用返回键**：小花仙里 Android 返回键无效（整屏面板关不掉，实测邮件对话框/家族面板 back 均无效）。
  - `pollin.py`：`ensure_home` 两处 `eng.back()` 兜底改为 `click_top_right_close()`（新增辅助：右上角关闭区依次试 close_family/close_corner_pink/close_online_small/close_signin 模板，未命中则点区域中心）。
  - `webui.py` + `webui.html`：手动「返回键」按钮及 `/api/back` 路由、_POST_ROUTES 白名单、`_back()` 方法全部删除。
  - 保留 `dev_tools`/`workbench` 调试脚本内的 back（仅调试非主干）。
- **项目清理（用户确认范围：归档 workbench、清理 data/click_debug、清理 debug 临时截图与日志）**：
  - `workbench/` → 归档副本到 `dev_tools/explore/pollin_workbench/`（含 template/ 子目录，内部相对路径失效不影响，作历史存档；原 workbench 目录按用户决定保留）。
  - `data/click_debug/`：42 个 test 模式点击存图全部删除（引擎运行时按需重建）。
  - `debug/`：删除 96 个临时截图/日志（含 _probe*/_repro*/_nav*/_a4*/icon_*/contour_* 调试图），**保留 `friend_friend_list.png`**（test_scan_marks/capture_friend_pollin/overlay_annotation 引用）。
  - 注：`debug/maafw.log` 被运行中 MaaFw 进程占用无法删除，引擎释放后可再删。
- **备份与缓存整理（里程碑 43）**：
  - **备份归档到备份区**（上级 git 根目录，与既有备份同区）：`FlowerAutoAssistant_templates.zip` → `e:\my_project\trae project\6a87d545e1df38ada361ca1c\`。备份区现含 3 个稳定可恢复版本：`_backup_premerge_20260921.zip`（合并前全量）、`FlowerAutoAssistant_handoff.zip`（接手版）、`FlowerAutoAssistant_templates.zip`（模板资源集）。
  - **清理 `__pycache__`**（字节码缓存，可自动重建）：主目录 `FlowerAutoAssistant/__pycache__`、`workbench/__pycache__`、`dev_tools/explore/pollin_workbench/__pycache__` 全部删除。
  - **保留 `.venv/`**：虚拟环境内部 `__pycache__` 及依赖为运行必需，不清理。
  - 说明：本次清理仅涉及备份与缓存，`__pycache__` 删除后 Python 运行时自动重建，不影响运行。

## 2026-09-22 · 社交结构重构 + 领取奖励 7.3 奇妙花宝（里程碑 44）
- **社交任务结构重构**（flow_social.json + FLOWS.md 同步，用户给定三级结构）：
  - 4.1 家族活动：4.1.1 摇钱树浇水（已实现）/ 4.1.2 闪耀委托挑战（enable_shine + if_time 10-21点）/ 4.1.3 矿洞探险礼包（占位 enable_mine=false）/ 4.1.4 守望兔子（占位 enable_rabbit=false）。
  - 4.2 好友采粉（enable_pollin，friend_pollin 闭环）。
  - 4.3 社区点赞（占位 enable_like=false）。
  - 占位实现：`if_config(key, value=false)` + 空流程，config 未定义该 key 时走 else 空分支跳过，不报错不空转；`_note` 字段作纯注释供阅读，引擎不读取。
  - 矿洞/守望/社区开关**未**加入 config.json 与 WebUI（用户决定：后续开发时再处理）。
- **引擎新增 `if_color_count` 步骤类型**（7.3 需要）：按 HSV 颜色统计连通域个数，与阈值比较（默认 `n<threshold`）决定 then/else；配套新增 `count_color()` 工具方法（HSV 过滤 + connectedComponents 统计，返回个数而非最大块中心）。
- **领取奖励 7.3 奇妙花宝（claim_hb 开关，初步开发）**（flow_claim.json）：
  - 点「家园」→ 点「奇妙花宝」→ 点「奇妙特权」→ `if_color_count` 统计已领取绿色勾号数，`<3` 则 `loop_text('领', max_loop=8)` 点领并 `if_text('恭喜获得')` 关闭弹窗，满 3 个跳过 → close_dialog。
  - ⚠ **待实机校准**：绿色勾号 HSV 阈值当前用通用绿 [35,40,40]-[85,255,255]，需定标；「奇妙花宝/奇妙特权」入口坐标与底部「领」按钮文字是否稳定待验。
  - FLOWS.md 已加 7.3 节及步骤类型说明。
- 编译校验：flow_claim.json / flow_social.json JSON 合法，ocr_engine.py 语法 OK 且 OCREngine 可导入，count_color 方法存在。
- **新增 `docs/DEV_PROMPT.md`**（继续开发提示词）：含开工口令（指定必读文件顺序）、JSON 任务链核心原则、最新功能结构、硬性约束/踩坑清单、PowerShell+venv 常用命令、交付规范。下次交给 AI 继续开发时复述其中的「交给 AI 的口令」整段即可。

## 2026-09-23 · 文档同步整理（里程碑 45）

> 本轮为**只读核对 + 文档同步**（用户选定范围），**未改任何代码/flow/数据坐标**；仅改 `PROGRESS.md`、`HANDOFF.md`、`data/config.json` / `data/config.example.json` 的注释文本。

- **核对方法**：逐项对比文档声明与文件实况（flows/data/目录树、git HEAD 与工作区差异、`config.json` 开关值）。
- **已同步（本轮改动）**：
  1. **§4 待办校正**：「更新过期回退坐标 (0.7508→0.784)」→ 勾选（全项目已无 `0.7508`，click_log 已是 0.784，旧流程 `enter_garden.json` 早已删除）；「修正 `--flow` 名称匹配歧义」标注为**当前唯一确认未修的代码缺陷**（`select_flow` 仍 `key in name`）；「一键种植 MISS」标注**影响面收窄**（`flow_plant` 现仅点家园）；「实机验证 retry_loop」标为 **4/4 全通过、关闭**；原「重跑 --flow 每日 验证种植作业」与实况不符 → 改为「种植花田作业待开发」。
  2. **§5 文件清单校正**：`daily.json` 模块顺序改为**文件实况** `startup→signin→plant→social→energy→daily→claim→idle`（原写 energy 在 social 前，且漏记全部 `required:false`）；`flow_shine.json` / `flow_party.json` 标注**已废止**及归属（并入 `flow_social` §4.1.2 / `flow_claim` 功能2）。
  3. **`config.json` / `config.example.json` 注释**：`enable_shine` 说明由「流程 flow_shine.json 内用 if_config 读取」改为「flow_social.json §4.1.2 内读取（原 flow_shine.json 已于里程碑44 并入并删除）」。
  4. **`HANDOFF.md`**：顶部标注为 **2026-09-19 历史快照、已被 `docs/DEV_PROMPT.md` 取代**（开工以 PROGRESS + DEV_PROMPT 为准）；§6 / §9 各加一行 **2026-09-23 状态更新**（哪些挂账项仍开放、哪些已解决）。
- **核对结论：与文档一致、无需改动**：`docs/FLOWS.md` §0 编排顺序与 §4.1.2 归属、`README.md` 模块表顺序、`docs/DEV_PROMPT.md` 功能结构——均已与代码一致。
- **⚠️ 本轮发现、未处理（留给后续决策）**：
  1. **git 未提交**：HEAD 停在 `0e61c34`（2026-09-19），里程碑 41–44 的全部改动未 commit（`docs/`、`pollin.py`、`workbench/`、`dev_tools/*` 仍 untracked）。
  2. **`data/config.json` 已被 git 跟踪且在 HEAD 中**，其 `target_tail: "61"` 已随历史 push 到 GitHub；`.gitignore` 后补的 `data/config.json` 规则对**已跟踪文件无效**（与第 2 节"不得内置真实账号尾号"自相矛盾）。
  3. **`enable_shine` 当前为 `true`**，与里程碑33"测试后已恢复 false"不符；`enable_switch` 亦为 `true`。
  4. **备份区路径失效**：里程碑43 称备份已归档到 `e:\my_project\trae project\6a87d545e1df38ada361ca1c\`，该目录**现不存在**；3 个备份 zip（含 181MB `_backup_premerge_20260921.zip`）现留在 `FAA_basis\` 根。
  5. **目录冗余**：`FAA_basis\_stage_faa\`（2026-09-17 整项目旧副本）、失效 `_compare.py`（指向两个已不存在的路径）、`workbench/` 与 `dev_tools/explore/pollin_workbench/` 内容重复、3 处 `__pycache__`、`data/` 混放标注截图与证据图、`config/maa_option.json` 与 `resource/template/` 3 个 GBK 乱码名文件属旧 MAA 路线残留。

## 2026-09-23 · 7.3 奇妙花宝实机验证 + 采集优先级规则（里程碑 46）

- **采集优先级规则确立（用户提出并确认有效，已写入 `docs/DEV_PROMPT.md` 硬性约束）**：实机验证/采集一律**先执行功能代码**（`main.py --flow <模块>`；只看某段时用 `if_config` 开关隔离其它段），由引擎日志定位失败/卡住的**那一步**；**仅当功能代码确实无法执行**时才对该步做定向采集（截图 + `--ocr-screen` + HSV）。禁止一上来就逐层手动点击采集——本例一次运行即暴露入口文字不存在，而人工采集需先逛一遍界面才可能发现。
- **验证过程**：① 临时置 `config.claim_hb=true` 跑 `main.py --flow 领取奖励`（7.1 通过 → 7.2 自旋 → 手动停止）；② 改用隔离法（`claim_online=false`/`claim_party=false` 只留 `claim_hb`）重跑，日志见 `workbench/hb_run1.log` / `hb_run2.log`。
- **7.3 实机结果（真实失败点）**：
  1. `click_text['家园']` → OCR MISS，走缓存回退 (0.8711,0.95)，点击成功；
  2. `click_text['奇妙花宝']` → **MISS**（当前家园/世界画面无此文字）；
  3. `click_text['奇妙特权']` → **MISS**；
  4. `if_color_count` 绿色块数=**2** < 3 → TRUE —— **未进入任何面板时就已返回 2**，证明「通用绿 HSV + 全图统计」无区分度；
  5. `loop_text['领']` 在**残留的花灵派对面板**上命中 (339,337) 并触发「恭喜获得」→ 证明入口失败后流程**不中止、继续在错误界面误点**（`click_text` fail 只打日志）。
  → 结论：7.3 的入口假设「家园→奇妙花宝→奇妙特权」与实况不符，**须先采集真实入口**；勾号计数须加区域限定 + 实测 HSV 定标。
- **新发现共性缺陷（同时影响 7.2 / 7.3）**：**场景均值复核把真实命中判为误命中**。`领`/`领取` 属「多按钮同名文本」，场景均值（往往仅 1 个样本）不构成有效锚点。日志原文：`[复核] 领 OCR命中(627,338) 与场景均值(0.265,0.468) 偏差289px > 60px … 超硬阈值 180px … 判为误命中` → 弃用后走缓存回退反复点同一坐标 (338,337)；7.2 因此连续 5+ 次空点自旋。**待修方向**：同名多按钮文本跳过场景均值复核，或改用 `region_rel` 限定定位（需给 `click_text` 步骤补 `region_rel` 支持——引擎已有 `locate(region_rel)`）。
- **⚠️ 知识库污染（已清理，2026-09-23）**：两轮运行以 `scene=未分类` 写入 7 条记录（在线礼包 / 弹窗关闭 / 家园 / 菜单 / 花灵派对 / close_online_small.png / 领）。清理动作：① 删除本轮新建的垃圾条目「领」（来自错误界面误点，会成为误导性回退锚点 → 未分类 30→29 条）；② 按写入公式 `mean_new=(mean_old*n_old+rel)/(n_old+1)` **反解复原**被均值累积拉偏的 5 条（家园 均值0.8716→0.8715/样本5→4；菜单 0.081→0.0811/7→6；在线礼包 0.8264→0.8263/5→4；花灵派对 0.7525→0.7524/7→6；弹窗关闭 均值(0.9136,0.0989)→(0.9119,0.0979)/46→41）；③ 还原 `close_online_small.png` 被 fallback 覆盖的 rel → [0.8633,0.1347]。JSON 校验通过。
- **新增工具**：`workbench/probe_hb.py`（分步探针：`--click rX,rY` 点击后 dump OCR+框体、`--hsv` 绿色连通域采样、`--crop x1,y1,x2,y2[,scale]` 局部放大）；本轮配置改动：`data/config.json` 增加 `claim_hb`（测完已回落 **false**），`data/config.example.json` 同步补 `claim_hb: false`。
- **下一步**：① 采集「奇妙花宝」真实入口（等用户给入口线索后验证）；② 修同名多按钮文本框的复核误杀；③ 定标绿色勾号 HSV + 区域；④ 入口跑通后回写 flow_claim + 开关 + WebUI 子面板 + FLOWS.md。

## 2026-09-26 · 7.3 入口定位 + 点击链路验证（里程碑 47）

- **点击功能确认有效（用户提出"是否点击无效"的疑问，已用本体代码证伪）**：单次 `click_text['家园']` 后**场景完全不变**（仍在古灵仙地，NPC 聊天文字在变→画面是活的）；**同一坐标连点第 2 次即生效**进入家园。→ 印证「点击会被吞、必须点-等-重试」，**禁止用单次点击判死活**。验证方式：本体 `run_steps([{type:click_text}])` + 关键字监视（`workbench/probe_hb.py --text 家园 --retry 4 --watch 奇妙花宝,快捷操作,种植箱,离开`）。
- **入口链确认（用户提供线索 + 实机验证）**：① 先进**家园界面** → ② 界面顶部工具栏「**奇妙花宝**」**rel(0.1125,0.0819) abs(144,59)**（OCR s0.79，紧邻「菜单」(0.0523,0.0806) 右侧；同行还有 园艺店(0.1688,0.0819)/访客(0.2281,0.0819)）→ ③ 打开「奇妙花宝」界面（左上粉色飘带标题、右上**粉色 X**、左侧竖排 3 页签）→ ④ 左侧页签「**奇妙特权**」**rel(0.0961,0.5319) abs(123,383)**（带红色「!」角标→有可领）。另两页签：限时充值(0.0938,0.2139)、花神之契(0.0953,0.3736)；底部档位 1/3/6/12 个月 (0.2602/0.3547/0.4969/0.7805, 0.926)；「前往充值」(0.9164,0.8903)。
- **⚠️ 同名歧义（必须防，本轮实机亲历）**：家园界面会浮出**同名的「奇妙花宝」充值/活动面板**（左上标题同为「奇妙花宝」）。本轮该面板恰在最前时，引擎 OCR 取到的是**面板标题 (69,26)** 而非家园入口 (144,59)——复核已报「偏差82px > 60px」但仍「沿用 OCR 命中」并点击。→ **7.3 入口必须做区域限定/位置校验**（如限定顶部工具栏区 `region_rel` [0,0,1,0.12]、或要求命中 rel≈0.1125±0.02），否则弹窗遮罩下必点错。这是第 4 节待办「流程名匹配歧义」的同类实例（同名不同位置）。
- **绿色勾号形态（初步实拍）**：**绿底 + 白色对勾的圆形徽章**；「限时充值」页在底部 4 个档位节点上各 1 个（约 abs (331,587)/(444,587)/(625,587)/(994,587)）。因为画面绿植/绿色元素极多（本轮全图泛绿命中 48 个连通域、最大 1850px），**勾号计数必须 region 限定 + 按徽章底色实测 HSV 定标**——里程碑46 已证「未进面板时泛绿计数=2」，通用阈值零区分度。「奇妙特权」页内的勾号形态待采集。
- **引擎 OCR 阈值疑点**：`click_text['家园']` 报「未OCR到」走缓存回退，但**同帧**我的全图 dump 能看到「家园」s0.63；本体 `find_text` 阈值把 s0.63 判为未命中。本轮低分命中频发（世界 0.52/0.67、家园 0.63、奇妙花宝 0.77/0.79）→ **待确认阈值是否偏高**（影响所有 OCR 步骤）。
- **工具增强**：`workbench/probe_hb.py` 新增 `--text`（走本体 `run_steps` 的 click_text，与 flows 完全同一代码路径）、`--retry N`（点-等-重试）、`--watch`（关键字判定场景是否真的切换）。
- **污染清理**：本轮测试又写入 `未分类`（家园 样本+1；奇妙花宝 误点面板标题写进 (0.0539,0.0361)）→ 已复原（家园 样本8→7、均值回 [0.8715,0.9504]；奇妙花宝 回 rel/mean [0.1125,0.0819] 样本1）；JSON 校验通过。
- **7.3 文字版流程 v2（修正入口后）**：
  1. 守卫在家园：`if_text ['奇妙花宝']`（区域限定顶部工具栏）→ 不在则 `click_text ['家园']`（**外层必须 retry_loop 点-等-重试**，因点击常被吞）
  2. `click_text ['奇妙花宝']`（**区域限定 y<0.12**，避开同名面板标题）
  3. `click_text ['奇妙特权']`（左侧页签 rel≈0.0961,0.5319）
  4. `if_color_count` 勾号计数（**region 限定特权列表区 + 实测 HSV**）op `<` threshold N
     - then：`loop_text ['领取']`（exact、区域限定）→ `click_text ['领取']` → sleep → `if_text ['恭喜获得']` → 关闭
     - else：已领满，跳过
  5. `close_dialog`（**右上粉色 X**，待验证落到哪一类：corner_pink_small / template）
- **下一步**：① 点「奇妙特权」进特权页 dump 结构与勾号（仍用本体代码）；② 定标勾号 HSV + 区域；③ 修「点击被吞→重试」与「同名歧义→区域限定」；④ 回写 flow_claim + 开关 + WebUI + FLOWS.md。

## 2026-09-26 · 7.3 奇妙花宝生产代码 + 实机跑通（里程碑 48）

- **特权页结构（实机 dump，参 `debug/hb_hb_priv.png`）**：左侧竖排 3 页签「限时充值」(0.0938,0.2139)/「花神之契」(0.0961,0.375)/「奇妙特权」(0.0938,0.5306，带红「!」)；**右侧竖排「奇妙礼包」栏**（x≈0.90）三档：**每日礼包**(标签 0.9555,0.2208) / **每周礼包**(0.9523,0.4069) / **每月礼包**(0.9492,0.6139)；底部「奇妙之羽兑换」(0.8984,0.7931)、左上「剩余天数 276」；右上**粉色 X** abs(1245,25) rel(0.9731,0.0356)。
- **7.3 的真实领取对象 = 右侧「奇妙礼包」三档**（不是特权格子）。判据实拍确认：
  - **可领**：图标右上带**红色「!」角标**，下方圆形按钮为**粉色**、内含「领」。
  - **已领**：图标上覆盖**灰底绿色对勾徽章**，下方圆形按钮转**灰**。
- **绿勾定标（关键）**：勾号 = 亮春绿，实测 abs(1154,456) meanHSV=(81,168,232)、面积≈316px。**用引擎现有通用绿阈值 HSV[35,40,40]-[85,255,255] 即可命中**，但全图泛绿干扰 48 个连通域（绿植/装饰）→ **必须区域限定**。限定到单档区间后实测：每日 0 / 每周 0 / 每月 1，与画面（仅每月已领）完全一致，area_min=100 可滤掉每周礼盒的青色盒盖(area 29)。绿勾在档位图标中心，与「领」按钮圆心恒差 63px。
- **「领」按钮坐标（霍夫圆检测定标，红圈已目视套准）**：每日 abs(1159,205) rel(0.9055,0.2861)；每周 abs(1157,353) rel(0.9039,0.4903)；每月 abs(1152,519) rel(0.9000,0.7208)。**「领」字 OCR 取不到**（放大 2.5x 仍认不出，是低对比艺术字）→ 只能用 `click_rel`，旧的 `loop_text('领')` 方案不可行。
- **⚠️ 引擎 bug 已修（`ocr_engine.py` `run_step` 的 `if_color_count` 分支）**：原先把 `step["region_rel"]`（0~1 浮点）**原样**当绝对像素传给 `count_color` → `mask[y1:y2, x1:x2]` 抛 `slice indices must be integers or None or have an __index__ method`。该分支此前从未被真实使用（旧 7.3 没写 region）故一直潜伏。已在 run_step 内先转绝对坐标再传入。
- **7.3 重写（已写入 `flows/flow_claim.json` 的 claim_hb 段）**：
  1. `retry_loop(max_rounds=6, fail_do=[sleep 2.0])` 包住**整条入口链**：`if_text('奇妙特权')` 命中→`click_text('奇妙特权', mark=true)` 本轮回成退出；否则 `if_text('奇妙花宝', region_rel=[0.06,0.05,0.22,0.12])` 命中→`click_text('奇妙花宝')`，未命中→`click_text('家园')`。
     - **区域限定 [0.06,0.05,0.22,0.12] 专治同名歧义**：画面左上「奇妙花宝」面板标题 (69,27) x=0.0539 落在区域外，工具栏入口 (144,59) 在内 → 弹窗遮罩下不会再点错标题（里程碑 47 的坑）。
     - **`fail_do` 只能 sleep、绝不能 close_dialog**：否则「本轮刚点开面板→判未命中→关掉面板」形成开/关死循环，永不收敛（已推演确认）。
  2. 三档各自 `if_color_count`（区域限定 + 通用绿阈值 + area_min 100，`op="<"` `threshold=1`）→ 未领则 `click_rel` 点该档「领」→ sleep → `if_text('恭喜获得')` 则点 (0.5,0.9375)。
  3. `if_text('奇妙特权')` 命中则 `click_rel(0.9731,0.0356)` 关面板。**不用 `close_dialog(only_types=['corner'])`**：注册表里「整体画面右上角关闭」与「家族活动右上角关闭」同为 `corner` 类型，会被**各点一次**（实机日志已见双击 1246,25 + 1245,27）。
  - 场景声明：`奇妙花宝`/`家园` 点击 → scene「家园主界面」；`奇妙特权` → scene「奇妙花宝界面」。
- **实机验证结果（`main.py --flow 领取奖励`，隔离态 claim_online/claim_party=false、claim_hb=true）**：第 1 轮在家园→点「奇妙花宝」开面板（未命中，进下一轮）；第 2 轮 `奇妙特权` HIT→点击→本轮回成退出；三档 `if_color_count` 均 =1 → 全部跳过；末尾守卫命中→ `click_rel` 关面板。**流程完整跑完、无异常、画面确实退出面板回到家园**（事后续截图确认工具栏「菜单/奇妙花宝/园艺店/访客」）。
- **⚠️ 未验证分支（必须说明）**：本次实机时三档**均已领取**（红「!」消失、按钮转灰、图标全挂绿勾），所以只验证了「已领→跳过」路径。点已领档位的「领」实测弹出的是**无关闭钮的半透明奖励预览浮层**（列出小粉兔狸藻/派对豆/神叶碎片/奇妙之羽等），并非「恭喜获得」。**「未领 → 点领 → 恭喜获得 → 关闭」这一段仍待出现未领取档位时校准**。
- **知识库清理**：删 `未分类/奇妙特权`（probe 未声明 scene 写入的错位条目，值本身正确）；`家园主界面/奇妙花宝`、`奇妙花宝界面/奇妙特权`、`奇妙花宝界面/弹窗关闭` 三条为正确记录予以保留。JSON 校验通过（16 场景）。
- **新增临时工具（workbench/，未并主体）**：`scan_gift.py`（右栏放大 OCR + 逐档绿勾统计 + 坐标标注 + 霍夫圆定标）、`probe_priv.py`（本体步骤复现入口链后逐档采样）、`clean_clicklog.py`（按日期列出 click_log 条目 / `--del 场景/按钮` 删除，供污染核对）；原 `probe_hb.py` 继续用。
- **配置回落**：`data/config.json` 已复原（claim_online=true / claim_party=true / claim_hb=false）。
- **点击功能再确认（用户质询「点击是否失效」，本轮复验）**：改用**状态变更**判据（不再用「场景是否已存在」这种易假阳性的判据）——面板已开在「限时充值」页时，本体 `run_steps` 的 `click_text('奇妙特权')` **一次**命中 abs(121,382) → 右侧立即切换为特权内容（dump 新出现 专属特权/专属技能/种植特权/奇妙礼包栏 每日(0.9555,0.2194)/每周(0.9523,0.4069)/每月(0.9492,0.6139) + 剩余天数 276）；随后 `click_abs(1245,25)`（rel 0.9731,0.0356）**一次**点中右上粉色 X → 画面回到家园主界面（工具栏 菜单/奇妙花宝/访客 + 蒲公英花园 + 离开）。**结论：点击链路正常、并非失效**；历史上「点不动」是模拟器输入被吞（须点-等-重试）与知识库污染叠加造成的误判。
- **新暴露风险：`click_text` 不支持 `region_rel`**。同一文字存在两处实例时可能点错：`click_text('奇妙花宝')` 实测命中**面板标题** abs(69,26)/rel(0.0539,0.0361)（而非家园工具栏按钮 abs(144,59)/rel(0.1125,0.0819)）；引擎复核已发现偏差 82px（**< 180px 误命中阈值**）仍「沿用 OCR 命中」→ 直接点了标题，并把该错位写入 `未分类/奇妙花宝`。7.3 目前靠 `if_text` 的 `region_rel=[0.06,...]` 守卫规避（标题 x=0.0539 刚好在区域外，**余量仅 8px**）。**根治需给 `click_text` 补 `region_rel` 支持**（主体改动，须确认 + 回归旧流程）。本轮该条目已再次删除并复核。
- **WebUI 加 `claim_hb` 开关（本轮完成并实机验证）**：在 4 处同步 —— 后端读 `GET /api/config`、后端写 `POST /api/set_config`（含 `功能3奇妙花宝=开/关` 日志行）、后端⚙面板 meta `_module_settings("claim")`（第三个 switch，「功能3 · 奇妙花宝」）、前端 `webui.html` 静态面板 `mp-claim-hb` 复选框 + `MP_FIELDS.claim.check`。前端两个面板都是「按 `data-key`/`MP_FIELDS` 收集 → POST set_config」的通用逻辑，后端补 key 即自动生效。
  - 验证：`py_compile` 通过；起真实服务 `webui.py --port 8766` → `GET /api/config` 回显含 `claim_hb:false`；`POST {"claim_hb":true}` → `data/config.json` 落盘为 `true`；再 POST `false` 复原 → 落盘 `false`；测试服务已停止。
  - 同步：`docs/FLOWS.md` §7 标题文案「两个」→「三个」。
- **下一步**：① 待每日/每周礼包出现「未领取」时校准点领分支（弹窗形态、是否需要「点击任意处关闭」）；② 评估 `click_text` 补 `region_rel`（根治同名文本点错）；③ 遗留工程项（git 未提交、target_tail 入库、enable_shine=true、备份区失效、目录冗余）仍待处理。

## 2026-09-27 · WebUI「保存日志」+ 实机日志问题清单（里程碑 49）

### A. 新增功能：WebUI 保存日志（已完成并验证）
- 后端 `webui.py`：`GET /api/log_download` → `_log_download()`，导出 `_LOGS` **全量缓冲**（含页面打开前的历史，非前端 DOM 已收到的部分），加 UTF-8 BOM + 头部元信息（导出时间/总行数），`Content-Disposition: attachment; filename="faa_log_YYYYmmdd_HHMMSS.txt"`。
- 前端 `webui.html`：「运行日志」标题右侧加 `保存日志` 按钮 → `location.href = "/api/log_download"`。
- **踩坑**：`_route()` 用 `api = p[len("/api/"):]`（**整段**），所以 `/api/log/download` 会解析成 `log/download` 而 404；**必须用单段扁平名** `/api/log_download`（与 `set_config`/`run_daily` 风格一致）。
- 验证：`py_compile` 通过；起真实服务 `webui.py --port 8766` → `/api/log_download` 返回 200 + 正确 `Content-Type`/`Disposition`/`Length`（130B，0 行）+ BOM 与头部正常；`/` 页面含 `id="log-save"` 与下载 URL。服务已停。

### B. 用户实机日志（17:54:43→18:15:15，5 模块）问题清单——**仅记录，未修**
**P0 危险（盲目点击/误触）**
1. **7.3 入口失败后仍盲点三个「领」坐标**（L883-951）：retry_loop 6 轮 `奇妙特权`/区域限定 `奇妙花宝` 全 MISS，每轮只重复点「家园」缓存 (1115,684)；6 轮耗尽后**无「是否已在奇妙花宝面板」守卫**，直接在未知界面跑三档 `if_color_count` → 色块数全 0 → 判「未领」→ 连点 (1159,205)/(1156,353)/(1152,518)。末尾 `if_text('奇妙特权')` MISS 故未关面板。**本缺陷由 7.3 设计缺失引入**（面板未打开就采样+盲点），必须在三档前补面板守卫。
2. **`close_dialog` 一次连点 4 处**（L559-577 / L688-717 / L772-787）：注册表 4 条关闭项各点一次，且 corner×2 / corner_white / corner_pink_small 的模板在**非目标界面仍命中**（0.838/0.866/0.824）→ 每次脱困真的误点 3~4 处（(1227,71)(1228,66)(1228,71)(1145,84)…）。

**P1 功能失效/空转**
3. **好友采粉整段失败**（L204-551）：`[列表] 第1/2/3次: 场景未知, 先回自己家园` → `打开好友列表失败`，密友+好友两类皆失败；期间 `[主界面] 未识别场景, 点右上角关闭区` 出现 **30+ 次**，每次 `close_family score=0.860 -> (1218,132)` 反复点同一无效坐标，空转约 8 分钟；`回自己家园 -> False`，结果 `{'密友': None, '好友': None}`。根因：场景识别不了 + `close_family` 0.860 属**背景误匹配**（同分恒值）→ 点不掉 → 死循环。
4. **7.2 花灵派对 `loop_text('领取')` 自旋 8 轮**（L804-875）：画面有**两个「领取」**(639,337) 与 (926,337)，场景均值 (0.499,0.641)≈(639,461)；右侧每次 `偏差307~314px > 180px 硬阈值 → 判误命中 → 弃用` 改点缓存 (640,599)，中间每次偏差 113~131px（>60 但<180）→ 沿用命中点 (639,337) → 两位交替点，均未命中真正按钮，`if_text('恭喜获得')` 8 次全 MISS。均值亦被污染（样本19→22，mean_rel 0.6515→0.6179 持续漂移）。
5. **摇钱树浇水未执行**（L114-122）：`[if_fraction] 区域[0.888, 0.7847] 未识别到 'a/b' 数字块` → 跳过浇水。
6. **闪耀委托挑战空跑**（L181-190）：`loop_text('参与挑战') 不存在` → 一次未做即退出。

**P2 知识库污染**
7. **`弹窗关闭` 均值严重污染**：`体力界面/弹窗关闭` 样本 4→15、`家族活动界面/弹窗关闭` 样本 9→12，把 **4 个不同按钮**的坐标混进同一 key，均值被拉成无物理意义的中间值（mean_rel≈0.92,0.09）→ 后续复核会按假均值判误命中。
8. **`未分类` 分组继续被写入**（L20/26/43/60）：`切换账号`/`账号条目#1`/`登录`/`点击进入游戏`（flow_startup 步骤未声明 `scene`）——DEV_PROMPT L46 已警示的坑仍在发生。

**P3 结构性 / 噪音**
9. **`[未知步骤] None`**（L72/73/137/198/200/202/553）：根因已定位 = `flow_social.json` 的 `{ "_note": "..." }` **注释步骤没有 `type` 字段**（共 7 条，与日志出现次数吻合）。引擎对未知步骤只打印不报错。
10. **占位开关未入库**：`config[enable_mine]=None == False -> FALSE`（同 enable_rabbit / enable_like）——靠 `None == False` 恰好为假，语义脆弱。
11. **编排层吞掉失败**（L953）：`ok=5 skip=0 fail=0`，但实际 social（含采粉）与 claim_hb 均彻底失败。模块返回值不参与成败判定 → **失败被记成成功**，属最需修的结构问题（否则无人察觉已坏）。
12. **日志被访问日志淹没**：954 行中约 **700 行**是前端 `GET /api/screen` 轮询行（Handler 仍 `super().log_message()`）。建议顺手抑制访问日志。

**正常（对照）**：7.1 在线礼包全程正常（抽奖 N=3→2→1 递减、50 分钟领取成功、关闭用模板 score=1.000 一次命中）；体力任务 5 轮速通全正常；登录+切号成功（`186****61` 匹配尾号 61）。

- **状态**：以上 B 节问题**均未修改**，等用户指令。

### C. 用户补充观察：「家族活动一直识别不到按钮、全走缓存」（核验为真，建议单列 P0-3）

- **事实（日志 L74-195）**：家族活动段 5 次 `click_text` **全部** `[回退缓存]`（社交 L84 / 家族 L94 / 家族活动 L104 / 摇钱树 L114 / 闪耀委托挑战 L181），OCR 命中 **0 次**；两次 navigate 的 `if_text['家族活动']`、`if_text['家族' 区域]` 全 MISS（L78/81、L143/146）。
- **机制缺陷（源码已证实）**：`ocr_engine.py` L1326-1330 `ok = self.click_text(...)`，而 **`click_text` 的缓存回退分支同样 `return True`**（L1071-1076），于是 `if ok and step.get("mark"): self._rr_hit = True` → `run_navigate`（L1545）判定「命中进入」。而 `flows/common/entries.json` 家族活动进入链的 3 步都写死 `fallback_rel`（L14/19/21/23）→ **这 3 次点击在任何画面下都必然 return True**，该进入链**永不失败**。故 `[navigate] 《家族活动》 第 1 轮命中进入` 是**缓存回退伪造的假阳性**。
- **后果**：① 识别层整体失效却零告警（模块「看起来成功」）；② 进入失败时模块仍按「已在家族活动界面」继续执行 —— 好友采粉整段失败（P1-3）就是在错误前提下继续跑的。
- **同源判定**：与 **P0-1**（7.3 面板未打开就盲点三档）本质相同 —— **把「缓存回退成功」当成「识别命中」**。建议合并为同级 P0-3：*「缓存回退不得作为命中判据」*。
- **根因待定（两类候选）**：① 这些文字本身读不出（半透明面板/艺术字体/描边/低对比）；② 截图时机（点击发生在画面未就绪或动画中）。
  - 判别要点：日志中「家园」「菜单」等文字有时 HIT 有时 MISS（L581/586 HIT vs L560/769 MISS），但逐条核对 MISS 时刻该文字**本就不在画面上**（画面语义不同，属正常 MISS），因此**不能**据此判定为并发/时机问题；**目前尚无「同一可见元素时好时坏」的确证**。
- **附带可疑项（未证实）**：`ocr_ui.get_engine()` 是**无锁单例**，流程线程与 WebUI 的 `/api/screen` 线程共享同一 RapidOCR 实例；而 `webui._screen()` **每次轮询都跑全帧 OCR**（L460 `_ocr_boxes(img)`），日志显示运行期间每 1~2 秒一次 → 并发调用同一 onnxruntime 会话 + CPU 争抢，是 OCR 偶发失败的可疑因素，需验证。
- **仪表缺口**：`find_text` 未命中时**不打印 OCR 原始文字块**，无法区分「没检出」与「检出但文字不符」。建议加 debug 开关：未命中时 dump 前 N 块的 `text/score/center` —— 下次运行即可自证，无需额外采集。
- **状态**：**未修改任何代码/流程**，等用户指令。

## 2026-09-27 · 修 P0-3 + 增加 OCR 诊断输出（里程碑 50）

- **诊断输出（新增）**：`find_text` 未命中时调用新增 `_log_ocr_miss()`，打印本次 OCR **实读**文字块摘要 —— 前 10 块 `text@score(center)` + 总块数（`ocr_engine.py` L494-511）。用于区分两种失败：「该文字根本没被检出」与「检出了但文字不符/被合并」。**这是上轮无法定性的直接原因**（原日志不打印 OCR 原始结果）。
- **P0-3 修复**：新增实例属性 `_last_locate_source`（取值 `ocr`/`anchor`/`color`/`template`/`fallback`/`none`），在 `click_text`、`click_template` 的每条返回分支赋值；`run_step` 的 `mark` 判定改为 **仅当来源非 `fallback` 时才置 `_rr_hit`**，否则打印 `[mark] … 本次为缓存回退, 不计入命中(无法证明已在目标界面)` → `navigate`/`retry_loop` 的「命中进入 / 命中目标」不再被缓存回退伪造。
- **验证（用项目本体代码，未连模拟器、未产生任何点击）**：`py_compile` 通过；离线直调 `run_steps` 两条用例 —— 缓存回退 → `_rr_hit=False` ✅、OCR 命中 → `_rr_hit=True` ✅；`_log_ocr_miss` 两种形态（有块/无块）输出正常。
- **影响面**：只改「成功判定」，不改任何点击行为与坐标，旧流程无需改动。副作用 = 家族活动这类「全程缓存回退」的进入链**由「永不失败」变为会失败**（跑满 `max_rounds` 后放弃并在日志显式暴露识别失效）—— 这正是本次修复的目的。
- **状态**：已完成并验证。**下一步（待办）**：按 6 区架构整理项目（见下条）。

## 2026-09-27 · 按 6 区架构整理项目（里程碑 51）

- **决策**：用户定义 6 区 —— 代码区（主体代码）/ 资源区（模板等依赖资源）/ 开发区（未并入主项目的功能代码+工具+脚本）/ 测试区（日志与 tpltool 截图，**手动保存**）/ 备份区 / 其他区（交接、提示词等内部文档）。硬要求：**只有代码区+资源区同步 GitHub**（类似 release / debug 区分）。经确认采用**方案 C**：`FlowerAutoAssistant/`（代码区+资源区）**原地不动、零路径改动**；开发区/备份区物理归集到工作区根新目录。
- **同步契约（`.gitignore` 重写）**：放开 `resource/` —— 原被整目录忽略，导致 **release 克隆下来缺模板、模板匹配全废、根本跑不起来**；出仓 `dev_tools/`、`workbench/`、`PROGRESS.md`、`HANDOFF.md`、`docs/DEV_PROMPT.md`；`data/*` 出仓、仅留 `data/config.example.json`；保留 `debug/`、`legacy/`、`data/click_debug/`、`data/annot_shots/` 忽略。
- **git 索引调整（未 commit）**：
  - 出仓 `git rm --cached`：`dev_tools/`(10 个)、`PROGRESS.md`、`data/{click_log,close_buttons,config}.json`、`config/maa_option.json`（旧 MAA 残留、全项目零引用）。
  - 入仓 `git add`：`pollin.py`（26KB 主体模块，此前 untracked → **release 跑 `friend_pollin` 必崩**）、`resource/template/*.png`(15)、`data/config.example.json`、`docs/FLOWS.md`、`flows/flow_shine.json` 的删除（里程碑 44 已并入 `flow_social.json` §4.1.2，删除属有意）。
- **物理归集**：新建 `FAA_basis/_dev/`（workbench、dev_tools、_stage_faa、_compare.py、faa_basis_config、_stale）、`_test/`（faa_basis_debug ← 原 `FAA_basis/debug/`，11.5MB）、`_backup/`（3 个 zip，含 172.7MB `_backup_premerge_20260921.zip`）。
- **死文件清理（移入 `_dev/_stale/` 留档，未删除）**：`resource/tasks/`（全项目零引用，实际用的是 `flows/daily.json`）、`resource/template/` 3 个 GBK 乱码名 PNG（实为「种植/快捷操作/地图」，与 `plant_btn.png`/`quick_ops.png`/`map.png` 重复且零引用）、`config/maa_option.json`。
- **不可搬迁项（实测约束）**：`FlowerAutoAssistant/debug/` 虽属测试区但**不能动** —— `webui.py` 的 `/api/tplt_load` 以 `BASE/"debug"` 为唯一允许载图目录（L319），`pollin.py`(L446) 向该目录写 `_enter_garden_fail.png`。
- **文档**：`docs/DEV_PROMPT.md` 新增「项目分区与同步契约（6 区）」章节，并修正开发区路径（`workbench/` → `_dev/workbench/`，`dev_tools/` → `_dev/dev_tools/`）。
- **影响面评估**：主代码**零改动** —— `ocr_engine.py` 的 7 个路径常量全为 `Path(__file__).parent / …` 相对形式，代码区+资源区同级关系未变，搬迁不影响运行。开发区脚本内的相对路径（`BASE/debug`、`resource/template`）在搬到 `_dev/` 后不再自洽，属预期副作用（需用时按现路径手工传参）。`data/click_log.json` 内本就存有**早已失效的旧机器绝对路径**（`…\FAA_2026-9-18\…\workbench\template\*.png`），出仓同时消除了这类污染。
- **待办**：git **尚未 commit**（HEAD 仍 `0e61c34`）；开发区脚本路径未修（不急用）；P0-1 / P0-2 / P1-3~6 / P2-7~8 / P3-9~12 仍未修。

## 2026-09-27 · 修 P0-1 + P0-2（里程碑 52）

**用户确认方案**：P0-1 走「流程层 `if_text` 守卫」（只改 JSON，零引擎改动）；P0-2 走「单选 + 顺手修认错」（引擎单选 + 阈值收紧 + 收窄 only_types）。

### P0-1 · 7.3 面板未打开仍盲点三档「领」
- **根因**：入口 `retry_loop` 6 轮耗尽后**无「是否已在面板」守卫**，直接在未知界面跑三档 `if_color_count`；面板没开 → 绿块数恒 0 → `0 < 1` 恒 TRUE → 判「未领」→ 连点三个「领」坐标。
- **修复**（`flows/flow_claim.json`，纯流程层）：`retry_loop` 之后插入
  `if_text(["奇妙特权"], min_score=0.4)` 守卫，把**三档 `if_color_count` + 关闭面板 `if_text/click_rel`** 整段移入其 `then`；无 `else`。
- **效果**：入口失败时打印 `[if_text] ['奇妙特权'] -> MISS`，**不采样色块、不点任何「领」坐标、不关面板**（宁可不领，绝不盲点）。

### P0-2 · `close_dialog` 一次脱困连点 4 处
- **根因两层**：① `close_dialog` 把命中的**每个**关闭钮各点一次（4 条命中 = 点 4 下）；② 注册表模板阈值过松，在非目标界面也命中（0.838/0.866/0.824 全过线）。
- **修复 ①（引擎 `ocr_engine.close_dialog`）**：由「`for h in hits` 全点一遍」改为**只点 `hits[0]`**（注册表顺序即优先级：明确锚点 > 右上角兜底），其余候选仅打印 `跳过 N 个次要候选: …` 便于诊断；`find_all_close_buttons` / `--close-test` 仍返回全部。
- **修复 ②（`data/close_buttons.json` 阈值收紧，滤掉背景误匹配）**：`close_corner_pink.png` 0.75→**0.85**（挡 0.838）、`close_family.png` 0.75→**0.88**（挡 0.866）、`close_online_small.png` 0.65→**0.85**（挡 0.824）；同源模板真实命中约 1.000，余量充足。
- **修复 ③（`flows/flow_claim.json` 7.2）**：`close_dialog` 的 `only_types` 由 `[corner_pink_small, corner, corner_white]` 收窄为 `[corner_pink_small, corner]`（花灵派对为粉 X，去掉跨场景的「签到白圆」）。
- **验证（离线，用项目本体代码、不连模拟器、无真实点击）**：`py_compile` 通过；两 JSON 解析通过；monkeypatch `find_all_close_buttons`+`click_abs` 直调 `close_dialog` —— 4 候选 → **只点 1 次** ✅、`only_types` 过滤后仍只点 1 ✅、无候选 → `False` 且 0 点击 ✅；断言注册表三阈值与 flow_claim 守卫结构（3×`if_color_count` 嵌套在守卫内、7.2 `only_types` 已收窄）✅。
- **待实机校准**：三处阈值抬高后需真机跑 7.1/7.2/社交脱困，确认正常关闭仍命中（真实分数应 ≥0.95，风险低）；P0-1 守卫在真机上应看到 `全 HIT 才进三档`。
- **未动**：P1-3~6 / P2-7~8 / P3-9~12；git 仍**未 commit**。

## 2026-09-27 · 日志总行数修复 + OCR 区域诊断 + 日志分诊工具（里程碑 53）

### 1. WebUI「保存日志」总行数计数错误
- **根因**：`_LOGS` 存的是 `_TeeOut.write()` 的**写入分片**（`print` 的正文与 `\n` 分两次 write），`len(_LOGS)` 是分片数而非行数（实测 2113 分片只对应 1202 行）。
- **修复**（`webui.py` → `_log_download`）：`# 总行数` 由 `len(lines)` 改为 `text.count("\n")`。
- **验证**：该真机日志物理 1202 行、原 header 却写 2113；修复后与实际行数一致。

### 2. `_log_ocr_miss` 增加区域诊断
- **目的**：原实现文本未命中时只打**全屏前 10 块**，无法区分三种失败：① 文字根本没检出；② 检出了但文字不符/被合并；③ 检出了但落在 `region_rel` 之外（即**区域坐标写错**）。7.3 就卡在无法区分后两者。
- **修复**（`ocr_engine.py` → `_log_ocr_miss`）：区域限定时分两行输出 —— 「区域内实读」+「⚠ 区域外含同字块(疑似区域坐标不对)」，并附区域**绝对像素范围** `x…-… y…-…`；无区域限定保持原全屏摘要。
- **验证**：`py_compile` 通过；用真机日志（含 `区域[0.06,0.05,0.22,0.12]` 的 7.3 未命中）核对输出格式与调用点 `if not hits: self._log_ocr_miss(...)` 未变。

### 3. 新增日志分诊工具 `_dev/dev_tools/analysis/log_triage.py`
- **目的**：把「完全正常运行」的日志筛走、只留相对不正常的部分，降低逐行读日志的开销。
- **做法**：逐行四分类（异常 / 噪音 / 结构 / 其他）→ 噪音只统计占比，异常按**归一化签名**（坐标、数量、轮次抹成 `#`）聚类 → 输出次数 + 模块归属 + 行号范围。
- **模式**：`digest`（默认：模块序列 + 编排结果 + 滤噪明细 + 异常签名 Top N）；`sections`（按模块列异常、连续重复合并 `×N`、`--context N` 带原文）；`raw`（只滤噪保原文）；`--grep <正则>`（含上下文）；`--module` / `--top`；**多文件或目录 → 批量分诊表**（每份一行「行数/异常数/判定/主要异常」），`--detail` / `--all` 展开详情。
- **验证**：真机日志 1202 行 → 滤除 **712 行(59.2%)** 例行噪音，**436 行异常聚成 57 种签名**，一眼可见 `[OCR未命中] ['社交']×46`（社交整段反复失败）与 claim 的 7.3 入口链失败；另造一份「完全正常」日志（23 行）→ 工具判定 `✅ 正常`、0 异常、列出可直接跳过。
- **归属**：开发区文件，**不入 git**（符合交付规范第 4 条）；后续分析日志 **先跑本工具**。

### 待办
- 跑真机复验 7.3，用新的 `_log_ocr_miss` 区域输出判断是「界面没进去」还是「文字识别不到」。
- P1-3（好友采粉）/ P1-4（花灵派对 `loop_text('领取')` 自旋）/ P1-6（闪耀委托挑战回退缓存）/ P2-7 / P3-9 / P3-11 仍未修。
- git 仍**未 commit**（HEAD `0e61c34`）。

## 2026-09-28 · 修 BUG1 领取点击 + BUG2 花灵派对收尾（里程碑 54）

真机日志 `faa_log_20260927_231325.txt`（418 行，本轮只跑了 claim 模块）实证两个 bug。

### BUG2（7.3 失效的真正病根）：7.2 花灵派对收尾没离开面板
- **证据**：L322 `loop_text` 退出后走 `close_dialog`，只有「在线礼包」的模板 `close_online_small.png`(0.908) 命中 (1117,87)，
  它只关掉了「时长礼包」**子面板**；L333 的画面仍是花灵派对**主面板**（左侧 `时长礼包@(68,306)`/`每日任务@(68,384)`、右侧 `商店@(1221,374)`）。
  于是 7.3 的 6 轮 `retry_loop` 全在错误界面上跑，`奇妙特权`/`奇妙花宝`/`家园` 全 MISS，只剩兜底坐标 (1115,684) 空转。
- **修复**（`flow_claim.json` 7.2 新增收尾守卫）：`if_text(['时长礼包','每日任务'])`（说明还在主面板）→ `close_dialog()` 关主面板 → sleep →
  `if_text(['菜单','离开'])` 判断是否已回到家园，没回去则点右上角兜底坐标。
- **判据按要求用「菜单」「离开」**（家园页面特征），**不用「奇妙花宝」** —— 花灵派对与奇妙花宝是两个分立功能，前者结束不代表后者可进入。
- ⚠️ 主面板关闭按钮实际位置**未实机校准**，兜底坐标 (0.9731,0.0356) 是占位，下一次实机日志即可确认/收敛。

### BUG1（识别到领取但没实际领取）：正确的 OCR 命中被均值复核误杀
- **证据**：L140-142 OCR 已读到 `领取`@(352,337)，但场景 `花灵派对界面` 的 `领取` `mean_rel`=(0.4992,0.6179)→(639,445)
  （`sample_n=22`，而它的 `rel` 是 (0.4992,0.4681)），偏差 305px 超硬阈值 → 判误命中弃用 → 走**错误的**硬编码兜底 (0.5,0.8333)→(640,599) 点了 8 次。
- **根因**：同一个「领取」在面板里出现多次（不同高度），单一均值必然对不上 → 复核把真实命中一票否决。
- **修复**：
  1. `click_text()` 新增 `region_rel` 参数，给定时**跳过均值复核**（区域限定本身已是可信来源；缓存不得 veto 真实 OCR 命中）；
  2. `click_text` 步骤补上 `min_score` / `region_rel` 透传（此前流程 JSON 里写的 `min_score: 0.4` 被**静默忽略**）；
  3. 7.2 的 `loop_text('领取')` 与内层 `click_text('领取')` 都加 `region_rel=[0.20,0.38,0.80,0.72]`，删掉错误兜底 (0.5,0.8333)。

### 顺带修的日志诚实性（同一类问题：用缓存当判据 + 日志撒谎）
- `click_text` 的回退日志原先一律打印「未OCR到」，实际是「复核弃用」→ 现在如实区分 `复核弃用后回退` / `未OCR到`。
- `loop_text` 跑满 `max_loop` 时原先打印「不存在, 领取/操作完成」（把**放弃**谎报成**成功**：L305 还「存在」、L322 就「不存在」）
  → 现在打印「已达上限 N 次仍在, 放弃本轮循环(未确认真已领完)」。

### 验证
- `py_compile` 通过；离线断言 16 项全绿：区域限定→跳过复核且点 OCR 命中点、无区域限定→复核回归生效、回退日志如实、
  `loop_text` 上限文案、flow_claim.json 结构（region_rel / 收尾守卫 / 菜单+离开判据 / 无错误兜底）。
- 日志分诊工具 `_dev/dev_tools/analysis/log_triage.py` 已交付可用：本次即先用它筛（418 行 → 滤噪 262 行，113 行异常聚成 22 种签名，
  一眼看到 8 次「复核弃用→回退缓存」）。

### 待办
- 实机复验 claim 模块：确认 7.2 收尾能回到家园（据日志校准主面板关闭坐标）、7.2 领取真的点到按钮上、7.3 入口链恢复。
- 跨场景误匹配：`close_online_small.png` 在**家园**(0.923) 与**花灵派对主面板**(0.908) 都会误命中，需收窄 `region_rel` 或给每个面板配专属关闭模板。
- P1-3 / P1-6 / P2-7 / P3-9 / P3-11 仍未修；git 仍**未 commit**（HEAD `0e61c34`）。

## 2026-09-28 · BUG2 复验通过 + BUG1 换根因重修（里程碑 55）

真机日志 `faa_log_20260928_011528.txt`（533 行，只跑 claim）。先用 `log_triage.py` 筛：滤噪 446 行(83.7%)，52 行异常聚成 20 种签名。

### BUG2：**收尾已生效**（上一轮修复得到实证）
- L433 `if_text(['时长礼包','每日任务'])` HIT（阶段一只关掉了子面板，主面板还在）→ L439-444 阶段二 `close_dialog` 命中
  `close_corner_pink.png`(0.851) → 点 (1243,28) → **L449 `if_text(['菜单','离开'])` HIT** → L454 的 OCR 确认画面已是**家园主界面**
  （`菜单@(68,58)`、`奇妙花宝@(144,59)`）→ 7.3 入口链一次成功（L478 `奇妙特权` HIT）。
- 主面板关闭按钮实测位置 = (1243,28)，即 rel (0.9711,0.0389)，与占位值 (0.9731,0.0356) 仅差 3px。**兜底坐标已按实测值收敛**，
  并补了「兜底点完再确认一次 `菜单/离开`，仍没回家就再 `close_dialog`」的最后手段，不再假装成功。

### BUG1：区域限定修好了「点在哪」，但按钮本身不可领（换根因）
- **证据**：`loop_text('领取')` 8 次全部点在同一坐标 (926,337)，8 次都**没有**「恭喜获得」，
  且 OCR 每轮实读都是同一份 39 块（`派对时长礼包@(639,58)`、`今日参与派对时长：0@(640,109)`、
  `5分钟在线礼包@(638,154)`/`1分钟在线礼包@(352,155)`/`15分钟在线礼包@(926,155)`）——画面**完全没变化**。
  L410 如实报「已达上限 8 次仍在, 放弃本轮循环」。
- **根因（两条，都是"点不动还硬点"）**：
  1. 关键字是**子串匹配**，`领取` 会命中 `已领取`（游戏里确实有「已领取」：7.1 就在 `count_text('已领取')`，
     日志 L79/L117 都有实测块）。点了已领的按钮当然什么都不会发生 —— 这正是「识别到领取，但没有实际领取」。
  2. `loop_text` 只要还能 `locate('领取')` 就一直循环，**不管上一次点击有没有产生任何变化**，于是空转到 `max_loop`。
- **修复**：
  1. `find_text` / `locate` / `click_text` 新增 `exclude` 参数，剔除「文字里含排除词」的块；命中块被全部剔除时
     打印 `[排除] ... 命中N块但均含排除词['已领取'], 不点击`（如实报出，避免被误读成"点击不准"）。
  2. `loop_text` 新增**无进展守卫**：这一轮定位到的点与上一轮相同（≤4px）即判定该按钮当前不可领，**提前退出**并如实说明。
  3. `[OCR命中]` 日志补打**实际命中的原始文字**（`命中块文字'已领取'`），下次一眼就能分辨。
  4. 7.2 的 `loop_text('领取')` 与内层 `click_text('领取')` 都加 `exclude: ["已领取"]`。
  5. `click_text('时长礼包')` 加 `region_rel=[0.0,0.36,0.16,0.60]` 限定在左侧导航带（防止命中子面板标题「派对时长礼包」，
     它含「时长礼包」子串且位于 (639,58)）。

### 验证
- `py_compile` 通过；`flow_claim.json` JSON 解析通过；离线断言 **14/14 全绿**（exclude 过滤与日志、locate 返回 None、
  无进展守卫（同坐标停 1 次 / 坐标变化正常跑满）、7.2 接线与坐标校准）。

### 待办
- **用户新提**：修正部分**资源模板图片错误**，并采集其他需要的模板（未开始）。
- 用户新报疑点：**点击花灵派对时可能误点到「每日礼包」** —— 本次日志中 `navigate(花灵派对)` 成功（第 2 轮 OCR 命中
  `花灵派对@(237,542)` 进入），**没有复现误点**；需要用户提供出现该现象的时机/截图才能定位。
- 跨场景误匹配仍在：`close_online_small.png` 在花灵派对子面板命中 0.891、主界面 1.000、家园 0.923，需专属模板。
- 实机复验：7.2 领取是否真点到可领按钮、`[排除]`/无进展守卫是否如期触发。
- git 仍**未 commit**（HEAD `0e61c34`）。

## 2026-09-29 · 三模块脱困归位 + 4.1 共用预界面实机复验 + 社区点赞并入主项目（里程碑 56）

本轮三件事：①按审计清单修 1/2/3 号模块的脱困与归位；②实机跑一次社交模块复验共用预界面；③社区点赞并入主项目并接线 WebUI。

### ① 1/2/3 号模块脱困与归位（三份 JSON 均已 `json.load` 通过）

> 设计受两处引擎硬约束支配：**(a) `mark` 只对 `click_text`/`click_template` 生效**（`if_text`/`wait_text` 不能当
> retry_loop 的命中证据）；**(b) `navigate` 的 `mark_text` 同时是探测器与点击目标**，无法表达「已经在那儿→什么都不做」。
> 故守卫统一写成「外层 `if_text` 守卫 + `retry_loop`（mark 落在真实会命中的点击上）+ `wait_text` 等加载 + 内层 `if_text` 复核」。

- **1 号 `flow_plant.json`**（原「点家园 + sleep」，卡子界面时既不重试也不脱困、无归位判据）：
  加「已在家园则整段跳过」的外层守卫（左上 `['菜单','离开','奇妙花宝']`，region `[0.0,0.0,0.25,0.16]`，
  与 `entries.json` 闪耀变身链、§7.3 判据一致）→ `retry_loop(3)` 进入链（`click_text('家园', mark:true)`，
  失败轮自动 `close_dialog` 脱困）→ `wait_text` 等加载 → 内层复核（脱困一次-尝试-不行再脱困）→ 两轮未到**如实报出**。
- **2 号 `flow_startup.json`**（原三步全是 `if_text` 条件触发，无「确认已进主界面」的守卫）：保留原登录三步，
  其后追加 `wait_text(['社交','家园','仙境花园'], timeout=25)` → `if_text` 复核（region `[0.0,0.80,1.0,1.0]`，
  实测「社交」@(424,683) / 「家园」@(1116,685) / 「仙境花园」@(62,687)）→ 未中则脱困 + `click_text('点击进入游戏/进入游戏')`
  重试，两层，仍不中如实报出。
- **3 号 `flow_energy.json`**（原 `navigate(闪耀变身)` 循环后**不归位**）：`loop_fraction`（once/do 原样保留）之后加收尾归位，
  到位态接受**户外主界面 或 家园**两种（嵌套 `if_text` 表达「或」），脱困手段 `close_dialog` + `wait_text`，共两层，最后如实报出。

### ② 社交模块实机复验（共用预界面逻辑）——**4.1 通过**

01:49 起 `main.py --flow 社交`（后台 + `Tee-Object` 落盘 `debug/social_run.log`）。证据链：
- `navigate《家族活动》第 1/3 轮` → 点 `社交`(423,682) → `家族`(423,595) → `家族活动`(98,329) → **第 1 轮即命中进入**（只导航一次）。
- `retry_loop 第 1/3 轮`：`摇钱树` OCR 命中 (349,354) → `if_fraction` a=0/b=3 → TRUE → `浇水` (1064,564) → `store_fraction ... water_count=0` → **第 1 轮命中退出**。
- 只关摇钱树子面板：`close_online_small.png` 0.951 → (1202,64) ← **没有 close_family**（正确，留在预界面）。
- `if_config enable_shine=True` 但 `[if_time] 当前 1 时, 窗口 10-21 -> FALSE` → **时段守卫生效，跳过 4.1.2**。
- **`[if_text] ['家族首页','家族排行'] -> HIT`** ← 关键证据：此刻仍停在家族活动预界面。
- `close_family.png` 0.946 → (1245,27) ← 新增的「4.1 收尾」正确清掉残留面板。

→ **结论：共用预界面逻辑（4.1.1 不退出预界面 / 4.1.2 复用 / 4.1 收尾兜底）实机验证通过。**
4.2 好友采粉为已知长耗时模块（密友 0 个可采；好友 9 页逐页扫描），本轮不需要验证它。

### ③ 社区点赞并入主项目（全部接线完成）

- `community_like.py` 由 `_dev/workbench/` 正式拷入项目根，**已删暂存引导块、改文件头**（去掉 `_FAA` 路径引导与 `# noqa: E402`）。
- 引擎 `ocr_engine.py` 新增 `community_like` 步骤类型分支（紧跟 `friend_pollin` 之后）；步骤总数由 21 增至 22。
- `flows/flow_social.json` 4.3 段：占位 `sleep` → `if_config(enable_like)` → `community_like` 步骤；description 同步改写。
- 开关落盘：`data/config.json` + `data/config.example.json` 新增 `"enable_like": false`（默认关闭，
  每日任务模块就绪前用开关兜住「误耗每期 20 次点赞额度」的风险）。
- WebUI 接线：`webui.py` 的 `/api/config` GET 响应、`/api/set_config` POST 与响应各加 `enable_like` 字段 + 日志；
  `webui.html` ④ 折叠面板标题改「④ 社交 + 闪耀挑战 + 好友采粉 + 社区点赞」并加 `mp-social-like` 复选框，
  注册进 `MP_FIELDS.social.check`（三个社交开关同一处）。
  > 曾一度把开关加到 ⚙ `_module_settings('social')` 面板，**已主动撤回** —— 社交开关的既有落点是 ④ 面板 + `MP_FIELDS`，两套入口会造成重复。

### 验证

- `py_compile community_like.py ocr_engine.py webui.py main.py pollin.py` → **OK**。
- `json.load` 七个文件（flow_social / flow_plant / flow_startup / flow_energy / flow_claim / data/config / data/config.example）→ **全部 OK**。
- 社区点赞**离线自测 20/20 全过**（`_dev/dev_tools/self_test/test_community_like.py`，合成图 + 假 eng，不连模拟器）。
- 社区点赞**零额度消耗实机链路**（`enter → state → leave`）：`ENTER True`、`PAGE (1,1953)`、`QUOTA (16,20)`（本期剩 4）、
  第 1 页 `LIKES []`（3 张卡今天都已点过）、左箭头 `None`（首页正常）/右箭头 `(1204,345)`、
  `community_close` 命中 1.000 @(1246,26) → `LEAVE True`。
- 文档同步：`docs/FLOWS.md` 改 §0、§1、§3、§4.1（含 4.1.1/4.1.2/收尾）、§4.3（占位→真实流程）、§5、§10（步骤表 + 新增 §10.1 退出/脱困/归位约定）。

### 待办

- 社区点赞**完整实机 `run`** 尚未跑（会消耗 2 次点赞额度，本期剩 4 且 09-29 23:59 换期）。→ **已由里程碑 57 完成**。
- `already_liked_today` 仍是占位（恒返回 False），待**每日任务模块**能识别「点赞」任务状态后替换实现。
- 审计清单第 4 条（`flow_claim.json` 7.3 入口链 `fail_do` 只有 `sleep`）与第 5 条（`flow_signin.json` 无收尾守卫）**本轮未修**（用户只要求修 1/2/3）。→ **已由里程碑 57 完成**。
- `{"_note": "..."}` 这类无 `type` 的注释步骤会走到 `run_step` 的 `else` 分支打印 `[未知步骤] None`（日志噪音，未修）。
- 跨场景误匹配仍在：`close_online_small.png` 在花灵派对子面板 0.891 / 主界面 1.000 / 家园 0.923，需专属模板。
- `find_arrow` 在主界面会把「种草社区」入口圆钮误判成右箭头（流程里只在社区页内调用，暂无实际影响；若要更稳可收窄 `ARROW_Y_RANGE`）。
- git 仍**未 commit**（HEAD `0e61c34`）。

---

## 2026-09-29 · 审计 4/5 号修复 + 脱困链加固（模态对话框）+ 社区点赞完整 run（里程碑 57）

本轮两件事：①补审计清单第 4/5 条；②跑一次社区点赞 4.3 段**完整实机 run**。另含一处**关键脱困链修复**。

### ① 审计第 4 条：`flow_claim.json` 7.3 入口链 `fail_do` 条件脱困

- 原 `fail_do` 只有裸 `sleep 2.0`：卡在未知界面（弹窗/别的面板）时 6 轮全空转（2026-09-27 日志实证）。
- 改为**条件脱困**：`if_text('奇妙特权')` → 只 sleep（已在目标界面）；否则
  `if_text('奇妙花宝', region_rel=[0.06,0.05,0.22,0.12])` → 只 sleep（已在家园）；两者都不是 → `close_dialog` 脱困一次 + sleep。
- **关键约束**：**不能在已打开面板时无条件 `close_dialog`** —— 会把自己刚打开的面板关掉，形成开/关死循环，故必须条件化。

### ② 审计第 5 条：`flow_signin.json` 加收尾归位复核

- 原文件 `steps=1`（`if_text(点击签到)` 内三连），**无 retry、无归位守卫**（点完就结束，不确认是否真退出签到界面）。
- 重写为：`if_text(点击签到)` 找不到即跳过（天然兼容已签）→ `retry_loop(3)` 点签到（`mark:true`，点击常被吞）→
  `wait_text` 等奖励框 → 点「点击任意处关闭」→ `close_dialog(only_types=[corner,corner_white])` 退出 →
  **收尾归位复核**（底部导航带 `['社交','家园','仙境花园']` region `[0.0,0.80,1.0,1.0]`）：未中则 `close_dialog` 脱困一次 +
  `wait_text` + 再复核；两轮仍未归位**如实报出**（日志可见 MISS），不在错误界面上假装成功。

### ③ 关键修复：模态对话框会吞掉一切点击（脱困链加固）

- **现象**：社区点赞首次端到端 run 失败（`未能进入种草社区`）。根因是模拟器画面残留在**好友列表 + 「跳转页签」模态对话框**上。
- **实测结论**：该模态框状态下点右上角 (1245,25)、点「社交」(423,681)、点关闭模板**全部无效** —— 实测 4 条路径全空转、
  画面一字未变（`close_corner_pink.png` 0.538 < 0.85；注册表原先无「跳转页签」锚点）。
- **修复**：
  1. `data/close_buttons.json` **数组首位**新增 `anchor:"跳转页签"` 的 `anchor_color` 条目（dx 150–400 / dy 60 / min_score 0.4 /
     粉色 HSV[150-175,80-255,90-255] area 300~3000）。实测锚点 @abs(639,225)、关闭钮 @abs(889,232)、dx=250 dy=7 面积≈504。
  2. `community_like.py` 新增 `escape_to_main(eng)`：**① `close_dialog()` 先关模态框**（否则后面点击全被吞）→
     ② `pollin.ensure_home(eng)` 复用既有归位链（关提示框/离开好友花园/关家族面板/右上角兜底）→
     ③ **仅当 ② 未成功**才用「菜单 → 家园」相对坐标兜底（避免在主界面上空点菜单）。`enter_community` 重试块改调它。
- **验证**：`[关闭弹窗] 选中 '弹窗标题右侧关闭（跳转页签等模态框）' (anchor_color) -> 897,232` → 模态框消失（OCR 块数 24→33）→
  `ensure_home` 归位 → `种草社区@(1229,329)` → `enter_community -> True`。

### ④ 社区点赞 4.3 段完整实机 run —— **通过**（消耗 2 次额度 16/20→18/20）

日志（`debug/like43_run.log`）证据链：
- `[if_config] config[enable_like]=True -> TRUE`（驱动临时内存置 true，**未落盘**）。
- `已在种草社区（第 1 轮）` → `本期点赞数 16/20`。
- `随机向右 11 次（总页数=1958, 上界=25）` → 11 次 `向右翻页 -> (1204,346)`。
- `本页候选 3 个, 随机取 2 个` → 点 (737,552) **胶囊已消失, 确认点中**（3→2）→ 点 (1061,552) **胶囊已消失, 确认点中**（2→1）→ `第 1 轮结束, 还差 0 次`。
- `community_close score=1.000 -> (1246,26)` → `社区页特征已消失, 视为已退出` + `重新看到主界面右侧导航入口, 归位确认`。
- 结果 `{'ok': True, 'entered': True, 'liked': 2, 'reason': ''}`。

### 验证

- `flow_claim.json` / `flow_signin.json` `json.load` 通过；结构复核（signin 顶层 1 步 / 内层 6 步 / 末步 else 3 子步；claim fail_do 结构正确）。
- 部署脚本 `py_compile community_like.py` OK；脱困链实机验证（见 ③）。

### 待办 / 新发现

- ✅ **已修**：`pollin.click_top_right_close` 的 `close_family` 阈值原统一取 **0.65**，在「非家族面板」的任意画面上
  以 0.72~0.84 分误命中右上角并空点（escape_probe2.log: 0.823@(1229,32) / 0.839@(1183,119)；escape_probe.log: 0.726@(1174,110)），
  而真命中为 0.946 → 改为 `CORNER_CLOSE_TEMPLATES` 按模板分阈值字典，`close_family` 取 **0.88**（对齐注册表 `data/close_buttons.json`），
  其余三个模板暂无实测误命中、维持 0.65 不动。
  离线复核（真实模板匹配，非仿真）：`friendlist_now.png` 残局里 close_family 最高 **0.726 < 0.88 → miss**（原先会命中空点），
  四个模板全 miss → 走「点右上角区域中心」的既有兜底；`py_compile pollin.py` OK。
  注：`cur_state.png` 里 `close_online_small.png` 仍以 0.953 命中（跨场景误匹配已列待办，需专属模板；该分支仅在
  `ensure_home` 的**未识别场景**兜底处，主界面/家园会在前面提前 return，实际无影响）。
- `already_liked_today` 仍是占位（恒 False），待每日任务模块就绪后替换。
- `[未知步骤] None` 日志噪音未修；`find_arrow` 主界面误命中未修；git 仍未 commit。
- ✅ **`close_online_small.png` 跨场景误匹配：已修（2026-09-30，见里程碑 58）**。以下为 09-29 的调查记录：
  - **根因**：该模板仅 **17×21 px**，内容就是「粉底白✕」——**游戏里所有面板共用的关闭字形**，故在哪里都像。
    实测（区内最高分）：注册表区域 `[0.84,0.11,0.89,0.16]` → cur_state **0.942**@(1097,111)、家园 **0.897**@(1143,121)、
    like_exp_before **0.941**@(1096,92)；pollin 区域 `[0.90,0,1.0,0.16]` → 普遍 0.94~0.98。
    → **靠收窄区域/提高阈值治不了**（真值就是这么高）。
  - **既定方案（与已成功的「跳转页签」同款）**：改用 `anchor_color`，以面板**标题文字**为锚，
    在右侧 dx_range 内按颜色找关闭钮 —— 锚点文字不同 → 天然不会被其它面板的同形 ✕ 误命中；
    随后把这个 17×21 通用小模板从注册表 + `flow_claim.json`(L78) + `flow_social.json`(L27) 一并**退役**。
    摇钱树子面板同理（用「摇钱树」做锚或收窄 region）。
  - **阻塞原因**：2026-09-29 10:06 定向采集时，模拟器 `127.0.0.1:16384` 跑的是**《明日方舟》**（OCR 读到
    「ARKNIGHTS / 鹰角网络 / 开始唤醒」），不在《小花仙》上，拿不到「在线礼包」面板的标题/✕ 几何。
    （已知 ✕ 约 @abs(1105,97)（= `flow_claim` fallback_rel 0.8633,0.1347）；标题位置需面板实拍才能定 dx_range/dy_tol。）
  - **待办**：游戏切回《小花仙》后 → 打开「在线礼包」面板实拍 + OCR 量标题/✕ 几何 → 加 anchor_color 条目 →
    退役旧模板 → 跨场景复测（要求：面板内命中，cur_state/家园/好友列表残局均不命中）。

---

## 2026-09-30 · close_online_small 跨场景误匹配修复（改走「场景锚点」，里程碑 58）

用户切回《小花仙》后完成。**方案：不再靠那个 17×21 的通用字形，改用与「跳转页签/提示」同款的 `anchor_color`。**

### 实拍取证（打开「在线礼包」面板，源 debug/z_panel2.png）
- 面板标题「在线礼包」@abs(202,90)（OCR score 0.784）；关闭钮（粉花+白✕）@abs(1105,97)（与 `flow_claim` 旧 fallback 0.8633,0.1347 完全一致）。
- ⚠ **dx_range 必须显式给 [700,1100]**：用默认 [150,400] 会命中标题栏里的**装饰粉块** @abs(553,96)（错位）。

### 改动清单
1. **`data/close_buttons.json`**：新增 `anchor_color` 条目「在线礼包面板标题右侧关闭（在线礼包界面）」
   （anchor `在线礼包` / dx_range [700,1100] / dy_tol 60 / min_score 0.4 / 粉色 HSV[150-175,80-255,90-255] area 300~3000），
   插在「提示」条目之后、corner 类之前（**锚点优先于 corner**）。
2. **`flows/flow_claim.json`**（7.1 退出，原 L78-79）：
   `click_template(close_online_small.png)` + `close_dialog(only_types=[corner_pink_small])`
   → **`close_dialog(only_types=['anchor_color'])` ×2**（锚点 + 复核再关一次）。
3. **`pollin.py`**：`CORNER_CLOSE_TEMPLATES` 剔除 `close_online_small.png`（通用兜底里的"随机误点生成器"）
   与 `close_signin.png`（资源文件根本不存在，死条目）；只留 `close_family`(0.88) / `close_corner_pink.png`(0.65)。

### 为何**不删**注册表的 `corner_pink_small` 条目
它是**共享型**定位：花灵派对「时长礼包」(flow_claim L115) 与「爱心记录」等面板**只有它有效**
（`_dev/_stage_faa/PROGRESS.md` 记录：这些面板 `corner`/`corner_white` 均无效）。故保留，靠**注册表顺序**（排在锚点类之后）保证在线礼包场景优先走锚点。

### 验证（`find_all_close_buttons` 实跑，非仿真）
- **面板 z_panel2.png**：新条目 **HIT (1105,97)** ✓（同场景 corner_pink_small 亦命中 (1104,96)，但锚点排在前面 → 被选中）。
- **噪点场景全部无锚点命中**（新条目名不在命中列表）：`z_before2`(主界面) / `hb_home`(家园) / `cur_state` / `L_first`(花灵派对?) / `like_exp_before`(社区页) / `friendlist_now`(好友列表残局)。
- `json.load` 8 份 flow/注册表全过；`py_compile pollin.py` OK。

### 复测/顺带发现（→ **两条均已于 09-30 处理，见里程碑 59**）
- 注册表 `corner_pink_small` 仍是共享型小✕，在 主界面 0.957@(1112,100) / 家园 0.897@(1143,121) / cur_state 0.942@(1097,111) 也能命中；
  但它**排在锚点类之后**且一般不是首个候选，实际影响小（保留原因见上）。
- `flow_social.json` 4.1 关摇钱树子面板仍用 `close_online_small.png`（tight region `[0.84,0,1.0,0.30]` + th 0.65）：
  它紧随「摇钱树面板已打开」之后执行，风险低；若要彻底根治可同样改为「摇钱树」锚点（需再实拍一次该子面板）。
- `like_exp_before` 场景里 `close_family` 模板以 **0.896** 命中 (1245,27)（> 现阈值 0.88，真命中 0.946）——
  阈值余量偏小，若要更稳可提到 0.92（仅 1 个真命中样本，暂未动）。

---

## 2026-09-30 · 摇钱树子面板关闭加守卫 + close_family 阈值提到 0.92（里程碑 59）

承接里程碑 58 结尾的两条「顺带发现」，用户「执行吧」批准后落地。

### 1. `flow_social.json` 4.1 摇钱树子面板关闭 → 改为「区域守卫 + 模板」

**实拍取证**（打开摇钱树子面板，源 `debug/z_yaoqian.png`）：
- 面板内容 OCR 仅 11 块（`家族等级LV.8` / `浇水奖励` / `个人资金` / `浇水` / `今日浇水次数：`@abs(1067,565) / `0/3`@(1188,565) …）；
- **标题栏 y<130 无任何文字块** → **无法照搬里程碑 58 的 `anchor_color` 锚点方案**（没有文字可当锚）；
- 旧关闭 fallback (1200,64) / 实测模板命中 (1202,64) 0.951。

**改动**（原 `click_template(close_online_small.png, 0.65, region [0.84,0,1.0,0.30])` 外面套一层 `if_text`）：
```json
{ "type": "if_text", "text": ["今日浇水次数"], "min_score": 0.4,
  "region_rel": [0.78, 0.74, 1.00, 0.84],
  "then": [ { "type": "click_template", "template": "close_online_small.png", "threshold": 0.65,
              "region_rel": [0.84, 0.0, 1.0, 0.30], "fallback_rel": [0.938, 0.089], "delay": 2.0,
              "name": "关闭摇钱树子面板(守卫:今日浇水次数)" } ] }
```
> 偏差说明：里程碑 58 设想的是「同样改『摇钱树』锚点」，实拍后发现该面板标题栏无文字、锚点方案不可行，
> 故改为**用它独有的「今日浇水次数：X/3」做门禁**（等价于「收紧到专属区域」，符合 §10 的教训口径）。

**为何必须加守卫**（离线真实模板匹配实测）：
- `close_online_small.png` 在**家族活动预界面**上以 **0.980**@(1245,25) 命中 —— 比真关闭钮 `close_family` 的 0.946 **还高**，
  且落点 (1245,25) 正是预界面的关闭钮 → **无守卫时的点击会把预界面一起关掉**，4.1.2 又得重新 `navigate`（里程碑 56 修过同类问题）。

**实机验证**（`debug/z_verify_*.png`，真实引擎 + 真实模拟器）：
| 场景 | 守卫 | 结果 |
|---|---|---|
| 摇钱树子面板开着（`[if_text] ... -> HIT`） | HIT | `close_online_small` 0.951@(1202,64) 点击 → 面板消失、**停在家族活动预界面** ✓ |
| 家族活动预界面（`[if_text] ... -> MISS`） | MISS | **一次都不点**，画面不变、预界面仍在 ✓ |

### 2. `close_family` 模板阈值 0.88 → 0.92（两处）
- `pollin.py` 的 `CORNER_CLOSE_TEMPLATES["close_family"]`：0.88 → **0.92**
- `data/close_buttons.json`「家族活动右上角关闭」的 `template_threshold`：0.88 → **0.92**
- 依据：社区页 `like_exp_before` 以 **0.896**@(1245,27) 误命中（> 0.88）；假命中样本 0.726 / 0.823 / 0.839 / 0.896，真命中 0.946。
- ⚠ **已记录的风险**：真命中目前**只有 1 个样本**（0.946），提到 0.92 后余量仅 **0.026**；若日后家族面板出现漏关，先怀疑此值。
- **实机复核**：家族活动预界面收尾 `close_family` 仍以 **0.946**@(1245,27) 命中 ✓（提到 0.92 后照常关得掉），随后正确回到户外主界面。

### 文档同步
`docs/FLOWS.md`：§4.1 共用预界面说明、§4.1.1 第 4 步（重写为守卫结构 + 为何要守卫）、§10 右上角兜底阈值段落（0.92 + 风险）。

---

## 2026-09-30 · 首次推送（里程碑 60）—— 发现远端历史曾被重写，改以「重挂」方式入仓

用户指示「提交代码并推送」。执行中发现**远端 main 已被重写并强推过**，本轮据此调整了推送方式。

### 关键事实（务必记住）
- 本地 `origin/main` 引用原停在 `0e61c34`；`git fetch` 报 **forced update `0e61c34...b1456cd`**。
  远端同里程碑的提交 message 相同但 **hash 全不同**（本地 `0e61c34` ↔ 远端 `f581bec`）= 历史被重建过。
- 远端多出两个提交，理由写在 commit message 里：
  - `9d35117 fix(security): 取消跟踪 data/config.json, 清除硬编码真实账号与账号写库键名`
  - `b1456cd docs: 记录敏感数据清除过程与验证证据, 补充 config.example.json 用法`
- 即：**远端是「已净化」的历史，本地这条线是净化前的旧谱系**；两边已分叉（本地独有 10 提交 / 远端独有 11 提交，merge-base `cb358eb`）。

### 为什么既不能 force push 也不能 rebase/merge
- force push 会用旧谱系覆盖远端 → 把已清除的真实账号数据重新发布到 GitHub。
- rebase/merge 本地的 10 个旧提交 → 同样把含真实账号的 `data/config.json` 内容重放进历史（**advisor 曾建议 rebase，核对后否决**）。

### 实际做法（已成功推送）
1. 先建安全分支 `local-old-lineage-20260930`（= 旧谱系提交 `a125497`）兜底。
2. `git reset --soft origin/main`（只移动 HEAD，不动工作区/索引），再 `git restore --staged` 撤回四组**出仓删除**
   （`PROGRESS.md` / `dev_tools/` / `data/click_log.json` / `config/maa_option.json`）——**用户裁定：这批删除本次不推，远端保持跟踪**。
3. 结果提交 **`8bef259`（父提交 = `b1456cd`，35 文件，+2507/-200）**，`git push origin main` 为 fast-forward，
   远端 `main` = `8bef259`，**未改写远端任何历史**。
4. 安全复核：`data/config.json` 两侧都不存在（净化的 `9d35117` 成果保留）；本地 README / `config.example.json`
   均为净化后的版本（内容更新且不含真实账号），已作为最新版入库。

### 遗留 / 待办
- **过渡态**：本轮入库的 `.gitignore` 已宣布六区契约出仓 `dev_tools/`、`PROGRESS.md`、`HANDOFF.md`、`docs/DEV_PROMPT.md`、
  `data/` 运行状态、`config/`，但**远端仍跟踪这些文件**（删除未提交）。要不要真删，待用户定夺。
- 本地工作区常驻三处「未提交差异」（属正常，勿误提交）：`PROGRESS.md`（本地版含里程碑 52~60，远端版含安全清除记录）、
  `data/click_log.json`（本机运行知识库，比远端新，**含账号类键名风险，切勿提交**）、`dev_tools/*`（已物理移出仓库到 `_dev/dev_tools/`，显示为 deleted）。
- 网络：GitHub 连通性不稳（推送途中出现过 `Connection was reset` / 502），重试后成功。

---

## 2026-09-30 · 日志工具时间预分析 + 修「采粉被记成家族活动界面」（里程碑 61）

用户提供 `faa_log_20260930_092739.txt`（1785 行），提出两件事：① 日志分析工具加**时间预分析**；
② 反馈「好友家园采粉时显示识别到家族活动界面」。

### 1. `_dev/dev_tools/analysis/log_triage.py` 新增 `-m timing`（时间预分析）

时间戳来源：日志里**只有 WebUI 的 `/api/screen` 访问日志带时间戳**（引擎几乎每步都拉截图 → 天然是「操作时钟」）。
本次日志 1785 行中 408 行带时间戳（覆盖率 23%，全部是 `/api/` 行）。

- `scan_timeline()`：按 `>>> 模块执行` / `<<< 模块完成` 切模块，把时间戳归到所属模块，算
  **模块耗时 = 末时间戳 − 首时间戳**、**相邻时间戳最大间隔 = 卡点候选**（附行号 + 向上跳过访问日志取到的前置原文行）。
- `print_timing()` 输出模块耗时表（开始/结束/耗时/占比/采样数/最大间隔/行号）+ 全局卡点 Top N。
- 速览（`digest`）新增「运行时长」行；argparse 加 `timing`，docstring/`DEV_PROMPT.md` 同步用法。
- **如实标注局限（重要）**：`energy`/`claim` 整段无 `/api/` 行（本次日志 03:05:09 之后时间戳就断了）→ 工具显式打印
  「无时间戳模块」与「耗时只是下限的模块」，不假装测到了。

**本次实测结论**：`social` 25分45秒（占观测时长 85%）是绝对大头；总时长 30分25秒中 `startup` 4分27秒、`signin` 6 秒。
卡点 Top6 全是 **60 秒 / 61 秒**的整齐间隔（L737→L871 连着 6 处），前置原文分别是
`[等待] 进入好友花园(第3次) 超时 45s`、`[OCR未命中]['抱歉']`、`[等待] 社交面板 命中 (4s)`……
→ 这不是"偶发卡顿"，而是**「请求/页面等待」按固定 60 秒档位超时**的地带，是后续优化的第一目标（对应 4.2 采粉的等待链）。

### 2. 修「采粉点击被记成 `家族活动界面`」——根因是场景从不复位

**证据**（本次日志）：**63 次点击被记进 `[家族活动界面]`**，全部发生在 4.2 采粉阶段，含 `快捷操作 23 / 采粉 16 / 弹窗关闭 12 / 社交 11 …`。
原文样式：`[记录] [家族活动界面] 按钮[快捷操作] 相对[0.6945, 0.95] 均值[…](样本40) 已存入 click_log.json`。

**根因**：`OCREngine._scene` 只在三处被赋值 —— flow 的 `scene` 字段、单步骤的 `scene` 字段、`navigate` 命中进入时置为目标场景。
**界面真的切换后没有任何地方复位**，于是 `navigate(家族活动)` 把场景钉在「家族活动界面」，之后同模块里的采粉/点赞点击全被误归。

**改动**：
1. `ocr_engine.py` 新增 public `set_scene(name, quiet=False)`（打印 `[场景] -> X`，同名静默）。
2. `pollin.py` 在界面切换点声明：`ensure_home`/`leave_garden` 确认归位 → `家园主界面`；
   `open_friend_list` 进入列表 → `好友列表`；`collect_one` 成功进园 → `好友花园`。
3. `community_like.py`：`enter_community` 进入 → `种草社区`；`leave` 确认退出 → `家园主界面`。
4. **数据清理**：`data/click_log.json` 的 `家族活动界面` 分组删掉 8 条采粉期误归条目
   （`快捷操作`(0.6906,0.9514, n=60) / `采粉`(n=35) / `社交`(n=28) / `在线礼包` / `菜单` / `花灵派对` / `家园` / `闪耀变身`），
   删前逐条比对了同名按钮在 `家园主界面`/`未分类` 的 rel（同一物理按钮）→ 27 条降到 19 条（余下均为家族活动功能自身按钮）。
   备份：`%TEMP%\click_log_before_scene_fix.json`。**保留** `浇水 n=13`（摇钱树浇水真实样本，只是场景本身偏）、`弹窗关闭`、
   `close_family.png`、`家族` 等，避免误删真样本。
5. 离线自检通过：引擎加载清理后 KB（16 场景）、`set_scene` 生效、场景优先未命中时正确回退扁平索引。
6. 文档：本文件 + `docs/FLOWS.md`（§4.2 / §4.3 各加「场景声明」段，写清根因）+ `docs/DEV_PROMPT.md`（工具用法 + 局限）。

### 待办 / 未处理（如实记录）
- **`家族活动界面` 的 `浇水`/`close_online_small.png` 仍是场景偏位的条目**（真按钮但记错场景），本次未动，待后续按需处理。
- **`未分类` 分组仍是脏的**（含把 Windows 全路径当按钮名、`采粉`/`快捷操作` 等跨场景重名条目）；
  `体力界面` 分组也残留 `社交/家族/家族活动/在线礼包/花灵派对/菜单` 各 n=1 的误归。均未处理。
- **`flow_social.json` 没有 flow 级 `"scene"` 声明**（对比 `entries.json` 的 navigate 目标与 `flow_claim.json` 的步骤级声明）：
  该模块进入 `navigate` 之前的点击会落在上一模块遗留的场景里。本次未改（需先确认 social 起始段到底应是哪个场景）。
- 本次改动**未实机验证**（需连模拟器跑一轮 social 才能看到 `[场景] ->` 与逐场景归类效果）。
- `log_triage.py` 的 60 秒档超时卡点已定位但**未优化**（属 4.2 等待链改造，待用户定夺）。

---

## 2026-09-30 · 修「闪耀委托挑战卡住」+ WebUI 日志落盘 / 关闭确认（里程碑 62）

用户提供 `faa_log_20260930_130955.txt`（707 行）反馈两问题：① 社交任务-闪耀委托挑战卡住；
② 误关 WebUI 后无法下载日志、重开 html 变新页面。代码修复已落地；**问题②已实机验证通过**（详见下方「验证（WebUI 问题②）」），问题①待连模拟器复验。

### ① 闪耀委托挑战卡住的根因：委托全屏子页**右上角没有关闭 X**

**证据链**（`faa_log_20260930_130955.txt`）：
- L162-186 委托挑战执行成功（`参与挑战` → … → 确认）。
- L188-201 退出失败：`close_family` 模板**恒 0.683 < 0.75 不命中**，回退 (1245,27) 点在空白处 ——
  **委托挑战是全屏子页，右上角没有关闭 X**；真实出口是**左上角「返回」箭头**（OCR `家族@(45,27)` 在左上角）。
- L209-242 因未退出，后续 pollin 空转约 12 分钟；L607-668 energy `《闪耀变身》` 3 轮全 miss；L708 用户手动停止。

**判据区分**（子页 vs 家族 2×2 网格，实机确认）：
- 委托子页独有文字：**「委托排行」「距离结束」**（家族网格不显示）。
- 家族网格独有文字：**「家族首页」「家族排行」「摇钱树」**。
- 网格右上角有关闭 X（`close_family.png` 真命中 0.946 / 阈值 0.92）；子页右上角**无**。

**改动**：
1. `flows/flow_social.json`（2 处）：
   - 4.1.2 刷完委托后：**新增两段式退出** —— ① `if_text(['委托排行','距离结束'])` 命中则 `click_rel(0.035,0.038)`
     点左上角返回 → 回家族网格；② `if_text(['家族首页','家族排行','摇钱树'])` 命中则
     `click_template('close_family.png', 0.92, region [0.90,0,1.0,0.15], fallback (0.9727,0.0375))` 关网格回主界面。
   - 4.1 收尾同样改造：先管子页分支（左上角返回），再管网格分支（右上角 X），close_family 阈值 0.75→**0.92**。
   - `json.load` 通过（21 steps）。
2. `pollin.py`：
   - 新增 `in_delegate_subpage(eng, img=None)`：`['委托排行','距离结束']` 任一命中即判为委托全屏子页。
   - `ensure_home` 在 `in_family_panel` 分支**前**加委托子页脱困分支：命中则 `click_rel(0.035,0.038)`
     （点左上角返回）后 `continue`（下一轮再关网格）；`close_family` 阈值 0.75→**0.92**（对齐注册表与里程碑 59）。
   - `py_compile` 通过。

### ② WebUI 关闭后无法下载日志 / 重开变新页面

**根因**：`_LOGS` 是 webui.py **服务端进程内存环形缓冲**，浏览器关掉只是失去「查看端」，服务端还在所以日志还在；
但 ① **服务端进程一旦重启/崩溃，历史日志永久丢失**；② 用户**误用 file:// 直接打开 webui.html** 得到全新静态页，
不连服务端 → 没有状态、也点不到下载（`/api/log_download` 在服务端）。

**改动**：
1. `webui.py`（日志落盘 + 运行状态）：
   - `_LOG_FILE = data/webui_runtime_log.txt`；`_log_persist(text)` 追加写盘；`log_append` 与 `_TeeOut.write` 都落盘；
     `_log_reload_history()` 在服务启动时读回内存 → **重启不丢历史日志**。
   - `_RUNNING_LOCK/_RUNNING` + `_set_running/_running`；`_run_daily_sel.job`/`_run.job` 开头置 True、finally 置 False；
     `_status()` 返回 `running` 字段。
   - `main()` 在 `serve_forever` 前 `_log_reload_history()` + `_set_running(False)`。
   - `py_compile` + import 测试通过（`import OK False True`）。
2. `webui.html`：
   - `location.protocol === 'file:'` → `showFileProtocolNotice()` 提示改用 `http://127.0.0.1:8765/`，
     并把**后续顶层代码整体包进 `else{}`** 使其干净退出（详见下方「顺带修的稳健性问题」）。
   - `beforeunload`：`runningFlag` 为真时弹确认「任务正在运行中, 关闭页面将失去实时监控。确定要离开吗?」。
   - `refreshStatus` 里 `runningFlag = !!s.running`；初始化 IIFE 加 file: 提前 return；刷新间隔改为 `setInterval(...,1500)` 同时刷截图+状态。

### 验证（WebUI 问题②：已实机验证通过）

首轮验证发现**日志文件根本没生成**，由此挖出落盘链路的最后一处缺口并补齐：

- **缺口**：启动阶段的横幅走**裸 `print()`**（此时 `_TeeOut` 还没挂到 stdout，它只在 `_run.job`/`_run_daily_sel.job` 内部安装）
  → 服务启动后 `data/webui_runtime_log.txt` **永远不生成**，整条落盘链路无从验证。
  另 `_log_persist` 未保证 `data/` 目录存在（全新克隆可能缺 → 静默 `except` 吞掉，无人知晓）。
- **补丁**：① `_log_persist` 首次写盘前 `_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)`；
  ② `main()` 在 `_log_reload_history()` 后 `log_append("[webui] 服务启动 <时间> -> <URL>")`，让启动即有落盘内容。
- 证据链（全部实跑，非仿真）：
  1. 启动服务 → `data/webui_runtime_log.txt` **生成**，内容为 `[webui] 服务启动 2026-09-30 23:58:32 -> http://127.0.0.1:8765/`。
  2. `GET /api/log?after=0` → `next=1`，1 条分片，内容同上（**分片下标语义**与 `_log_reload_history` 把整段历史当 0 号分片相容）。
  3. `GET /api/log_download` → **HTTP 200**、`Content-Disposition: attachment; filename="faa_log_*.txt"`，
     正文 `# 总行数: 1` + 启动行。
  4. **核心诉求验证（关掉 webui 再重开）**：停服务 → 文件**仍在磁盘**（8765 只剩 TIME_WAIT）→ 重启 →
     `/api/log?after=0` 返回 **2 条分片** = 上一会话那行 + 本次启动行；`/api/log_download` 报 `# 总行数: 2`，两行俱全。
     → 证明「服务重启后历史不丢、重开仍能查看与下载」。
  5. **浏览器实测**（正常 HTTP 访问）：页面正常渲染、**控制台零报错**、控件齐全（切换界面/关闭服务/截图区/日志区）、
     自动刷新正常、日志区可见 `[webui] 服务启动 ...` 行。
- **顺带修的稳健性问题**：`showFileProtocolNotice()` 会清空 `document.body`，但同一 `<script>` 顶层后续还有
  `$("view-toggle").onclick` 等语句 → file:// 模式下必然空引用抛错。已把后续顶层代码整体用 `else{}` 包住，
  使 file:// 分支**干净退出**（HTTP 模式行为完全不变）。`node --check` 校验 script 块 **SYNTAX OK**。

### 验证（问题①：待实机）

- `flow_social.json` JSON 校验 OK（21 steps）；`pollin.py`/`webui.py` `py_compile` OK；`webui.py` import 测试 OK。
- 问题①（委托子页两段式退出 + `ensure_home` 子页脱困）**仍未实机验证**——本机 `adb` 不在 PATH、模拟器未连接，
  需连上模拟器跑一轮 social 才能看到真实退出效果。

### 待办 / 未处理

- 问题①**待实机验证**：连模拟器跑一轮 social，确认「委托排行/距离结束」判据命中 → 点左上角返回 → 关家族网格 → 回主界面；
  以及 `ensure_home` 在委托子页残局下的脱困走向。
- file:// 提示与关闭确认弹窗的**浏览器实景**未逐项复现（file:// 不在浏览器子agent 支持范围内；关闭弹窗需真实关闭动作），
  但代码已通过 `node --check` + 正常模式零报错实测。
- 上一轮遗留（里程碑 61）不变：`家族活动界面` 残留 `浇水`/`close_online_small.png` 场景偏位条目；`未分类`/`体力界面` 脏分组；
  `flow_social.json` 无 flow 级 `scene` 声明；set_scene 效果未实机复验；4.2 等待链 60 秒档超时未优化；git 未 commit。

---

## 2026-10-01 · 登录后「公告」窗口的关闭逻辑（里程碑 63）

用户上传 `faa_log_20261001_021736.txt`（163 行）反馈：登录界面**会不定期弹出「公告」**需要关掉，
当前界面正卡在公告页，弹出顺序在点「登录」之后。

### 日志证据链

- L39-105：切号 → 选账号 → 点「登录」@(754,394) 成功。
- L122：`if_text(['点击进入游戏','进入游戏']) -> MISS`；此时登录页页脚「健康游戏忠告」仍可读 → **公告还没弹**。
- L124：`[未知步骤] None` —— 流程里的 `{"_note": ...}` 文档节点被当成步骤执行（噪音）。
- L163：`wait_text(['社交','家园','仙境花园'])` 读到的正是**公告面板**：`公告@(175,91) | 版本公告@(173,180) | 维护公告@(172,273) | 9月30日版本更新@(382,359) | 防沉迷说明@(173,365)`。
- L166：`[等待超时] (25s)`；L140 用户已先按停止，收尾脱困分支没机会跑到。
> 时序结论：**公告是延迟弹出的**（登录后 19s 未弹、48s 已弹），固定 25s 的 `wait_text` 必然被它吃掉。

### 实测采集（走本体定位器，不靠猜）

- 守卫文字可识别：`版本公告@(173,181)`、`维护公告@(172,273)`、`防诈骗提示@(173,457)`。
- 关闭钮：通用 ✕ 模板 `close_online_small.png` 在区域 `[0.80,0.05,0.92,0.20]` 内 **score=1.000 → (1104,96) = rel(0.8625,0.1333)**。
- `find_all_close_buttons` 在本画面**唯一命中**就是注册表既有的 `corner_pink_small（在线礼包右上角粉色圆形关闭）`
  → 说明 `close_dialog` 本来也能关掉公告，只是日志里没跑到。
- ⚠ **`公告` 不能当锚点**：关键字是子串匹配，会撞上「版本公告」——实测 `locate('公告')` 落在 (199,180)，即版本公告那一行。

### 改动

1. `flows/flow_startup.json`：原单条 `if_text(['点击进入游戏','进入游戏'])` → 换成
   **「主界面快速跳过 + 有限轮询关公告」**：`if_text(主界面底部导航)` 命中则整块跳过（不退化成空转），否则
   `retry_loop(max_rounds=8)` —— 每轮先 `if_text(['版本公告','维护公告','防诈骗提示'])` 命中就
   `click_template('close_online_small.png', 0.85, region_rel=[0.80,0.05,0.92,0.20], fallback_rel=[0.8625,0.1333])` 关公告；
   再 `if_text(['点击进入游戏','进入游戏'])` 命中就 `click_text(..., mark=true)`；两都没中则 `fail_do: sleep 3` 进下一轮。
   → 边关公告边等按钮，覆盖实测约 48s 的延迟弹出。`json.load` 通过（8 steps）。
2. `ocr_engine.py`：`run_step` 开头加 `if not s_type: return` —— 纯文档节点（`{"_note": ...}`）不再落到末尾
   `[未知步骤] None` 刷噪音（本流程与 `flow_social.json` 都在用 `_note`）。`py_compile` 通过。

### 验证

- **点击目标**：在**真实公告画面**上用本体 `locate_template` 实测 score=1.000 @(1104,96)（探针脚本，已删）。
- **负向路径（实跑）**：在真实设备上单独执行新步骤。此时公告已不在（画面已是「双生签到/童话邮差」活动页），
  守卫正确判 MISS → 连续 8 轮**一次坐标都没点**、`_note` 也不再打印 `[未知步骤]`，复核「公告不存在」。
  → 证明无公告时该逻辑**不会误点**。
- **正向路径（未实机）**：公告在时点 (1104,96) 能否真正关掉面板，尚未端到端跑到（公告不定期，本次未复现）。
  > `close_online_small.png` 在本项目属「通用 ✕ 字形」，单用会跨场景乱命中（见里程碑 59）；这里靠
  > **唯一文字守卫 + 紧区域**约束，正是 memory 里记录的推荐方案。

### 待办

- 公告真弹出时跑一轮 startup，确认点 (1104,96) 确实关闭面板、并随后点到「点击进入游戏」。
- `retry_loop` 最后一轮仍打印「未命中, 脱困重试」（其实已无下一轮），与项目「如实打印」约定略有出入，本轮未改。

---

## 2026-10-01 · WebUI 日志保存改造：离线快照 + 停轮询（里程碑 64）

用户提问「关闭服务后，日志似乎不会刷新，是有意为之吗？」→ 追问「为什么」→ 提出自己的 4 条改造设想 → 拍板。
结论：**不是有意为之**，是两个独立实现副作用叠出来的；日志数据一条未丢（`_LOG_FILE` 只追加）。

### 两个独立机制（都定位到行）

1. **点「关闭服务」= 整页被替换**：`webui.html` 关闭成功后执行 `document.body.innerHTML = "Web UI 服务已关闭…"`，
   整体覆盖 → 日志区 `#log` 连同 header、按钮一起被销毁。看起来像「日志不刷新」，实为**承载日志的页面没了**。
   服务端 `_shutdown()` 那边照常 `log_append` 并落盘。
2. **服务重启后分片游标失效**：`_LOGS` 存的是 `_TeeOut.write()` 的**写入分片**（`print("abc\n")` 产生 2 个分片），
   `logCursor` 是**分片下标**。重启后 `_log_reload_history()` 把整个磁盘文件当成 **1 个**分片塞回 → `len(_LOGS)=1`，
   而前端游标仍是旧的大数 N → `_log()` 判 `after >= len(_LOGS)` → 长期返回 `{"next": N, "lines": []}`；
   `pollLog` 只在 `lines.length>0` 时更新游标、`catch(e){}` 又静默 → **无自愈出口**，观感即「冻住」。
   > ⚠ 关键洞察：重启后 `/api/log` 是 **HTTP 200 + 空数组**，**不是报错**，所以不能靠 `catch` 判断「服务重启过」。

### 用户拍板的边界（本轮据此实施）

- **关页面不关服务** → **已经是现状，零改动**：新页面 `logCursor=0`，`/api/log?after=0` 返回 `_LOGS[0:]` 全量。
  两个备选均否：a) 浏览器端缓存 —— 与现状重复、localStorage 仅 5~10MB 且同步写会卡 UI；b) 「挂机标记起点」—— 非必需。
- **服务已停（ctrl+c / 误关控制台）但页面还开着** → 保存日志必须仍可用 → 新增**客户端离线导出**。
- **点按钮关服务 = 主动行为** → 保持整页替换，**不做**非破坏式改造（防护只为误操作准备）。
- **第 4 条「启动时清空日志缓存」自动失效**：其前提是采纳浏览器端缓存方案，已否；服务端文件保持 append-only
  —— 这恰好保证「服务端导出 ⊇ 页面快照」，「用户可选保存旧日志」零成本成立。
- **「服务重启但页面仍开着」的盲区不做 epoch resync**：用户判定旧页面此时即**用户自控的快照**（可自行选择保存），
  新页面/刷新则天然完整（`after=0`），无需额外机制。

### 改动（全部在 `webui.html`）

1. 新增 `const logChunks = []`，`pollLog` 内 `logChunks.push(line)` 留存**原始分片**。
   > 离线导出必须 `logChunks.join("")` 才与服务端 `"".join(_LOGS)` 等价；按 DOM 的 div 拼行会多出空行、断行错位。
2. `$("log-save").onclick` 由 `location.href = "/api/log_download"` 改为 `saveLog()`：
   服务端可达 → `fetch` 后转 Blob 下载（**页面不跳转**）；不可达 → 用 `logChunks.join("")` 生成快照 txt（带 BOM + 头部注释）。
   > 顺带干掉旧隐患：原 `location.href` 在服务已死时会把浏览器**导航到打不开的地址**，为保存反而丢掉页面与页面上的日志。
3. `pollLog` 开头加 `if(!logPolling) return`；`shutdown-btn` 成功回调里 `logPolling = false` + `clearInterval(autoTimer)`。
4. `run-btn` 重置处补 `logChunks.length = 0`（原处已有 `$("log").innerHTML=""` + `logCursor = 0`），保持快照与页面显示一致。
5. 「保存日志」按钮补 `title` 说明双模式行为。

### 验证（实跑）

- `node --check` 校验 script 块 **SYNTAX OK**（临时 js 写在 `%TEMP%`，已删）。
- 起服务 → `/api/status` 200；`/api/log?after=0` → `next=2`（历史分片 + 本次启动行）。
- **路径①（关页面再重开，服务在跑）**：浏览器新加载页面后，日志区即出现服务启动记录 → 确认 `after=0` 拉回全量。
- **路径②（服务端可达时保存）**：切到测试界面 → 点「保存日志」→ `/api/log_download` **HTTP 200**、地址栏 URL **未变**（无整页跳转）、
  控制台**无新增 JS 异常**。
- **路径③（服务已停时保存）**：停掉服务（8765 无监听）后**不刷新页面**、在同一页面再点「保存日志」→
  `/api/log_download` 请求失败、URL 仍未变、页面**未被替换成浏览器错误页**、**无新增 JS 异常**（新增 3 条均为
  `net::ERR_CONNECTION_REFUSED`，指向 `/api/log`、`/api/screen`、`/api/status`）→ 证明 `catch` 分支被走到、离线快照路径已执行。
  > 诚实注明：自动化浏览器无法观测 blob 下载动作本身，**未端到端确认落盘文件**（见待办）。
- **路径④（点按钮关服务）**：重启服务 → 刷新页面 → 点「⏻ 关闭服务」并确认 confirm/alert → 页面变为
  「Web UI 服务已关闭。重新启动请运行 start_webui.bat 或 python webui.py」、URL 未变；随后**静置 6 秒**
  控制台消息数 **10 → 10 未增长** → 证明轮询与自动刷新定时器确实已停。

### 待办

- 自动化浏览器观不到 blob 下载落盘：建议在真机浏览器上、**服务已停**的状态下点一次「保存日志」，
  确认 `faa_log_snapshot_*.txt` 落盘且内容与页面一致（分片拼接保真）。
- 旧页面在缓冲重新长过旧游标后会自行「解冻」，那时起点落在某分片中间，页面顶部可能冒出一个半行片段
  （仅影响该页显示，不影响服务端导出与新页面；刷新即消失）。

---

## 2026-10-01 · 多 agent 协作接口：项目总纲 + 合并闸门（里程碑 65）

用户需求两条：①「给项目留一个其他 agent 可以开发本项目的**接口**」——能访问项目文件与文档、调用项目代码、
做日常开发事务，并使其成果易于合并；②「在原有分区架构基础上整理项目，形成一个**新文档**」——含项目基本信息、
架构、技术方案、进度、待办，以及其他 agent 接手的必要信息与开发标准。

### 决策（按用户"工作量最低 / 效果最优 / 最不破坏架构"口径）

- **不新增 HTTP API、不建 MCP server、不加新依赖**。「接口」= **文档契约 + 一个校验脚本**：
  - **入口契约** = `docs/PROJECT_GUIDE.md`（接手 agent 的唯一入口）；
  - **可执行约定（合并闸门）** = `tools/check_project.py`。
- 合并方式：**不引入复杂 git 流程**，靠「文件归属分区表 + 校验脚本」让并行成果干净落到同一项目。
- 归属判定：`PROJECT_GUIDE.md` 与 `DEV_PROMPT.md`/`PROGRESS.md` 同级 → **其他区（出仓）**；
  `tools/` 是"克隆后即需"的闸门 → **代码区（入仓）**。

### 改动

1. **新增 `docs/PROJECT_GUIDE.md`（其他区）** —— 项目总纲 / 接手接口，共 10 节：
   基本信息、架构（双层 + 目录树 + 6 区 + 入口）、技术方案（三通道/知识库/关闭钮注册表/navigate/脱困/22 种步骤）、
   进度摘要（指向 PROGRESS.md）、待办、**接手须知（必须阅读顺序+环境）**、开发标准（硬性约束/踩坑）、
   **日常开发工作流**（修 bug / 加功能 / 采集 / 交付四套流程）、**文件归属分区表（A~J 区，谁能改哪些文件）**、
   合并闸门与检查清单。
2. **新增 `tools/check_project.py`（代码区）** —— 合并闸门，静态三查 + 地图：
   ① `flows/**/*.json` 与 `data/*.json` 全部可解析；② 递归比对流程里所有 `type` 是否在
   **从 `ocr_engine.py` 实时提取**的步骤类型集合内（防 typo/未支持步骤，避免硬编码漂移）；
   ③ 代码区全部 `.py` 用内置 `compile` 做语法校验（不落 `.pyc`）；④ 文档同步软提示。
   附 `--map` 打印项目地图（目录职责/常用命令），供接手 agent 秒级定位；`-v` 逐项明细；退出码 0/1。
3. **同步 6 区契约**：`docs/DEV_PROMPT.md` 的 6 区表——代码区补 `community_like.py` 与 `tools/`、
   其他区补 `PROJECT_GUIDE.md`；「必须阅读」加为第 0 条；「交付规范」加第 0 条"过合并闸门"。
   `.gitignore` 其他区加 `docs/PROJECT_GUIDE.md`；`README.md` 目录树补 `tools/`。

### 验证

- **实跑（闸门）**：`& ".venv\Scripts\python.exe" tools\check_project.py` →
  JSON **14/14** 可解析；步骤类型 **22 种**、流程中检查 **220 处**、未知 **0** 处；语法 **7/7** 通过；**退出码 0**。
- **负向测试**：临时造 `flows/_gate_selftest.json`（含错字 `click_txt`）→ 闸门精确报
  `[步骤] 未知步骤类型 'click_txt' @ flows\_gate_selftest.json.steps[0]`、**退出码 1**；测毕已删该临时文件。
- **归属校验**：`git check-ignore -v docs/PROJECT_GUIDE.md` 命中（出仓）；`git status` 显示 `tools/` 为
  待跟踪（入仓）——与设计一致。
- **`--map`**：正常打印项目地图。

### 待办

- 无（本里程碑为接口/文档类，无实机项）。后续里程碑请按 `PROJECT_GUIDE.md` §8 工作流执行，收尾过 §10 闸门。

---

## 2026-10-01 · 其他 agent 协作开发区 + 闸门预检（里程碑 66）

用户需求：新增一个**协作开发区** —— 其他 agent **只能在该区域内开发**，之后**等待合并**（新区域）。

### 决策

- 物理位置 `FAA_basis/_collab/`（工作区根，与代码区同级，**出仓**），与 `_dev/` `_test/` `_backup/` 同属出仓区；
  这样"其他 agent 只能在此写文件"是**物理约束**（不在 git 仓库内，不会直接改到代码区）。
- 区内结构：`inbox/`（待合并，一人一子目录）+ `merged/`（已合并归档）+ `README.md`（规则/格式/流程）。
- 提交格式：`inbox/<agent>/files/` 按**仓库相对路径**放拟合并文件（`files/flows/x.json` → `flows/x.json`）
  + `REPORT.md`（改动/验证/待定标项）+ `evidence/`（可选）。
- 分区契约由 **6 区 → 7 区**。

### 改动

1. **新建 `FAA_basis/_collab/`**：`inbox/`、`merged/`、`README.md`。README 写明硬性规则
   （只在本区写文件 / 可读可跑主项目 / 完成后停下等合并 / 主项目开发标准同样适用 / 新步骤类型须随引擎补丁）、
   提交格式、**合并流程（主 agent 执行）**、提交前自检清单。
2. **`tools/check_project.py` 增加第 5 项「协作开发区预检」**：`_collab/inbox/**` 的 JSON **硬判**可解析
   + 步骤类型**软提示**（其他 agent 可能随引擎补丁一并合并）+ 打印「待合并清单」（缺 `files/` 或 `REPORT.md` 标 ⚠）；
   `--map` 与模块文档串补上 `_collab`。
3. **契约同步**：`docs/DEV_PROMPT.md`（标题 6 区→7 区 + 新增「协作开发区」行 + 新增约束条）、
   `.gitignore` 头注释；`docs/PROJECT_GUIDE.md`（§2.3 分区表 + §6 新增「其他 agent」段 + §8.5 协作开发流程 +
   §9 新增 **K 区** + §10 第 4 项与检查清单）。
4. **顺手更正 + 销项**：`PROJECT_GUIDE §5 待办` 中「修正流程名匹配歧义」经查**代码已实现**
   （`ocr_engine.select_flow` 已是“精确名优先 + 子串次之”，L1820），标为已完成；同时把 `PROGRESS.md`
   §4 该条**销项**（`[ ] → [x]`，附实现位置 L1820-L1833），并把 §5 技术要点中的同项描述同步为“已修”。

### 验证

- **闸门实跑**：`.venv\Scripts\python.exe tools\check_project.py` → JSON **14/14**、步骤 **22 种 / 220 处 / 0 未知**、
  语法 **7/7**、协作区「**待合并 0 份 / 已归档 0 份**」、**退出码 0**。
- **负向测试**：在 `_collab/inbox/_selftest/bad.json` 造非法 JSON → 闸门精确报
  `[协作区] JSON 解析失败: …\_collab\inbox\_selftest\bad.json -> Illegal trailing comma …`、
  同时列出「待合并 1 份」、**退出码 1**；测毕已删该目录（`_collab/` 现仅 inbox/ merged/ README.md 三项）。
- **越界自证**：`_collab/` 位于仓库之外，主仓 `git status` 不会因其他 agent 在协作区写文件而变化 —— 物理隔离成立。

### 待办

- 无。后续其他 agent 的成果按 `_collab/README.md` §4 的合并流程处理（读 REPORT → 落位 → 过闸门 → 归档 `merged/`）。

---

## 2026-10-02 · 协作区合并：日志生命周期修复 + 全项目 Bug 修复（里程碑 67）

**来源**：协作开发区 `_collab/inbox/` **两支**其他 agent 提交，按 `_collab/README.md` §4 合并流程评审后合并。

### 提交内容

1. **`trae-log-20261001`（日志生命周期）** —— 需求#4：服务每次启动**清空**日志缓存，
   修「重开 webui 仍看到上一次会话残留日志」。改 `webui.py`：
   `_log_reload_history()`（启动载回历史）→ **`_log_reset_history()`**（`_LOGS.clear()` + 磁盘 `data/webui_runtime_log.txt` 以 `"w"` 截断重建）；
   同步更新 `_LOG_FILE` 注释与 `_log_download` docstring；`main()` 调用点改名。
2. **`trae-bugfix-20261001`（全项目审查 Bug 修复）** —— 通读代码区全量 Python/HTML/flows 后产出 BUG-1~6 修复（BUG-7~10 仅记录）：
   - `webui.py`：**BUG-1** `_run`/`_run_daily_sel` 加并发守卫（`if _running(): 409`）；**BUG-3** `_tplt_load` 由 `startswith` 前缀比较改为 `Path.relative_to`（防 `debug_evil/` 兄弟目录绕过）。
   - `webui.html`：**BUG-1** `refreshStatus` 按 `s.running` 同步 `run-btn`/`maa-start` 的 disabled，onclick 立即禁用、失败恢复；**BUG-4** 点「运行」不再重置 `logCursor`/`logChunks`（只清 DOM 显示），避免 `cursor=0` 把服务端全量历史重新拉回。
   - `ocr_engine.py`：**BUG-2** `run_module` 找不到流程文件时 `return "fail"`（原只打警告仍误报 "ok"）；**BUG-6** `click_text` 回退链改用 `.get("rel")`（防旧格式条目 `KeyError`）。
   - `community_like.py`：**BUG-5** `like_some` 去重 `gap` 由硬编码 `1280` 改为 `eng.screen_w`，与 `like_at` 判定统一按实际屏宽。

### 冲突处理

- 两支**都改 `webui.py`**，但改动区域**互不重叠**（log 改日志生命周期 4 处 / bugfix 改 `_tplt_load`、`_run`、`_run_daily_sel` 3 处）。
  合并为同一文件后，分别对两支原件做 `git diff --no-index` 复核：`merged↔log` 仅剩 bugfix 的 9 增 1 删、`merged↔bugfix` 仅剩 log 的改动 —— 两边改动均已完整保留、无覆盖。

### 验证

- **闸门（合并后实跑）**：`& ".venv\Scripts\python.exe" tools\check_project.py` →
  JSON **14/14**、步骤类型 **22 种 / 220 处 / 0 未知**、语法 **7/7**、协作区「待合并 2 份」、**退出码 0**。
- **日志行为（合并后的 webui.py 落入隔离测试台 `_collab/…/evidence/testbed`，桩引擎）** → **10/10 PASS**：
  预置磁盘残留 JUNK → 启动后 `/api/log?after=0` 与磁盘文件均无 JUNK（截断生效）；会话中日志在页面重开时能全量拉回；**重启后无上一会话日志**、仍见本次启动横幅。
- **BUG-1 / BUG-3（合并后的 webui.py 起真实 HTTP 服务，临时测试台 `%TEMP%\faa_merge_verify`）** → **8/8 PASS**：
  运行中二次 `/api/run`、`/api/run_daily` 均 **409**；结束后可再次提交；`../ocr_engine.py` 与兄弟目录 `debug_evil/x.png` 均 **400「仅允许载入 debug/」**；`debug/nope.png`、`debug`（目录本身）报 **「文件不存在」**。
- **BUG-2 / BUG-6（导入真实 `ocr_engine.py`）** → **4/4 PASS**：`run_module({"flow":"flow_not_exist.json"})` 返回 `'fail'`；`click_text` 源码已无裸 `["rel"]` 取值。
- **BUG-5（静态）**：`eng.screen_w` 确实存在（`OCREngine` L110 初始化、L403 按截图尺寸赋值），gap 与 `like_at` 现已统一按实际屏宽。

### 待办 / 遗留

- **仅记录未修**（bugfix REPORT 中 BUG-7~10，本轮**未纳入**提交，保持提交范围不扩）：
  BUG-7 `pollin.collect_one` 快捷操作 toggle 重试可能把已开菜单点关；BUG-8 `flow_social.json` 占位 `if_config` 与正式功能写法相反；
  BUG-9 `webui.html` `pollLog` 成功行样式三元两分支皆空串（死代码）；BUG-10 `/api/log` 的 `after` 参数未防御负数。
  待用户决定是否另起修复。
- **待真机复核（未连 MuMu/浏览器）**：BUG-1 前端按钮 disabled 的实际观感、BUG-4 点「运行」后旧日志确不复现 —— 属前端行为，建议真机各复核一次。
- `docs/FLOWS.md` 本次**无需改动**（未改任何 flow；BUG-2 使 `run_module` 缺文件返回 `fail`，与 §0 已述「模块失败仅跳过(on_fail:skip)」语义一致，是代码向文档收敛）。

### 归档

- `_collab/inbox/trae-log-20261001/`、`_collab/inbox/trae-bugfix-20261001/` 已整体移入 `_collab/merged/`。

---

## 2026-10-02 · 性能收敛 + 采粉提速 + 奖励领取归位 + 失败提醒（里程碑 68）

**来源**：用户对一次真实运行日志（`faa_log_20261002_234848.txt`，22:41:39→23:40:00 = 58m21s）提出三个问题：
① 单轮平均 CPU >50%（R9 7845HX / 12C24T / 4.6GHz）不可接受，**要求把「优化性能开销」写成项目长期目标**；
② 好友采粉耗时太长（本轮 social 47m36s 占 81%，其中采粉约 46 分钟）；
③ 奖励领取功能几乎全未触发，并**要求加两个调试设置**（失败即提醒 / 每步截图）。

上一轮经 `AskUserQuestion` 确认的三项决策：预览轮询 → **按需 OCR**；每步截图 → **暂时记为待办、先不实现**；失败提醒 → **运行时弹窗**。

### ① 性能：预览按需 OCR（「CPU >50%」主凶）

- **根因**：WebUI `GET /api/screen` 每帧都做一次**全屏 OCR** 并返回文字框，前端每 1.5s 拉一次 → 单轮 **1183 次全屏 OCR**，
  且与引擎抢同一把 `ENGINE_LOCK`（串行等待放大卡顿）。
- **修复**：
  - `webui.py`：`_screen()` 只回 `jpeg/w/h`（去掉 `boxes`）；新增 `_ocr()`（截图 + `_ocr_boxes`）与路由 `GET /api/ocr`。
  - `webui.html`：`refreshScreen()` 只取图像；文字框走新增的**按需** `refreshBoxes()`（仅勾选「OCR标注(按需)」或手动「取框」时调一次）；
    `ocr-chk` 默认不勾选；`visibilitychange` 后台暂停预览与日志轮询；`pollLog` 后台降频 1500ms。
- **长期目标落文档**：`docs/PROJECT_GUIDE.md` 新增 **§11 性能目标与基准**（基准表 / 预算表 / 五条硬性设计原则），
  §5 🔴 高优先级与 §7 开发标准同步加入；`docs/DEV_PROMPT.md` 硬性约束加性能预算条目。

### ② 好友采粉提速（`pollin.py`）

- **同页重复全页扫描**：旧版内层 `while True` **每采一个好友就重扫一次本页全页模板**（单轮共 24 次，相邻两次常隔 130~295s）。
  → 改为 `run_category` **每页只 `scan_marks` 一次**，候选按 y 升序 + `seen` 槽位去重后逐个 `collect_one`；
  仅在「后续还有候选」时才回列表翻页（去掉末尾多余的开列表+翻页）。
- **点「采粉」后固定等 45s**：→ 改为取一帧 `base`，用新增 `frame_diff`（缩到 96×54 灰度 absdiff 均值）等画面变化、
  **变化即返回**（上限 20s），变化后只做**一次**确认 OCR。20s 无变化如实报「点击可能被吞」并跳过本槽位。
- **判据强化 + 离开好友列表**：`in_home` 先 `in_list`（『删除好友』/『好友设置』）判否再看「社交」；
  `ensure_home` 若仍在列表则走新增 `leave_friend_list`。根因是好友列表底部导航同样有「社交」，旧 `in_home` 把列表误判成主界面。

### ③ 奖励领取归位（`flow_claim.json` + 引擎新步骤）

- **现象**：本轮奖励领取几乎全未触发。根因：social 采粉结束停在**好友列表**，`in_home` 误判为主界面 → `ensure_home` 直接收工 →
  领取奖励三个入口（在线礼包/花灵派对/奇妙花宝）都只在家园主界面可见 → 整段空跑。
- **修复**：`flow_claim.json` `steps` **首步**新增 `{"type":"ensure_home"}` 归位守卫；
  引擎 `ocr_engine.py` 新增步骤类型 **`ensure_home`**（调 `pollin.ensure_home`，失败 `report_failure` 如实报出），步骤总数 **22 → 23**。

### ④ 失败即提醒（运行时弹窗）

- **引擎侧**：新增模块级失败登记 `report_failure(module, detail)`（打印 `[失败] [模块] 详情` → 日志可搜，同时进内存清单 `get_failures(after)` / `clear_failures()`）。
  已埋点：`wait_text`/`wait_text_gone` 超时、`loop_text` 达上限、`retry_loop` 跑满未命中（可 `"report_fail": false` 免打扰）、
  `navigate` 未找到目标/轮数耗尽、`run_module` 流程缺失/异常、`friend_pollin` 有类别未跑通、`ensure_home` 未归位。
- **WebUI 侧**：新增 `GET /api/failures?after=<id>`（增量，`after` 用 `max(0,...)` 防负）与 `POST /api/failures_clear`；
  前端右下角新增「功能失败提醒」弹窗，`refreshStatus` 顺带轮询、有新失败即弹出，可「已知悉，清空列表」。

### ⑤ 每步截图调试 —— 仅记为待办（用户决策：暂不实现）

- 已写入 `docs/PROJECT_GUIDE.md` §5 🟠 中优先级：「调试：每步截图（环形缓冲 + 可开关）…用户 2026-10-02 定为待办、暂不实现」。

### 验证

- **闸门（实跑）**：`& ".venv\Scripts\python.exe" tools\check_project.py` →
  JSON **14/14**、步骤类型 **23 种 / 221 处 / 0 未知**、语法 **7/7**、协作区「待合并 0 份」、**退出码 0**。
- **文档同步**：`docs/FLOWS.md` §4.2（每页只扫一次 / 变化即返回 / 判据强化+离开列表）、§7.0（归位守卫）、
  §10（步骤表 22→23 + `ensure_home` 说明 + 失败上报/弹窗 + 预览按需 OCR）、§10.1（「社交」不足以判定主界面）；
  `docs/PROJECT_GUIDE.md` §11；`docs/DEV_PROMPT.md`。

### 待办 / 待实机校准

- **待实机验证**（本轮未连 MuMu）：采粉提速后的实际耗时、`frame_diff` 阈值 0.02 是否合适、领取奖励归位守卫是否真归位、
  WebUI 失败弹窗观感与 `/api/ocr` 按需取框。
- **`leave_friend_list` 的关闭出口是推断**（右上角关闭区 / 底部栏「离开」），好友列表真实关闭钮位置**尚未采集**，代码注释已标「待实机校准」。
- `RapidOCR` 参数（未设线程数 / 检测边长，目前全分辨率）未调，属性能长期目标后续项（见 PROJECT_GUIDE §11）。
- BUG-10（`/api/log` 的 `after` 未防负数）仍未修；`[未知步骤] None` 噪音未修；git 仍**未 commit**。

---

## 2026-10-03 · 切换账号误登录修复：禁止缓存回退 + 主动判失败 + startup 终止本轮（里程碑 69）

**来源**：用户报告 BUG ——「切换账号按钮没有检测到，点击缓存位置时，会直接点击登录，从而影响后续的全部检测」，
附运行日志 `faa_log_20261003_004410.txt`（00:42:45 启动，00:44:03 用户手动 `POST /api/stop` 中断）。

**用户决策（`AskUserQuestion`）**：① 折角图标改版后的真实形态/坐标 → **用户自己用 `/tpltool` 采集**；
② 若「切换账号」失败（未展开列表/未找到目标账号）→ **如实上报并中止 startup**（不继续点「登录」；
宁可当天不跑，也不能用错误账号跑完当天全部任务）。

### ① 根因：三层链式失效

1. **图形按钮 OCR 永不可达**：「切换账号」是无可读文字的灰色折角图标，`click_text(['切换账号'])` 的 OCR 通道每轮必 MISS。
2. **回退链命中毒坐标**：OCR 未命中 → 走缓存回退 → 用历史坐标 rel(0.7727,0.3944) → 绝对 **(989,283)**；
   而 2026-08-23 定稿的 `b1_switch_down.png`（36×21px）当时命中的正是这一点 —— **登录页改版后该点已变成「登录」按钮**
   （日志 L56–59：点击成功 → 实际误登录）。
3. **毒坐标自我强化**：`_log_click` 原来只挡「已有 ocr/color/anchor 条目」的情形；旧条目本身就是 `fallback` 时**会再次落库**，
   于是「认不到 → 盲点 → 盲点坐标被写回知识库 → 下次继续盲点」形成闭环。
   直接后果：误登录后公告/进入游戏/收尾守卫全部空转（`if_text(['登录']) -> MISS`，公告 retry_loop 8 轮全 MISS），
   且 `daily.json` 里 startup 是 `on_fail:skip` → **后续 7 个模块继续跑**，即用户所说的「影响后续的全部检测」。

### ② 引擎修复（与坐标无关的缺陷，`ocr_engine.py`）

- **`_log_click`：`method=="fallback"` 一律不落库**（回退坐标永远不是位置证据，不得据以续传）。
- **回退查找跳过 `method=="fallback"` 的历史条目**（否则一次「没识别到就盲点」会把错坐标反复续传）。
- **新增 `no_fallback` 步骤选项**（`click_text` / `click_template`）：OCR/锚点/颜色全未命中就直接如实返回失败，
  不采信任何历史坐标盲点。用于「点错后果严重」的高危按钮。
- **新增 `FlowFailed` + `fail_flow` 步骤类型**：`{"type":"fail_flow","reason":"..."}` 抛 `FlowFailed`（继承 `Exception`），
  `run_module` 新增 `except FlowFailed` 分支 → 收成 `"fail"` + `report_failure`（单跑流程时 `run_flow` 也接住）。
  用于「前置条件不满足时主动中止，避免带着错前提继续跑出一整轮假结果」。步骤总数 **23 → 24**。
- **新增 `abort_on_fail` 步骤选项**（`click_text` / `click_template` / `click_account_tail`，前者可配 `abort_reason`）：
  该步骤失败即 `raise FlowFailed` 中止本模块，不再往下执行。
- `click_account_tail` 找不到目标账号时改为 `report_failure` 如实上报（此前只 print，不进失败清单）。

### ③ 知识库清理（`data/click_log.json`）

- `登录界面` 的「切换账号」anchor 条目（rel 0.7742,0.3986 + anchor 基于 `****` 与「登录」偏移）**已过时且有害**：
  改名 `切换账号_已失效_待重采` 并置 `method=disabled`，使其退出可复用键名（引擎只按原键名索引，不会再被任何通道取用）；
  `未分类` / `体力界面` 两条 `method=fallback` 的「切换账号」毒条目删除。

### ④ 流程改造

- **`flows/flow_startup.json`**：切号链改为 fail-safe ——
  `click_text(['切换账号','切换'], region_rel=[0.85,0.05,1.0,0.30], min_score=0.5, no_fallback=true, abort_on_fail=true)`
  → `click_account_tail(tail=${target_tail}, region_rel=[0.80,0.03,1.0,0.65], min_score=0.4, abort_on_fail=true)`。
  关键词给新旧两种：2026-10-03 日志显示改版后该处可 OCR 到「切换」@(1227,111)=rel(0.959,0.154)。
- **`flows/daily.json`**：`startup` 的 `on_fail` 由 `skip` 改为 **`stop_round`** —— 登录/切号没做成时直接终止本轮，
  不再让后续模块在登录页/错误账号上空跑。

### 验证

- **闸门（实跑）**：`& ".venv\Scripts\python.exe" tools\check_project.py` →
  JSON **14/14**、步骤类型 **24 种 / 221 处 / 0 未知**、语法 **7/7**、协作区「待合并 0 份」、**退出码 0**。
- **文档同步**：`docs/FLOWS.md` §0（startup 必须 stop_round）、§1（切号 fail-safe + 故障复盘）、
  §10（步骤表 23→24 + `fail_flow`/`no_fallback`/`abort_on_fail` 说明）。

### 待办 / 待实机校准

- **`region_rel` 与关键词「切换」是据 2026-10-03 日志推断**（登录页右上入口区、改版后账号列表区），
  **待用户用 `/tpltool` 采集新折角图标模板后复核**，届时把 `click_text` 换成 `click_template`。
- `click_account_tail` 目前**只认含 `****` 的脱敏账号块**（防误点普通数字，是安全性设计）；
  若改版后账号列表改为显示完整 ID（2026-10-03 日志里玩家 ID/昵称均未脱敏），则切号必然失败 → 如实中止 startup。
  是否放宽匹配待实机确认，**不放宽之前不会误点**。
- 本轮**未连 MuMu 实跑**；未 git commit。

---

## 2026-10-03 · 「记录按钮位置 / 使用缓存位置」做成开关（默认关闭）（里程碑 70）

**来源**：用户请求 ——「把记录按钮位置、使用缓存位置这两个设置做成可开关的，然后默认关闭，
目前这两个设置 bug 有一点多。把完善这两个设置记入待办。」

**背景**：里程碑 69 的「切换账号误登录」根因正是「运行时把点到的坐标写进知识库」+「认不到就用历史坐标回退盲点」
这两条链路互相咬合（错坐标被反复放大）。故先把它们各自做成全局开关、**默认关闭**，
让运行时只认本次实时识别，坐标样本改由用户显式开启后再积累。

### ① 新增两个全局开关（`data/config.json`，均默认 `false`）

| 键 | 名称 | `false`（默认）时的行为 |
|---|---|---|
| `log_click_pos` | 记录按钮位置 | `_log_click` 直接返回，运行时不把点击坐标写入知识库 `data/click_log.json` |
| `use_cache_pos` | 使用缓存位置 | `click_text` 不做均值复核，回退链不查自动缓存（`mean_rel`/`last_rel`/知识库 `rel`）→ 认不到就如实失败 |

- **`log_click_pos=false` 只挡「引擎运行时的自动记录」**：人工标注（`/tpltool` 提交后写库）或直接编辑
  `data/click_log.json` 是用户显式动作，不受此开关影响。
- **`use_cache_pos=false` 只挡「自动学习到的历史坐标」**：步骤里**显式手写的 `fallback_rel` 仍生效** ——
  flows 中有数十处人工兜底（`flow_claim` / `common/entries` / `flow_startup` / `flow_plant` / `flow_energy` / `flow_social`），
  全局开关**不得静默禁用**它们；步骤级 `no_fallback=true` 才是更严格的一档（连显式 `fallback_rel` 一并禁用）。
- 两个「已关闭」提示各**只打印一次**（`_logpos_notice_done` / `_cachepos_notice_done`），避免每次点击刷屏把日志淹掉。

### ② 实现落点

- **`ocr_engine.py`**：
  - `_log_click` 开头加 `log_click_pos` 门控（+ 一次性提示），docstring 同步；
  - `click_text` 拆成两段式门控 —— `no_fallback`（禁一切回退坐标）与 `use_cache_pos=false`（只禁自动缓存查找）分离；
    OCR 命中段的「均值复核」按 `use_cache` 门控并加一次性提示；docstring 同步说明「显式 `fallback_rel` 仍生效」。
  - `click_template` 保持**只判 `no_fallback`**（其 `fallback_rel` 全是人工手写兜底，不接全局开关）。
- **`webui.py`**：`GET /api/config` 与 `GET /api/daily` 回显两个键；`POST /api/set_config` 接收并 `update_config`
  （日志打印「记录按钮位置=开/关, 使用缓存位置=开/关」）。
- **`webui.html`**：右栏「连接设置」与「今日小提示」之间新增**「识别设置」面板**（两个复选框 + 说明），
  `refreshMaa()` 回显，`onchange` 即时 `POST /api/set_config` 持久化。

### 验证

- **闸门（实跑）**：`& ".venv\Scripts\python.exe" tools\check_project.py` →
  JSON **14/14**、步骤类型 **24 种 / 221 处 / 0 未知**、语法 **7/7**、协作区「待合并 0 份」、**退出码 0**。
- **离线实跑**（无设备）：`OCREngine` 载入 `data/config.json` 后两开关读到 `False`；
  关闭态下 `_log_click` 不落库（打印一次性提示）、`click_text` 未命中时打印
  `(use_cache_pos=false: 不用自动缓存的历史坐标, 交调用方处置)` 并返回 `False`（不盲点）。

### 待办

- 「完善这两个设置」已记入 `docs/PROJECT_GUIDE.md` §5（中优先级）：
  ① fallback 不落库/回退跳过 fallback 条目的防御是否覆盖全部"错坐标续传"路径；
  ② 「记录」关掉后 `mean_rel` 均值样本不再更新 → 再开「使用缓存位置」会用到过期均值；
  ③ 知识库 `method="disabled"`（如「切换账号_已失效_待重采」）只靠改名退出索引，语义太脆弱，需正式失效标记；
  ④ 两开关 × 步骤级 `no_fallback` × `mark_fallback_rel`/`fallback_rel` 的交互矩阵补文档与用例。
- 本轮**未连 MuMu 实跑**；未 git commit。

---

## 2026-10-03 · 合并协作区 zcode-20261003：OCR 性能收敛（线程上限 + 同帧复用 + 预览零截图）（里程碑 71）

**来源**：协作 agent `zcode` 提交 `_collab/inbox/zcode-20261003/`（任务来源「项目启动后占用 CPU 过高」），
对应 §5 🔴「性能开销优化」原收敛点 ①②③。

### ① 审阅（合并前）

- `REPORT.md` 与 `files/` 一致（4 个文件：`ocr_ui.py` / `ocr_engine.py` / `webui.py` / `data/config.example.json`）。
- **冲突核对**：`git diff --no-index` 逐文件比对 zcode 版本与当前主仓库版本 —— zcode 快照**已包含里程碑 69/70**
  （`FlowFailed`/`fail_flow`/`abort_on_fail`/`log_click_pos`/`use_cache_pos`/`_logpos_notice_done` 全部在），
  差异**纯增量**（`ocr_ui.py` +29/−0；`webui.py` 仅 `_screen`；`ocr_engine.py` 为 `_ocr_frame` 重构），
  **不回退既有修复**，可按相对路径覆盖。
- ⚠ `files/__pycache__/*.pyc` 属构建产物，**不合并**（已删除）。
- ⚠ `evidence/` 两个基准文件末尾各有一段 traceback（离线无 ADB 时脚本收尾所致），
  报告称「`detect_scene` 同帧复用 ✓」在证据中未跑完 → **由主 agent 自行复验**（见下）。

### ② 合并内容

- **`ocr_ui.py`（最大头）**：RapidOCR 1.2.3 的 `OrtInferSession` 内部自建 `SessionOptions`、未暴露线程配置，
  默认吃满全部物理核。改为在 `get_engine()` 首次建引擎前对 `rapidocr_onnxruntime.utils.SessionOptions` 做
  **受控包装**（`intra_op_num_threads=2` / `inter_op_num_threads=1`，det/cls/rec 三个 ONNX 会话全部生效），
  并新增 `set_thread_limit(n)`；可用环境变量 `FAA_OCR_THREADS` 或 `data/config.json` 的 `ocr_threads` 调整，
  **`0` = 不限制（天然回滚开关）**。
- **`ocr_engine.py`**：新增 `_frame_hash` + `_ocr_frame(img) -> (全图块, 过宽块子块)`（blake2b-128 全帧指纹，
  同帧直接复用上次结果；画面一变指纹必然失效，语义与逐次 OCR 完全一致），原 `find_text` 的
  「全图 OCR + 过宽块 2x 拆分」整段移入，并把 `locate_anchor_offset`/`click_account_tail`/`parse_fraction_at`/
  `parse_count_at`/`count_text`/`detect_scene` 一并接入；`screenshot()` 记录 `last_frame`/`last_frame_ts`；
  `__init__` 读取 `ocr_threads` 并调 `set_thread_limit`；新增 `_frame_lock` 串行化缓存读写（引擎被 WebUI 线程并发调用）。
- **`webui.py`**：`_screen()` 优先返回引擎 **2s 内**的 `last_frame`（只花 JPEG 编码、不碰 ADB），过期才自己截 ——
  空闲期行为不变、运行期预览零额外截图；同时**修正原 docstring 的错误说法**（`ENGINE_LOCK` 只用于引擎单例创建，
  预览的真实代价是自己 `post_screencap` 与引擎争抢 ADB 控制器）。
- **`data/config.example.json`**：新增 `ocr_threads`（默认 2）+ 注释（只增不改）。
- **`data/config.json`**（本机配置）：同步加入 `"ocr_threads": 2` 并在 `_comment` 说明（行为与代码默认一致）。

### ③ 主 agent 复验（离线，合并后实跑）

- **闸门**：`tools/check_project.py` → JSON **14/14**、步骤类型 **24 种 / 221 处 / 0 未知**、语法 **7/7**、退出码 **0**。
- **线程上限真的生效**：`ocr_ui._thread_limit` 默认 = 2；实际 `RapidOCR` 实例化成功；
  包装后的 `SessionOptions()` 返回 `intra_op_num_threads = 2 / inter_op = 1` ✓
- **同帧复用**（桩计数 `ocr_image` 调用次数）：同帧 `find_text` ×2 → **1 次**；换帧 → 2 次；
  **回旧帧 → 3 次**（单槽缓存被覆盖后正确重识别，无误用陈旧结果）✓
- **`detect_scene` 两标识同帧** → **1 次** OCR（原为 2）✓ —— 补上诉证据缺口。
- **里程碑 69/70 未被回退**：`log_click_pos=false` 下 `_log_click` 不落库；`use_cache_pos=false` 未命中**不盲点**；
  显式 `fallback_rel` 仍生效 ✓

### ④ 预期效果 / 待实机核对

- OCR 瞬时占用 **≈13 核 → ≈2 核**、CPU 时间 **−81%**；识别块与默认**逐块完全一致**（**不下调检测边长** ——
  实测 960/max 会在好友列表丢 5 块，影响采粉）。
- **待实机**：① 跑一轮核对单轮平均 CPU / 总耗时（对照 §11.1 的 58m21s）；② WebUI 运行期预览观感；
  ③ `last_frame` 若因截图库返回内部缓冲复用而花屏 → 改持 `img.copy()`（+1ms/次）；
  ④ 个别界面识别偏慢可调 `ocr_threads`（4 ≈ 4 核；`0` = 完全回旧行为）。

### ⑤ 文档同步

`docs/PROJECT_GUIDE.md` §5（原 ①②③ 销项 + 后续收敛口径）、§11.1（修正 `ENGINE_LOCK` 错误说法）、
**§11.4（新增：里程碑 71 收敛结果 + 基准表 + 待实机项）**、§11.3-6（新增「勿裸调 `ocr_image`」原则）；
`docs/DEV_PROMPT.md`（OCR 链路走 `_ocr_frame`、`ocr_threads` 开关）；`docs/FLOWS.md` §10（引擎侧性能优化说明 + 修正 `ENGINE_LOCK`）。
`flows/*.json` 未改动 → 无需同步流程章节。

- 本轮**未连 MuMu 实跑**；未 git commit。协作区目录已归档至 `_collab/merged/zcode-20261003/`。

---

## 2026-10-03 · 测试界面新增「清除日志」按钮（里程碑 72）

**来源**：用户请求 ——「给测试界面增加一个清除日志按钮，放在保存日志按钮旁边。」

### 实现

- **`webui.html`**：「运行日志」标题栏新增 `#log-clear`「清除日志」，`float:right` 放在「保存日志」**左侧**（同栏相邻）；
  `clearLog()` 先 `confirm`（清空不可恢复、且日志是排查主要依据 → 与「关闭服务确认」同一套谨慎口径），
  成功后清 `logChunks` + 把 `#log` 复位为「暂无日志」，并**把 `logCursor` 复位**。
- **`webui.py`**：新增 `POST /api/log_clear`（已同步 `_POST_ROUTES` 白名单）→ 复用 `_log_reset_history()`
  清空**内存缓冲 + 磁盘备份** `data/webui_runtime_log.txt`，再补一条标记日志，返回 `{"ok":true,"next":0}`。

### 为什么三处必须一起清（本次改动的关键设计点）

「保存日志」导出的是**服务端缓冲全量**（含页面打开之前的历史），所以：
- **只清前端 DOM** → 页面空的、导出却还是旧的（假清空）；
- **只清服务端** → `_LOGS` 下标归零，而前端 `logCursor` 还停在旧下标，下次 `GET /api/log?after=旧下标`
  会从**新缓冲中部**开始取 → 日志凭空缺一段（且不会自愈）。
故服务端清空后**回 `next=0`**、前端必须同步复位游标；补一条 `[webui] 运行日志已被手动清除 <时间>` 标记行，
让"清理确实生效、何时清理"可被验证（否则清空后一片空白，无从判断）。

### 验证（真机 WebUI + 浏览器实点）

- **接口级**（临时端口 8799 实跑）：清空前 `next=1`；`POST /api/log_clear` → `ok=True, next=0`；
  `?after=0` 取到标记行、`?after=1` 取 0 行（游标语义正确）；磁盘备份已截断且仅含标记行；
  `GET /api/log_clear` → 404（不会被误触发）。
- **浏览器实点**（browser_use 子代理）：两按钮并排顺序正确（清除在左/保存在右）→ 点击弹出 `确定清除日志？` 确认框 →
  确认后「服务启动」行消失、出现「运行日志已被手动清除」行 → **控制台零 JS 报错**。
- **闸门**：`tools/check_project.py` → JSON 14/14、步骤类型 24 种/221 处/0 未知、语法 7/7、退出码 0。

- 仅前端 + WebUI 后端，**未动 flows / 引擎**；未 git commit（WebUI 相关按约定只入 PROGRESS）。

---

## 2026-10-03 · 合并协作区两批提交（codeart A1–A3 + zcode A4/A5/A6/B + 卡死根因坐标回填）（里程碑 73）

**来源**：用户 ——「对协作agent-codeart和zcode提交的更新进行代码审阅与合并，其中 zcode 提交的内容是基于 codeart 进行的进一步开发」
（`_collab/inbox/codeart/` 与 `_collab/inbox/zcode-20261003-2/`，基线均为 `8586814` 里程碑 68-72）。

### 合并内容（两批补丁 + 一个整文件，共 8 处）

| 编号 | 作者 | 目标 | 内容 |
|---|---|---|---|
| A2 | codeart | `ocr_engine.run_module` | 去掉 `print(desc)`，模块 `description` 不再流入运行日志（治日志首屏污染） |
| A1 | codeart | `ocr_engine.run_module` | 收尾比对 `get_failures()` 增量：流程内 `report_failure` 软失败 → 如实返回 `fail`，交 `on_fail` 处置（治「`fail=0` 却有 8 条 `[失败]`」） |
| A3 | codeart | `ocr_engine` | 新增 `_ts()`；`run_daily`/`run_module`/`run_flow` 关键节点打 `[HH:MM:SS]`（energy/claim 耗时不再依赖 WebUI 轮询） |
| A4 | zcode | `ocr_engine._log_ocr_miss` | 同画面（帧指纹+exact+区域）重复 `[OCR未命中]` 折叠为「首条 + 每 10 次一行」，命中/换帧复位 |
| B | zcode | `ocr_engine.locate_template`/`_all` | **模板尺度自适应**：`scale_range` 按 `screen_w/1280` 缩放（720p 完全兼容，1080p 自动 ×1.5） |
| A6 | zcode | `pollin.ensure_home`/`leave_friend_list` | 三条**实测出口坐标** + `wait_screen_change` 画面变化复核 + 连续 2 次无变化快速如实失败 + `debug/escape_fail_*.png` 存证 |
| A5 | zcode | `flows/flow_social.json` | 浇水 `click_text(['浇水'])` 加 `exclude:['浇水次数']`（防子串命中「9浇水次数：」标签） |
| B1 | zcode | `flows/flow_social.json` | 委托子页退出 `(0.035,0.038)`→`(0.9010,0.1065)`；家族外壳 `close_family 模板`→`click_rel (0.9833,0.0509)`（各 2 处，含 `_note` 同步） |

### 冲突与取舍（审阅结论）

- **两批补丁无 hunk 冲突**：A2 与 A1/A3 在同一函数但改不同行（A1/A3 刻意避开 A2 的 `>>> 模块执行` 行），5 个补丁按
  A2→A1A3→A4→B→A6 顺序叠加 `git apply` 全部 `rc=0`、无 offset/fuzz；`flow_social.json` 为整文件替换，逐行比对为**纯增量**（9 增 17 删）。
- **保守取舍**：所有改动**均为纯增量**，未触碰里程碑 69/70 的门控区（`no_fallback`/`abort_on_fail`/`FlowFailed`/
  `log_click_pos`/`use_cache_pos`/`_logpos_notice_done`/`_cachepos_notice_done` 及 `method=="fallback"` 不落库逻辑）——
  离线断言逐项复核仍在。
- **A6 只做了 codeart 列表中的 ②③**（画面无变化守卫 + 退出后复查 `in_home`）；①「抬高 `if_text` `min_score` / `exact`」**未采纳**，
  因为 zcode 已用**实机实测出口坐标**消除根因（子页上 `['家族首页','家族排行']` 仍会假 HIT，但已先被 ①「委托排行/距离结束」退出，
  顺序保证不误点），抬阈值反而可能误伤正常命中。
- **A2 补丁文件缺末行换行符**（`git apply` 报 `corrupt patch at :13`）：合并时用补 Temp 副本追加 `\n` 后应用；
  **inbox 原件未改动**（保留提交原貌），已在 `merged/` 归档与下方「遗留」中记录。
- **`git apply` 受本机全局 `core.autocrlf=true` 影响会把 LF 补丁写成 CRLF**：应用后已把 `ocr_engine.py`/`pollin.py` 归一化回 **LF**
  （与仓库既有工作区一致；`flows/flow_social.json` 用字节拷贝保持 LF）。

### 验证（闸门 + 离线桩测，全绿）

- **合并闸门** `tools/check_project.py`：JSON **14/14**、步骤类型 **24 种 / 221 处 / 0 未知**、语法 **7/7**、退出码 **0**。
- **独立离线桩测（自写，不依赖提交方脚本）**：A2（`description` 不入日志、标题行保留）；A1（软失败 → `fail`；无软失败仍 `ok`）；
  A3（`_ts()` 形如 `HH:MM:SS` + 收尾行带时间戳）；里程碑 69/70 门控逐项断言仍在。
- **提交方桩测复跑（已审阅脚本，只读主仓库 + FakeEng）**：`faa_a4_test.py` 5 断言全过；`faa_a6_test.py` 3 场景全过
  （死出口 4 次点击即停并存证）；`faa_final_test.py` 三出口常量 = 实测值、**1080p 尺度自适应 `close_family` score 0.999 命中**
  （旧 scale 必 MISS）、`leave_friend_list` 主路径 = `rel(0.4313,0.4694)`。
- 均为离线验证；`debug/` 为出仓测试区，桩测存证图不纳入版本控制。

### 待实机回归（合并后跑一轮即可销项）

1. `--flow 社交`：委托子页退出链、好友列表退出、浇水 `water_count` 应从 0 变 1/3、A4 折叠生效；
2. 完整每日编排：`energy`/`claim` 应随卡死根因消除而恢复（B4–B6）；汇总 `fail` 数应与 `[失败]` 登记一致（A1 行为收紧：
   登记过软失败的模块会按其 `on_fail` 处置，`stop_round` 将终止本轮 —— 这是修复目标，非回归）；
3. `log_triage.py -m timing` 复核耗时 + CPU（对比 §11 基准）；
4. 若模拟器保持/切回 720p：相对坐标与尺度自适应均自动兼容。

### 归档与文档

- 两份 inbox 归档至 `_collab/merged/codeart-20261003/` 与 `_collab/merged/zcode-20261003-2/`（`inbox/` 已清空，剔除 `__pycache__`）。
- 同步 `docs/FLOWS.md` §4.1.1/§4.1.2/§4.1 收尾/§4.2/§10/§10.1；本地更新 `docs/PROJECT_GUIDE.md` §3.1/§3.5/§5 与 `docs/DEV_PROMPT.md` 硬性约束/常用命令。
- 未处理（非本轮范围）：P2-02/P2-03/P2-04 中的日志工具覆盖与 `data/click_log.json` 失效条目清理；B7 搭配界面语义待人工确认。

