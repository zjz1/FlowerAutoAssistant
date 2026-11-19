# FAA 1.0 发布准备最终方案

> 目标：**基础功能全部完成后，一次性打包发布 1.0**。发布准备期间不引入版本号、不打内部 tag；只在最终发布时打 `v1.0.0`。
>
> 本方案在侧边对话草案基础上定稿：保留 23 项编号，取消“今日闭环”和 0.x 版本号，改为**阶段 + 发布门槛**，避免把 1.0 做成 MVP。
>
> 范围：发布工程、合规、质量、文档与分发；**不开发游戏新功能**。

---

## 0. 关键修正（相对侧边草案）

1. **取消“23 项今日闭环”**：23 项是发布准备清单，不是一天的任务。每项标注 `1.0 必须 / 1.0 优先 / 1.x 延后`。
2. **取消内部版本号**：不建 `v0.1.0-internal`，不打 0.x tag；`CHANGELOG.md` 只写 `Unreleased`，1.0 发布时整理为 release notes。
3. **G1 已有结论**：当前 `maafw 5.12.3` 的许可证是 **LGPL-3.0**，不是 AGPL。项目 `LICENSE` 为 MIT，可以保留，但发布包必须包含：
   - LGPL-3.0 许可证文本；
   - maafw 上游源码/获取方式；
   - “该库为可替换依赖”的说明；
   - `THIRD_PARTY_NOTICES.md`。
4. **G2 已定：保留模板（方案 B）**：`resource/template` 当前有 **38 个模板**，按“保留 + 风险记录”处理，不因模板重写 Git 历史。1.0 必须补齐 `ASSETS.md`、README 免责声明、MIT 许可例外（模板不属于 MIT 授权范围）和下架机制；本地采集工具列为 1.x 可选。
5. **已核实的基线**：
   - `LICENSE`：MIT；
   - 服务监听：`127.0.0.1`（不是 `0.0.0.0`）；
   - `.gitignore`：已隔离 `data/config.json`、`click_log.json`、`debug/`、`native/dist/` 等；
   - 当前工作树有未提交的升级弹窗/重启后端修复，Phase 0 先提交；
   - 尚无 CI、`CHANGELOG.md`、`CONTRIBUTING.md`、`SECURITY.md`、`THIRD_PARTY_NOTICES.md`、`ASSETS.md`。
6. **发布前不建版本 tag**：只建发布准备分支（建议 `release/prep`）；最终发布时才打 `v1.0.0`。

---

## 1. 1.0 的进入与退出条件

### 1.1 进入条件（开始发布准备）

- 游戏基础功能清单完成（以 `PROGRESS.md` / `docs/FLOWS.md` 为准）：
  - 7 大模块编排：startup / plant / social / energy / claim / daily / idle；
  - 买种、种植/收获、花仙乐园、好友采粉、社区点赞等闭环；
  - WPF 原生 UI 主路径可用，WebUI 备用/调试可用。
- 用户确认**功能冻结**：发布准备期间只修 bug 和发布工程，不加游戏功能。
- 当前未提交修复已提交；基线全绿：
  - Python 测试 **80/80**；
  - WPF 测试 **65/65**；
  - `check_project --with-tests` **100/100**。

### 1.2 退出条件（允许发布 1.0）

- 所有 **P0（1.0 必须）** 项完成；P1 完成或明确 `deferred` 且写明原因；**不允许 P0 deferred**。
- CI 全绿；干净 Windows VM 上便携 zip 可启动，`/api/health=faa`（此步不需要 MuMu）。
- 宿主 MuMu 上完成一条基础 smoke（连接 + 一个模块）；真机门槛与干净 VM 分开执行。
- 文档闭环：Quick Start / FAQ / Troubleshooting / 支持矩阵 / 诊断导出可用。
- 安全闭环：只绑 `127.0.0.1`、Origin 白名单、日志/诊断脱敏。
- 只在最后打 `v1.0.0`；此前不产生任何版本 tag。

### 1.3 环境依赖

| 依赖 | 涉及项 | 说明 |
|---|---|---|
| 不需要 MuMu | Phase 0；#2-#9；#11-#13；#15-#20；#23 | 离线测试、构建、文档、扫描、本地 HTTP、回放（截图） |
| 可选 MuMu | #10/#11 实机复核 | 实现/单测/回放可离线；实机复核是加分项，不是 1.0 阻塞 |
| 需要 MuMu | #1/#22 的最终 smoke；#14 正向连接；Phase 6 | `/api/health=faa` 不需要 MuMu；“连接 + 跑一个模块”的 smoke 需要 |
| 需要 GitHub 远端 | #2/#3/#23；Phase 6 tag/release | CI/Release/推送需要远端写权限 |
| 需要干净 Windows VM | #1/#22 启动验证 | 只验启动/health，不需要 MuMu；真机 smoke 在宿主做 |
| 需要先关闭当前 UI | Phase 2 WPF 发布 | `native/dist/FAA.WpfGui.exe` 被运行中的 UI 锁定 |

---

## 2. 23 项发布准备清单

> 编号沿用侧边草案，便于引用。  
> `1.0 必须` = 发布门槛；`1.0 优先` = 尽量完成，可记录 deferred；`1.x 延后` = 不阻塞 1.0。

| # | 项目 | 1.0 要求 | 交付/验收 | 阶段 |
|---|---|---|---|---|
| 1 | 后端可分发打包 | **1.0 必须** | PyInstaller one-folder（含 OCR 模型/flows/模板策略产物）；干净 VM 不装 `.venv` 可启动 `/api/health=faa` | Phase 2 |
| 2 | GitHub Actions CI | **1.0 必须** | windows-latest：Python 80 测试 + `check_project` + WPF build/test；PR 全绿 | Phase 2 |
| 3 | Release 工作流 | **1.0 必须** | 手动 `workflow_dispatch` 干跑：产 zip + SHA256；发布前不建版本 tag | Phase 2 |
| 4 | 许可证与第三方合规 | **1.0 必须** | MIT + LGPL-3.0 处理；`THIRD_PARTY_NOTICES.md`；maafw 源码链接/可替换说明；G1 记录 | Phase 1 |
| 5 | 模板/截图版权策略 | **1.0 必须** | 按方案 B 保留 38 个模板；补 `ASSETS.md`（来源/用途/版权归属）、README 免责声明、MIT 例外、下架机制；G2 风险接受记录 | Phase 1 |
| 6 | 仓库卫生与隐私扫描 | **1.0 必须** | 密钥/个人绝对路径/账号尾号扫描；`.gitignore` 审计；历史问题记录；重写需明确批准 | Phase 1 |
| 7 | 首启配置与数据隔离 | **1.0 必须** | 自动复制 `config.example`；zip 不含 `data/config.json`、`click_log`、`fail_cache`、`debug` | Phase 1/2 |
| 8 | 发行版 UI 策略 | **1.0 必须** | WPF 主推；WebUI 备用/调试；pywebview 只留开发，不进发行包/运行依赖 | Phase 1 |
| 9 | 离线回放/回归基座 | **1.0 必须** | `dev_tools/replay` + 3–5 个 golden case（升级弹窗/无花粉/底行/好友列表出口）；输出 OCR/定位/动作证据 | Phase 3 |
| 10 | 输入可靠性/动作结果校验 | **1.0 必须** | 共享 `verify_action`：无变化/阻断层/无花粉/真失败；接入高频点击与 `close_dialog`；单测覆盖 | Phase 3 |
| 11 | 阻断层/覆盖层 registry | **1.0 优先** | `data/blockers.json` + 四类弹窗；接入 `ensure_home`/`close_dialog`；新增弹窗只加数据 | Phase 3 |
| 12 | flow 校验器 | **1.0 必须** | `check_project` 增加必填字段、`region_rel` 四元数、关键字列表校验；坏 flow 能被拒 | Phase 3 |
| 13 | 配置迁移/版本化 | **1.0 必须** | `schema_version` + 保留未知键；旧配置升级不丢键；校验通过 | Phase 3 |
| 14 | 首启环境检查 | **1.0 必须** | `--check-env` + WPF 首启入口；ADB/端口占用/缺配置有可操作提示 | Phase 4 |
| 15 | 支持矩阵 | **1.0 必须** | `docs/SUPPORTED_ENV.md`：Windows 10/11、MuMu 12、分辨率；不支持环境明确报错 | Phase 4 |
| 16 | 诊断包导出 | **1.0 优先** | 日志 + 环境 + 脱敏配置；截图默认不含；导出包可复现问题且无敏感信息 | Phase 4 |
| 17 | 用户文档与社区模板 | **1.0 必须** | README Quick Start + FAQ + Troubleshooting + CONTRIBUTING + issue/PR 模板 | Phase 4 |
| 18 | 用户可读错误目录 | **1.0 必须** | ADB/模板/分辨率/端口/权限错误有建议；错误码/文案集中维护 | Phase 4 |
| 19 | 本地 HTTP 安全加固 | **1.0 必须** | 保持只绑 `127.0.0.1`；Origin 白名单；非白名单 POST 被拒；本机 UI 正常 | Phase 5 |
| 20 | 日志/诊断脱敏 | **1.0 必须** | ADB 路径、账号尾号、用户名不出现；日志/诊断统一走脱敏模块 | Phase 5 |
| 21 | 自动重启 | **1.x 延后** | 手动「重启后端」已可用；自动重启需退避+上限，1.x 再做 | Phase 6 |
| 22 | 便携 zip | **1.0 必须** | WPF dist + 后端包 + 启动脚本 + SHA256；zip 可启动；安装器/签名 1.x | Phase 2 |
| 23 | Dependabot/SECURITY | **1.0 优先** | `.github/dependabot.yml` + `SECURITY.md`；依赖更新策略明确 | Phase 5 |

---

## 3. 阶段与执行顺序

### Phase 0：基线冻结

- 提交当前未提交修复（升级弹窗、重启后端、PROGRESS 等）。
- 建发布准备分支（建议 `release/prep`，不带版本号）。
- 跑基线：Python 80/80、WPF 65/65、`check_project --with-tests` 100/100。
- 新建 `CHANGELOG.md`，只写 `Unreleased`，按里程碑记录；不建 0.x tag。
- 确认功能冻结清单。

### Phase 1：合规与公开准备（决定“能不能公开”）

- #4 许可证/NOTICE：按 LGPL-3.0 处理 maafw；补齐第三方清单。
- #5 模板策略（G2 已定 B）：保留 38 个模板；补 `ASSETS.md`、README 免责声明、MIT 例外和下架机制；不因模板重写历史。
- #6 仓库扫描：密钥、个人路径、账号尾号；历史提交审计；重写需批准。
- #8 UI 策略：WPF 主推；WebUI 备用；pywebview 移出发行依赖。
- #7 配置隔离：首启复制 `config.example`；发行包排除用户数据。

**G2 已定 B**：发行包保留模板；#1 打包时按 `ASSETS.md` 一并带入，不再等待模板移除。

### Phase 2：可分发（决定“能不能发出去”）

- #1 打包 spike：先验证 PyInstaller 能否打包 maafw/RapidOCR/ONNX；失败则回退“嵌入 Python + venv”方案。
- #2 CI：先跑 Python 测试 + 闸门；WPF build/test 可拆 job。
- #3 Release 工作流：`workflow_dispatch` 干跑，产出 artifact；不建版本 tag。
- #22 便携 zip：WPF dist + 后端 + 启动脚本 + SHA256。
- #7 首启验证：干净目录/干净 VM 启动。
- 发布前关闭当前运行中的 UI（`native/dist` 被运行中的 exe 锁定）；CI 可先构建到临时目录。

### Phase 3：质量与回归

- #9 回放：用 `fail_cache` 和日志固化 golden cases。
- #10 `verify_action`：统一点击后的验证/分类/重试。
- #11 阻断层：先覆盖四类已知弹窗；后续只加数据。
- #12 flow 校验器：集成 `check_project`。
- #13 配置迁移：`schema_version` + 未知键保留。

### Phase 4：用户上手与支持

- #14 `--check-env` + WPF 首启入口。
- #15 支持矩阵与明确报错。
- #16 诊断包导出（脱敏，截图默认不含）。
- #17 用户文档/社区模板。
- #18 错误目录与文案。

### Phase 5：安全与维护

- #19 Origin 白名单（监听已是 `127.0.0.1`）。
- #20 脱敏模块接入日志/诊断。
- #23 Dependabot/SECURITY。
- #6 扫描复跑。

### Phase 6：1.0 发布门

- 干净 Windows VM：便携 zip 启动，`/api/health=faa`（不依赖 MuMu）。
- 宿主 MuMu：连接 + 一个模块 smoke 通过；这是唯一集中使用 MuMu 的发布门。
- CI 全绿；回放 case 全过；扫描 0 命中；合规/文档/安全证据齐全。
- 整理 `CHANGELOG` → release notes；打 `v1.0.0`（唯一版本 tag）。

---

## 4. 决策门

| 门 | 问题 | 结论/建议 |
|---|---|---|
| G1 | maafw 许可证 | **已核实 LGPL-3.0**；MIT 保留，补 LGPL 文本、源码链接、可替换说明、NOTICE |
| G2 | 游戏截图模板 | **已定：B 保留**。补 `ASSETS.md`、README 免责声明、MIT 例外（模板不在 MIT 授权范围）、下架机制；不因模板重写历史；本地采集工具 1.x 可选 |
| G3 | UI 发行策略 | WPF 主推；WebUI 备用/调试；pywebview 只留开发 |
| G4 | 后端打包方式 | PyInstaller 优先；失败回退嵌入 Python/venv；干净 VM 为最终判据 |
| G5 | 安装器/签名 | 1.0 只发便携 zip；安装器/代码签名 1.x |
| G6 | 自动重启 | 1.x；1.0 保留手动「重启后端」 |
| G7 | Git 历史重写 | 仅当扫描发现模板/密钥/个人路径；必须明确批准后执行 |
| G8 | 支持环境 | Windows 10/11 + MuMu 12 为 1.0 支持范围；其他模拟器 best-effort |

---

## 5. 风险清单

| 风险 | 影响 | 应对 |
|---|---|---|
| PyInstaller 打包 maafw/RapidOCR 失败 | 无法分发 | 先做 spike；回退嵌入 Python/venv；不阻塞其他项 |
| 保留模板的版权风险 | 公开分发风险 | 方案 B：`ASSETS.md` + 免责声明 + MIT 例外 + 下架机制；收到权利方异议即移除/替换；不构成法律保证 |
| Git 历史含密钥/个人路径 | 公开风险 | #6 扫描；必要时 `git filter-repo`/BFG，需批准后 force-push；模板保留不触发重写 |
| CI 安装依赖/WPF 构建慢 | 反馈慢 | 缓存、拆 job；Python 测试+闸门必须，WPF 可 nightly |
| 干净 VM/法律意见不可用 | 无法宣称 1.0 | 明确标为发布门槛，不冒充完成 |
| 当前修复未提交就继续开发 | 改动混杂 | Phase 0 先提交，再建发布分支 |
| pywebview 被误打进发行包 | 依赖膨胀/支持面扩大 | #8 移出发行依赖，dev-only |
| 版本号提前出现 | 违背用户策略 | 发布前不建 tag；仅最终 `v1.0.0` |

---

## 6. 证据记录模板

| 项 | 结果（done/deferred） | 证据 | 备注 |
|---|---|---|---|
| 1 | | 包路径 / health 输出 / 干净 VM 记录 | |
| 2 | | CI run URL | |
| 3 | | workflow run URL / artifact | |
| 4 | | NOTICE 路径 / G1 结论 | |
| 5 | | 模板审计表 / ASSETS.md / G2 结论 | |
| 6 | | 扫描摘要 / 历史处理决定 | |
| 7 | | 首启验证日志 | |
| 8 | | README / 启动脚本 / 发行清单 | |
| 9 | | 回放输出 | |
| 10 | | 单测输出 | |
| 11 | | blockers.json / 测试 | |
| 12 | | 校验器输出 | |
| 13 | | 配置升级测试 | |
| 14 | | `--check-env` 输出 | |
| 15 | | SUPPORTED_ENV.md | |
| 16 | | 脱敏导出包样例 | |
| 17 | | 文档链接 | |
| 18 | | 错误目录/测试 | |
| 19 | | 安全测试输出 | |
| 20 | | 脱敏测试输出 | |
| 21 | | deferred 说明 | |
| 22 | | zip 路径 / SHA256 | |
| 23 | | 文件链接 | |

---

## 7. 明确不做

多语言、多平台、资源热更、作业分享、任务队列/多账号、步骤插件 API、完整 MaaDebugger、继续拆 `OCREngine`/`pollin`/`webui`、指标面板/结构化日志、自动更新（先用 GitHub Releases 手动下载）。

1.x 延后：自动重启、安装器/代码签名、完整首启向导、校准工具、本地模板采集工具、全量 46 种步骤的 `verify_action` 覆盖。

---

## 8. 下一步

1. Phase 0：提交当前修复，建 `release/prep`，跑基线，写 `CHANGELOG.md`（Unreleased）。
2. Phase 1：完成 #4 许可证/NOTICE、#5 模板 `ASSETS.md`/免责声明/MIT 例外、#6 仓库扫描、#8 UI 策略、#7 配置隔离。
3. Phase 1 完成后进入 Phase 2：打包 spike → CI → 便携 zip。
4. 全部 P0 完成且干净 VM 通过后，才打 `v1.0.0`。
5. 可按 Phase 0→6 一口气推进；MuMu 只在 Phase 6 真机 smoke（以及 #10/#11 可选实机复核）启动。Phase 2 前需关闭当前 UI（dist 锁），CI/Release 需 GitHub 远端权限。
