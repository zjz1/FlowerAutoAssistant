# 错误目录（FAA 1.0）

`--check-env` 与诊断包（`--export-diag`）中的错误码解释。代码侧单一事实源是
[`diagnostics/errors.py`](../diagnostics/errors.py)；新增检查项时两处同步（`tests/test_error_catalog.py` 会校验）。

| 错误码 | 含义 | 常见原因 | 建议动作 |
|---|---|---|---|
| `ENV-OS` | 操作系统不受支持 | 在 macOS / Linux / 旧版 Windows 上运行 | 在 Windows 10/11 x64 上运行；其他系统请自行适配源码 |
| `ENV-PY` | Python 运行时版本过低 | 源码模式用了 Python < 3.11 | 重建 `.venv` 并 `pip install -r requirements.txt`；或改用发行包 |
| `ENV-PATH` | 程序资源目录缺失 | 只拷贝了 exe，`flows/`、`resource/template/`、`data/` 不在 | 重新解压完整发行包，保持 `backend/`、`_internal/` 与 exe 同级 |
| `ENV-FLOW` | 流程文件损坏或引用缺失 | 手工编辑 / 合并 `flows/*.json` 出错 | 从发行包恢复 `flows/`；或 `python tools/check_project.py` 定位坏文件 |
| `ENV-TEMPLATE` | UI 模板数量异常 | `resource/template/` 被裁剪 | 从发行包恢复模板目录（清单见 ASSETS.md） |
| `ENV-CONFIG` | 用户配置类型错误 | `data/config.json` 被手工改坏 | 备份后删除该文件，程序会从 `config.example.json` 重新生成 |
| `ENV-DATA-WRITE` | `data/` 不可写 | 程序放在 `Program Files` 或只读盘 | 解压到普通用户目录（如 `D:\FAA`）后重试 |
| `ENV-ADB-PATH` | 默认 ADB 不存在 | MuMu 装在非默认路径 / 未安装 | 安装 MuMu 12 到默认路径，或用 `--adb` 指定 adb.exe |
| `ENV-ADB-CONN` | 连不上模拟器 | MuMu 未启动、ADB 端口未就绪 | 启动 MuMu 并确认 ADB 已开启；地址默认 `127.0.0.1:16384` |
| `ENV-PORT` | 本地服务端口被占用 | 8765 被其他程序占用 | 关闭占用程序，或用 `--port` 换端口 |
| `ENV-OCR` | OCR 运行库缺失 | 安装不完整 / 发行包解压损坏 | 源码重装 `requirements.txt`；发行包重新解压 `backend/_internal` |

## 状态含义

| 状态 | 含义 | 是否阻断启动 |
|---|---|---|
| `OK` | 检查通过 | 否 |
| `WARN` | 有问题但不影响启动（如模拟器尚未打开、端口已有 FAA 实例可复用） | 否 |
| `FAIL` | 必须修复（资源缺失、配置损坏、目录不可写等） | 是（建议先按建议处理） |

## 排查顺序建议

1. 先看 `FAIL` 项，按「建议动作」处理；
2. 再看 `WARN`：模拟器未开、端口占用通常属于时机问题；
3. 仍无法启动：导出诊断包（不含截图），附到 Issue：

```bat
backend\faa_webui.exe --export-diag diag.zip
rem 源码模式：.venv\Scripts\python.exe webui.py --export-diag diag.zip
```
