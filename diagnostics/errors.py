# -*- coding: utf-8 -*-
"""用户可读错误目录（1.0 #18）：错误码 → 标题 / 常见原因 / 可操作建议。

约定:
  - 新增检查项时先在此登记错误码，再在 `env_check` 里使用；
  - `docs/ERRORS.md` 必须同步（`tests/test_error_catalog.py` 会校验码集一致）；
  - 文案面向使用者：说清楚「哪里不对」和「下一步怎么做」，不堆内部实现细节。
"""
from __future__ import annotations

ERRORS: dict[str, dict[str, str]] = {
    "ENV-OS": {
        "title": "操作系统",
        "cause": "FAA 1.0 仅支持 Windows 10/11（依赖 WPF 壳与 MuMu 的 ADB 通道）",
        "action": "在 Windows 10/11 x64 上运行；其他系统请使用源码模式自行适配（不承诺支持）",
    },
    "ENV-PY": {
        "title": "Python 运行时",
        "cause": "源码模式需要 Python 3.11+；打包版应显示 frozen",
        "action": "重新创建 .venv 并安装 requirements.txt；或改用发行包（无需 Python）",
    },
    "ENV-PATH": {
        "title": "程序资源目录",
        "cause": "flows/、resource/template/、data/ 缺失或安装不完整（常见于只拷贝了 exe）",
        "action": "重新解压完整发行包；不要单独移动 exe，backend/ 与 _internal/ 必须与它同级",
    },
    "ENV-FLOW": {
        "title": "流程文件",
        "cause": "flows/daily.json 解析失败或引用的模块流程不存在（手工编辑/合并事故）",
        "action": "从发行包恢复 flows/ 目录；或运行 python tools/check_project.py 定位坏文件",
    },
    "ENV-TEMPLATE": {
        "title": "UI 模板",
        "cause": "resource/template/ 模板数量异常（缺失会导致模板匹配通道失效）",
        "action": "从发行包恢复 resource/template/；模板清单见 ASSETS.md",
    },
    "ENV-CONFIG": {
        "title": "用户配置",
        "cause": "data/config.json 类型错误或结构损坏（键类型不符）",
        "action": "删除（或改名备份）data/config.json，让程序从 config.example.json 重新生成",
    },
    "ENV-DATA-WRITE": {
        "title": "数据目录写入",
        "cause": "data/ 不可写（常见于把程序解压到 Program Files 或只读目录）",
        "action": "把 FAA 解压到普通用户目录（如 D:\\FAA）后重新运行",
    },
    "ENV-ADB-PATH": {
        "title": "ADB 可执行文件",
        "cause": "默认 MuMu adb 路径不存在（MuMu 装在别处 / 未安装）",
        "action": "安装 MuMu 12 到默认路径，或用 --adb 指定 adb.exe 全路径后启动",
    },
    "ENV-ADB-CONN": {
        "title": "模拟器连接",
        "cause": "127.0.0.1:16384 连不上（MuMu 未启动 / ADB 端口未就绪）",
        "action": "启动 MuMu 模拟器并确认 ADB 已开启；连接地址可在界面「连接设置」确认",
    },
    "ENV-PORT": {
        "title": "本地服务端口",
        "cause": "8765 被其他程序占用（不是 FAA 实例）",
        "action": "关闭占用端口的程序，或用 --port 指定其他端口启动",
    },
    "ENV-OCR": {
        "title": "OCR 运行库",
        "cause": "rapidocr_onnxruntime / onnxruntime / 模型文件缺失（安装不完整）",
        "action": "源码模式重装 requirements.txt；发行包重新解压 backend/_internal",
    },
}
