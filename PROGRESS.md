# FlowerAutoAssistant (FAA) 项目进度与任务

> **用法（重要）**：这是项目的"活文档"。**每次运行/开始新任务前，先读本文件**了解当前状态与未完成任务；每次里程碑完成后更新它并勾选任务。保持本文件为当前真实进度的唯一权威来源。

---

## 1. 项目目标
为页游《小花仙》实现一键挂机（收获/种植/浇水等）。长期对标 MAA 质量，但**技术路线已切换**（见下）。

### 📌 技术路线（2026-08-22 确定，已弃用 MAA 模板匹配路线）
**改为 "OCR 文字定位 + 相对坐标" 数据驱动方案**，与 MAA 模板匹配区分：

- **核心思想**：每次运行时用 OCR 识别界面文字 → 定位文字中心坐标 → 归一化为**相对坐标**（×屏宽高 / 屏高）。**相对位置不受屏幕尺寸变化影响**。定点时 `相对 × 当前屏尺寸` → 点击。
- **三通道回退**：`click_text()` 依次尝试 **① OCR 文字定位 → ② 颜色特征定位（无文字图形按钮）→ ③ 坐标锚点（click_log 知识库）**。
- **知识库自积累**：每次点击成功后自动把「按钮名 → 相对坐标/绝对坐标 → 界面」写入 `data/click_log.json`，同名按钮只保留最新。

### 技术栈
- Python 3.11+ / **MaaFw（新版 maa Python 接口，spawn+tasker）** / OpenCV / RapidOCR / MuMu 模拟器 12
- 当前模拟器：`127.0.0.1:16384`
- 画面坐标系：**1280×720 横屏**；截图 `shape=(720,1280,3)`；点击 `x∈[0,1280), y∈[0,720)`；相对坐标归一化 0~1

---

## 2. 当前进度（AS OF 2026-08-22）

### ✅ 已完成
1. **连接与截图链路**：Tasker 连接 `127.0.0.1:16384` 成功，截图 1280×720 成功。
2. **OCR 单例**（[ocr_ui.py](ocr_ui.py)）：RapidOCR 引擎**进程内只初始化一次**（单例复用），避免每次调用重复加载模型/触发权限。
3. **核心引擎**（[ocr_engine.py](ocr_engine.py)）：连接/截图/`ocr_image`/`find_text`/`locate`/`locate_color`/`click_abs`/`click_rel`/`click_text`(三通道回退)/`collect_ui`/流程执行(`--flow`)。
4. **三通道识别全部验证成功**：
   - OCR 定位并点击「家园」「一键种植」（种植箱→一键种植两按钮已靠坐标锚点正确区分）
   - **关闭按钮**（右上角粉色四瓣花形，**无文字**）→ 用**颜色特征**（HSV 粉色过滤 + 连通区域）定位点击成功，界面从种植面板返回家园 ✅
   - 坐标锚点回退：OCR 漏识别"一键种植"的"一"时，靠 click_log 相对坐标仍稳定点击 ✅
5. **知识库自动采集**：`collect_ui()` 一键采集当前界面所有文字块（相对坐标）写入 `data/click_log.json`（当前含种植界面 50+ 按钮）。
6. **界面采集进度**：已进入家园、种植操作界面，识别到核心作业按钮（见第 3 节）。
7. **主循环 `main.py` 已构建并端到端验证成功**：
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
     - `corner`：整体画面右上角按颜色找关闭（种植面板式，region_rel 相对区域）
   - `find_close_button()` 遍历注册表返回首个命中的关闭按钮；`close_dialog()` 改为调用它（`--flow`/`loop` 步骤 `close_dialog` 自动生效）。
   - CLI 扩展：`--close-test`（仅定位打印不点击）、`--add-close <名称> <corner|anchor_color>`（后续新增关闭按钮用）。
   - 实测：`--close-test` 当前画面右上角逻辑命中候选 (1265,107) rel(0.988,0.149)，是否真实关闭按钮需种植面板内肉眼复核。

10. **✅ 体力任务模块首链跑通**（AS OF 2026-08-22）：
   - `--flow 体力任务 --loop 1` 实测（用 `-u` 无缓冲）：6 次 `close_dialog` 未命中弹窗（无「提示」，符合预期）；`if_text 闪耀变身 → HIT`，OCR 定位 (134,450) rel(0.1047,0.625) 并点击成功，流程退出码 0。
   - 注意：进程无输出多为 Python 输出缓冲所致，命令需加 `-u`。

11. **✅ 新增步骤类型 `if_fraction` + 体力任务逻辑4**（AS OF 2026-08-22）：
   - 引擎新增 `parse_fraction_at()`（OCR 找距 `region_rel` 最近的 `a/b` 数字块）/ `eval_fraction()`（用变量 a=分子、b=分母 求值 condition，如 `a<b`、`a>=20`），`run_step` 支持 `if_fraction` 分支。
   - `flow_energy.json` 逻辑4：①顶栏 `(0.598,0.038)` 读到 `a/b`，`a<b` 才继续；②顶栏 `(0.860,0.038)` 读到 `c/d`，`c>=20` 才继续；③两项都满足则点「光偶像」(fallback_rel [0.0508,0.5417])。
   - 实测：当前闪耀变身页 `(0.598,0.038)=342/600`→`a<b` TRUE、`(0.860,0.038)=100/100`→`a>=20` TRUE。

12. **✅ OCR 扫描开发工具 `--ocr-screen` + 区域文本判断 + 体力任务逻辑5**（AS OF 2026-08-22）：
   - 新增 CLI `--ocr-screen`：连接→截图→一次OCR→打印当前画面**所有字符及相对坐标**（不写入知识库），替代临时脚本，供开发采集坐标用。
   - `find_text()`/`locate()`/`if_text` 支持 `region_rel=[x1,y1,x2,y2]`：只在指定区域做文本判断（避免全局同名误命中）。
   - `flow_energy.json` 逻辑5：①区域 `(0.05,0.86,0.18,0.94)` 含「成为最闪耀明星」则点 (0.817,0.893)「速通」；②点「确定」；③**`wait_text` 等「确认/确定」出现后再点**。
   - ✅ 坐标已校准（实测 速通→确定→结算）：第②个「确定」=速通弹窗 `[0.497,0.644]`；第③个＝结算页「确认」`[0.638,0.858]`（OCR 文本是「确认」非「确定」，故 text 用 ["确认","确定"]）。点结算「确认」后回到星光偶像选择界面。
   - ✅ 时序已修复：点「速通」弹窗确定后挑战进行数秒，第③部已用 `wait_text`（timeout 25s）等「确认」出现再点，避免在挑战界面过早误点。

13. **✅ 新增步骤类型 `loop_fraction`：体力任务按需循环**（AS OF 2026-08-22）：
   - 引擎新增 `_calc_int()`（受信公式安全求值，支持 a/b/ceil()/floor() 四则）与 `run_loop_fraction()`（读多个分数区域→各按公式算整数→取 min/max→夹到 max_loop→重复执行 do）。
   - `flow_energy.json` 重构：顶栏 `(0.598,0.038)` 算 `n=ceil((b-a)/57)`、`(0.860,0.038)` 算 `m=floor(a/20)`，`combine=min` 得循环次数，重复 do= [点光偶像→若区域有「成为最闪耀明星」则点速通→点确定→等结算确认→点确认]。均<=0 则不循环（天然充当条件闸门）。
   - 公式实测：`ceil((600-399)/57)=4`、`floor(52/20)=2`；现场画面 `342/600→n=5`、`62/100→m=3`、`min=3`。

14. **✅ 锚点偏移定位法 + 登录界面「切换账号」按钮知识库**（AS OF 2026-08-22）：
   - **背景**：小花仙登录界面为**固定尺寸**（不随设备分辨率缩放），整体画面相对坐标(0~1)在启动就绪/登录功能中**失效**；改用「锚点 + 像素偏移」法，偏移恒定不随分辨率变化。
   - 引擎新增 [`locate_anchor_offset()`](ocr_engine.py)：按 `text_contains`（子串，如账号 `abc****de` 中的 `****`）或 `text`（关键字）找锚点块 → 锚点中心 + 像素偏移 → 目标点，支持多锚点依次回退。
   - `click_text()` 回退链升级为四通道：**OCR → 锚点偏移 → 颜色特征 → 坐标缓存**（知识库条目含 `anchor` 字段即走锚点通道）。
   - `_log_click()` 改为合并式写入：保留旧条目人工标注的 `anchor/color/scene/note` 扩展字段，不被自动日志覆盖。
   - 「切换账号」按钮（灰色向下折角，无文字）已写入 `data/click_log.json`，三种方法实测均命中 (991,287)：
     1. 主锚点=账号文本 `****` + 偏移 (+351,+1)
     2. 次锚点=「登录」按钮 + 偏移 (+237,-107)
     3. 颜色特征：账号右侧 dy±20 / dx 150~380 区域内浅灰块（HSV V 205~245, S≤30, 面积 60~100；收窄后唯一命中，排除干扰块 area 125/475）
   - CLI 新增开发工具 `--ocr-anchor <锚点> [--exact]`：以指定文字为锚点打印各文字块像素偏移（固定尺寸界面采集用）。
   - 登录界面其它锚点偏移（锚点=登录按钮）：切换(+475,-282)、公告(+474,-212)、登录其他账号(-1,+85)、账号文本(-114,-108)。
   - **✅「切换账号」模块实机跑通**：`flow_switch.json`（可选模块，`daily.json` 已插到「启动就绪」之前，on_fail=skip）→ ①`click_text("切换账号")` 锚点通道点折角图标展开列表(实机 992,287) ②新增步骤 `click_account_tail` 按账号文本尾部数字点目标账号(实机命中 138****00 at 652,361)。目标账号用尾部数字识别（如 89），region_rel 限定账号列表区避免误点底部数字。<br>引擎新增 [click_account_tail()](ocr_engine.py)：OCR 在 region 内找 `****` 账号块且尾部==tail → 点击中心。（注：点击账号后回到目标账号登录页，由「启动就绪」后续点「登录」进游戏。）<br>目标账号尾部已改为**可配置项**：`data/config.json` 的 `target_tail` 字段（默认 89），flow 步骤 `tail` 用 `${target_tail}` 占位符引用；引擎新增 `_load_config()`/`resolve()` 支持 `data/config.json` 加载与 `${key}` 占位符解析（仅替换 config 中非 `_` 开头字段）；CLI 可用 `--tail <数字>` 临时覆盖（`ocr_engine.py --flow 切换账号 --tail 61` / `main.py --tail 61`）。<br>**切换账号已做成可选功能（UI 开关）**：`data/config.json` 增加 `enable_switch`（默认 false）；`run_daily` 在模块循环中，id=='switch' 且未启用时直接 skip；引擎新增 `_save_config()`/`update_config(**kw)` 持久化；Web UI「运行流程」面板新增「可选功能」区（勾选切换账号 + 目标尾部输入 + 保存），新增 API `GET /api/config` / `POST /api/set_config`。

15. **✅ 本地 Web UI（自测/使用模式）**（AS OF 2026-08-22）：
   - [`webui.py`](webui.py)：标准库 `http.server` 实现，无第三方依赖；`python webui.py [--port 8765]` 启动，浏览器开 `http://127.0.0.1:8765/`。
   - [`webui.html`](webui.html)：内嵌单页前端，功能齐全：
     - **实时画面 + OCR 标注**：每 1.5s 自动刷新，粉色框标出 OCR 文字块并显示相对坐标；点击画面任意位置即对模拟器发点击（转相对坐标）。
     - **连接 / 返回键 / 模式切换**：ADB「连接」、送「返回键」；「使用」/「测试」模式（测试周期切 `debug_click` 存点击截图到 `data/click_debug`）。
     - **运行流程**：下拉选 8 个 flow（含「每日挂机编排」）+ 一键运行，后台线程执行，日志经环形缓冲实时增量滚动（`/api/log?after=`）。
     - **流程/知识库浏览**：下方面板展示 `flows/*.json` 与 `data/click_log.json` / `data/close_buttons.json`。
   - API 一览：`/api/status` `/api/flows` `/api/kb` `/api/connect` `/api/set_mode` `/api/screen` `/api/click` `/api/back` `/api/run` `/api/log`。
   - 已修复：[webui.html](webui.html) `refreshStatus()` 里未定义的 `rank()` 改为 `!!s.connected`（原先会抛 ReferenceError 致连接徽标刷新崩溃）。

16. **✅ Web UI 重构：使用 / 测试双界面（MAA 风格）**（AS OF 2026-08-22）：
   - **拆分为两个界面，右上角「切换界面」按钮互切**：
     - **使用界面**（新，仿 MAA 主界面）：左栏「每日挂机任务」勾选列表（全选/清空/反选）+「完成后」下拉 +「开始一轮」大按钮；右栏「账号切换」（启用开关 + 目标账号下拉 + 立即切换）、“连接设置”（连接配置/ADB/地址/连接状态按钮）。**去除任何「必选」标记**——任务全部可由用户勾选决定是否执行。
     - **测试界面**（原单页能力全部保留）：实时画面 + OCR 标注、点击、运行流程、可选功能、运行日志、流程/知识库浏览。
   - 前端 [webui.html](webui.html)：两视图容器 `#use-view` / `#test-view` 用 `.hidden` 切换，右上角 `#view-toggle` 切换按钮；共用同一条 `/api/log` 日志流。
   - 后端 [webui.py](webui.py) 新增接口：
     - `GET /api/daily`：读 `flows/daily.json` 返回模块列表（id→中文名映射）+ config/enable_switch/target_tail。
     - `POST /api/run_daily`：接收勾选模块 id 列表，从 daily.json 过滤构造编排后跑，「开始一轮」使用；会**去掉必选标记**（统一 `on_fail=skip`）、空选择返回 400。
   - 实机验证：页面 200、`/api/daily` 返回正确中文映射、`/api/run_daily` 空选择返回 400「未勾选任何任务」。
   - **注意：端口 8765 曾被未关闭的旧 webui 进程（系统 Python313）占用**，导致新接口返回旧逻辑；用 `Stop-Process` 清掉旧进程、以 `.venv` 重启后一切正常。启动脚本 [start_webui.bat](start_webui.bat) 仍适用（会优先用 `.venv`）。

17. **✅ 启动脚本增强 + UI 关闭服务按钮**（AS OF 2026-08-22）：
   - [start_webui.bat](start_webui.bat)：双击即用，启动后约 2 秒**自动打开浏览器**（内嵌 PowerShell `Start-Process`）；支持 `start_webui.bat [port] [--address xxx] [--adb xxx]`，沿用 `.venv` 优先；进程退出后自动关窗（`timeout 3s`）。
   - 后端 [webui.py](webui.py) 新增 `POST /api/shutdown`：记录日志后用独立线程调用 `srv.shutdown()`+`server_close()`，优雅退出并释放端口（`main()` 里把 server 实例存入模块级 `_SERVER`）。
   - 前端 [webui.html](webui.html)：header 右上角新增红色「⏻ 关闭服务」按钮（确认弹窗 → 请求 `/api/shutdown` → 页面提示已关闭）。为避免改变 `.view-link` 布局，`shutdown` 不加 `margin-left:auto`（`view-link` 上的 auto 已生效，默认间距不变）。
   - 实测：POST `/api/shutdown` 返回 `{"ok":true,"message":"服务已关闭"}`，监听进程退出、端口释放（`LISTENERS_LEFT=0`）。

18. **✅ 架构调整：启动就绪→开始启动，切换账号并入作为可选功能**（AS OF 2026-08-22）：
   - **「启动就绪」更名为「开始启动」**；**「切换账号」合并进开始启动**（不再是独立模块），作为启动内的可选功能存在。
   - 引擎 [ocr_engine.py](ocr_engine.py) 新增步骤类型 **`if_config`**（`eval_config()`）：流程内按 `data/config.json` 键值做条件分支（`key`/`value`/`op` ∈ == != >= <= > <；value 支持 `${key}` 占位符与 bool/int 自动转换）。
   - [flow_startup.json](flows/flow_startup.json)：更名为「开始启动」；步骤前方包一层 `if_config`（`enable_switch=true` 才执行：点切换账号 → `click_account_tail` 点目标账号），随后点「登录」→「点击进入游戏」。
   - `flow_switch.json` **已删除**（逻辑并入 startup，不再独立）。
   - [daily.json](flows/daily.json)：编排从 **9 → 8 模块**，移除独立 `switch` 模块；`startup` 描述为「开始启动(登录进游戏, 含可选切换账号)」。
   - 后端 [webui.py](webui.py)：`id2name` 移除 `switch`、`startup` 改名「开始启动」，使用界面任务列表同步更新。
   - `run_daily()` 中原先针对 `switch` 的 `enable_switch` 特判已删除（开关判断下沉到 startup 流程内部 `if_config`，逻辑等价的职责内聚）。
   - 验证：daily 8 模块无 switch、startup 首步 if_config、flow_switch 已删、`eval_config` 对 enable_switch true/false 判断正确。

19. **✅ 签到功能开发 + 新增右上角白色圆形关闭按钮类型**（AS OF 2026-08-22）：
   - **签到面板**：游戏自动弹出（仅当日未签时）；「兔尔电波/双生签到」日历，8/23 位置 `点击签到(abs(624,327))`，21/22 已显示「已签到」，累计 9/41→10/41。
   - [flow_signin.json](flows/flow_signin.json)（`signin` 模块）：① `if_text` 全屏 OCR 找「点击签到」→ 命中才执行（不留存坐标，位置随日历每日变化）②点「点击签到」③点「点击任意处关闭」关『恭喜获得』弹窗 ④ `close_dialog only_types=["corner","corner_white"]` 退出签到面板。当日已签则不弹、OCR 找不到「点击签到」自动跳过（天然兼容）。
   - 实测：签到+关弹窗成功、累计 10/41。
   - **🔴 修复：签到面板右上角关闭按钮未能退出**——它是**白色圆形**（中心 abs(1228,71)，边缘粉色描边 HSV(172,42%,96%)），而旧逻辑用摇钱树坐标 `click_rel(0.938,0.125)=(1200,90)` 点到背景色，退不出。
     - `data/close_buttons.json` 新增第 3 种关闭类型 **`corner_white`**：右上角 rel 区域 `(0.9,0,1.0,0.16)` 内找白色块（HSV V>200,S<30,面积600~3000），精确命中 (1228,71)。
     - `ocr_engine.py`：`_locate_close_by_entry` 支持 `corner_white`（与 `corner` 同走 region_rel+color）；`close_dialog()`/`run_step` 新增 **`only_types`** 参数（按类型过滤遍历，退出整屏面板时避免误点「提示」锚点弹窗）。
     - 实测：`corner`→(1228,66)、`corner_white`→(1228,71) 双命中；`close_dialog(only_types=["corner","corner_white"])` 成功退出签到界面 → 回到主界面（寻梦童话/手账/在线礼包等）。

20. **✅ 新增功能2「花灵派对」独立流程（AS OF 2026-08-23）**：
   - [`flow_party.json`](flows/flow_party.json)（`party` 候选，独立流程）参照「闪耀变身」进入结构，但**入口走「菜单」**（非更多活动）：①关弹窗(loop 6×close_dialog anchor=提示) ②`if_text` 就近直达「花灵派对」→点 ③否则回主界面(点菜单, 若只有家园先点家园再点菜单) ④从菜单 OCR 找「花灵派对」→点。
   - `--list` 已识别「花灵派对」流程；**暂未挂载 daily.json**（先独立测试，实机校准菜单内「花灵派对」坐标后再决定是否挂载）。
   - ⚠️「花灵派对」在菜单内的相对坐标未校准，`fallback_rel` 暂用 [0.105,0.625] 占位，需实机 `--ocr-screen` 校准。

21. **✅ 花灵派对·领取奖励（时长礼包）实机跑通（AS OF 2026-08-23）**：
   - `flow_party.json` 扩展为完整领取流程：进花灵派对 → 点「派对时长礼包」rel(0.0539,0.4250) → 顺序领取6个在线时长礼包 → 关面板。
   - **派对时长礼包面板校准**：6礼包分两行3列，标题「派对时长礼包」rel(0.5,0.0806)；第1行「1分钟/5分钟/15分钟在线礼包」(y=0.2167)，各「领取」按钮 rel(0.2750,0.4694)/(0.5000,0.4694)/(0.7242,0.4694)；第2行「30/60/90分钟在线礼包」(y=0.5806)，领取 rel(0.2758,0.8333)/(0.5000,0.8333)/(0.7242,0.8333)。
   - **领取机制**：点「领取」→ 弹「恭喜获得」窗 → 点「点击任意处关闭」(0.5,0.9375)→ 该礼包「领取」按钮消失。已领的按钮消失后，固定坐标点击无效（自然跳过，流程健壮）。
   - 实测领完1/5/15/30分钟，弹窗+关闭全程正常。
   - **面板关闭**：派对时长礼包/爱心记录面板的关闭按钮 = `corner_pink_small` 类型，命中 (1108,80)。**注意每日任务/爱心记录面板被覆盖时 `corner`/`corner_white` 也测过无效，只有 `corner_pink_small` 有效**。
   - 花灵派对场景：进入他人派对时顶部有「点赞」、左侧功能栏(时长礼包/每白任务/排行榜/爱心记录)；`corner_pink_small` 关闭面板回到派对场景。
   - test flow JSON 23 步，`json.load` 合法。
   - **✅ 已挂载为「领取奖励」功能2**：花灵派对领取流程合并进 [`flow_claim.json`](flows/flow_claim.json)（27步），在功能1在线礼包后顺序执行；`daily.json` 的 claim 模块不变，自动继承。`flow_party.json` 保留为独立流程便于单独测试。

22. **✅ 领取奖励·功能1/功能2 可选开关 + Web UI 模块 ⚙ 设置面板（AS OF 2026-08-23）**：
   - **config.json** 新增 `claim_online`、`claim_party` 布尔开关(默认 true)，`_comment` 已说明。
   - **flow_claim.json** 重构为 2 个 `if_config` 块：`claim_online`(功能1, then=4步) 与 `claim_party`(功能2, then=23步)；任一关 skip 该整段。引擎已支持 `if_config`(见课内 eval_config/run_step if_config)。
   - **webui.py**：`/api/config` GET 新增返回 `claim_online`/`claim_party`；`/api/set_config` POST 支持写这两个开关并写日志；`/api/daily` 每个模块新增 `settings` meta——`claim` 模块含功能1/2 的 switch、`startup` 模块含 enable_switch/target_tail，其它模块为空数组。
   - **webui.html**：使用界面改三栏布局(任务|设置|账号连接提示)；左栏任务行加 `⚙` 键(无独立设置的模块置灰禁用)；点击 ⚙ 展开该模块「模块设置」面板(在左栏面板内)，渲 switch/text 设置项，"保存设置"调 `/api/set_config`。
   - **已验证**：`/api/daily` 返回 claim/startup settings、`/api/config` 含新字段、`set_config` 写回 config.json 正常；测试后已将 claim_party 恢复为 true。

23. **✅ 新增 `retry_loop` 原语：把「批量关弹窗」改为「脱困式重试」**（AS OF 2026-08-23）：
   - **问题背景**：旧流程一律在核心步骤前 `loop_times 6 × close_dialog(提示)` 批量连关弹窗。关闭按钮可能误识别/误触，且连点次数多易产生误触。优化目标：关弹窗不再是"开场必做"，而是"核心步骤无法进行时的最后一招脱困"。
   - **引擎新增 `retry_loop` 步骤类型**（[ocr_engine.py](ocr_engine.py) `run_step`）：`max_rounds`(默认3)+ `do`(每轮内容) + 可选 `fail_do`(脱困动作；不写则自动 `close_dialog()` 尝试**全部类型**关闭按钮)。
   - **命中机制**：`click_text` 支持 `mark:true` 标记"目标命中"。retry_loop 每轮开始把 `self._rr_hit` 置 False，执行 `run_steps(do)`；仅 when do 内**真实点击成功且该点击带 `mark:true`** 时置 `_rr_hit=True`。轮末：`_rr_hit=True` → 本轮成功退出；`False` → 脱困(关全部类型弹窗) → 进入下一轮。跑满 `max_rounds` 仍无命中 → 放弃，继续流程后续步骤（不抛错）。
   - **语义（方案B/A 融合）**：进入目标的**候选序列定位为前段**，只有"点到目标(带 mark)"才算本轮成功；「菜单/家园/社交/家族」等**导航层不 mark**，点它们后继续向下层探测；**后段核心步骤(领礼包/速通/浇水)不参与成败判定**，进门命中即本轮成功 → 避免"当日无事可做(如已领/次数已满)"时被误判失败而空转脱困。
   - **四个流程统一改造**（删掉开头 `loop_times 6 × 关提示`，改由 retry_loop 轮末脱困触发）：
     - [`flow_party.json`](flows/flow_party.json)：目标=「花灵派对」(mark)，导航=菜单/家园；后段领6礼包。
     - [`flow_energy.json`](flows/flow_energy.json)：目标=「闪耀变身」(mark)，导航=菜单/家园；后段 loop_fraction 速通循环。
     - [`flow_social.json`](flows/flow_social.json)：目标=「家族活动」(mark)，导航=社交/家族(嵌套)；后段摇钱树浇水。
     - [`flow_claim.json`](flows/flow_claim.json)：功能2 花灵派对的`if_config claim_party` then 内，用同一 retry_loop 结构替换原 loop_times+if_text 链（功能1在线礼包不变）。
   - **模拟验证**（无设备，`locate`/`click_text` 打桩）：场景1(目标全 MISS)→3轮各脱困1次=3次、无异常退出；场景2(首轮命中)→0次脱困、首轮即退出。`json.load` 校验 4 流程合法。

24. **✅ 花灵派对·时长礼包领取改为 `loop_text` 动态循环（AS OF 2026-08-23）**：
   - **问题背景**：花灵派对「时长礼包」面板内礼包分成两行三列（1/5/15 + 30/60/90 分钟）。旧版用**固定 6 个相对坐标**逐个点击领取（如 (0.275,0.47)/(0.5,0.47)/(0.724,0.47) 等）。实机发现：**这些坐标落在每张卡片的"种植/经验"作物区，不是"领取"按钮** → 点 6 次全程无「恭喜获得」、礼包面板也关不掉。
   - **关键规则（用户确认）**：礼包一经领取，"领取"按钮即消失。因此：**能否识别到"领取"文字 == 是否还有可领的礼包**。
   - **处理方案**：`领取`按钮相对坐标虽固定，但以**OCR 判定有无**为准更可靠 → 两者结合。
   - **引擎新增 `loop_text` 步骤类型**（[ocr_engine.py](ocr_engine.py) `run_step`）：只要还能识别到 `text`（如"领取"）就重复执行 `do`；识别不到即退出。参数 `text`/`min_score`/`max_loop`(守卫上限,默认20)/可选 `region_rel`。用于"有'领取'就点、领完按钮消失即自然停止"的领取循环。
   - **[`flow_party.json`](flows/flow_party.json) / [`flow_claim.json`](flows/flow_claim.json) 功能2 改造**：原 6 个固定领取坐标 → `loop_text(text=["领取"])` do=[ `click_text("领取")` → 等1.2s → if_text(「恭喜获得」)→点(0.5,0.9375)关闭 ]。面板内识别到"领取"就点，全部领完按钮消失即停，随后 `close_dialog` 关面板。
   - **实机已确认**：`--ocr-screen` 验证点左侧栏「时长礼包」rel(0.0539,0.4250) 确实进入「派对时长礼包」面板（标题出现），面板内可识别到"领取"按钮（如 (0.5,0.8333)/(0.7242,0.8333)）。`json.load` 校验两流程合法。
   - **注意（本次实机遗留）**：因当日在面板外截图时"领取"按钮已部分消失（领完即隐藏），实际"点进入面板→loop_text 领取"的连贯性需下次整流程 `--flow 花灵派对 --loop 1` 复核；正常路径应全程零脱困，仅目标被挡时触发 retry_loop 脱困。

25. **✅ 花灵派对·整流程实机跑通 + 「时长礼包」入口改为 OCR 驱动（AS OF 2026-08-23，未提交）**：
   - **问题（用户指出，此前已确认）**：进入花灵派对后流程**没有点「时长礼包」按钮**，导致 `loop_text('领取')` 一开始就找不到按钮而直接结束。
   - **实机定位**：`--ocr-screen` 确认登录「花灵派对」主面板左侧栏有「时长礼包」tab `rel(0.0531,0.425)=(68,306)`；点它进入「派对时长礼包」面板（标题 rel0.5,0.079），面板内当时有 **2 个「领取」按钮** `(0.499,0.833)`/`(0.723,0.833)`（其余已领完即消失）。
   - **修复**（[`flow_party.json`](flows/flow_party.json) 步骤47-55）：把裸 `click_rel(0.0539,0.425)` 改为 **`if_text('时长礼包')` → `click_text('时长礼包')`（OCR 定位点）+ else 兜底 `click_rel(0.0531,0.425)`**。
   - **实机验证**（`--flow 花灵派对` 完整跑通）：retry_loop 第3轮从脱困恢复→识别「菜单」(68,59)→点「花灵派对」(237,542)→mark 命中；`if_text('时长礼包')` 本轮 **MISS**（文字未识别到），靠**兜底坐标** `click_rel(67,306)` 点中面板；`loop_text('领取')` 连续点 2 次 `(639,600)/(926,600)`，每次→`if_text('恭喜获得')`→点 `(0.5,0.9375)` 关闭，直到按钮消失结束；最后 `close_dialog(corner_pink_small)` 关面板。**全程领取+关弹窗正常**。
   - **残留注意**：①`if_text('时长礼包')` 实机有 MISS，当前靠兜底坐标救回的，OCR 对该字样识别不稳定，后续可再加强；② OCR 精度修复（`det_use_dilation=False`，见第 6 节）本次实机有效——`菜单` 干净识别 `(68,59)`，未误点「奇妙花宝」。

26. **⚠️ retry_loop 改造了 4 个功能，仅「花灵派对」实机验证，其余 3 个待验证（AS OF 2026-08-23）**：
   - 「retry_loop 脱困式重试」（里程碑 23）共改造 4 处：`flow_party`（花灵派对）、`flow_energy`（闪耀变身）、`flow_social`（家族活动/摇钱树浇水）、`flow_claim` 功能2（claim_party 花灵派对）。
   - **目前唯一实机验证通过的是「花灵派对」（flow_party）**；其余 3 个 `${mark}` 命中/脱困/后段逻辑均**尚未在真机实测**，需逐一验证（见待办 🟠）。

### 🚧 进行中 / 待确认（实机作业校准）
- **种植模块作业未真正执行**：每日编排里对"一键种植/种植箱"MISS（8s 超时）→ 未进花田 → 浇水/施肥/授粉/收花循环全部空转。编排框架 OK，实机作业动作需校准。
- **离线诊断为有效线索**：`after_home.png` 上 OCR 把「种植箱一键种植」识别为**单一合并块**（box [930,672,1078,698]，宽 148>90，score 0.82）；`ocr_find` 用严格方式能命中。**MISS 根因疑似与 `find_text()` 中"过宽块放大重识别"（宽>90 触发）有关**，需下个会话重点排查（见待办 🔴-1）。

### 🐛 本次会话发现的问题（待修复）
- **（记录，非重点）体力任务右上角误点**：某次测试开局停留在「世界聊天」界面时，清弹窗阶段 `corner` 右上角关闭逻辑连点 (1252,9)/(1245,26)/(1226,33) 5 次（该处为世界聊天入口小圆点），把画面带到世界聊天导致后续找不到「闪耀变身」、循环=0 提前结束。但**未能稳定复现**（另一次开局在齐他界面时全程干净），判断依赖开局画面状态，暂不作为重点任务，仅记录备查。corner 区域见 close_buttons.json。
- **流程名关键字歧义**：`--flow 种植` 命中先载入的「进入种植界面」(enter_garden.json) 而非「种植任务」(flow_plant.json)。`main.py/ocr_engine.main` 用 `key in name` 取第一个，名称重合会选错流程 → 需改"精确名优先"匹配。
- **过期回退坐标**：enter_garden.json 里「一键种植」回退缓存 (0.7508,0.9514)=(961,685)，已被新采集 (0.784,0.950)=(1004,684) 取代 → 应更新 click_log / 流程 fallback_rel。
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
   - 推送成功尾部见 `  <旧hash>..<新hash>  main -> main`。
   - 若报 `Recv failure: Connection was reset`（多为临时网络/代理抖动）：提交已在本地（不丢），稍后重跑 `git push origin main` 即可。
   - **绝不 `git push --force`**，不 `--force-with-lease`，不直接改 `git config`。

5. **验证**：
   ```powershell
   git status              # 工作树干净
   git log --oneline -1    # 最新 commit
   git branch -vv          # main 应显示 up to date
   ```
   - 仓库不纳入版本管理的文件：`.venv/`、`debug/`、`legacy/`、`resource/`、`__pycache__/`（已在 `.gitignore`）。

> ⚠️ 注意：`data/config.json` 的 `target_tail`、`data/click_log.json` 属坐标/配置数据，提交前严格筛查账号类信息；不能确定时先脱敏或暂不提交（讨论后再定）。

---

## 3. 关键按钮相对坐标（来自 click_log / OCR 采集）

> 相对坐标 = 绝对坐标 ÷ 屏尺寸。屏幕尺寸变化时，`相对×新尺寸` 仍定位正确。

### 家园 / 世界界面
| 按钮 | 绝对 | 相对 |
|---|---|---|
| 家园(底部导航) | (1116, 684) | (0.872, 0.950) |
| 种植箱一键种植 | (1004, 684) | (0.784, 0.950) |
| 快捷操作 | (886, 684) | (0.692, 0.950) |
| 离开 | (1117, 686) | (0.873, 0.953) |
| 园艺店 | (216, 59) | (0.169, 0.082) |
| 菜单 | (69, 58) | (0.054, 0.081) |
| 社交(底部导航) | (424, 683) | (0.331, 0.949) |
| 在线礼包 | (1058, 157) | (0.827, 0.218) |
| 世界(底部导航) | (505, 679) | (0.398, 0.943) |
| 勇气国花园 | (68, 688) | (0.053, 0.956) |

### 种植操作界面（点「一键种植」后进入）
| 按钮 | 绝对 | 相对 |
|---|---|---|
| 种植(左栏) | (87, 165) | (0.068, 0.229) |
| 照料(左栏) | (90, 255) | (0.070, 0.354) |
| 授粉(左栏) | (90, 342) | (0.070, 0.475) |
| 浇水(右栏) | (1233, 127) | (0.963, 0.176) |
| 施肥(右栏) | (1233, 212) | (0.963, 0.294) |
| 收花(右栏) | (1233, 297) | (0.963, 0.413) |
| 清理(右栏) | (1231, 382) | (0.962, 0.531) |
| 开花(右栏) | (1233, 466) | (0.963, 0.647) |
| 造型种植 | (843, 633) | (0.658, 0.879) |
| 随机种植 | (1054, 633) | (0.823, 0.879) |

### 无文字图形按钮（颜色特征识别）
- **关闭按钮有"特殊逻辑"注册表**（[data/close_buttons.json](data/close_buttons.json)），目前**两种**：①「提示」锚点右侧（弹窗式）；②整体画面右上角（种植面板式，region_rel=[0.93,0,1.0,0.1]）。找关闭按钮时遍历注册表，可后续扩展。
- 原 `corner` 区域 [0.82,0,1.0,0.18] 过宽会扫到中间偏右的其它粉色图标（如 (1100,89) 处误报、被循环连点），已收窄至 [0.93,0,1.0,0.1] 消除误报。真实关闭按钮约 (0.973,0.036)。
- 原有"关闭"条目：右上角粉色四瓣花形，绝对 (1245,26)，相对 (0.973, 0.036)。颜色 `hsv_lower=[150,100,100], hsv_upper=[175,255,255], area 100~1000`（该坐标属旧采集，注册表 `corner` 逻辑为当前优先）。

---

## 4. 待办任务（按优先级）

### 🔴 高优先级（下一步）
- [ ] **修复「一键种植」MISS 根因**：排查 `find_text()` 的"过宽块放大重识别"逻辑（宽>90 触发）对合并块「种植箱一键种植」的处理。离线证据：`after_home.png` 上该块 score0.82、`ocr_find`严格能命中，但补点后仍 MISS。可临时把 90 阈值调大 / 关闭合并块重识别 / 改用 exact 匹配验证。
- [ ] **修正流程名匹配歧义**：`main.py` 与 `ocr_engine.main` 用 `key in name` 取第一个，`--flow 种植` 误选「进入种植界面」。改为"先精确名匹配，再关键字子串匹配"。
- [ ] **更新过期回退坐标**：click_log 与 flow 里「一键种植」回退 (0.7508)→(0.784)；同步旧流程 enter_garden.json。
- [ ] **清理干扰文件**：删除/归档 `flows/enter_garden.json`、`enter_home.json`、`login_verify.json`、`test_close.json`、`diag.py`、`validate_daily.py`、`debug/`，避免干扰 `--flow` 匹配。
- [ ] 校准后重跑 `main.py --flow 每日` 验证种植作业真实执行（浇水/施肥/收花）。

### 🟠 中优先级
- [ ] **实机验证 retry_loop 其余 3 个功能**（里程碑 23 改造、里程碑 26 记录；仅花灵派对已验证）：逐一跑 `--flow` 复核 `${mark}` 目标命中 / 脱困重试 / 后段逻辑。
  - [ ] **体力·闪耀变身**（`flow_energy.json`）目标=「闪耀变身」(mark)，导航=菜单/家园，后段 loop_fraction 速通循环。
  - [ ] **社交·家族活动/摇钱树浇水**（`flow_social.json`）目标=「家族活动」(mark)，导航=社交/家族(嵌套)，后段摇钱树浇水（含 10 分钟冷却 + store_fraction 计次）。
  - [ ] **领取奖励·功能2 claim_party**（`flow_claim.json` 功能2，独立于 flow_party 的挂载形态）：`if_config claim_party` then 内的 retry_loop + 时长礼包 + loop_text 领取连贯性。
- [ ] **方案②：点击位置"立体化分级 + 均值 + 偏差复核"加固定位**：把可点击按钮按其定位方式**分级/分类/命名**（普通相对坐标 / 锚点-像素偏移(固定尺寸界面如登录页) / 颜色特征）。每次点击成功 `_log_click` 时记录该按钮的相对位置样本，累积求**平均值**；下次 `click_text` 命中坐标与该均值**偏差过大**（如 > N px）→ 判为可疑 → 进行**二次更精细处理**（如放大局部重识别 / 用均值点补齐）。**注意**：部分按钮用「锚点-相对绝对位置法」而非「整体相对坐标法」，必须按其类别各维护独立样本，不能混用整体相对均值。
- [ ] `main.py` 主程序入口：参数化（adb 地址、流程选择、循环次数/无限）、日志、状态反馈
- [ ] 循环机制：流程结束后自动回到起点反复执行至手动停止
- [ ] 界面状态感知：识别当前所处界面（家园/种植/登录），决定下一动作

### 🟢 低优先级 / 后续扩展
- [ ] 更多任务：施肥、领奖、社交、收花批量（跨模块动作深度联动）
- [ ] 颜色特征按钮扩展：如登录页"点击进入游戏"等无/弱文字元素
- [x] ~~安装 git 做正式版本控制~~（已同步 GitHub，见第 2 节）
- [ ] README.md 完善（补模块化编排说明）

---

## 5. 关键文件清单

| 文件 | 作用 |
|---|---|
| `ocr_ui.py` | RapidOCR 单例：`ocr_image` / `ocr_find`（文字→块，含 center/score） |
| `ocr_engine.py` | 核心引擎：连接/截图/OCR定位/颜色定位/点击/相对坐标/知识库回退/界面采集/关闭按钮遍历/区域文本判断/流程执行（CLI: `--flow`, `--collect`, `--list`, `--close-test`, `--add-close`, `--ocr-screen`） |
| `data/click_log.json` | **按钮知识库**：按钮名→相对/绝对坐标、识别方式(ocr/color/fallback)、时间（自动积累） |
| `data/close_buttons.json` | **关闭按钮-特殊逻辑注册表**：`corner`/`anchor_color` 两种关闭按钮定位逻辑，可扩展 |
| `flows/*.json` | 数据驱动流程定义（`type: wait_text/click_text/click_rel/sleep/close_dialog/if_text/if_fraction/loop_fraction/loop_times`） |
| `flows/daily.json` | **编排**：按序调度 7 大模块（启动→签到→种植→体力→每日→挂机→领取），含 `required`/`on_fail` 容错 |
| `flows/flow_*.json` | 各模块流程：startup/signin/plant/**energy**/daily_task/idle/claim |
| `legacy/` | 已弃用的旧 MAA 模板路线 & Unity 解包脚本**备份**（不参与运行） |
| `.gitignore`（项目根） | 已忽略 `.venv/`、`debug/`、`legacy/`、`__pycache__/` 等 |
| ⚠️ 旧流程残留 | `flows/enter_garden~test_close.json`、`diag.py`、`validate_daily.py` 会干扰 `--flow` 关键字匹配，待清理（见待办 🔴） |

### 运行环境（务必用 venv）
- 系统 `python`(3.13) 无依赖 → **必须用 `.\.venv\Scripts\python.exe`**。
- 实机模拟器：`127.0.0.1:16384`，adb=`D:\Program Files\Netease\MuMu\nx_main\adb.exe`。
- 常用命令（`cwd`=FlowerAutoAssistant/）：`.\.venv\Scripts\python.exe main.py --flow 每日 --loop 1`（单轮）`/ --list`（列流程）/ `--collect`（采集界面写知识库，在 ocr_engine.py）。

---

## 6. 技术要点 / 避坑记录
- **MaaFw 是全新 API**（`maa` 包），非老版 `maa-core`。新版用 `Spawn → Future → tasker = Asst(role=App)`，连接、截图通过 `tasker.controller` / Toolkit。
- **关 OCREngine 单例**：`OCR_ENGINE` 实例全局复用，避免多进程反复加载模型（每次新进程 still 触发权限，应尽量同一进程内循环）。
- **相对坐标是核心**：所有定位最终转归一化相对坐标，屏幕尺寸变化不失效。
- **颜色识别**用于无文字图形按钮（如关闭）：HSV 过滤 + 连通区域取最大连通块。
- **点击即记录**：`click_text` 成功后自动 `_log_click` 写回 click_log，知识库随使用增长。
- **合并文字块 <-> find_text 冲突**：OCR 常把相邻按钮合并成一个块（如「种植箱一键种植」宽 148>90），`find_text()` 会触发"过宽块放大 2x 重识别"，可能反而丢命中 → 这是「一键种植」MISS 的疑似根因，改造后务必回归测试。
- **OCR 合并「菜单/奇妙花宝」⚠️（2026-08-23 已查根因）**：记录帧 `debug_menu_frame.png` 在任意参数下本就能分开两块；实时帧偶发合并是因**半透明按钮背后的背景变化**导致检测框粘为一个宽块，而 `ocr_find` 用**子串匹配**(`"菜单" in "菜单奇妙花宝"`)+**点整块中心** → 误点邻钮。**第 1 层修复已落地**：`ocr_ui.get_engine()` 单例初始化改为 `det_use_dilation=False` + `det_thresh=0.2`+`det_box_thresh=0.3`+`det_unclip_ratio=1.4`，从检测源减少膨胀粘连（传 `det_*` 参数时该库强制读 `det_model_path`，须显式传 `None` 沿用默认模型路径）。**第 2 层待实机验证**：若仍粘连，`click_text` 对"过宽合并块"按横轴分段分别重识别、取真正含关键字的子段点击，而非点整块中心。勿用"字符在块内占比"估算位置（不可靠）。
- **`--flow` 名称匹配歧义**：`key in name` 取第一个会选错同名流程 → 应"精确名优先，子串次之"。
- **运行依赖在 venv**：系统 python 无 numpy/maa → 一律用 `.\.venv\Scripts\python.exe`（其他终端也一样）。
- **PowerShell 重定向会破坏二进制 PNG**：`exec-out screencap` 输出必须用 Python `subprocess` 捕获原始字节，勿用 `>` 或管道。
- ~~MAA 模板匹配路线已废弃~~：原 4 个模板（quick_ops/plant_box/one_click/map）与 `daily.json` 属旧方案，不再使用（备份在 legacy）。