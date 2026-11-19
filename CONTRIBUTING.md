# 贡献指南（FAA）

感谢参与。提交前请先读本文件与 [docs/SUPPORTED_ENV.md](docs/SUPPORTED_ENV.md)。

## 1. 开发环境

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
rem 构建期（打包）依赖：
.venv\Scripts\python.exe -m pip install -r requirements-build.txt
```

WPF 壳：.NET 8 SDK；`dotnet build native\FAA.WpfGui\FAA.WpfGui.csproj -c Release`。

## 2. 提交前的必跑项

```bat
rem Python 全量测试 + 项目闸门（语法/flow 结构/契约/离线单测）
.venv\Scripts\python.exe tools\check_project.py --with-tests

rem WPF 单元测试
powershell -NoProfile -ExecutionPolicy Bypass -File native\FAA.WpfGui\run_selftest.ps1 -RunUnitTests

rem 离线回放（有真机故障帧时；缺帧会 SKIP）
.venv\Scripts\python.exe tools\replay.py --all
```

要求：闸门 0 FAIL；测试全绿。闸门对 `dotnet` 不在 PATH 的情况只降级 WARN（不是失败）。

## 3. 目录与改动约定

- **新功能先确认再进主项目**：未确认的开发内容放 `workbench/`（不入库），确认后再并入 `flows/`、`webui/` 等主体。
- 新增流程步骤类型必须同步 `ocr_engine/_constants.py` 的 `STEP_TYPES`（闸门会校验）。
- 新增配置键必须同步 `config/schema.py`、`data/config.example.json`、WebUI/WPF 面板（闸门会校验键一致性）。
- 新增覆盖层弹窗优先改 `data/blockers.json`（数据驱动），不要往引擎里加分支。
- 日志/诊断导出统一走 `diagnostics/redact.py`，不得输出账号、绝对路径、ADB 路径或密钥。

## 4. 隐私红线（硬性）

- 不提交任何个人信息：真实姓名、账号、邮箱、API Key、密码、个人绝对路径（`C:\Users\<你>`）。
- 不提交 `data/config.json`、`data/click_log.json`、`data/fail_cache/`、`data/collect/`、`debug/`（已在 `.gitignore`）。
- 游戏截图不入库（IP 风险）；需要回归时用 `tools/replay.py` + 本机 `fail_cache` 帧。
- 测试/示例里需要账号时用 `abc****de` 形式占位，不得写真实尾号。

## 5. 素材与许可

- 代码 MIT；`resource/template/` 下的游戏 UI 模板**不属于 MIT**，版权归游戏权利方，仅用于界面识别（见 [ASSETS.md](ASSETS.md)）。
- 新增第三方依赖：同步 `requirements*.txt`、`THIRD_PARTY_NOTICES.md`，并在 `licenses/` 放入许可证文本（如许可证要求）。

## 6. 提交流程

1. 从 `main` 开分支（如 `fix/xxx`、`feat/xxx`），**不要**直接在 `main` 上改。
2. 提交信息：`type: 摘要`（type ∈ feat/fix/docs/build/test/chore），一次提交只做一件事。
3. PR 描述写清：问题、方案、验证命令与结果；UI 改动附截图（确认无个人信息）。
4. 合并前确认 CI 全绿（Python 闸门 + WPF 单测）。

## 7. 报告问题

请附上 `--export-diag` 导出的脱敏诊断包与复现步骤；不要直接粘贴含账号/路径的原始日志。
