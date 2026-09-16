"""引擎自测脚本: OCREngine.run_navigate 四场景(顶层命中 / 全 miss 脱困 / target 缺失 / nav 链逐层进入)。

归档于 dev_tools/self_test/ —— navigate 步骤或导航注册表改动后的回归自测。不连设备。
打桩 click_text/close_dialog/time.sleep/locate。原为临时脚本 _selftest_nav.py。
用法(项目根下): .venv\\Scripts\\python.exe -u dev_tools\\self_test\\test_navigate.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 项目根, 保证 import ocr_engine

import json, time
from ocr_engine import OCREngine, NAV_ENTRIES_PATH

# 1) 注册表 JSON 合法
entries = json.load(open(NAV_ENTRIES_PATH, encoding="utf-8"))
targets = entries["targets"]
assert {"家族活动", "闪耀变身", "花灵派对"} <= set(targets), targets.keys()
for t, e in targets.items():
    assert e.get("mark_text") and e.get("scene") and e.get("max_rounds") == 3

# 只读示例验证 nav 结构(标准 schema: 内层存在带 mark:true 的目标点击)
def has_mark(node):
    if isinstance(node, list):
        return any(has_mark(x) for x in node)
    if not isinstance(node, dict):
        return False
    if node.get("type") == "click_text" and node.get("mark"):
        return True
    for b in ("then", "else", "do"):
        if has_mark(node.get(b)):
            return True
    return False
assert all(any(s.get("type") == "if_text" for s in entry["nav"]) for entry in targets.values())
assert all(has_mark(entry["nav"]) for entry in targets.values())

# 2) 打桩
time.sleep = lambda *a, **k: None  # 免等待
import ocr_engine as OE
OE.time.sleep = lambda *a, **k: None

class Counter:
    def __init__(self): self.close = 0
    def inc(self, *a, **k): self.close += 1

def make_eng(visible, on_click=None):
    eng = OCREngine()
    visible = set(visible)
    eng._test_visible = visible
    def fake_click_text(kws, fallback_rel=None, exact=False, **k):
        kws_list = kws if isinstance(kws, list) else [kws]
        ok = any(kw in visible for kw in kws_list)
        if ok and on_click:
            on_click(kws_list, visible)
        return ok
    eng.click_text = fake_click_text
    def fake_locate(kws, *a, **k):
        kws_list = kws if isinstance(kws, list) else [kws]
        if any(kw in visible for kw in kws_list):
            return {"name": "stub"}
        return None
    eng.locate = fake_locate
    return eng

# ---- 场景A: 顶层直接命中 ----
cA = Counter()
engA = make_eng(["家族活动"])
engA.close_dialog = cA.inc
fA = {"name": "t", "steps": [{"type": "navigate", "target": "家族活动"}]}
rA = engA.run_navigate(fA["steps"][0])
assert rA is True, f"场景A 应命中: {rA}"
assert engA._scene == "家族活动界面", f"场景A scene 未切换: {engA._scene}"
assert cA.close == 0, f"场景A 不应脱困: {cA.close}"
print("场景A 顶层命中: OK, scene=", engA._scene, "; 脱困0次")

# ---- 场景B: 全 miss -> 脱困 rounds=2 次后放弃 ----
cB = Counter()
engB = make_eng([])  # 什么都看不到
engB.close_dialog = cB.inc
fB = {"type": "navigate", "target": "闪耀变身", "max_rounds": 2}
rB = engB.run_navigate(fB)
assert rB is False, f"场景B 应放弃: {rB}"
assert cB.close == 2, f"场景B 应脱困2次: {cB.close}"
assert engB._scene == "未分类", f"场景B scene 不应被改: {engB._scene}"
print("场景B 全miss->脱困2次->放弃: OK")

# ---- 场景C: target 缺失 ----
cC = Counter()
engC = make_eng(["随便"])
engC.close_dialog = cC.inc
rC = engC.run_navigate({"type": "navigate", "target": "不存在的界面"})
assert rC is False and cC.close == 0, f"场景C 应直接跳过且不脱困: r={rC} close={cC.close}"
print("场景C target缺失->跳过, 脱困0次: OK")

# ---- 场景D: 顶层看不到目标, 走 nav 导航链逐层点击后 mark 命中 ----
def enter_family(kws_list, visible):
    if "社交" in kws_list:
        visible.add("家族")
    if "家族" in kws_list:
        visible.add("家族活动")
engD = make_eng(["社交"], on_click=enter_family)
engD.close_dialog = lambda *a, **k: (_ for _ in ()).throw(AssertionError("场景D 不应脱困"))
rD = engD.run_navigate({"type": "navigate", "target": "家族活动"})
assert rD is True, f"场景D 应经导航链命中: {rD}"
assert engD._scene == "家族活动界面", f"场景D scene 未切换: {engD._scene}"
print("场景D nav导航链逐层进入: OK, scene=", engD._scene)

print("\n全部 navigate 自测通过")