# -*- coding: utf-8 -*-
"""运行环境自检与诊断包（1.0 Phase 4）。

- `errors.ERRORS`：错误码目录（用户可读含义/原因/建议），docs/ERRORS.md 为人读版本；
- `env_check`：`--check-env` 的实现（CLI 与 WPF「环境检查」共用）；
- `redact`：日志/配置脱敏（Phase 5 #20 统一入口）；
- `bundle`：`--export-diag` 脱敏诊断包导出（不含截图）。
"""
