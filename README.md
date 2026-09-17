# FlowerAutoAssistant (FAA)

面向页游《小花仙》的**一键挂机**自动化框架。基于 **OCR 文字识别 + 相对坐标** 的数据驱动方案，实现"识别界面 → 定位按钮 → 点击执行 → 循环挂机"。

> ⚠️ **仅供学习与个人使用。** 本项目不包含任何游戏素材、资源包或解包工具，仅含通用自动化逻辑。请遵守游戏服务条款及所在地区法律法规，由此产生的账号风险由使用者自行承担。

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

另有独立步骤类型 **`click_template`** 专供纯图形按钮：多尺度（默认 0.7~1.0）模板匹配 `TM_SQDIFF_NORMED`，支持 `region_rel` 限定与 `fallback_rel` 兜底；模板在 `resource/template/`。

---

## 目录结构

```
FlowerAutoAssistant/
├── main.py              # CLI 入口：连接、选流程、循环执行、断线重连、Ctrl+C 停止
├── webui.py             # 本地 WebUI 后端（标准库 http.server，端口 8765）
├── webui.html           # WebUI 前端：使用界面 / 测试界面（实时画面+OCR标注+日志）
├── tpltool.html         # 人机协同标注页 /tpltool：只产出坐标标注，不直接存模板
├── start_webui.bat      # 双击启动 WebUI（优先用 .venv，自动开浏览器）
├── ocr_engine.py        # 核心引擎：连接/截图/OCR定位/颜色/模板/点击/知识库/流程执行
├── ocr_ui.py            # RapidOCR 单例（模型只初始化一次）
├── flows/               # 数据驱动流程（改 JSON 不改代码）
│   ├── daily.json       #   编排：8 大模块按序调度
│   ├── flow_*.json      #   各模块流程（startup/signin/plant/social/energy/daily_task/claim/idle）
│   └── common/entries.json  # 公共导航注册表（navigate 步骤引用）
├── data/
│   ├── click_log.json      # 按钮知识库（v2 场景两层嵌套 + 均值/样本数）
│   ├── close_buttons.json  # 关闭按钮-特殊逻辑注册表
│   ├── config.example.json # 功能开关模板（复制为 config.json 后填写）
│   ├── config.json         # 功能开关与目标账号尾号等配置（本地私有，已 gitignore）
│   ├── tplt_annotations.jsonl / annot_shots/  # tpltool 标注产物（坐标+绑定截图）
├── resource/template/   # 模板匹配模板（已 gitignore）
├── workbench/           # 未确认功能的暂存区（用户确认后才并入主体）
├── dev_tools/           # 常驻开发工具：self_test(离线自测) / calibrate(实机校准) / explore(探查采集)
└── PROGRESS.md          # 项目活文档：运行前先读，里程碑完成即更新
```

> `debug/`（截图）、`legacy/`（旧 MAA 路线备份）、`.venv/`、`resource/` 已加入 `.gitignore`，不参与版本控制。

---

## 依赖安装

```bash
pip install -r requirements.txt
# maafw, opencv-python, Pillow（RapidOCR 随依赖安装）
```

## 环境

- Python 3.11+（**务必用项目 `.venv`**；系统 Python 通常无 `numpy`/`maa`）
- MuMu 模拟器 12（ADB 端口默认 `127.0.0.1:16384`）
- 画面：1280×720 横屏（相对坐标自动适配其它尺寸）

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

# 执行某个模块流程，如社交任务（含可选「闪耀委托挑战」）
python main.py --flow 社交任务 --loop 1

# 指定 ADB 地址 / adb 路径 / 临时覆盖切换账号目标尾号
python main.py --address 127.0.0.1:16384 --adb "D:\Program Files\Netease\MuMu\nx_main\adb.exe" --tail 61
```

引擎侧另有一批开发用 CLI（直接运行 `python ocr_engine.py` 会打印用法）：`--collect`（采集当前界面文字写入知识库）、`--ocr-screen`（打印全屏文字块+相对坐标）、`--ocr-anchor <锚点关键字> [--exact]`（打印各块相对锚点的像素偏移）、`--close-test`、`--add-close <名称> <corner|anchor_color>`。

### WebUI

```bash
python webui.py            # 默认 8765
start_webui.bat            # 或双击：优先用 .venv，启动后自动开浏览器
```

浏览器打开 `http://127.0.0.1:8765/`，右上角可切换两个界面：

- **使用界面**（仿 MAA）：每日挂机任务勾选（全部可选，逐项可 ⚙ 设置）、完成后动作、开始一轮 / 停止当前流程、账号切换、连接设置。
- **测试界面**：实时画面 + OCR 标注（点画面即点击模拟器）、运行单个流程、可选功能开关、运行日志、流程/知识库浏览（按场景树形分组）。

`/tpltool` 为**人机协同标注页**：连接后截图 → 框选 / 画笔重点 / 描边轮廓 → 保存标记 → 提交坐标 JSON（提交时附带原始截图，落到 `data/annot_shots/`，保证坐标与画面严格绑定）。

---

## 模块化编排

[`flows/daily.json`](flows/daily.json) 按序调度 8 大模块，**全部为可选**（`required:false` + `on_fail:skip`）：单个模块失败只跳过，不终止整轮。

| 模块 id | 流程 | 说明 |
|---|---|---|
| `startup` | flow_startup.json | 开始启动（登录进游戏，内含可选「切换账号」） |
| `signin` | flow_signin.json | 签到（当日已签自动跳过） |
| `plant` | flow_plant.json | 种植作业 |
| `social` | flow_social.json | 家族活动·摇钱树浇水；内含「闪耀委托挑战」(`enable_shine`) |
| `energy` | flow_energy.json | 体力任务（闪耀变身循环速通） |
| `daily` | flow_daily_task.json | 每日任务 |
| `claim` | flow_claim.json | 领取奖励（在线礼包 `claim_online` / 花灵派对 `claim_party`） |
| `idle` | flow_idle.json | 挂机 |

各模块的开关在 `data/config.json`（WebUI 使用界面逐模块 ⚙ 可直接改）。公开仓库中的默认值应为（本地运行时可自行填写目标账号尾号）：

```json
{
  "enable_switch": false, "target_tail": "",
  "claim_online": true, "claim_party": true, "enable_shine": false
}
```

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

**支持的步骤类型（共 18 种）**

| 类别 | 步骤类型 |
|---|---|
| 定位/点击 | `click_text`（可 `exact`/`region_rel`/`fallback_rel`/`mark`）、`click_template`、`click_rel`、`click_account_tail` |
| 等待/停顿 | `wait_text`、`sleep` |
| 条件分支 | `if_text`、`if_fraction`（读 `a/b` 求值）、`if_greater`（读 `关键字:N`）、`if_config`（读 `config.json`）、`count_text`（文本计数） |
| 循环 | `loop_text`（识别到就重复，按钮消失即停）、`loop_fraction`（按分数算次数）、`loop_times`（固定次数）、`retry_loop`（脱困重试，`mark` 命中即成功） |
| 状态/其它 | `store_fraction`（把 `a/b` 分子存入 config，如每日浇水次数）、`close_dialog`（关弹窗，可 `only_types` 过滤）、`navigate`（按公共注册表进入目标界面） |

- **公共导航**：`navigate` 引用 [`flows/common/entries.json`](flows/common/entries.json) 的 target（已登记 家族活动 / 闪耀变身 / 花灵派对），把"归位→逐层导航→目标命中→脱困重试"收敛到一处，避免各流程重复内嵌进入链。
- **知识库自动积累**：每次点击成功即写入 `data/click_log.json`（按 `scene` 场景 + `category` 类别分组，`ocr`/`color` 命中还会累积 `mean_rel` 均值样本），越用越稳。

---

## 提交前注意

本仓库为公开仓库。`data/config.json` **已取消版本跟踪并加入 `.gitignore`**（它含 `target_tail`、`water_count*` 等本机运行状态）——首次使用请复制 [`data/config.example.json`](data/config.example.json) 为 `data/config.json` 再填写；提交模板时 `target_tail` 必须留空 `""`。此外仍需筛查 `data/click_log.json` 是否混入账号类条目（2026-09-18 已改为 `账号条目#N` 行序键名，不再写入真实账号文本）。详见 [`PROGRESS.md`](PROGRESS.md)「提交 GitHub 方法」与「敏感数据清除记录」。

---

## License

MIT License — see [LICENSE](LICENSE).

This software is provided for learning and personal use only. No affiliation with the game's developer/publisher.