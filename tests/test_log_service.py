# -*- coding: utf-8 -*-
"""日志服务基线：增量游标、SSE 原子增量、缓冲重置。"""
from __future__ import annotations

import unittest

from app import log_service


class LogServiceTests(unittest.TestCase):
    def setUp(self):
        log_service.reset_history()

    def tearDown(self):
        log_service.reset_history()

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


if __name__ == "__main__":
    unittest.main()
