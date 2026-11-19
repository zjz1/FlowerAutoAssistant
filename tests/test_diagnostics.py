# -*- coding: utf-8 -*-
"""1.0 Phase 4/5: 错误目录 / 环境检查 / 脱敏 / 诊断包。"""
from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from diagnostics import bundle, env_check, errors, redact

ROOT = Path(__file__).resolve().parents[1]


class ErrorCatalogTests(unittest.TestCase):
    def test_every_code_is_documented(self):
        doc = (ROOT / "docs" / "ERRORS.md").read_text(encoding="utf-8")
        missing = [code for code in errors.ERRORS if code not in doc]
        self.assertFalse(missing, f"docs/ERRORS.md 缺少错误码: {missing}")

    def test_catalog_entries_have_actionable_text(self):
        for code, meta in errors.ERRORS.items():
            for field in ("title", "cause", "action"):
                self.assertTrue(meta.get(field), f"{code} 缺 {field}")


class EnvCheckTests(unittest.TestCase):
    def test_checks_cover_catalog_and_valid_status(self):
        results = env_check.run_checks()
        codes = {r["code"] for r in results}
        self.assertTrue(codes <= set(errors.ERRORS), f"未登记错误码: {codes - set(errors.ERRORS)}")
        self.assertEqual({"ENV-OS", "ENV-PATH", "ENV-FLOW", "ENV-CONFIG", "ENV-OCR"} - codes, set())
        for r in results:
            self.assertIn(r["status"], ("ok", "warn", "fail"), r)
            if r["status"] != "ok":
                self.assertTrue(r["action"], f"{r['code']} 非 OK 但无建议")

    def test_text_output_and_exit_semantics(self):
        results = env_check.run_checks()
        text = env_check.format_text(results)
        self.assertIn("FAA 环境检查", text)
        self.assertIn("结果:", text)
        self.assertEqual(env_check.main(json_out=True) in (0, 1), True)

    def test_json_output_is_parseable(self):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            env_check.main(json_out=True)
        data = json.loads(buf.getvalue())
        self.assertIsInstance(data, list)
        self.assertTrue(all("code" in x and "status" in x for x in data))


class RedactTests(unittest.TestCase):
    def test_user_path_account_secret_adb(self):
        adb = r"D:\Program Files\Netease\MuMu\nx_main\adb.exe"
        raw = (r"路径 C:\Users\alice\FAA\data 与 D:/Users/bob/x.adb; "
               r"账号 123****45; api_key=abc123; " + adb)
        out = redact.redact_text(raw, adb_path=adb)
        self.assertNotIn("alice", out)
        self.assertNotIn("bob", out)
        self.assertNotIn("123****45", out)
        self.assertNotIn("abc123", out)
        self.assertNotIn("Program Files", out)
        self.assertIn("%USERPROFILE%", out)
        self.assertIn("<ADB_PATH>", out)

    def test_config_hides_target_tail_and_comments(self):
        cfg = {"target_tail": "61", "claim_online": True, "_comment": "x",
               "note": r"C:\Users\alice\a"}
        out = redact.redact_config(cfg)
        self.assertEqual(out["target_tail"], "***")
        self.assertNotIn("_comment", out)
        self.assertNotIn("alice", out["note"])

    def test_empty_and_non_string_values_safe(self):
        self.assertEqual(redact.redact_text(""), "")
        self.assertEqual(redact.redact_text(None), "")
        self.assertEqual(redact.redact_config({"ocr_threads": 2})["ocr_threads"], 2)


class LogRedactionTests(unittest.TestCase):
    """1.0 #20: 日志写入前统一脱敏（内存缓冲 + 落盘同一份）。"""

    def test_append_and_tee_are_redacted(self):
        from app import log_service
        log_service.append(r"路径 C:\Users\alice\FAA 账号 123****45 adb "
                           r"D:\Program Files\Netease\MuMu\nx_main\adb.exe" + "\n")
        text = "".join(log_service.snapshot())
        self.assertNotIn("alice", text)
        self.assertNotIn("123****45", text)
        self.assertNotIn("Netease", text)

        import io
        buf = io.StringIO()
        tee = log_service.TeeOut(io.StringIO(), buf)
        tee.write(r"E:\Users\bob\app 账号 123****45" + "\n")
        text2 = "".join(log_service.snapshot())
        self.assertNotIn("bob", text2)
        self.assertNotIn("123****45", text2)


class DiagBundleTests(unittest.TestCase):
    def test_bundle_layout_and_no_screenshots(self):
        with tempfile.TemporaryDirectory() as d:
            out = bundle.export_bundle(Path(d) / "diag")
            self.assertTrue(out.exists())
            with zipfile.ZipFile(out) as z:
                names = set(z.namelist())
                self.assertTrue({"manifest.json", "env.json", "config.json",
                                 "logs/runtime_tail.txt", "flows/summary.json"} <= names)
                self.assertFalse([n for n in names if n.lower().endswith((".jpg", ".png"))])
                manifest = json.loads(z.read("manifest.json"))
                self.assertEqual(manifest["app"], "FlowerAutoAssistant")
                cfg = json.loads(z.read("config.json"))
                if "target_tail" in cfg:
                    self.assertIn(cfg["target_tail"], ("***", ""))
                text = z.read("logs/runtime_tail.txt").decode("utf-8", "replace")
                import re
                self.assertIsNone(re.search(r"\d{2,4}\*{3,5}\d{1,3}", text), "日志仍含账号掩码")


if __name__ == "__main__":
    unittest.main()
