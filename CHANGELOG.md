# Changelog

本文件记录 FAA 的发布变更。1.0 之前不建立版本号；发布准备阶段统一记录在 `Unreleased`，1.0 发布时整理为 release notes。

## Unreleased

### Added

- 种植增强（2026-11-20）：
  - 种子数据库 `data/plant_presets.json`（桃花/白·粉·绿，肥力消耗均 2，绿色为稀有）；种子名合法性由该库统一判定，非法名称保存时拒绝并回退。
  - 选种模式：手动输入全称 / 预设选择（花名 → 颜色下拉）；预设与手动均支持稀有种子二次确认。
  - 数量模式：固定 1~360 / auto（按肥力、可种槽位、库存/360 上限计算）；auto 可单独开启自动购买。
  - 缺种购买：按差额去园艺店分批购买（单批≤99），返回后重读库存继续种植。
  - 稀有种子不可购买：强制关闭购买开关并在运行日志头部标注。
  - 种植流程顺序调整为 授粉（占位）→ 收获 → 种植，避免花园满时可收获花朵挡住种植。
  - 配置 `schema_version` 升至 2，旧配置自动补键迁移。
- 收获保护（2026-11-20）：
  - `plant_harvest_allowed` 允许不授粉直接收获的白名单（默认白色桃花/粉色桃花，WPF 种植 ⚙「收获保护」勾选）。
  - 收获判定改为：`可授粉(y)>0` 时读取待授粉列表，仅当全部属于允许集合才收花；任一种不允许（或列表不可读）即跳过；稀有种子强制保护、不可勾选。
  - 配置 `schema_version` 升至 3，旧配置自动补键迁移。
- 运行前统一确认（2026-11-20）：新增 `POST /api/preflight`，后端汇总本次开启/关闭的功能与风险项，WPF「开始一轮」在单个弹窗展示；取不到时降级为普通继续确认。
- `if_config` 组合条件（2026-11-21）：支持 `keys` 列表 + `any`/`all`，用于“任一子功能开启才执行”的门控；旧 `key` 写法不变。
- WPF 种植设置面板（2026-11-20）：设置从「设置页」移回种植模块 ⚙，分组为 选种 / 数量与购买 / 收获保护；设置页仅保留「稀有种子二次确认」开关。WebUI 已冻结，后续仅更新原生 UI。
- 便携发行包：PyInstaller one-folder 后端（`tools/faa_webui.spec`）+ WPF 自包含外壳，`tools/build_release.ps1` 产出 `FAA-<版本>-win-x64.zip` 与 SHA256。
- WPF 宿主支持打包后端：路径解析新增 `FAA_BACKEND_EXE` 与便携包布局 `backend/faa_webui.exe`（源码模式不变）。
- CI/Release 工作流：`.github/workflows/ci.yml`（Python 闸门 + WPF 单测）、`release.yml`（便携包构建，tag 时发 Release）。
- `requirements-build.txt`（构建期依赖，PyInstaller）。
- flow 结构校验（`check_project`）：必填字段、模块引用、`region_rel` 形状、关键字列表、`fallback_rel` 与数值字段。
- 配置版本化：`schema_version` + 旧配置自动迁移（只补键/升版本，保留用户值与未知键）。
- 阻断层注册表 `data/blockers.json`（等级提升/领取成功/资源更新/通用提示），接入 `close_dialog` 与 `ensure_home`，新增弹窗只加数据。
- `verify_action`：点后五分类（failed/empty/blocker/changed/no_change）；`click_text` 步骤可用 `"verify": true` 启用。
- 离线回放基座 `tools/replay.py` + `tools/replay/cases/*.json`（真机帧不入库，缺帧默认跳过）。
- 环境自检 `--check-env`（资源/配置/写入/ADB/端口/OCR，逐项 OK/WARN/FAIL + 修复建议），WPF「环境检查」按钮 + 首启失败自动诊断。
- 脱敏诊断包 `--export-diag`（manifest/env/脱敏配置/日志尾部/流程清单，不含截图），WPF「导出诊断包」按钮。
- 文档：`docs/SUPPORTED_ENV.md`、`docs/ERRORS.md`、`CONTRIBUTING.md`、README 快速开始/FAQ/故障排查、Issue/PR 模板。

### Security

- 本地 HTTP 服务 POST 增加 Origin 白名单：仅允许无 Origin（原生客户端）或 `http://127.0.0.1/localhost/[::1]`，其他来源 403。
- 日志与诊断统一脱敏：账号尾号、`C:\Users\<name>`、ADB/模拟器安装路径、密钥键值在写入日志前与导出诊断包时替换。
- 新增 `SECURITY.md` 与 `.github/dependabot.yml`（pip / nuget / actions 每周依赖更新）。

### Fixed

- 静态审查修复（2026-11-20，30 项 findings）：
  - 日志 SSE 游标统一按全局序号计算，缓冲满 2 万分片后不再每 0.8s 重放全量（W5-001）。
  - 诊断包 `env.json` 全字段脱敏并替换程序根目录；`[config]` 日志不再写账号尾号明文（W5-003）。
  - 配置写盘加锁 + 临时文件 `os.replace` 原子替换，并发 `set_config` 不丢键/不读半写（W5-002）。
  - `wait_text` 透传 `region_rel`；`if_text` 透传 `exact`；条件步骤 `scene` 仅命中后登记；`run_flow` 统一走 `run_steps`；`if_greater` 的 `min_score` 生效（W1-003/004/005/006/007）。
  - 守望兔子开放日修正为周五~周日 `[4,5,6]`（W3-001）。
  - 后台运行连接失败时不再空跑：只连接一次，`connect()` 返回 False 直接取消本轮（W2-001）。
  - 花仙乐园各领取函数返回 bool 并在主入口汇总；关闭兜底改用注册表角区条目（0.85 + 粉色一致性）（W1-002/W3-002）。
  - 采粉翻页失败清理「跳转页签」模态框；买种回好友家园改为轮询等待；`claim_scroll` 默认排除「已领取」并在达上限时登记软失败（W2-002/W3-004/W1-001/W1-008）。
  - HTTP 增加 1MB body 上限、非回环 Host 拒绝、`/api/log?after=abc` 返回 400；bool 配置键仅接受 JSON 布尔值；`_config_echo` 缺键按 schema 默认值（W2-003/004/005）。
  - WPF 全选/清空/反选 CanExecute 修正为空闲可用；切换花名后自动选中首色立即保存，界面与实际预设一致（W4-001/004）。
  - 发行包补带 `licenses/`；测试日志与配置写入临时目录；诊断目录纳入语法闸；`api_contract_selftest` 同步 28 端点/种植面板/新契约（W4-002/003/005/006）。
  - 种植阶段0 增加“任一子功能开启”门控：三个子功能全关时整段跳过，不再产生无关归位失败（W3-003）。
  - 失败清单上限与日志缓冲同步为 20000；运行日志/HTTP 日志各加 100MB 单会话写盘保护（到上限停止追加并提示，不删除已有内容）；清日志时同步清空失败清单（W5-004）。
  - 实机 2026-11-21：花园已满（可种槽位=0）、肥力不足或种子库存为 0 且未开购买时，种植跳过并保持模块 ok，不再记为「阶段1/2失败」。
- 种植/收获精细 OCR（2026-11-21 实机）：
  - 待授粉卡片：粗 OCR 定位「选择花粉颜色」→ 按行与 x 间距切分横排卡片 → 每卡 3x 精识；
  - 名称只做确定性归一化 + 种子库精确匹配，**禁止模糊匹配**；未登记/无法识别的卡片标记 unknown 并阻断收花；
  - 一键收花后处理「是否同时收获爱心地的花朵？」确认框，点精确「收取」（排除「不收取」）；
  - 种子网格名称/角标、状态栏、数量窗口精识；数量窗口 0/0 按跳过处理；
  - 实机帧验证：`粉色桃花 + 紫色康乃馨` 两卡正确分离，粉色命中、紫色触发保护；无未知卡时粉色按当前设置直接收花。
- 修复「等级提升 / 点击任意处关闭」全屏弹窗导致 claim/daily 卡死：标题优先关闭，`close_dialog` / `ensure_home` 增加覆盖层兜底。
- 修复「花灵派对」今日参与时长为 0 时仍逐次点「领取」并登记软失败：显式读到 0 时跳过领取循环（2026-11-20 实机）。
- 修复服务不可达时「重启后端」按钮被禁用：托管服务断线时保持可用，重启执行期间防连点。
- 修复冻结包经管道输出时中文乱码：非 tty 的 stdout/stderr 统一 UTF-8。

### Changed

- 发行版 UI 策略：WPF 主推；WebUI 备用/调试；pywebview 壳移出发行依赖（`requirements-dev.txt`）。
- 首次运行自动从 `config.example.json` 生成 `data/config.json`。

### Docs

- 新增 `docs/RELEASE_PLAN_1.0.md`：1.0 发布准备最终方案（23 项、阶段、门槛）。
- 新增 `THIRD_PARTY_NOTICES.md` / `ASSETS.md` / `docs/RELEASE_SCAN.md`；README 补充素材与许可说明。
