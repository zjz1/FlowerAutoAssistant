# 《小花仙》挂机助手 · 批次审阅规则（主 agent 专用）

> **用途**：把「每批审阅必须检查什么、什么算不合格」固化成**可执行清单**，供
> `tools/review_batch.py` 自动执行、供主 agent 人工复核。
> **原则**：自动检查只证明「形式合规」；**不替代独立判断**，也不采信提交方 REPORT 的结论。
> **同源**：每次合并后发布到 [`_collab/审阅通报.md`](../../_collab/审阅通报.md)；本文件是其机器化版本。

---

## 1. 分级审阅（Tier）

分级由 `tools/review_batch.py` **按交付文件路径自动判定**，写入台账。

| 级别 | 触发条件 | 审阅强度 |
|---|---|---|
| **T0 文档/注释** | 仅 `docs/**`、`README.md`、`PROGRESS.md`、`*.md`、注释级改动 | 自动检查全过 + 抽读关键段 |
| **T1 配置/流程** | 仅 `flows/**`、`data/*.json`（无引擎/ pollin/webui 改动） | 语义 diff（字段级）+ 关键断言 + 闸门；按比例抽样复核 |
| **T2 引擎/关键路径** | 触及 `ocr_engine.py` / `pollin.py` / `webui.py(.html)` / `ocr_ui.py` / `community_like.py` | **逐 hunk 独立复验** + 规则全扫 + 回归桩测 + 闸门；严格度不降 |

> 分级是**审阅强度**的分级，不是「信任传递」。T2 永远全量；T1 的抽样不等于免检，
> 发现一处问题即升级为全量。

---

## 2. 自动规则（`review_batch.py` 执行）

| ID | 级别 | 规则 | 为什么 |
|---|---|---|---|
| **R0** | FAIL | 交付文件与 `files/` 清单完整、可解析（JSON/py） | 缺文件/坏 JSON 直接阻断 |
| **R1** | WARN | 基线 md5 与 REPORT 声称一致（若 REPORT 中出现该值） | 防「拿错基线」的幽灵 diff |
| **R2** | FAIL | 新增 `click_rel` / `fallback_rel` / 直坐标点击 | 用户规则 6：点击必须实时 OCR/模板定位 |
| **R3** | WARN | 新增 `click_template.threshold < 0.9` | 低阈值关闭兜底会误点收起菜单（M103/M105 教训） |
| **R4** | FAIL | 新增点击危险控件：「屏蔽聊天」「删除好友」「神叶/灵豆/星之粉」等 | 误点不可逆或消耗货币 |
| **R5** | FAIL | 交付的新模板必须已在主仓库且 md5 一致 | 只交 inbox 不落位 → 运行时模板 MISS（M105 事故） |
| **R6** | FAIL | 主仓库 `flows/**` 引用的模板全部存在 | 同上，落位后立刻可运行 |
| **R7** | FAIL | 交付 flow 用到的步骤类型 ⊆ 引擎 `s_type ==` 分派 | 防未知类型静默不执行 |
| **R8** | WARN | 新增 `require_seen: true` | 快速过场链会假失败（D19）；需人工确认该链不会「点击后立即换页」 |
| **R9** | WARN | 新增默认开启的性能/行为闸门 | 新闸门必须默认关 + 缺省路径逐字节等价（-9/-13 模式） |
| **R10** | INFO | 语义 diff 清单（新增/删除/修改路径）与 REPORT 声称的「N 处 diff」比对 | 防「格式重排掩盖语义改动」 |

> WARN 不阻断合并，但**必须进入台账「待人工确认」**并在回复中列出。

---

## 3. 人工复核（主 agent 必做，不可外包给脚本）

1. **只看证据，不看主张**：REPORT 的「已验证」一律不当结论，必须能在 diff / 测试输出 / 日志中找到对应物。
2. **T2 逐 hunk**：每个 hunk 回答三问 —— ①改了什么行为？②缺省/关闭时是否逐字节等价？③失败方向是否安全？
3. **判据选型**：新增 `require_seen` / `wait_text` / `wait_scene` / `if_*` 时，先判断页面切换速度与假阳性方向。
4. **回归面**：本次触及的公共函数（`close_*`、`ensure_home`、`click_btn_fine`、`_timed_ocr`、
   `run_navigate`、`reward_dialog`）的其它调用点是否受影响。
5. **文档同步**：FLOWS 对应章节 / PROGRESS 里程碑 / 台账 / C 类回归项 / D 类缺陷结案。

---

## 4. 审阅台账（`_collab/审阅台账.jsonl`）

只追加、不改写。每批一行 JSON：

```json
{"ts":"2026-11-01 12:00:00","batch":"zcode-20261031-11","tier":"T1","milestone":109,
 "files":[{"path":"flows/flow_daily_task.json","repo_md5":"...","delivered_md5":"...","baseline_match":true,"state":"已落位"}],
 "checks":{"gate":"PASS","rules":{"R2":"PASS","R4":"PASS","R7":"PASS","R10":"3 处语义差异"}},
 "verdict":"PASS","manual_notes":["D19：两链移除 require_seen，保留 required"],"followups":["C59"]}
```

下次审阅只需：`git status` + 最近一条台账 + 本批 `review_batch` 输出，**不再重读全部历史文档**。

---

## 5. 用法

```powershell
# 审阅一个批次（inbox 或 merged 均可）
& ".venv\Scripts\python.exe" tools\review_batch.py --batch zcode-20261031-11

# 审阅并写入台账（合并完成后执行）
& ".venv\Scripts\python.exe" tools\review_batch.py --batch zcode-20261031-11 --write-ledger

# 指定路径 / 跳过闸门（仅调试工具本身时使用）
& ".venv\Scripts\python.exe" tools\review_batch.py --path "_collab\merged\zcode-20261031-11" --no-gate
```

输出 = 分级 + 文件指纹表 + 规则结果 + 语义 diff 摘要 + **人工必看清单**。
退出码：`0` = 无 FAIL；`1` = 有 FAIL（不得合并）。
