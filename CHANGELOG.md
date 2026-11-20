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
