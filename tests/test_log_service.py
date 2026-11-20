# -*- coding: utf-8 -*-
"""日志服务基线：增量游标、SSE 原子增量、缓冲重置。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app import log_service


class LogServiceTests(unittest.TestCase):
    def setUp(self):
        # 隔离: 不碰真实 data/webui_runtime_log.txt
        self._td = tempfile.TemporaryDirectory()
        self._old = (log_service.LOG_FILE, log_service.HTTP_LOG_FILE)
        log_service.LOG_FILE = Path(self._td.name) / "runtime.txt"
        log_service.HTTP_LOG_FILE = Path(self._td.name) / "http.txt"
        log_service.reset_history()

    def tearDown(self):
        log_service.reset_history()
        log_service.LOG_FILE, log_service.HTTP_LOG_FILE = self._old
        self._td.cleanup()

    def test_append_and_get_since(self):
        log_service.append("甲")
        log_service.append("乙")
        nxt, lines = log_service.get_since(0)
        self.assertEqual(nxt, 2)
        self.assertEqual(lines, ["甲", "乙"])
        nxt2, lines2 = log_service.get_since(1)
        self.assertEqual(nxt2, 2)
        self.assertEqual(lines2, ["乙"])

    def test_read_increment(self):
        log_service.append("甲")
        nxt, lines, last = log_service.read_increment("", 0)
        self.assertEqual((nxt, lines, last), (1, ["甲"], "甲"))
        log_service.append("乙")
        nxt2, lines2, last2 = log_service.read_increment(last, nxt)
        self.assertEqual((nxt2, lines2, last2), (2, ["乙"], "乙"))

    def test_read_increment_resets_on_replaced_buffer(self):
        log_service.append("甲")
        log_service.read_increment("", 0)
        log_service.reset_history()
        log_service.append("新")
        nxt, lines, last = log_service.read_increment("旧末片", 1)
        self.assertEqual((nxt, lines, last), (1, ["新"], "新"))

    def test_read_increment_uses_global_cursor_after_overflow(self):
        """W5-001: LOG_BASE>0 后游标是全局序号，不能拿 len(LOGS) 比较。"""
        old_max = log_service.LOG_MAX_LINES
        log_service.LOG_MAX_LINES = 3
        try:
            for s in ("a", "b", "c", "d", "e"):
                log_service.append(s)
            nxt, lines, last = log_service.read_increment("", 0)
            self.assertEqual((nxt, lines, last), (5, ["c", "d", "e"], "e"))
            # 已消费到末尾: 不得重放全量
            self.assertEqual(log_service.read_increment(last, nxt), (5, [], "e"))
        finally:
            log_service.LOG_MAX_LINES = old_max

    def test_runtime_log_stops_at_size_cap(self):
        """W5-004: 单会话日志到 100MB 上限后停止写盘, 不删除已有内容。"""
        old_cap = log_service.LOG_FILE_MAX_BYTES
        log_service.LOG_FILE_MAX_BYTES = 10
        try:
            log_service.append("12345678")
            log_service.append("abcdef")   # 8+6 > 10, 应停止
            self.assertEqual(log_service.LOG_FILE.read_text(encoding="utf-8"), "12345678")
            self.assertTrue(log_service._persist_capped)
        finally:
            log_service.LOG_FILE_MAX_BYTES = old_cap

    def test_http_log_stops_at_size_cap(self):
        old_cap = log_service.HTTP_LOG_MAX_BYTES
        log_service.HTTP_LOG_MAX_BYTES = 5
        try:
            log_service.persist_http("1234")
            log_service.persist_http("5678")
            self.assertEqual(log_service.HTTP_LOG_FILE.read_text(encoding="utf-8"), "1234")
            self.assertTrue(log_service._http_log_capped)
        finally:
            log_service.HTTP_LOG_MAX_BYTES = old_cap

    def test_failure_buffer_syncs_with_log_buffer(self):
        from core.limits import SESSION_BUFFER_MAX
        from ocr_engine import _failures
        self.assertEqual(log_service.LOG_MAX_LINES, SESSION_BUFFER_MAX)
        self.assertEqual(_failures._FAILURES.maxlen, SESSION_BUFFER_MAX)


if __name__ == "__main__":
    unittest.main()
