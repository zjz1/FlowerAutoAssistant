# native — 原生 WPF 客户端（壳 2，已并入正式版）

> 来源：zcode 重构工作流（`_collab/inbox/zcode-20261114-1 … -11`，已归档 `_collab/merged/`）。
> **已并入正式版**（里程碑 116，2026-11-16；实机复跑 5 模块 ok=5 / fail=0）。

## 组成

| 路径 | 内容 |
|---|---|
| `FAA.WpfGui/` | WPF 客户端 **53 个源文件**（.NET 8，csproj v0.5.0） |
| `FAA.WpfGui.Tests/` | xunit 测试工程 **6 个文件**（65 个用例） |
| `dist/` | 自包含发布产物（`FAA.WpfGui.exe` 154MB + 6 个原生 DLL） |
| `start_faa_native.bat` | 从仓库根启动 `native\dist\FAA.WpfGui.exe` |
| `evidence/` | 批 21/22 的 UI 截图、SSE/API 自测证据（历史留存） |

后端**不随本包**：使用正式版 `webui.py`（`python webui.py --port 8765`）或 `webui_app.py`；
客户端支持 `--api-base http://127.0.0.1:8765` 直连。

## 已验证 / 未验证

**已验证（主 agent 实跑）**
- `dotnet 8.0.427` 编译 `FAA.WpfGui.sln`：**0 警告 0 错误**。
- `dotnet test FAA.WpfGui.Tests`：**65/65 通过**。
- 2026-11-16 真实 MuMu 完整链路：`--api-base http://127.0.0.1:8766` 连接 → 勾选 5 模块开始一轮 → SSE 日志实时刷新 → `ok=5 / fail=0` → 回到空闲。连接徽章按 `--api-base` 显示实际端口（修复前误显示缺省 8765）。

**未验证**
- 关窗停服（`closing` 确认 → `/api/shutdown`）与 `finish_action=close_client` 的实机关闭效果（需 `target_package`；默认 `none`）。
- 多显示器/非 100% 缩放布局。
- 登记项：**C64**（`_collab/inbox/zcode-developing/C类_待实机回归.md`）。

## 怎么跑

1. 准备后端：在正式版仓库根启动 `webui.py`（默认端口 8765；SSE/`finish_action` 已内置）。
2. 启动客户端：
   ```
   dist\FAA.WpfGui.exe --api-base http://127.0.0.1:8765
   ```
   或直接双击 `dist\FAA.WpfGui.exe` 走三态探测/托管。
3. 源码调试：在 `FAA.WpfGui\` 下 `dotnet run -c Release`。

## 注意

- `dist/` 是构建产物（不纳入任何提交）；需要新版本时在 `FAA.WpfGui\` 重新 build/publish。
- `bin/`、`obj/`、`.vs/` 已从本包排除；本地构建后会重新生成。
- 本包不含 `webui_app.py`（pywebview 外壳）；那是正式版独立入口，见 `_lab/ocr/refactor/`。
- 历史版本（批 21/22）的 `native_ui/backend/` 已移除，避免与 `_lab/ocr/refactor/` 的后端重复。
