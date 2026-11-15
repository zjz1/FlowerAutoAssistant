"""
FlowerAutoAssistant - OCR 数据驱动引擎核心（替代 MAA 模板匹配路线）

核心循环: 截图 -> OCR识别文字 -> 按关键字定位按钮 -> 计算相对坐标(归一化) -> 点击

与 MAA 模板匹配的区别:
- 不依赖模板图片, 每次运行通过 OCR 直接识别文字/按钮位置
- 使用「相对坐标」: 记录 (x/宽, y/高) 归一化坐标, 屏幕尺寸变化时相对位置不变
- 数据驱动: 流程由 JSON 描述(flow), 无需改代码即可适配新流程
- 回退缓存: 记录「最后已知相对坐标」, 当 OCR 瞬时失败时可用缓存补点击, 提高鲁棒性

用法:
    python ocr_engine.py --list            # 列出可用流程
    python ocr_engine.py --flow 每日      # 运行指定流程(按关键字匹配)

拆包说明(E01, batch-03, 2026-11-14):
    本模块自单文件 ocr_engine.py(4712 行)机械拆分为 ocr_engine/ 包(Mixin 纵切 + facade):
    import ocr_engine 一律解析到 ocr_engine/ 包(常规包优先于同目录同名 .py 文件);
    全部旧符号由 ocr_engine/__init__.py 再导出, import 面零改动 —— 消费方
    main.py:25 / pollin.py:23-24 / community_like.py:59 / webui.py:26 / tools/collect_frames.py:41。
    根 ocr_engine.py 保留为 `python ocr_engine.py ...` CLI 直执行入口(shim)。
"""
from __future__ import annotations

from ocr_engine import *  # noqa: F401,F403 —— 全部旧公开符号(经包 facade 再导出)
from ocr_engine import main  # noqa: F401 —— CLI 入口(本文件 __main__ 直执行用)

if __name__ == "__main__":
    main()
