# -*- coding: utf-8 -*-
"""批次审阅脚手架（主 agent 专用，规则见 docs/REVIEW_RULES.md）。

一条命令完成「确定性检查」，把需要判断的点收敛成少量「人工必看」：
  ① 文件指纹（基线/交付/当前仓库）与基线匹配（R1）
  ② 分级（T0 文档 / T1 配置流程 / T2 引擎关键路径）
  ③ 语义 diff（JSON 字段级；文本行级），与 REPORT 声称的 diff 数对照（R10）
  ④ 硬规则（R2 直坐标 / R4 危险控件 / R5 模板落位 / R6 引用存在 / R7 步骤类型 / R8 require_seen / R9 新闸门）
  ⑤ 合并闸门 tools/check_project.py

用法：
  python tools/review_batch.py --batch zcode-20261031-11
  python tools/review_batch.py --path "_collab/merged/zcode-20261031-11" --write-ledger
  python tools/review_batch.py --batch zcode-20261031-11 --no-gate --json
退出码：0 = 无 FAIL；1 = 有 FAIL。
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parent.parent          # FlowerAutoAssistant
COLLAB = REPO.parent / "_collab"
INBOX = COLLAB / "inbox"
MERGED = COLLAB / "merged"
LEDGER = COLLAB / "审阅台账.jsonl"

T2_MARKERS = ("ocr_engine.py", "pollin.py", "webui.py", "webui.html",
              "ocr_ui.py", "community_like.py")
DANGER_WORDS = ("屏蔽聊天", "删除好友", "神叶", "灵豆", "星之粉")


def md5_of(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest() if p.exists() else ""


def rel_of(p: Path) -> str:
    return p.as_posix()


def _strip_prefix(rel: str) -> str:
    return rel[len("FlowerAutoAssistant/"):] if rel.startswith("FlowerAutoAssistant/") else rel


def resolve_batch(batch: str, path: str) -> Path:
    if path:
        return Path(path).resolve()
    for root in (INBOX, MERGED):
        d = root / batch
        if d.exists():
            return d
    raise SystemExit(f"找不到批次目录: {batch}（inbox/merged 均无）")


def collect_files(batch_dir: Path):
    files_root = batch_dir / "files"
    if not files_root.exists():
        return []
    out = []
    for p in files_root.rglob("*"):
        if p.is_file():
            rel = _strip_prefix(rel_of(p.relative_to(files_root)))
            out.append((rel, p))
    return sorted(out, key=lambda x: x[0])


def report_md5s(batch_dir: Path) -> set:
    rep = batch_dir / "REPORT.md"
    if not rep.exists():
        return set()
    txt = rep.read_text(encoding="utf-8", errors="ignore")
    return {m.lower() for m in re.findall(r"\b[0-9a-fA-F]{32}\b", txt)}


# ---------------- JSON 结构扫描 ----------------
def scan_tree(obj, out=None) -> dict:
    if out is None:
        out = {"click_rel": 0, "fallback_rel": 0, "low_threshold": [], "danger_clicks": [],
               "require_seen": 0, "types": set(), "click_count": 0}
    if isinstance(obj, list):
        for x in obj:
            scan_tree(x, out)
    elif isinstance(obj, dict):
        for k in ("click_rel", "fallback_rel"):
            if k in obj or obj.get("type") == k:
                out[k] += 1
        t = obj.get("type")
        if t:
            out["types"].add(t)
        if t in ("click_text", "click_row_button", "click_template") and (
                obj.get("text") or obj.get("template")):
            out["click_count"] += 1
            words = json.dumps(obj.get("text") or obj.get("template"), ensure_ascii=False)
            if any(w in words for w in DANGER_WORDS):
                out["danger_clicks"].append(words[:120])
        th = obj.get("threshold")
        if isinstance(th, (int, float)) and th < 0.9:
            out["low_threshold"].append({"template": obj.get("template"), "threshold": th})
        if obj.get("require_seen") is True:
            out["require_seen"] += 1
        for v in obj.values():
            scan_tree(v, out)
    return out


def sem_diff(a, b, path="", out=None):
    if out is None:
        out = []
    if type(a) is not type(b):
        out.append(("change", path, a, b))
        return out
    if isinstance(a, dict):
        for k in sorted(a.keys() | b.keys()):
            p = f"{path}/{k}"
            if k not in a:
                out.append(("add", p, None, b[k]))
            elif k not in b:
                out.append(("del", p, a[k], None))
            else:
                sem_diff(a[k], b[k], p, out)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append(("len", f"{path}/len", len(a), len(b)))
        for i in range(min(len(a), len(b))):
            sem_diff(a[i], b[i], f"{path}[{i}]", out)
    elif a != b:
        out.append(("change", path, a, b))
    return out


def text_diff_stats(cur: Path, new: Path):
    import difflib
    a = cur.read_text(encoding="utf-8").splitlines() if cur.exists() else []
    b = new.read_text(encoding="utf-8").splitlines()
    added, removed = [], []
    for ln in difflib.unified_diff(a, b, n=0):
        if ln.startswith("+") and not ln.startswith("+++"):
            added.append(ln[1:])
        elif ln.startswith("-") and not ln.startswith("---"):
            removed.append(ln[1:])
    return added, removed


def add_rule(results, rid, level, ok, detail):
    results.append({"id": rid, "level": level, "ok": ok, "detail": detail})


def check_gate():
    try:
        cp = subprocess.run([sys.executable, str(REPO / "tools" / "check_project.py")],
                            cwd=str(REPO), capture_output=True, text=True,
                            encoding="utf-8", timeout=240)
        ok = cp.returncode == 0
        last = [l for l in (cp.stdout or "").splitlines() if l.strip()][-3:]
        return ok, " | ".join(last)
    except Exception as e:                     # noqa: BLE001
        return False, f"闸门执行异常: {e}"


def main():
    ap = argparse.ArgumentParser(description="批次审阅脚手架")
    ap.add_argument("--batch", default="", help="inbox/merged 下的批次目录名")
    ap.add_argument("--path", default="", help="批次目录绝对/相对路径")
    ap.add_argument("--no-gate", action="store_true", help="跳过 check_project 闸门")
    ap.add_argument("--write-ledger", action="store_true", help="把结论追加到 _collab/审阅台账.jsonl")
    ap.add_argument("--ledger", default="", help="台账路径覆盖（调试/演练用）")
    ap.add_argument("--json", action="store_true", help="只输出 JSON")
    args = ap.parse_args()

    batch_dir = resolve_batch(args.batch, args.path)
    batch = batch_dir.name
    files = collect_files(batch_dir)
    if not files:
        raise SystemExit(f"{batch}: files/ 为空（纯分析批？无需合并）")

    rep_md5 = report_md5s(batch_dir)
    tier = "T0"
    if any(r.endswith(T2_MARKERS) for r, _ in files):
        tier = "T2"
    elif all(r.endswith(".json") and (r.startswith("flows/") or r.startswith("data/")) for r, _ in files):
        tier = "T1"

    file_rows, results = [], []
    sem_total = 0
    baseline_ok = True
    for rel, delivered in files:
        repo_p = REPO / rel
        d_md5, r_md5 = md5_of(delivered), md5_of(repo_p)
        state = "新文件" if not repo_p.exists() else ("已落位" if r_md5 == d_md5 else "未落位")
        bmatch = (r_md5.lower() in rep_md5) if r_md5 else False
        if not bmatch:
            baseline_ok = False
        file_rows.append({"path": rel, "repo_md5": r_md5, "delivered_md5": d_md5,
                          "baseline_match": bmatch, "state": state})

        if rel.endswith(".json"):
            try:
                new_obj = json.loads(delivered.read_text(encoding="utf-8"))
            except Exception as e:             # noqa: BLE001
                add_rule(results, "R0", "FAIL", False, f"{rel} JSON 解析失败: {e}")
                continue
            base_obj = json.loads(repo_p.read_text(encoding="utf-8")) if repo_p.exists() else {}
            d = sem_diff(base_obj, new_obj)
            sem_total += len(d)
            # R2 直坐标：新增数量
            ns, bs = scan_tree(new_obj), scan_tree(base_obj)
            for key in ("click_rel", "fallback_rel"):
                before = bs[key] if bs else 0
                if ns[key] > before:
                    add_rule(results, "R2", "FAIL", False, f"{rel} 新增 {key} {ns[key] - before} 处")
            # R3 低阈值
            base_th = len(bs["low_threshold"]) if bs else 0
            if len(ns["low_threshold"]) > base_th:
                add_rule(results, "R3", "WARN", False,
                         f"{rel} 新增 {len(ns['low_threshold']) - base_th} 处 threshold<0.9: "
                         f"{ns['low_threshold'][-(len(ns['low_threshold']) - base_th):]}")
            # R4 危险控件
            base_dg = len(bs["danger_clicks"]) if bs else 0
            if len(ns["danger_clicks"]) > base_dg:
                add_rule(results, "R4", "FAIL", False,
                         f"{rel} 新增危险点击目标: {ns['danger_clicks'][base_dg:]}")
            # R8 require_seen
            base_rs = bs["require_seen"] if bs else 0
            if ns["require_seen"] > base_rs:
                add_rule(results, "R8", "WARN", False,
                         f"{rel} 新增 require_seen {ns['require_seen'] - base_rs} 处（确认非快速过场链）")
            # R7 步骤类型（仅 flows）
            if rel.startswith("flows/"):
                engine_src = (REPO / "ocr_engine.py").read_text(encoding="utf-8")
                known = set(re.findall(r's_type == "([^"]+)"', engine_src))
                unknown = sorted(ns["types"] - known)
                add_rule(results, "R7", "FAIL", bool(not unknown),
                         f"{rel} 未知步骤类型: {unknown}" if unknown else f"{rel} 步骤类型全部已知")
            # R10 语义 diff 摘要（供人工比对 REPORT）
            if d:
                shown = [x for x in d[:60]]
                add_rule(results, "R10", "INFO", True,
                         f"{rel} 语义差异 {len(d)} 处" +
                         "".join(f"\n      {k} {p}" for k, p, _a, _b in shown))
        else:
            added, removed = text_diff_stats(repo_p, delivered)
            if any('"click_rel"' in ln or '"fallback_rel"' in ln for ln in added):
                add_rule(results, "R2", "FAIL", False, f"{rel} 新增直坐标键")
            bad_th = [ln.strip() for ln in added
                      if (m := re.search(r'"threshold"\s*:\s*([0-9.]+)', ln)) and float(m.group(1)) < 0.9]
            if bad_th:
                add_rule(results, "R3", "WARN", False, f"{rel} 新增低阈值: {bad_th[:5]}")
            add_rule(results, "R10", "INFO", True,
                     f"{rel} 文本 diff: +{len(added)} / −{len(removed)} 行")

    # R1 基线
    add_rule(results, "R1", "WARN", baseline_ok,
             "基线 md5 与 REPORT 一致" if baseline_ok else "当前仓库 md5 不在 REPORT 的基线列表中")

    # R5 新模板落位
    tpl_files = [(r, p) for r, p in files if "resource/template/" in r]
    for rel, delivered in tpl_files:
        repo_p = REPO / rel
        ok = repo_p.exists() and md5_of(repo_p) == md5_of(delivered)
        add_rule(results, "R5", "FAIL", ok,
                 f"{rel} 已落位且 md5 一致" if ok else f"{rel} 未落位或 md5 不一致")

    # R6 主仓库 flow 模板引用存在性
    tpl_dir = REPO / "resource" / "template"
    missing = []
    for f in (REPO / "flows").rglob("*.json"):
        for name in re.findall(r'"template"\s*:\s*"([^"${}]+)"', f.read_text(encoding="utf-8")):
            if not (tpl_dir / name).exists():
                missing.append(f"{f.relative_to(REPO).as_posix()}:{name}")
    add_rule(results, "R6", "FAIL", not missing,
             "flow 模板引用全部存在" if not missing else f"缺失: {missing[:8]}")

    # R9 新增默认开启闸门（仅 data/*.json 顶层布尔键）
    for rel, delivered in files:
        if not (rel.startswith("data/") and rel.endswith(".json")):
            continue
        try:
            new_obj = json.loads(delivered.read_text(encoding="utf-8"))
            repo_obj = json.loads((REPO / rel).read_text(encoding="utf-8")) if (REPO / rel).exists() else {}
        except Exception:                      # noqa: BLE001
            continue
        new_keys = [k for k in new_obj if k not in repo_obj and new_obj[k] is True]
        if new_keys:
            add_rule(results, "R9", "WARN", False, f"{rel} 新增默认开启键: {new_keys}")

    gate_ok, gate_detail = (True, "已跳过(--no-gate)") if args.no_gate else check_gate()
    add_rule(results, "GATE", "FAIL", gate_ok, gate_detail)

    fails = [r for r in results if r["level"] == "FAIL" and not r["ok"]]
    warns = [r for r in results if r["level"] == "WARN" and not r["ok"]]
    verdict = "FAIL" if fails else ("WARN" if warns else "PASS")

    payload = {"batch": batch, "tier": tier, "verdict": verdict,
               "semantic_diff_total": sem_total, "files": file_rows,
               "checks": results, "ts": time.strftime("%Y-%m-%d %H:%M:%S")}

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=1))
    else:
        print(f"\n批次 {batch}  分级 {tier}  结论 {verdict}  语义差异 {sem_total} 处")
        print("文件:")
        for f in file_rows:
            print(f"  {f['path']:<44} {f['state']:<4} "
                  f"repo={f['repo_md5'][:8] or '(无)':<10} 交付={f['delivered_md5'][:8]}")
        print("检查:")
        for r in results:
            flag = "OK  " if r["ok"] else ("FAIL" if r["level"] == "FAIL" else "WARN")
            print(f"  [{flag}] {r['id']:<4} {r['detail']}")
        if warns or fails:
            print("人工必看:")
            for r in fails + warns:
                print(f"  - {r['id']}: {r['detail'].splitlines()[0]}")
        print()

    if args.write_ledger:
        ledger = Path(args.ledger).resolve() if args.ledger else LEDGER
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
        print(f"台账已追加: {ledger}")

    sys.exit(0 if verdict != "FAIL" else 1)


if __name__ == "__main__":
    main()
