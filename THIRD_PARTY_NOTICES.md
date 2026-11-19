# Third-Party Notices

FAA 的源代码采用 MIT 许可证（见 `LICENSE`）。发行包包含或依赖以下第三方组件；各组件的版权与许可证归其作者所有。

## 直接依赖

| 组件 | 版本 | 许可证 | 用途 | 来源 |
|---|---|---|---|---|
| maafw（MaaFramework Python binding） | 5.12.3 | **LGPL-3.0** | 设备控制 / 截图 / 输入 | https://github.com/MaaXYZ/MaaFramework |
| rapidocr_onnxruntime | >=1.2.3,<2 | Apache-2.0 | OCR 文字识别 | https://github.com/RapidAI/RapidOCR |
| opencv-python | >=4.10.0 | Apache-2.0 | 图像处理 | https://github.com/opencv/opencv-python |
| Pillow | >=10.0.0 | MIT-CMU | 图像读写 | https://python-pillow.org |
| pywebview | >=6.0 | BSD-3-Clause | **仅开发**：WebView 壳，不进入发行包 | https://pywebview.flowrl.com |
| Python | 3.11+ | PSF-2.0 | 运行时（打包时随附） | https://www.python.org |

## 传递依赖（发行包内）

| 组件 | 许可证 | 说明 |
|---|---|---|
| onnxruntime | MIT | RapidOCR 推理后端；见 https://onnxruntime.ai |
| NumPy | BSD-3-Clause | 数值计算；许可证文本见 `licenses/BSD-3-Clause-numpy.txt` |
| pythonnet / clr_loader | MIT | maafw 的 .NET 互操作依赖 |
| 其他 pip 传递依赖 | 各自许可证 | 以安装包 `*.dist-info/licenses/` 为准 |

## WPF 原生壳

| 组件 | 许可证 | 说明 |
|---|---|---|
| .NET 8 / WPF | MIT | 自包含发布件随附 .NET 运行时 |
| CommunityToolkit.Mvvm | MIT | MVVM 工具包 |
| WebView2 Runtime | Microsoft 许可 | 随 Windows/Edge 提供，不随本项目再分发 |

自包含 WPF 发布件中的 .NET 运行时及其第三方组件，以 Microsoft .NET 发布说明中的第三方 notices 为准。

## 许可证文本

| 许可证 | 文件 |
|---|---|
| LGPL-3.0 | `licenses/LGPL-3.0.txt` |
| Apache-2.0 | `licenses/Apache-2.0.txt` |
| MIT-CMU（Pillow） | `licenses/MIT-CMU-Pillow.txt` |
| BSD-3-Clause（pywebview） | `licenses/BSD-3-Clause-pywebview.txt` |
| BSD-3-Clause（NumPy） | `licenses/BSD-3-Clause-numpy.txt` |

onnxruntime 的 MIT 文本、RapidOCR 与 OpenCV 的 Apache 文本以上游仓库/安装包为准；本项目随附 Apache-2.0 通用文本。

## maafw（LGPL-3.0）合规说明

- `maafw` 以**独立 Python 包**形式加载，不与本项目源代码静态链接；
- 用户可以替换/升级 `.venv` 或发行包中的 `maafw`；
- 完整 LGPL-3.0 文本见 `licenses/LGPL-3.0.txt`；
- 上游源码与获取方式：https://github.com/MaaXYZ/MaaFramework ；
- 本项目源代码仍按 MIT 发布；LGPL 义务仅覆盖 `maafw` 及其修改（如有）。

## 游戏素材

`resource/template/` 下的 38 个模板是游戏界面截图裁剪，**不属于**上述第三方软件许可证，也**不在 MIT 授权范围内**。来源、用途、版权归属和下架机制见 `ASSETS.md`。

## 发行前检查

1. 依赖版本变化时，同步更新本文件；
2. 运行打包后，确认 `licenses/` 随 zip 一起分发；
3. 不把 `.venv`、`data/config.json`、`data/click_log.json`、`data/fail_cache/`、`debug/` 打进发行包。
