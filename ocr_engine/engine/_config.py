"""用户配置(data/config.json)加载/持久化/占位符解析。

E01(batch-03, 2026-11-14) 自单文件 ocr_engine.py 机械拆包: 本文件各段为原文件对应
行段的**逐行原文**(唯 __file__ 锚点因包层级 +1 机械重锚定, 见 ast_hash_compare.py
allowlist)。行为等价口径: 帧集回归 0 退化 + 闸门全绿 + import 面零改动。
原行段映射: evidence/batch-03/tiles_manifest.json。
"""
from __future__ import annotations

import json
import re

from .._constants import CONFIG_PATH

class _ConfigMixin:
    # ---- 用户配置 (data/config.json) ----
    def _load_config(self) -> dict:
        """加载用户配置 (data/config.json)。流程 JSON 中可用 ${key} 占位符引用配置值,
        例如 ${target_tail} -> config["target_tail"]。缺失字段返回空字符串。

        2026-11-20(1.0 #7): 首次运行且 config.json 不存在时, 自动从
        config.example.json 复制一份, 保证新克隆/发行包开箱有完整默认键;
        示例缺失时保持旧行为(返回空 dict, 由步骤 default/缺键语义兜底)。
        """
        cfg = {}
        try:
            example = CONFIG_PATH.with_name("config.example.json")
            if not CONFIG_PATH.exists() and example.exists():
                CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
                CONFIG_PATH.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
                print(f"[配置] 首次运行: 已从 {example.name} 生成 {CONFIG_PATH.name}")
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, encoding="utf-8") as fp:
                    data = json.load(fp)
                    if isinstance(data, dict):
                        cfg = {k: v for k, v in data.items() if not k.startswith("_")}
        except Exception as e:
            print(f"[配置加载失败] {e}")
        return cfg

    def _save_config(self) -> None:
        """把 self.config 写回 data/config.json (合并注释字段除外)。"""
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, encoding="utf-8") as fp:
                    data = json.load(fp)
        except Exception:
            data = {}
        for k, v in self.config.items():
            data[k] = v
        with open(CONFIG_PATH, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=4)

    def update_config(self, **kwargs) -> None:
        """更新配置项并持久化。例如 update_config(enable_switch=True, target_tail="61")。"""
        self.config.update(kwargs)
        self._save_config()

    def resolve(self, val):
        """把字符串中的 ${key} 占位符替换为配置值; 非字符串或未含占位符则原样返回。"""
        if isinstance(val, str) and "${" in val:
            def _repl(m):
                key = m.group(1)
                if key not in self.config:
                    print(f"[配置] 提示: 配置键 '{key}' 未定义, 使用空值")
                return str(self.config.get(key, ""))
            return re.sub(r"\$\{(\w+)\}", _repl, val)
        return val
