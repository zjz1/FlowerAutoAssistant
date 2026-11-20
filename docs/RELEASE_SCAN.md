# 1.0 发布扫描记录

> 分支：`release/prep`  
> 范围：当前树 + Git 历史  
> 目标：确认没有密钥、个人绝对路径、账号尾号等敏感信息进入公开仓库/发行包。

## 1. 当前树扫描

命令（在仓库根执行）：

```powershell
git grep -n -I -E 'C:\\Users|E:\\my_project|/home/|api[_-]?key|password|secret|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY' -- . ':!data' ':!debug' ':!native/dist'
```

结果：**0 命中**（2026-11-20 修复后）。

已修复的当前树问题：

| 文件 | 原问题 | 处理 |
|---|---|---|
| `native/FAA.WpfGui/run_selftest.ps1` | 写死 `C:\Users\<user>\AppData\Local\Microsoft\dotnet` | 改为 `%LOCALAPPDATA%\Microsoft\dotnet` + `C:\Program Files\dotnet` 兜底 |
| `native/FAA.WpfGui/dbg_close_once.ps1` | 同上 | 改为 `Join-Path $env:LOCALAPPDATA ...` |
| `native/FAA.WpfGui/dbg_lock.ps1` | 同上 | 改为 `Join-Path $env:LOCALAPPDATA ...` |
| `PROGRESS.md` | 写死工作区绝对路径与 GitHub noreply 邮箱 | 改为 `<工作区根>` / `<GitHub 用户名>` / `<GitHub noreply 邮箱>` |

## 2. 公开别名（不是敏感信息）

以下位置保留公开仓库账号别名，属于有意公开：

- `LICENSE` 的版权署名；
- `README.md` 的仓库/文档链接；
- `PROGRESS.md` 的仓库链接；
- `native/FAA.WpfGui/ViewModels/AboutViewModel.cs` 的文档/仓库链接。

这些是公开 GitHub 地址/版权署名，不包含本地路径或凭证。若你希望改用组织名/别名，需在发布前统一替换。

## 3. 数据隔离

`git ls-files data` 仅包含：

- `data/close_buttons.json`（手工维护的关闭按钮注册表）
- `data/config.example.json`（示例配置）

未跟踪/不入仓：

- `data/config.json`（用户配置，可能含账号尾号）
- `data/click_log.json`（运行时坐标记忆）
- `data/fail_cache/`、`data/fail_archives/`（失败截图）
- `debug/`、`native/dist/`、`.venv/`

`.gitignore` 已覆盖上述路径；`config/*` 仅保留 `config/__init__.py` 与 `config/schema.py`。

## 4. Git 历史扫描

命令：

```powershell
git log --all -S'C:\Users' --oneline
git log --all -S'api_key' --oneline
git log --all -S'password' --oneline
git log --all -S'BEGIN OPENSSH PRIVATE KEY' --oneline
git log --all -S'token' --oneline
```

结果：

| 模式 | 结果 |
|---|---|
| `C:\Users` | 命中 `1a54b55`（旧版 WPF 自测脚本的个人 dotnet 路径，已在当前树修复） |
| `api_key` | 0 |
| `password` | 0 |
| `BEGIN OPENSSH PRIVATE KEY` | 0 |
| `token` | 命中 `1a54b55`；逐条检查为注释/测试中的“参数 token”等普通词，不是凭证 |

**结论**：历史中没有发现账号/密码/API Key/私钥；但 `1a54b55` 含个人本地路径。当前树已修复，历史仍保留该路径。

## 5. 历史重写决定

- 方案 A（推荐）：1.0 发布前用 `git filter-repo`/BFG 清理 `1a54b55` 中的个人路径，然后 force-push；需要仓库所有者明确批准。
- 方案 B：保留历史，在 release notes/README 中不放大该路径；但仓库历史仍可检索到，不完全满足隐私要求。

当前状态：**未重写，等待批准**（对应发布方案 G7）。

## 6. 复扫命令

每次发布前重跑：

```powershell
git grep -n -I -E 'C:\\Users|E:\\my_project|/home/|api[_-]?key|password|secret|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY' -- . ':!data' ':!debug' ':!native/dist'
git log --all -S'C:\Users' --oneline
git log --all -S'api_key' --oneline
git log --all -S'password' --oneline
```

## 7. Phase 5 复扫（2026-11-20）

- 当前树：`tools/clean_click_log.py` 的 3 条历史工作区绝对路径已改为 `<工作区根>` 占位符；`flow_startup.json` / `docs/FLOWS.md` / `_flowexec.py` 中的真实账号掩码统一改为 `abc****de`；测试数据改为明显虚构的 `123****45`。
- 复扫结果：当前树 **0 命中**（个人绝对路径 / 真实账号掩码 / 密钥赋值）。
- 历史提交 `1a54b55` 仍含个人路径；**未重写**，等待 G7 批准（见 §5）。
- 新增 `.github/dependabot.yml`（pip / nuget / actions 每周更新）与 `SECURITY.md`（私密漏洞报告入口）。

