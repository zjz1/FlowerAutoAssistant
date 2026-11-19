# Changelog

本文件记录 FAA 的发布变更。1.0 之前不建立版本号；发布准备阶段统一记录在 `Unreleased`，1.0 发布时整理为 release notes。

## Unreleased

### Added

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

### Fixed

- 修复「等级提升 / 点击任意处关闭」全屏弹窗导致 claim/daily 卡死：标题优先关闭，`close_dialog` / `ensure_home` 增加覆盖层兜底。
- 修复服务不可达时「重启后端」按钮被禁用：托管服务断线时保持可用，重启执行期间防连点。
- 修复冻结包经管道输出时中文乱码：非 tty 的 stdout/stderr 统一 UTF-8。

### Changed

- 发行版 UI 策略：WPF 主推；WebUI 备用/调试；pywebview 壳移出发行依赖（`requirements-dev.txt`）。
- 首次运行自动从 `config.example.json` 生成 `data/config.json`。

### Docs

- 新增 `docs/RELEASE_PLAN_1.0.md`：1.0 发布准备最终方案（23 项、阶段、门槛）。
- 新增 `THIRD_PARTY_NOTICES.md` / `ASSETS.md` / `docs/RELEASE_SCAN.md`；README 补充素材与许可说明。
