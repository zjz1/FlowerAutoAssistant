# -*- coding: utf-8 -*-
"""日志/诊断脱敏（1.0 #20）：统一入口，日志导出与诊断包都走这里。

覆盖:
  - 本机绝对路径中的用户名（`C:\\Users\\<name>` → `%USERPROFILE%`）；
  - 账号掩码（`123****45` → `***`）；
  - ADB 路径（按传入真实路径精确替换为 `<ADB_PATH>`，避免暴露安装位置）；
  - 常见密钥键值（api_key/token/password/secret → `***`）。
纯函数、无 IO；不修改源文件，只在导出内容上生效。
"""
from __future__ import annotations

import re

_USER_PATH = re.compile(r"[A-Za-z]:\\Users\\[^\\\s\"'<>|]+", re.IGNORECASE)
_USER_PATH_FWD = re.compile(r"[A-Za-z]:/Users/[^/\s\"'<>|]+", re.IGNORECASE)
# 模拟器/ADB 安装路径：路径里可能含空格（如 "Program Files"），故按「盘符 → 首个 .exe/.dll」
# 整段匹配，再用关键字二次确认，避免误伤项目路径或吞掉后续日志字段。
_EXE_PATH = re.compile(r"[A-Za-z]:\\[^\r\n\"'<>|]*?\.(?:exe|dll)", re.IGNORECASE)
_EMU_HINT = re.compile(r"(?:MuMu|Netease|nx_main|adb\.exe)", re.IGNORECASE)
_ACCOUNT = re.compile(r"\b\d{2,4}\*{3,5}\d{1,3}\b")
_SECRET = re.compile(r"(?i)\b(api[_-]?key|token|password|passwd|secret)\b\s*[:=]\s*[^\s,\"']+")


def _mask_exe_path(match: "re.Match[str]") -> str:
    return "<ADB_PATH>" if _EMU_HINT.search(match.group(0)) else match.group(0)


def redact_text(text: str, adb_path: str | None = None) -> str:
    """对一段文本做脱敏；None/空串原样返回。"""
    if not text:
        return text or ""
    out = str(text)
    if adb_path:
        out = out.replace(str(adb_path), "<ADB_PATH>")
    out = _USER_PATH.sub("%USERPROFILE%", out)
    out = _USER_PATH_FWD.sub("%USERPROFILE%", out)
    out = _EXE_PATH.sub(_mask_exe_path, out)
    out = _ACCOUNT.sub("***", out)
    out = _SECRET.sub(r"\1=***", out)
    return out


def redact_config(data: dict) -> dict:
    """导出用配置副本：丢弃 `_` 注释键、账号尾号置 `***`、字符串值统一过 redact_text。"""
    out: dict = {}
    for key, value in (data or {}).items():
        if str(key).startswith("_"):
            continue
        if key == "target_tail":
            out[key] = "***" if value not in (None, "") else ""
        elif isinstance(value, str):
            out[key] = redact_text(value)
        else:
            out[key] = value
    return out
