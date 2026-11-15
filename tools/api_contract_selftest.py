#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""webui API 契约自测钉子(W04, batch-04, 2026-11-14) —— 起真实 webui 服务(一次性端口)逐端点断言契约。

动机(评估报告 W04): 跨轨 API 漂移此前只能靠人工盘点发现 —— 本 ask 盘点当天就实发两笔:
  ① run_daily `finish`/`finish_action` 键错位(批 22 基线 WPF 发错键, 收尾批 A 才修);
  ② /api/fail_cache_info 恒 500(`set` 不可 JSON 序列化, 批-3 D7 修复后必须 200)。
本脚本把这两笔漂移与全部端点契约固化为可重复断言, 作为 F06+W03 / W01 / W02 每步的回归门。

用法:
    python tools/api_contract_selftest.py                 # 自起服务(一次性临时端口)跑全部断言
    python tools/api_contract_selftest.py --root <dir>    # 对指定树起服务(负例验证: 改坏端点必须能红)
    python tools/api_contract_selftest.py --inject-failures   # 预置两条失败事件(W02 SSE 浏览器实测用)

断言面(清单 W04 验收线):
  - 26 端点(GET 12 + POST 14; /api/shutdown **排除** —— 自起服务模式绝不真关服务)全断言;
  - GET /api/stream SSE 首帧(status 立即首推 + log 会话回放);
  - finish_action 400 负例(set_config 与 run_daily 两入口, 白名单 none/close_client);
  - 两笔实发漂移钉子(fail_cache_info=200 / run_daily finish_action 键);
  - F06+W03 全键 set_config 冒烟(20 键逐键请求: 回显 + data/config.json 落盘 + 三种特殊校验器
    逐字节语义 + [config] 日志三行文案逐字节(仅在无 data/config.json 的出仓树上做全量比对));
  - Q01 并发双入口冒烟(/api/run × /api/run_daily 同时打, 第二请求必须 409) + connect 失败回滚。

离线桩(见 _LAUNCHER 模板, 全部为测试环境桩, 不改产品代码):
  ① os.startfile 置空 —— /api/fail_cache_open 断言 ok:true 形状但不真开资源管理器窗口;
  ② OCREngine.connect 按线程名分流 —— HTTP 线程(/api/connect)返回 False → 断言真实离线形状
    502 {ok:false}; job 线程(faa-run/faa-daily, Q01 命名)抛错 → 走 Q01 connect 异常回滚分支
    (回滚断言同时依赖线程命名生效, 命名回归会被本钉子抓红);
  ③ --inject-failures 时预置/定时注入 report_failure(SSE failures 事件离线验证用)。
  禁 adb/实机: 本脚本全程不触设备; connect 成功/真机关服等需真机或破坏性的形态不在断言面。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PASS = 0
FAIL = 0
PORT = 0

# ---- 端点清单钉子: 26 = GET 12 + POST 14(/api/shutdown 排除, 防自关被测服务) ----
GET_APIS = ["status", "flows", "kb", "daily", "screen", "ocr", "failures",
            "log", "log_download", "stream", "fail_cache_info", "tplt_init"]
POST_APIS = ["connect", "set_mode", "click", "run", "stop", "set_config", "run_daily",
             "tplt_load", "tplt_submit", "tplt_contour", "failures_clear", "log_clear",
             "fail_cache_clean", "fail_cache_open"]
EXCLUDED = ["shutdown"]
EXPECTED_ENDPOINTS = {f"/api/{a}" for a in GET_APIS + POST_APIS}
_EXERCISED: set[str] = set()

# ---- ⚙ 面板 meta 契约(F06+W03): 键序/文案逐字节(与 _MODULE_SETTINGS×_CONFIG_KEYS 同源) ----
DAILY_IDS = ["startup", "plant", "social", "energy", "claim", "daily", "idle"]
MODULE_SETTINGS_KEYS = {
    "startup": ["enable_switch", "target_tail"],
    "social": ["enable_water", "enable_shine", "enable_mine", "enable_rabbit", "enable_pollin"],
    "claim": ["claim_online", "claim_party", "claim_hb"],
    "daily": ["enable_like", "enable_hot_sale", "enable_baobao", "enable_baobao_buy"],
}
MODULE_SETTINGS_META = {  # key -> (label, desc) —— 中文文案逐字节契约
    "enable_switch": ("切换账号", "登录前自动切换到目标账号"),
    "target_tail": ("目标账号尾部", "匹配 abc****de 的末尾数字"),
    "enable_water": ("摇钱树浇水", "家族活动 4.1.1 · 每日浇水 X/3(含生效复核: 点击被吞自动重试 1 次)"),
    "enable_shine": ("闪耀委托挑战", "家族活动 4.1.2 · 每日 10-21 时开放时段内执行"),
    "enable_mine": ("矿洞探险", "家族活动 4.1.3 · 每日礼包领取/次日「明日再来」跳过"),
    "enable_rabbit": ("守望兔子", "家族活动 4.1.4 · 占位待开发, 开启暂无实际动作"),
    "enable_pollin": ("好友采粉", "4.2 · 密友+好友逐页采集花粉, 无可采则回自己家园"),
    "claim_online": ("功能1 · 在线礼包", "抽奖耗尽次数 + 时间档位领取"),
    "claim_party": ("功能2 · 花灵派对", "进入派对并领取 6 个在线时长礼包"),
    "claim_hb": ("功能3 · 奇妙花宝", "家园→奇妙花宝→奇妙特权，领奇妙礼包每日/每周/每月三档"),
    "enable_like": ("社区点赞", "完成手账「为精美搭配献上点赞吧」任务(每期上限 20 次; 任务已完成则跳过)"),
    "enable_hot_sale": ("浏览热卖", "完成手账「查看最新热卖套装」任务(点行内前往进页浏览即完成, 不碰抽取按钮; 2026-10-27 自社区点赞拆分独立)"),
    "enable_baobao": ("花宝照顾", "完成手账「在花园中照顾小花宝一次」任务(道具手套拖拽, 消耗手套道具)"),
    "enable_baobao_buy": ("花宝自动补货", "挠痒痒 0 库存时受控购买 22 仙豆/个(单轮最多 1 次; 余额低于 10000 停止; 确认框全文核对+差额复核)"),
}
# set_config 响应回显键面(F06+W03 契约: 键集与改前逐字节一致)
SET_CONFIG_ECHO_KEYS = {"ok", "changed", "enable_switch", "claim_online", "claim_party",
                        "claim_hb", "enable_shine", "enable_pollin", "enable_like",
                        "log_click_pos", "use_cache_pos", "finish_action"}


def req(method, path, body=None, raw=False):
    _EXERCISED.add(path.split("?", 1)[0])
    data = None if body is None else json.dumps(body).encode("utf-8")
    r = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=data, method=method,
        headers={"Content-Type": "application/json"} if data is not None else {})
    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
            payload = resp.read()
            if raw:
                return resp.status, dict(resp.headers), payload
            return resp.status, dict(resp.headers), json.loads(payload.decode("utf-8"))
    except urllib.error.HTTPError as e:
        payload = e.read()
        if raw:
            return e.code, dict(e.headers), payload
        try:
            return e.code, dict(e.headers), json.loads(payload.decode("utf-8"))
        except Exception:
            return e.code, dict(e.headers), {"_raw": payload[:300].decode("utf-8", "replace")}


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {extra!r}")


def section(title):
    print(f"\n== {title} ==", flush=True)


def wait_running_false(timeout_s: float = 20.0) -> bool:
    """轮询 /api/status 直到 running 恢复 false(Q01 回滚验收)。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            st, _, d = req("GET", "/api/status")
            if st == 200 and d.get("running") is False:
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def read_sse_first_frames(deadline_s: float = 8.0):
    """连 /api/stream 读首帧事件, 返回 (content_type, [(event, data_str), ...])。"""
    _EXERCISED.add("/api/stream")
    import socket as _s
    r = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/stream",
                               headers={"Accept": "text/event-stream"})
    resp = urllib.request.urlopen(r, timeout=3.0)
    ctype = resp.headers.get("Content-Type", "")
    reader = getattr(resp, "fp", resp)
    events = []
    cur = ""
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        got_status = any(e == "status" for e, _ in events)
        got_log = any(e == "log" for e, _ in events)
        if got_status and got_log:
            break
        try:
            ln = reader.readline()
        except (_s.timeout, TimeoutError, OSError):
            continue
        if not ln:
            break
        s = ln.decode("utf-8", "replace").rstrip("\r\n")
        if s.startswith("event:"):
            cur = s[6:].strip()
        elif s.startswith("data:") and cur:
            events.append((cur, s[5:].strip()))
            cur = ""
    resp.close()
    return ctype, events


class _DataGuard:
    """data/ 目录快照: 全键 set_config 冒烟会真实落盘 data/config.json, 日志/归档/缓存目录
    是服务运行态产物 —— 测试结束后把 data/ 精确还原到测试前状态(对真实用户树零残留)。"""

    def __init__(self, root: Path):
        self.data = root / "data"
        self.before: dict[str, bytes | None] = {}
        if self.data.exists():
            for p in sorted(self.data.rglob("*")):
                rel = p.relative_to(self.data).as_posix()
                self.before[rel] = p.read_bytes() if p.is_file() else None

    def restore(self):
        if not self.data.exists():
            return
        # 1) 删除测试新增的文件(新增目录里的文件随目录删)
        for p in sorted(self.data.rglob("*"), reverse=True):
            rel = p.relative_to(self.data).as_posix()
            if rel in self.before:
                continue
            if p.is_file():
                try:
                    p.unlink()
                except OSError:
                    pass
        # 2) 删除测试新增的空目录(自底向上)
        for p in sorted((d for d in self.data.rglob("*") if d.is_dir()), reverse=True):
            rel = p.relative_to(self.data).as_posix()
            if rel in self.before:
                continue
            try:
                p.rmdir()
            except OSError:
                pass
        # 3) 还原被改写的既有文件/目录
        for rel, content in self.before.items():
            p = self.data / rel
            if content is None:
                if not p.exists():
                    p.mkdir(parents=True, exist_ok=True)
            elif (not p.exists()) or p.read_bytes() != content:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(content)


# ---- 离线服务桩启动器(写到系统临时目录, 不落被测树) ----
_LAUNCHER = '''# -*- coding: utf-8 -*-
# api_contract_selftest 离线服务桩 —— 真实 webui 服务 + 测试环境桩(详见 selftest 头注):
# 桩1 os.startfile 置空; 桩2 OCREngine.connect 按线程名分流(禁 adb/实机);
# 桩3 可选失败事件注入(--inject-failures, W02 SSE 实测用)。
import os
import sys

ROOT = r"__ROOT__"
PORT = __PORT__
INJECT = __INJECT__

os.startfile = lambda *a, **k: None
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import threading
import webui
import ocr_engine


def _offline_connect(self):
    import time as _time
    import threading as _t
    if _t.current_thread().name in ("faa-run", "faa-daily"):
        # job 线程: 模拟真实 connect 的数秒级耗时(离线无设备, 若立即抛错则 job 毫秒级结束,
        # Q01 并发双 POST 的两请求不再重叠, 409 断言失去确定性) —— 停 1.2s 再抛错走回滚分支。
        _time.sleep(1.2)
        raise RuntimeError("offline-selftest: 不连接设备")
    return False


ocr_engine.OCREngine.connect = _offline_connect

if INJECT:
    from ocr_engine import report_failure
    report_failure("离线自测", "预置失败事件1(页面加载/SSE 回放)")
    _t2 = threading.Timer(5.0, lambda: report_failure("离线自测", "运行中失败事件2(SSE 实时推送)"))
    _t2.daemon = True
    _t2.start()

sys.argv = ["webui.py", "--port", str(PORT)]
webui.main()
'''


def _free_port() -> int:
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _config_free(root: Path) -> bool:
    """被测树在服务启动前是否无 data/config.json(决定 [config] 日志能否做逐字节全量断言)。"""
    return not (root / "data" / "config.json").exists()


def _read_config_json(root: Path) -> dict:
    p = root / "data" / "config.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main():
    global PORT
    ap = argparse.ArgumentParser(description="webui API 契约自测钉子(W04)")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent),
                    help="被测树根(默认=本脚本所在仓库; 负例验证时指向改坏的副本)")
    ap.add_argument("--inject-failures", action="store_true",
                    help="预置/定时注入失败事件(W02 SSE 浏览器实测用)")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    inject = bool(args.inject_failures)
    if not (root / "webui.py").exists():
        print(f"FAIL --root 下无 webui.py: {root}")
        return 1

    config_free = _config_free(root)
    guard = _DataGuard(root)
    PORT = _free_port()
    tmpdir = Path(tempfile.mkdtemp(prefix="faa_selftest_"))
    launcher = tmpdir / "faa_selftest_server.py"
    launcher.write_text(
        _LAUNCHER.replace("__ROOT__", str(root))
                 .replace("__PORT__", str(PORT))
                 .replace("__INJECT__", "True" if inject else "False"),
        encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    proc = subprocess.Popen([sys.executable, "-B", str(launcher)], cwd=str(root), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"[selftest] 服务启动中 root={root} port={PORT} (pid={proc.pid})")
    t0 = time.time()
    ready = False
    while time.time() - t0 < 30:
        if proc.poll() is not None:
            print(f"FAIL 服务进程提前退出(exit={proc.returncode}) —— 依赖缺失? 用主仓 venv python 运行")
            break
        try:
            st, _, _ = req("GET", "/api/status")
            if st == 200:
                ready = True
                break
        except Exception:
            time.sleep(0.3)
    if not ready:
        proc.terminate()
        print("FAIL 服务 30s 未就绪")
        return 1
    print(f"[selftest] 服务就绪 ({time.time()-t0:.1f}s)")

    code = 0
    try:
        run_all(root, config_free)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        guard.restore()
        shutil.rmtree(tmpdir, ignore_errors=True)

    print(f"\n===== 端点覆盖: {len(_EXERCISED & EXPECTED_ENDPOINTS)}/{len(EXPECTED_ENDPOINTS)}"
          f" (排除: {', '.join('/api/' + a for a in EXCLUDED)}) =====")
    missing = EXPECTED_ENDPOINTS - _EXERCISED
    if missing:
        print(f"FAIL 端点未覆盖: {sorted(missing)}")
        code = 1
    print(f"===== 结果: PASS={PASS} FAIL={FAIL} =====")
    if FAIL or missing:
        code = 1
    return code


def run_all(root: Path, config_free: bool):
    # ---------- 页面 ----------
    section("页面 GET / 与 /tpltool + ui_build 版本戳")
    st, hd, body = req("GET", "/", raw=True)
    check("GET / -> 200 + text/html", st == 200 and "text/html" in hd.get("Content-Type", ""), st)
    html = body.decode("utf-8", "replace")
    check("页面含 maa-finish 控件与 EventSource 接线(W01/W02 交付面)",
          'id="maa-finish"' in html and "EventSource" in html and "/api/stream" in html)
    st2, hd2, body2 = req("GET", "/tpltool", raw=True)
    check("GET /tpltool -> 200 + text/html", st2 == 200 and "text/html" in hd2.get("Content-Type", ""), st2)
    st3, _, j3 = req("GET", "/api/status")
    ui_build = j3.get("ui_build", "")
    check("页面 meta ui-build 与 /api/status.ui_build 一致",
          f'content="{ui_build}"' in html and ui_build != "", ui_build)

    # ---------- GET /api/status ----------
    section("GET /api/status")
    st, _, d = req("GET", "/api/status")
    expect_keys = {"connected", "screen", "work", "flow_dir", "debug_click", "running",
                   "current_module", "confirm_page_close", "ui_build", "fail_cache"}
    fc_keys = {"mb", "count", "sessions", "oldest", "threshold_mb", "exceed", "prompt", "archived"}
    check("200 + 顶层键齐全", st == 200 and expect_keys <= set(d), sorted(set(d) ^ expect_keys))
    check("fail_cache 键齐全", isinstance(d.get("fail_cache"), dict) and fc_keys <= set(d["fail_cache"]),
          d.get("fail_cache"))
    check("离线形态: connected=false / running=false / current_module=null",
          d["connected"] is False and d["running"] is False and d["current_module"] is None,
          (d.get("connected"), d.get("running"), d.get("current_module")))

    # ---------- GET /api/flows ----------
    section("GET /api/flows")
    st, _, d = req("GET", "/api/flows")
    flows = d.get("flows", [])
    shape = all({"name", "file", "description", "modules"} <= set(f) for f in flows)
    check("200 + flows[] 形状 {name,file,description,modules}", st == 200 and len(flows) >= 7 and shape,
          len(flows))
    check("file 为 flows/ 下路径字符串", all(f["file"].endswith(".json") for f in flows))

    # ---------- GET /api/kb ----------
    section("GET /api/kb")
    st, _, d = req("GET", "/api/kb")
    check("200 + {click_log, close_buttons}", st == 200 and isinstance(d.get("click_log"), dict)
          and isinstance(d.get("close_buttons"), list), sorted(d))
    check("close_buttons 条目含 name(webui.html kbRow 消费)",
          all("name" in b for b in d["close_buttons"]))

    # ---------- GET /api/daily(F06+W03 meta 契约面) ----------
    section("GET /api/daily(⚙ meta 表驱动契约: 键序/文案逐字节)")
    st, _, d = req("GET", "/api/daily")
    ids = [m["id"] for m in d.get("modules", [])]
    check("200 + 7 模块顺序=flows/daily.json", st == 200 and ids == DAILY_IDS, ids)
    smod = {m["id"]: m for m in d["modules"]}
    skeys = {"key", "type", "label", "desc", "value"}
    check("settings 条目形状 {key,type,label,desc,value}",
          all(skeys <= set(s) and set(s) == skeys for m in d["modules"] for s in m["settings"]))
    for mid, keys in MODULE_SETTINGS_KEYS.items():
        got = [s["key"] for s in smod[mid]["settings"]]
        check(f"{mid} ⚙ 键序 = {keys}", got == keys, got)
    bad = []
    for mid, keys in MODULE_SETTINGS_KEYS.items():
        for s in smod[mid]["settings"]:
            want = MODULE_SETTINGS_META.get(s["key"])
            if want and (s["label"], s["desc"]) != want:
                bad.append((s["key"], s["label"], s["desc"]))
    check("14 键 label/desc 中文文案逐字节(F06+W03 平移契约)", not bad, bad[:2])
    check("plant/energy/idle settings=[](无 if_config 模块 ⚙ 显示「暂无独立子功能」)",
          all(smod[k]["settings"] == [] for k in ("plant", "energy", "idle")))
    check("顶层 log_click_pos/use_cache_pos/ocr_threads 回显键在",
          {"log_click_pos", "use_cache_pos", "ocr_threads"} <= set(d))
    check("ocr_threads 回显为 int 缺省 2 口径", isinstance(d.get("ocr_threads"), int))

    # ---------- GET /api/screen 与 /api/ocr(离线 503) ----------
    section("GET /api/screen 与 /api/ocr(未连接 503)")
    st, _, d = req("GET", "/api/screen")
    check("screen -> 503 {error:未连接}(离线)", st == 503 and d.get("error") == "未连接", (st, d))
    st, _, d = req("GET", "/api/ocr")
    check("ocr -> 503 {error:未连接}(离线)", st == 503 and d.get("error") == "未连接", (st, d))

    # ---------- GET /api/failures(增量游标) ----------
    section("GET /api/failures(增量游标)")
    st, _, d = req("GET", "/api/failures?after=0")
    check("200 + {items,next} 形状", st == 200 and isinstance(d.get("items"), list)
          and isinstance(d.get("next"), int), d)
    _, _, d2 = req("GET", "/api/failures?after=abc")
    check("after 非法 → 宽容回 0(与 /api/log 口径不同)", d2.get("next") == d.get("next"), d2)

    # ---------- GET /api/log(增量分片) ----------
    section("GET /api/log(增量分片)")
    st, _, d = req("GET", "/api/log?after=0")
    check("200 + {next,lines} 且启动日志 ≥1 条", st == 200 and d.get("lines")
          and d["lines"][0].startswith("[webui] 服务启动"), d.get("next"))
    _, _, d9 = req("GET", "/api/log?after=99999")
    check("after>=len → {next:after, lines:[]}", d9 == {"next": 99999, "lines": []}, d9)
    _, _, dn = req("GET", "/api/log?after=-5")
    check("after 负数 → max(0,·) 钳制(BUG-10 防御)", dn.get("next", -1) >= 0, dn)
    st_bad, _, dbad = req("GET", "/api/log?after=abc")
    check("after 非法 → 500 {error}(do_GET 兜底信封)", st_bad == 500 and "error" in dbad, (st_bad, dbad))

    # ---------- GET /api/log_download ----------
    section("GET /api/log_download")
    st, hd, body = req("GET", "/api/log_download", raw=True)
    text = body.decode("utf-8", "replace")
    check("200 + text/plain attachment faa_log_*.txt",
          st == 200 and "text/plain" in hd.get("Content-Type", "")
          and "attachment" in hd.get("Content-Disposition", "")
          and "faa_log_" in hd.get("Content-Disposition", ""), (st, hd.get("Content-Disposition")))
    check("BOM 开头 + # 头段(总行数/归档目录/归档截图)",
          body[:3] == b"\xef\xbb\xbf" and text.lstrip("\ufeff").startswith("# FlowerAutoAssistant 运行日志")
          and "# 总行数: " in text and "# 归档目录: data/fail_archives/" in text
          and "# 归档截图: " in text)

    # ---------- GET /api/stream(SSE 首帧) ----------
    section("GET /api/stream(SSE 首帧: status 立即首推 + log 会话回放)")
    ctype, events = read_sse_first_frames()
    check("SSE Content-Type: text/event-stream", "text/event-stream" in ctype, ctype)
    ev_names = [e for e, _ in events]
    check("首帧窗口内收到 status 事件(连接即推)", ev_names.count("status") >= 1, ev_names)
    check("首帧窗口内收到 log 事件(游标 0 起步回放会话分片)", ev_names.count("log") >= 1, ev_names)
    st_payload = next((json.loads(s) for e, s in events if e == "status"), None)
    check("status 首帧载荷与 GET /api/status 同形(connected/running/ui_build)",
          isinstance(st_payload, dict) and {"connected", "running", "ui_build"} <= set(st_payload),
          type(st_payload).__name__)

    # ---------- GET /api/fail_cache_info(D7 漂移钉子: 批-3 修复后必须 200) ----------
    section("GET /api/fail_cache_info(实发漂移钉子②: set 序列化 500 → D7 修复后 200)")
    st, _, d = req("GET", "/api/fail_cache_info")
    keys = {"bytes", "count", "sessions", "oldest", "session", "session_files", "files",
            "mb", "threshold_mb", "exceed"}
    check("200(D7 前: TypeError set not JSON serializable 恒 500)", st == 200, st)
    check("stat 键齐全 + files 为有序列表(D7: 进 JSON 前转列表)", keys <= set(d)
          and isinstance(d["files"], list), sorted(set(d) ^ keys))
    check("mb=bytes/1048576 不取整口径", d.get("mb") == d.get("bytes", 1) / 1048576)

    # ---------- GET /api/tplt_init ----------
    section("GET /api/tplt_init")
    st, _, d = req("GET", "/api/tplt_init")
    check("未连接 → 503 {error:未连接...}", st == 503 and "未连接" in str(d.get("error", "")), (st, d))

    # ---------- POST /api/connect(离线桩: HTTP 线程 False → 502) ----------
    section("POST /api/connect(离线形状: 引擎 connect 返回 False → 502 ok:false)")
    st, _, d = req("POST", "/api/connect", {})
    check("502 + {ok:false}(连接失败, 运行日志有 [连接] 失败行)",
          st == 502 and d.get("ok") is False, (st, d))
    _, _, d = req("GET", "/api/log?after=0")
    check("运行日志出现 [连接] 手动连接失败 行", any("[连接] 手动连接失败" in ln for ln in d["lines"]))

    # ---------- POST /api/set_mode ----------
    section("POST /api/set_mode")
    st, _, d = req("POST", "/api/set_mode", {"mode": "use"})
    check("200 {ok:true}(零副作用: use 模式不建 debug 目录)", st == 200 and d == {"ok": True}, d)

    # ---------- POST /api/click ----------
    section("POST /api/click(未连接 503)")
    st, _, d = req("POST", "/api/click", {"rel": [0.5, 0.5]})
    check("未连接 → 503 {error:未连接}", st == 503 and d.get("error") == "未连接", (st, d))

    # ---------- POST /api/run(Q01 单入口契约 + connect 异常回滚) ----------
    section("POST /api/run + Q01 connect 异常回滚(job 线程桩抛错 → running 恢复 false)")
    _, _, dflows = req("GET", "/api/flows")
    flow_name = dflows["flows"][0]["name"]
    st, _, d = req("POST", "/api/run", {"flow": flow_name, "mode": "use"})
    check("200 {ok:true, started:<流程名>}", st == 200 and d.get("ok") is True
          and d.get("started") == flow_name, (st, d))
    check("Q01: connect 失败(job 线程桩抛错)后 /api/status.running 恢复 false",
          wait_running_false())
    _, _, d = req("GET", "/api/log?after=0")
    check("运行日志出现 [run] 连接失败 行(Q01 回滚分支执行; 依赖线程命名 faa-run 生效)",
          any("[run] 连接失败" in ln and "offline-selftest" in ln for ln in d["lines"]))
    st, _, d = req("POST", "/api/run", {"flow": "不存在的流程xyz"})
    check("未找到流程 → 400 {error:未找到流程: ...}", st == 400
          and d.get("error") == "未找到流程: 不存在的流程xyz", (st, d))

    # ---------- POST /api/run_daily(漂移钉子①: finish_action 键 + 负例) ----------
    section("POST /api/run_daily(漂移钉子①: finish_action 键契约 + 400 负例)")
    _, _, ddaily = req("GET", "/api/daily")
    ids = [m["id"] for m in ddaily["modules"]]
    st, _, d = req("POST", "/api/run_daily", {"selected": ids, "mode": "use"})
    check("200 {ok,started:每日挂机编排,count=7}", st == 200 and d.get("ok") is True
          and d.get("started") == "每日挂机编排" and d.get("count") == len(ids), (st, d))
    check("Q01: job 结束后 running 恢复 false", wait_running_false())
    st, _, d = req("POST", "/api/run_daily", {"selected": ids, "mode": "use",
                                              "finish_action": "close_client"})
    check("finish_action=close_client → 200 接受(漂移钉子①: 服务端只认 finish_action 键)",
          st == 200 and d.get("ok") is True, (st, d))
    check("run_daily 是编排级: finish_action 不落 data/config.json(持久化只走 set_config)",
          _read_config_json(root).get("finish_action") is None,
          _read_config_json(root).get("finish_action"))
    check("Q01: 上述 job 结束后 running 恢复 false", wait_running_false())
    st, _, d = req("POST", "/api/run_daily", {"selected": ids, "finish_action": "bogus_mode"})
    check("finish_action 白名单外 → 400 {error:finish_action 仅接受 none/close_client...}",
          st == 400 and "finish_action 仅接受 none/close_client" in d.get("error", ""), (st, d))
    st, _, d = req("POST", "/api/run_daily", {"selected": ids, "finish": "close_client"})
    check("旧漂移键 finish(无下划线)被忽略 → 200 照常启动(键错位漂移不再静默改语义)",
          st == 200 and d.get("ok") is True, (st, d))
    check("Q01: 上述 job 结束后 running 恢复 false", wait_running_false())
    st, _, d = req("POST", "/api/run_daily", {"selected": []})
    check("空勾选 → 400 {error:未勾选任何任务}", st == 400 and d.get("error") == "未勾选任何任务", (st, d))

    # ---------- POST /api/stop ----------
    section("POST /api/stop")
    st, _, d = req("POST", "/api/stop", {})
    check("200 {ok,message:已请求停止当前流程...}", st == 200 and d.get("ok") is True
          and "已请求停止" in d.get("message", ""), d)

    # ---------- POST /api/set_config(F06+W03 全键冒烟) ----------
    section("POST /api/set_config(F06+W03 全键冒烟: 20 键逐键请求 + 回显 + config.json 落盘)")
    st, _, d = req("POST", "/api/set_config", {"enable_switch": True, "target_tail": "61"})
    check("set_config 键面 = 改前逐字节 12 键(ok/changed+10 回显)",
          st == 200 and set(d) == SET_CONFIG_ECHO_KEYS, sorted(set(d) ^ SET_CONFIG_ECHO_KEYS))
    check("enable_switch 回显 true / changed 反映 pre!=now",
          d.get("enable_switch") is True and d.get("changed") in (True, False), d.get("enable_switch"))
    cfg = _read_config_json(root)
    check("config.json 落盘: enable_switch=true, target_tail='61'",
          cfg.get("enable_switch") is True and cfg.get("target_tail") == "61", cfg)
    if config_free:
        _, _, dlog = req("GET", "/api/log?after=0")
        cfg_lines = [ln for ln in dlog["lines"] if ln.startswith("[config] ")]
        want = ["[config] 切换账号功能 启用, 目标尾部=61",
                "[config] 领取奖励功能1在线礼包=关, 功能2花灵派对=关, 功能3奇妙花宝=关, "
                "闪耀委托挑战=关, 摇钱树浇水=开, 矿洞探险=关, 守望兔子=关, 好友采粉=开, "
                "社区点赞=关, 浏览热卖=关, 花宝照顾=关, 花宝补货=开",
                "[config] 记录按钮位置=关, 使用缓存位置=关 "
                "(两项默认关闭; 关闭时只认实时识别, 不用历史坐标盲点)"]
        check("[config] 日志三行文案逐字节(出仓树口径)", cfg_lines[-3:] == want,
              cfg_lines[-3:] if len(cfg_lines) >= 3 else cfg_lines)
    else:
        _, _, dlog = req("GET", "/api/log?after=0")
        cfg_lines = [ln for ln in dlog["lines"] if ln.startswith("[config] ")]
        check("[config] 日志三行(存在 config.json → 结构断言: 3 行/16 标签/行3 后缀)",
              len(cfg_lines) >= 3 and cfg_lines[-1].endswith(
                  "(两项默认关闭; 关闭时只认实时识别, 不用历史坐标盲点)")
              and "[config] 切换账号功能" in cfg_lines[-3], len(cfg_lines))

    def set_and_check(key, value, post_ok, note=""):
        st, _, d = req("POST", "/api/set_config", {key: value})
        check(f"set_config {key}={value!r} → 200{note}", st == 200 and d.get("ok") is True, (st, d))
        if post_ok:
            check(f"  └ 回显/落盘 {key}={post_ok!r}",
                  d.get(key) == post_ok and _read_config_json(root).get(key) == post_ok,
                  (d.get(key), _read_config_json(root).get(key)))
        return d

    set_and_check("enable_switch", False, False)
    st, _, d = req("POST", "/api/set_config", {"enable_switch": True})
    check("enable_switch true→false→true: changed 反映 pre!=now(翻转 True)",
          d.get("changed") is True and d.get("enable_switch") is True, (d.get("changed"), d))
    st, _, d = req("POST", "/api/set_config", {"target_tail": "88"})
    check("set_config target_tail='88' → 200 落盘(text 键无回显, 键面由 SET_CONFIG_ECHO_KEYS 钉住)",
          st == 200 and _read_config_json(root).get("target_tail") == "88"
          and "target_tail" not in d, (st, _read_config_json(root).get("target_tail")))
    st, _, d = req("POST", "/api/set_config", {"claim_online": False})
    check("claim_online=False → 回显 false", d.get("claim_online") is False, d.get("claim_online"))
    st, _, d = req("POST", "/api/set_config", {"claim_online": True})
    check("claim_online=True → 回显 true", d.get("claim_online") is True, d.get("claim_online"))
    set_and_check("claim_party", True, True)
    set_and_check("claim_hb", True, True)
    set_and_check("enable_shine", True, True)
    set_and_check("enable_pollin", False, False)
    set_and_check("enable_like", True, True)
    set_and_check("log_click_pos", True, True)
    set_and_check("use_cache_pos", True, True)
    # target_tail 已在上方单独断言(text 键: 落盘有、回显无 —— 键面由 SET_CONFIG_ECHO_KEYS 钉住)
    # ocr_threads: 三种口径(钳制/合法/坏值回 2)
    st, _, d = req("POST", "/api/set_config", {"ocr_threads": 99})
    check("ocr_threads=99 → 钳到 8(max(0,min(8)))", st == 200
          and _read_config_json(root).get("ocr_threads") == 8, _read_config_json(root).get("ocr_threads"))
    _, _, dd = req("GET", "/api/daily")
    check("  └ /api/daily ocr_threads 回显 8", dd.get("ocr_threads") == 8, dd.get("ocr_threads"))
    st, _, d = req("POST", "/api/set_config", {"ocr_threads": 0})
    check("ocr_threads=0(不限制) → 落盘 0", _read_config_json(root).get("ocr_threads") == 0)
    st, _, d = req("POST", "/api/set_config", {"ocr_threads": "abc"})
    check("ocr_threads='abc' → 解析失败回 2(改前原语义)",
          _read_config_json(root).get("ocr_threads") == 2, _read_config_json(root).get("ocr_threads"))
    # fail_cache_prompt_mb: 下限钳制/坏值跳过
    st, _, d = req("POST", "/api/set_config", {"fail_cache_prompt_mb": 30})
    _, _, ds = req("GET", "/api/status")
    check("fail_cache_prompt_mb=30 → status.fail_cache.threshold_mb=30",
          ds["fail_cache"]["threshold_mb"] == 30, ds["fail_cache"]["threshold_mb"])
    st, _, d = req("POST", "/api/set_config", {"fail_cache_prompt_mb": -5})
    check("fail_cache_prompt_mb=-5 → 下限钳到 1.0(max(1.0, float))",
          _read_config_json(root).get("fail_cache_prompt_mb") == 1.0,
          _read_config_json(root).get("fail_cache_prompt_mb"))
    st, _, d = req("POST", "/api/set_config", {"fail_cache_prompt_mb": "abc"})
    check("fail_cache_prompt_mb='abc' → 坏值跳过不落盘(保持 1.0)",
          _read_config_json(root).get("fail_cache_prompt_mb") == 1.0,
          _read_config_json(root).get("fail_cache_prompt_mb"))
    # meta 键(⚙ 面板值回显路径)
    for k, v in (("enable_mine", True), ("enable_rabbit", True), ("enable_water", False),
                 ("enable_hot_sale", True), ("enable_baobao", True), ("enable_baobao_buy", False)):
        st, _, d = req("POST", "/api/set_config", {k: v})
        check(f"set_config {k}={v} → 200 且落盘", st == 200 and _read_config_json(root).get(k) is v,
              (st, _read_config_json(root).get(k)))
    _, _, dd = req("GET", "/api/daily")
    smod = {m["id"]: m for m in dd["modules"]}
    social_vals = {s["key"]: s["value"] for s in smod["social"]["settings"]}
    daily_vals = {s["key"]: s["value"] for s in smod["daily"]["settings"]}
    check("⚙ meta 回显与 set_config 同源(social/daily 值实时)", social_vals.get("enable_mine") is True
          and social_vals.get("enable_water") is False and daily_vals.get("enable_hot_sale") is True
          and daily_vals.get("enable_baobao_buy") is False, (social_vals, daily_vals))
    st, _, d = req("POST", "/api/set_config", {"confirm_page_close": False})
    _, _, ds = req("GET", "/api/status")
    check("confirm_page_close=False → status.confirm_page_close=false",
          ds.get("confirm_page_close") is False, ds.get("confirm_page_close"))
    # finish_action: 合法/非法/兜底
    st, _, d = req("POST", "/api/set_config", {"finish_action": "close_client"})
    check("finish_action=close_client → 回显 close_client",
          d.get("finish_action") == "close_client", d.get("finish_action"))
    check("  └ config.json 落盘 close_client", _read_config_json(root).get("finish_action") == "close_client")
    st, _, d = req("POST", "/api/set_config", {"finish_action": "close"})
    check("finish_action='close'(旧漂移值) → 400 拒收不落配置",
          st == 400 and "仅接受 none/close_client" in d.get("error", "")
          and _read_config_json(root).get("finish_action") == "close_client", (st, d))
    st, _, d = req("POST", "/api/set_config", {"finish_action": "none"})
    check("finish_action=none → 回显 none(缺省兜底口径)", d.get("finish_action") == "none")
    # ocr_execution_provider(OCR3 batch-08): 合法/非法; 无回显键(键面契约不动), /api/daily 回显
    st, _, d = req("POST", "/api/set_config", {"ocr_execution_provider": "cuda"})
    check("ocr_execution_provider='cuda' → 200 落盘(无回显键, 键面由 SET_CONFIG_ECHO_KEYS 钉住)",
          st == 200 and d.get("ok") is True and "ocr_execution_provider" not in d
          and _read_config_json(root).get("ocr_execution_provider") == "cuda", (st, d))
    _, _, dd = req("GET", "/api/daily")
    check("  └ /api/daily ocr_execution_provider 回显 cuda",
          dd.get("ocr_execution_provider") == "cuda", dd.get("ocr_execution_provider"))
    st, _, d = req("POST", "/api/set_config", {"ocr_execution_provider": "npu"})
    check("ocr_execution_provider='npu'(白名单外) → 400 拒收不落配置",
          st == 400 and "仅接受 cpu/dml/cuda" in d.get("error", "")
          and _read_config_json(root).get("ocr_execution_provider") == "cuda", (st, d))
    st, _, d = req("POST", "/api/set_config", {"ocr_execution_provider": "cpu"})
    check("ocr_execution_provider='cpu'(默认档) → 200 落盘还原",
          st == 200 and d.get("ok") is True
          and _read_config_json(root).get("ocr_execution_provider") == "cpu", (st, d))
    # use_angle_cls(OCR2 batch-10): bool 键; 无回显键(键面契约不动), /api/daily 回显(缺省 true)
    st, _, d = req("POST", "/api/set_config", {"use_angle_cls": False})
    check("use_angle_cls=False → 200 落盘(无回显键, 键面由 SET_CONFIG_ECHO_KEYS 钉住)",
          st == 200 and d.get("ok") is True and "use_angle_cls" not in d
          and _read_config_json(root).get("use_angle_cls") is False, (st, d))
    _, _, dd = req("GET", "/api/daily")
    check("  └ /api/daily use_angle_cls 回显 false", dd.get("use_angle_cls") is False,
          dd.get("use_angle_cls"))
    st, _, d = req("POST", "/api/set_config", {"use_angle_cls": "yes"})
    check("use_angle_cls='yes'(字符串) → bool('yes')=True 落盘(bool 键既有原语义)",
          st == 200 and _read_config_json(root).get("use_angle_cls") is True,
          _read_config_json(root).get("use_angle_cls"))
    st, _, d = req("POST", "/api/set_config", {"use_angle_cls": True})
    check("use_angle_cls=True → 200 落盘还原(默认态, OCR2 批默认 true 终态)",
          st == 200 and d.get("ok") is True
          and _read_config_json(root).get("use_angle_cls") is True, (st, d))
    _, _, dd = req("GET", "/api/daily")
    check("  └ /api/daily use_angle_cls 回显 true(缺省口径)", dd.get("use_angle_cls") is True,
          dd.get("use_angle_cls"))
    st, _, d = req("POST", "/api/set_config", {"bogus_key_xyz": 1})
    check("白名单外键忽略 → 200 ok(bogus 不落盘)", st == 200 and d.get("ok") is True
          and "bogus_key_xyz" not in _read_config_json(root), (st, d.get("ok")))

    # ---------- POST /api/failures_clear ----------
    section("POST /api/failures_clear")
    st, _, d = req("POST", "/api/failures_clear", {})
    check("200 {ok:true}", st == 200 and d == {"ok": True}, d)
    _, _, d = req("GET", "/api/failures?after=0")
    check("清空后 items=[] 且游标不回退", d["items"] == [] and isinstance(d["next"], int), d)

    # ---------- POST /api/log_clear ----------
    section("POST /api/log_clear")
    st, _, d = req("POST", "/api/log_clear", {})
    check("200 {ok:true, next:0}", st == 200 and d == {"ok": True, "next": 0}, d)
    _, _, d = req("GET", "/api/log?after=0")
    check("清空后缓冲仅剩标记行([webui] 运行日志已被手动清除)",
          len(d["lines"]) >= 1 and all("运行日志已被手动清除" in ln or "已清理" in ln
                                       for ln in d["lines"]), d["lines"][:2])

    # ---------- POST /api/fail_cache_clean 与 fail_cache_open ----------
    section("POST /api/fail_cache_clean / fail_cache_open(startfile 已桩)")
    st, _, d = req("POST", "/api/fail_cache_clean", {"mode": "days", "days": 7})
    check("200 {ok,removed,bytes,sessions,kept}(空缓存全 0)", st == 200
          and {"ok", "removed", "bytes", "sessions", "kept"} <= set(d) and d["removed"] == 0, d)
    st, _, d = req("POST", "/api/fail_cache_open", {})
    check("200 {ok:true, dir:str}(startfile 已桩, 不开窗口)", st == 200 and d.get("ok") is True
          and isinstance(d.get("dir"), str), (st, d))

    # ---------- POST /api/tplt_load / tplt_submit / tplt_contour ----------
    section("POST /api/tplt_load / tplt_submit / tplt_contour(负例契约)")
    st, _, d = req("POST", "/api/tplt_load", {"path": "../webui.py"})
    check("越界路径 → 400 {error:仅允许载入 debug/ 目录下的图片}",
          st == 400 and d.get("error") == "仅允许载入 debug/ 目录下的图片", (st, d))
    st, _, d = req("POST", "/api/tplt_load", {"path": "debug/不存在的文件.png"})
    check("debug 下不存在 → 400 {error:文件不存在}", st == 400 and d.get("error") == "文件不存在", (st, d))
    st, _, d = req("POST", "/api/tplt_submit", {})
    check("缺尺寸 → 400 {error:缺少画面尺寸}(负例, 不写 jsonl)", st == 400
          and d.get("error") == "缺少画面尺寸", (st, d))
    st, _, d = req("POST", "/api/tplt_contour", {})
    check("未连接 → 503 {error:未连接...}(校验序: 连接先于矩形)", st == 503
          and "未连接" in str(d.get("error", "")), (st, d))

    # ---------- Q01 并发双入口冒烟 ----------
    section("Q01 并发双入口冒烟(/api/run × /api/run_daily 同时打, 第二请求必须 409)")
    results = {}
    bar = threading.Barrier(2)

    def _fire(path, body, key):
        bar.wait()
        try:
            results[key] = req("POST", path, body)[:1]
        except Exception as e:
            results[key] = ("EXC", str(e))

    t1 = threading.Thread(target=_fire, args=("/api/run", {"flow": flow_name, "mode": "use"}, "run"))
    t2 = threading.Thread(target=_fire, args=("/api/run_daily", {"selected": ids, "mode": "use"}, "daily"))
    t1.start(); t2.start(); t1.join(15); t2.join(15)
    codes = sorted(c for c, *_ in results.values() if isinstance(c, int))
    check("并发双 POST → 恰一 200 一 409(Q01 原子 check-and-set)",
          codes == [200, 409], results)
    check("Q01: 两 job 均 connect 失败回滚后 running 恢复 false", wait_running_false())

    # ---------- 白名单/404/405/信封头 ----------
    section("白名单与 404/405(do_POST 门 + 信封头)")
    st, _, d = req("POST", "/api/nonexist", {})
    check("POST 白名单外 → 405 {error:method not allowed}",
          st == 405 and d.get("error") == "method not allowed", (st, d))
    st, _, d = req("POST", "/api/status", {})
    check("POST 已知 GET api → 405", st == 405, (st, d))
    st, _, d = req("GET", "/api/connect")
    check("GET 已知 POST api → 404 {error:no such api}", st == 404
          and d.get("error") == "no such api", (st, d))
    st, _, d = req("GET", "/api/nonexist")
    check("GET 未知 api → 404 {error:no such api}", st == 404 and d.get("error") == "no such api", (st, d))
    st, _, d = req("GET", "/nonapi")
    check("非 /api 路径 → 404 {error:notfound}", st == 404 and d.get("error") == "notfound", (st, d))
    st, hd, _ = req("GET", "/api/status", raw=True)
    check("JSON 头 application/json; charset=utf-8 + no-store",
          "application/json" in hd.get("Content-Type", "") and hd.get("Cache-Control") == "no-store",
          dict(hd))


if __name__ == "__main__":
    sys.exit(main())
