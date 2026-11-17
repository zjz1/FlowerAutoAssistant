# FlowerAutoAssistant (FAA)

面向页游《小花仙》的**一键挂机**自动化框架。基于 **OCR 文字识别 + 相对坐标** 的数据驱动方案，实现"识别界面 → 定位按钮 → 点击执行 → 循环挂机"。

> ⚠️ **仅供学习与个人使用。** 本项目不包含任何游戏素材、资源包或解包工具，仅含通用自动化逻辑。请遵守游戏服务条款及所在地区法律法规，由此产生的账号风险由使用者自行承担。

> 🧪 **试验包（`_lab`，LAB-2）**：本目录是 zcode 重构双包中的 OCR 侧，**未进正式版**。
> `native/` 已拆分到 `_lab/native_ui/`；`webui_app.py` / `PROGRESS.md` 取当前工作树（含 M113）；
> 性能灰度默认全关、实机 A/B 未执行；详见同目录 `LAB_NOTES.md`。

---

## 技术路线

与传统的"模板匹配"（如 MAA）不同，本项目以 **“OCR 文字定位 + 相对坐标”** 为主：

- **每次运行时**用 OCR 识别界面文字 → 定位文字中心坐标
- 坐标归一化为**相对坐标**（`x/屏宽, y/屏高`），**屏幕尺寸变化时相对位置不变**
- 坐标写入本地知识库（含多次命中的**运行均值**），OCR 瞬时失败时用均值/缓存兜底点击
- 纯图形、无文字的按钮（关闭钮、切换账号折角图标等）才用 **模板匹配**（借鉴 MAA 的多尺度算法）或颜色特征

### 核心循环

```
连接模拟器 → 截图 → OCR识别文字 → 按关键字定位按钮
→ 计算相对坐标 → 点击 → 回退缓存 → 循环
```

### 定位回退链（`click_text` 自动逐级回退）

| 通道 | 适用 | 原理 |
|---|---|---|
| ① OCR 文字定位 | 有文字的按钮 | RapidOCR 识别文字 → 中心坐标 |
| ② 锚点 + 像素偏移 | 固定尺寸界面（登录页，相对坐标失效） | 以关键字为锚点 + 恒定像素偏移 |
| ③ 颜色特征 | 无文字的纯图形按钮 | HSV 过滤 + 连通区域分析 |
| ④ 坐标缓存 / 均值点 | 任意已记录按钮 | 知识库 `mean_rel`（按场景累积）→ `rel` 兜底 |

另有独立步骤类型 **`click_template`** 专供纯图形按钮：多尺度（默认 0.7~1.0）模板匹配 `TM_SQDIFF_NORMED`，支持 `region_rel` 限定；`offset_rel`（2026-10-24）表示命中后按屏幕相对比例偏移再点（偏移点仍由**本次实时命中**推导，满足规则 6）；模板在 `resource/template/`。

---

## 目录结构

```
FlowerAutoAssistant/
├── main.py              # CLI 入口：连接、选流程、循环执行、断线重连、Ctrl+C 停止
├── webui.py             # HTTP 服务兼容入口（Stage 3 后仅启动/导出 Handler；实现见 transport/http/）
├── transport/http/      # Handler 路由 mixin：base/router/pages/template/device/status/meta/run/log
├── webui.html           # WebUI 前端：使用界面 / 测试界面（实时画面+OCR标注+日志）
├── tpltool.html         # 人机协同标注页 /tpltool：只产出坐标标注，不直接存模板
├── start_webui.bat      # 双击启动 WebUI（优先用 .venv，自动开浏览器）
├── webui_app.py         # 原生窗口外壳（WebView2/pywebview）：复用或拉起独立服务进程，启动不自开浏览器
├── start_webui_app.bat  # 双击启动原生窗口（优先用 .venv；端口缺省 8765）
├── native/FAA.WpfGui/   # 原生桌面壳（WPF/C#，第二套「原生窗口」实现，见「两个原生窗口（术语区分）」）
├── ocr_engine/          # 核心引擎包：连接/截图/OCR定位/颜色/模板/点击/知识库/流程执行
│   └── engine/_layers.py #   Stage 3 职责层（device/ocr/locator/action/flow）
├── ocr_ui.py            # RapidOCR 单例（模型只初始化一次）
├── pollin.py            # 好友采粉兼容入口（`python pollin.py state|all`）；实现见 pollin/
├── pollin/              # 好友采粉分包（Stage 5）：constants/primitives/popups/navigation/
│                        #   list_panel/collect/runner（facade 再导出旧符号）
├── plant.py             # 种植/收获闭环（步骤 plant_flower / plant_harvest）
├── buy_seed.py          # 购买种子闭环（步骤 buy_seed；独立流程 flow_buy_seed.json）
├── fairyland.py         # 花仙乐园领取闭环（步骤 fairyland_claim）
├── ui_ops.py            # 通用 UI 原语（截图 / 小区域精识 / 输入框聚焦与输入）
├── navigation.py        # 通用导航原语（任意家园归位；plant 的「自己家园」仍走流程三态）
├── core/                # 核心端口（Stage 3）
│   └── ports.py         #   EnginePort / UiPort / TemplatePort / JudgePort / ConfigPort
├── app/                 # 应用服务层（Stage 1）：engine/log/failcache/config/status/run/lifecycle
│   ├── engine_service.py
│   ├── log_service.py
│   ├── failcache_service.py
│   ├── config_service.py
│   ├── status_service.py
│   ├── run_service.py
│   └── lifecycle_service.py   # Stage 4：服务探测/拉起/就绪等待/优雅停/父进程看护
├── config/              # 配置 schema 单源（Stage 2）
│   └── schema.py        #   键/默认值/⚙meta/日志文案/示例校验
├── flows/               # 数据驱动流程（改 JSON 不改代码）
│   ├── daily.json       #   编排：7 大模块按序调度
│   ├── flow_*.json      #   各模块流程（startup/plant/social/energy/claim/daily_task/idle）
│   └── common/entries.json  # 公共导航注册表（navigate 步骤引用）
├── tools/               # 项目校验 / 合并闸门
│   └── check_project.py #   静态校验 + config 键门禁；--with-tests 跑 tests/；--map 打印项目地图
├── tests/               # 离线 unittest 基线（不联网/不连 ADB）
├── docs/                # 流程手册 FLOWS.md / 架构路线 ARCHITECTURE_ROADMAP.md / API 契约 API_CONTRACT.md
├── data/
│   ├── click_log.json      # 按钮知识库（v2 场景两层嵌套 + 均值/样本数）
│   ├── close_buttons.json  # 关闭按钮-特殊逻辑注册表
│   ├── config.example.json # 功能开关模板（复制为 config.json 后填写）
│   ├── config.json         # 功能开关与目标账号尾号等配置（本地私有，已 gitignore）
│   ├── tplt_annotations.jsonl / annot_shots/  # tpltool 标注产物（坐标+绑定截图）
├── resource/template/   # 模板匹配模板（入仓；缺失则模板通道全废）
├── workbench/           # 未确认功能的暂存区（用户确认后才并入主体）
├── dev_tools/           # 常驻开发工具：self_test(离线自测) / calibrate(实机校准) / explore(探查采集)
└── PROGRESS.md          # 项目活文档：运行前先读，里程碑完成即更新
```

> `debug/`（截图）、`legacy/`（旧 MAA 路线备份）、`.venv/` 已加入 `.gitignore`，不参与版本控制；`resource/template/` 入仓。

---

## 依赖安装

```bash
pip install -r requirements.txt
# maafw, opencv-python, Pillow, pywebview, rapidocr_onnxruntime（OCR 引擎）
```

## 环境

- Python 3.11+（**务必用项目 `.venv`**；系统 Python 通常无 `numpy`/`maa`）
- MuMu 模拟器 12（ADB 端口默认 `127.0.0.1:16384`）
- 画面：横屏（分辨率不固定，相对坐标自动适配任意尺寸）

---

## 使用

### 命令行

```bash
# 列出可用流程
python main.py --list

# 执行「每日挂机编排」1 次（默认）
python main.py

# 无限循环（Ctrl+C 停止；停止请求会在步骤边界生效）
python main.py --flow 每日 --loop 0

# 执行某个模块流程，如社交任务（含可选「闪耀委托挑战」与「好友采粉」）
python main.py --flow 社交任务 --loop 1

# 指定 ADB 地址 / adb 路径 / 临时覆盖切换账号目标尾号
python main.py --address 127.0.0.1:16384 --adb "D:\Program Files\Netease\MuMu\nx_main\adb.exe" --tail 61
```

引擎侧另有一批开发用 CLI（直接运行 `python ocr_engine.py` 会打印用法）：`--collect`（采集当前界面文字写入知识库）、`--ocr-screen`（打印全屏文字块+相对坐标）、`--ocr-anchor <锚点关键字> [--exact]`（打印各块相对锚点的像素偏移）、`--close-test`、`--add-close <名称> <corner|anchor_color>`。

### WebUI

```bash
python webui.py            # 默认 8765
start_webui.bat            # 或双击：优先用 .venv，启动后自动开浏览器
python webui_app.py        # 原生窗口（WebView2/pywebview），启动不自开浏览器
start_webui_app.bat        # 或双击原生窗口
```

> **推荐原生窗口**（`start_webui_app.bat` / `python webui_app.py`）：同一套 `webui.py` 服务装进独立 WebView2 窗口；
> 端口已有 FAA 实例则**直接复用、不重复起服务**，否则在**后台拉起独立服务进程**
> （`webui.py --port N --parent-pid 壳PID`，壳不加载引擎）；**启动不自动开浏览器**，
> 关窗即停掉本窗口拉起的服务（父进程看护兜底，不留孤儿端口）。
> 原生窗口内「保存日志」走**原生另存为对话框**（WebView2 无浏览器下载管理器，由壳层 js_api 落盘）。
> `start_webui.bat` 仍保留（浏览器模式，会自动开浏览器）。

### 两个原生窗口（术语区分，2026-11-13 N04 补档）

「原生窗口」一词在本项目里指**两个不同的实现**，注意不要混用：

| | 壳 1 · `webui_app.py`（Python） | 壳 2 · `native/FAA.WpfGui`（C#/WPF） |
|---|---|---|
| 技术栈 | WebView2 / pywebview，Python 单文件（~405 行） | WPF + CommunityToolkit.Mvvm（48 文件，cs+xaml 7712 行） |
| 自称 | 模块 docstring「原生窗口外壳」 | 窗口标题/弹框标题 **`FAA 原生窗口`**（`DialogService.cs` DefaultTitle、`App.xaml.cs` FindWindow 按此标题单实例激活） |
| 启动 | `python webui_app.py` / `start_webui_app.bat` | 构建后运行 `native/FAA.WpfGui`（`build_native.bat`）；后端仍复用同一 `webui.py` 服务 |
| 状态 | 已入仓可运行（HEAD「新增原生窗口外壳」） | 批 16-22 + 收尾批交付，构建需 .NET SDK（闸门 `check_project.py` 原生 UI 预检，无 SDK 降级 WARN） |

两壳**共用同一个后端**（`webui.py` 的 HTTP 服务，端口 8765），功能等价仅外壳不同；本文档「推荐原生窗口」段落指**壳 1**（当前 README 启动说明所覆盖的实现），壳 2 的工程细节见 `native/FAA.WpfGui/` 与 `PROGRESS.md` WPF 线里程碑索引。

浏览器打开 `http://127.0.0.1:8765/`，右上角可切换两个界面：

- **使用界面**（仿 MAA）：每日挂机任务勾选（全部可选，逐项可 ⚙ 设置）、完成后动作、开始一轮 / 停止当前流程、账号切换、连接设置。
- **测试界面**：实时画面 + OCR 标注（点画面即点击模拟器）、运行单个流程、可选功能开关、运行日志、流程/知识库浏览（按场景树形分组）。

`/tpltool` 为**人机协同标注页**：连接后截图 → 框选 / 画笔重点 / 描边轮廓 → 保存标记 → 提交坐标 JSON（提交时附带原始截图，落到 `data/annot_shots/`，保证坐标与画面严格绑定）。

---

## 模块化编排

[`flows/daily.json`](flows/daily.json) 按序调度 **7 大模块**（2026-10-06 签到并入 startup；2026-10-12 领取与每日任务换序），**全部为可选**（`required:false` + `on_fail:skip`）：单个模块失败只跳过，不终止整轮。

| 模块 id | 流程 | 说明 |
|---|---|---|
| `startup` | flow_startup.json | 开始启动（资源更新守卫 → 登录进游戏 → 可选「切换账号」→ 签到） |
| `plant` | flow_plant.json | 种植作业（桃花系花种可选 `plant_flower_type`；种植/收获/关面板归位已实现，授粉占位） |
| `social` | flow_social.json | 社交任务 = ①家族活动（摇钱树/矿洞探险/闪耀委托挑战/守望兔子）②好友采粉（`enable_pollin`）；社区点赞已于里程碑 90 迁入每日任务 |
| `energy` | flow_energy.json | 体力任务（闪耀变身循环速通） |
| `claim` | flow_claim.json | 领取奖励（在线礼包 `claim_online` / 花灵派对 `claim_party` / 奇妙花宝 `claim_hb`——含奇妙特权三档与**花神之契周/月礼包** / **花仙乐园 `claim_fairyland`**——在线骰子+每日任务，含仙豆补购闭环） |
| `daily` | flow_daily_task.json | 每日任务（手账 v2 闭环，含社区点赞） |
| `idle` | flow_idle.json | 挂机 |

各模块的开关在 `data/config.json`（WebUI 使用界面逐模块 ⚙ 可直接改）。公开仓库中的默认值应为（本地运行时可自行填写目标账号尾号）：

```json
{
  "enable_switch": false, "target_tail": "",
  "claim_online": true, "claim_party": true, "claim_hb": false,
  "claim_fairyland": true, "enable_shine": false, "enable_pollin": true,
  "plant_flower": false, "plant_flower_type": "桃花",
  "plant_pollinate": false, "plant_harvest": false, "plant_buy_seed": false
}
```

完整键位与默认值见 [`data/config.example.json`](data/config.example.json)；`data/config.json` 缺失新键时按各步骤的 `default`/缺键语义执行（如 `claim_fairyland` 默认 true、`enable_water` 缺键视为开启）。

---

## 流程 JSON

流程是纯数据，步骤类型由引擎解释（[`ocr_engine.py`](ocr_engine.py) `run_step`）。下例摘自 [`flows/flow_startup.json`](flows/flow_startup.json)（略去部分步骤）：

```json
{
  "name": "开始启动",
  "steps": [
    { "type": "if_config",
      "key": "enable_switch",
      "value": true,
      "then": [
          { "type": "click_text", "text": ["切换账号"], "delay": 1.8 },
          { "type": "click_account_tail",
            "tail": "${target_tail}",
            "region_rel": [0.45, 0.35, 0.58, 0.56],
            "min_score": 0.4, "delay": 1.5 }
      ] },
    { "type": "if_text",
      "text": ["登录"], "min_score": 0.35,
      "then": [{ "type": "click_text", "text": ["登录"], "delay": 2.0 }] },
    { "type": "if_text",
      "text": ["点击进入游戏", "进入游戏"], "min_score": 0.35,
      "then": [{ "type": "click_text", "text": ["点击进入游戏", "进入游戏"], "delay": 2.0 }] }
  ]
}
```

**支持的步骤类型（共 46 种，2026-11-17 核对）**

| 类别 | 步骤类型 |
|---|---|
| 定位/点击 | `click_text`（可 `exact`/`region_rel`/`exclude`/`mark`/`no_fallback`）、`click_template`（可 `metric`/`offset_rel`）、`click_rel`、`click_account_tail`、`click_row_button`（行锚定点击） |
| 等待/停顿 | `wait_text`、`wait_text_gone`（可 `require_seen`）、`wait_update_done`（资源更新守卫）、`sleep`、`wait_scene`（可传场景列表） |
| 条件分支 | `if_text`、`if_account_tail`、`if_fraction`、`if_greater`、`if_config`、`if_time`、`if_weekday`、`if_scene`、`count_text`、`if_color_count`、`if_collected`、`if_count` |
| 循环 | `loop_text`、`loop_fraction`、`loop_times`、`retry_loop` |
| 状态/其它 | `store_fraction`、`close_dialog`、`ensure_menu`、`ensure_home`、`navigate`、`friend_pollin`、`plant_flower`（种植花朵阶段1+2：搜索→按 `plant_flower_type` 精点目标花种→数量1→随机种植→详情确认→回读 d-1/肥力变化→关面板归位）、`plant_harvest`（收获花朵：可收获/可授粉判定→无待授粉才一键收花→关奖励弹窗→关面板归位）、`fairyland_claim`（花仙乐园：在线骰子+每日任务兑换/浇水/仙豆，按钮底色置灰判据）、`buy_seed`（购买种子：搜索→选种→数量→价格/余额校验→购买→二次确认→关弹窗；参数 `seed`/`count`/`times`）、`community_like`、`claim_scroll`、`dump_text`、`reward_dialog`、`count_probe`、`touch_drag`、`slide`、`dump_frame`（手动故障存证）、`buy_item`（花宝受控购买）、`fail_flow` |

- **公共导航**：`navigate` 引用 [`flows/common/entries.json`](flows/common/entries.json) 的 target（已登记 家族活动 / 闪耀变身 / 花灵派对），把"归位→逐层导航→目标命中→脱困重试"收敛到一处，避免各流程重复内嵌进入链。
- **知识库（可选）**：默认 `log_click_pos=false`，运行时不写 `data/click_log.json`；显式开启后，OCR/颜色命中才会按 `scene` + `category` 分组并累积 `mean_rel` 均值样本。缓存回退不作为命中证据、不落库。

---

## 提交前注意

本仓库为公开仓库。`data/config.json` **已取消版本跟踪并加入 `.gitignore`**（它含 `target_tail`、`water_count*` 等本机运行状态）——首次使用请复制 [`data/config.example.json`](data/config.example.json) 为 `data/config.json` 再填写；提交模板时 `target_tail` 必须留空 `""`。此外仍需筛查 `data/click_log.json` 是否混入账号类条目（2026-09-18 已改为 `账号条目#N` 行序键名，不再写入真实账号文本）。详见 [`PROGRESS.md`](PROGRESS.md)「提交 GitHub 方法」与「敏感数据清除记录」。

---

## License

MIT License — see [LICENSE](LICENSE).

This software is provided for learning and personal use only. No affiliation with the game's developer/publisher.