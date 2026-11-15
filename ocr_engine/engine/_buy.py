"""花宝道具受控购买原子(G1 v2)。

E01(batch-03, 2026-11-14) 自单文件 ocr_engine.py 机械拆包: 本文件各段为原文件对应
行段的**逐行原文**(唯 __file__ 锚点因包层级 +1 机械重锚定, 见 ast_hash_compare.py
allowlist)。行为等价口径: 帧集回归 0 退化 + 闸门全绿 + import 面零改动。
原行段映射: evidence/batch-03/tiles_manifest.json。
"""
from __future__ import annotations

import re
import time

from .._exceptions import BranchAborted
from .._failures import report_failure

class _BuyMixin:
    # ------------------------------------------------------------------
    # 花宝道具「受控购买」原子 (G1 v2, 2026-11-03; 用户已明确授权真实花费仙豆)
    # ------------------------------------------------------------------
    # 弹窗区域实测(11-01 取证件 1280x720, 购买框): 标题「购买道具」(380,148) /
    # 商品名(635,328) / 数量行(625,423) / 价格「消耗22仙豆」(647,469) / 按钮「购买」(634,526)
    # / 右上角余额(1084,27) / ✕(923,157)。区域面积 0.56x0.65=0.364 <= 40%, 可走裁片 OCR。
    BUY_DIALOG_REGION = (0.22, 0.17, 0.78, 0.82)
    BUY_CLOSE_TEMPLATE = "buy_popup_close.png"
    BUY_CLOSE_REGION = (0.66, 0.17, 0.78, 0.27)

    @staticmethod
    def _box_center(box) -> tuple[float, float]:
        return ((float(box[0]) + float(box[2])) / 2.0, (float(box[1]) + float(box[3])) / 2.0)

    def _ocr_dialog_text(self, img, box) -> tuple[str, list[dict]]:
        """把弹窗区域内的合并块按阅读顺序(y 分桶→x)拼成无空白文本, 供全文 AND 核对。
        仅读不点; 分行/空格/标点差异通过去空白与拼接消除(如说明两行「增加3点年」+「龄点数。」)。"""
        blocks = self._ocr_blocks_in_box(img, box)
        ordered = sorted(blocks, key=lambda b: (round(b["center"][1] / 20), b["center"][0]))
        text = re.sub(r"\s+", "", "".join(str(b.get("text", "")) for b in ordered))
        return text, blocks

    def _ocr_blocks_in_box(self, img, box) -> list[dict]:
        """取区域内的 OCR 合并块(不改判定; 区域面积<=40% 走裁片, 否则全图过滤)。
        仅用于读取弹窗文字/数字, 不做任何点击。"""
        if img is None:
            return []
        w, h = self.screen_w, self.screen_h
        blocks = None
        if self.config.get("region_ocr", True) and w and h:
            r = self._ocr_frame_region(img, box, need_split=False)
            if r is not None:
                blocks = r[0]
        if blocks is None:
            x1, y1 = float(box[0]) * w, float(box[1]) * h
            x2, y2 = float(box[2]) * w, float(box[3]) * h
            blocks = [b for b in self._ocr_frame(img, need_split=False)[0]
                      if x1 <= b["center"][0] <= x2 and y1 <= b["center"][1] <= y2]
        return blocks

    def _close_buy_popup(self, indent: int = 1) -> bool:
        """关闭「购买道具」弹窗: 先用 D21 实测 ✕ 模板(区域收紧 + no_fallback + 0.97),
        未命中再走 close_dialog 锚点档。返回 True=模板关闭 / False=模板未命中(已尝试兜底)。"""
        pt = self.click_template(self.BUY_CLOSE_TEMPLATE, threshold=0.97,
                                 region_rel=list(self.BUY_CLOSE_REGION), no_fallback=True)
        if pt is not None:
            time.sleep(1.0)
            return True
        print("  " * indent + "[buy_item] ✕ 模板未命中, 退回 close_dialog(锚点档)")
        self.close_dialog(anchor_kw="购买道具", only_types=["anchor_color"])
        time.sleep(1.0)
        return False

    def buy_item(self, step: dict, indent: int = 1) -> None:
        """受控购买原子: OCR 全文核对 → 读余额 → 点「购买」→ 差额复核 → 关弹窗/如实失败。

        安全约束(缺一不可):
          ① 单轮次数硬上限(max_per_run / baobao_buy_max), 达上限即软失败退出, 不循环补货;
          ② 确认前必须 OCR **全文** AND 校验(标题/商品名/消耗/仙豆/说明) + 数量/价格分区域纯数字;
             不允许仅凭「有确认按钮」判定;
          ③ 开跑前读余额 B0, 低于下限或不足本次金额立即停;
          ④ 点击后按 0.12s 起多次快照读 B1, 差额必须 = price*qty; 不可读则 balance_unverified
             如实 WARN(不伪造差额), 到手与否交调用方的行为复核;
          ⑤ 任何失败: 关弹窗 → report_failure → raise BranchAborted(只中止当前道具分支,
             不中止整轮, 也不追加购买);
          ⑥ 禁用缓存回退: 定位「购买」用 no_fallback=True, 余额/文字一律读当前帧。
        """
        pad = "  " * indent
        item_kws = step.get("item_keywords") or ["挠痒痒"]
        price = int(step.get("price", 0))
        qty = int(step.get("qty", 1))
        dialog_box = step.get("dialog_region_rel") or list(self.BUY_DIALOG_REGION)
        bal_center = step.get("balance_region_rel") or [0.858, 0.038]
        qty_box = step.get("qty_region_rel") or [0.33, 0.52, 0.67, 0.60]
        price_box = step.get("price_region_rel") or [0.42, 0.62, 0.60, 0.68]
        desc_kws = step.get("desc_keywords") or ["可使用5次"]
        floor = float(step.get("balance_floor", self.config.get("baobao_buy_floor", 10000)))
        max_run = int(self.config.get("baobao_buy_max", step.get("max_per_run", 1)) or 1)
        bal_tol = int(step.get("balance_tol", 80))

        def fail(reason: str) -> None:
            print(f"{pad}[buy_item] FAIL: {reason}")
            self._close_buy_popup(indent)
            report_failure(self._module, f"花宝购买失败: {reason}(已关弹窗, 不再补货)")
            raise BranchAborted(f"buy_item 失败: {reason}")

        # ① 单轮次数硬上限(计数在真正进入原子时 +1, 失败尝试也计入)
        if self._buy_count >= max_run:
            fail(f"单轮购买上限 max={max_run} 已达, 拒绝再次购买")
        self._buy_count += 1
        print(f"{pad}[buy_item] 第 {self._buy_count}/{max_run} 次尝试: 商品{item_kws} 价格{price}仙豆 x{qty}")

        img = self.screenshot()
        if img is None:
            fail("截图失败, 无法读取购买弹窗")
            return

        # ② 确认框 OCR 全文 AND 校验(标题/商品名/消耗/仙豆/说明)
        text, _ = self._ocr_dialog_text(img, dialog_box)
        need = ["购买道具"] + list(item_kws) + ["消耗", "仙豆"] + list(desc_kws)
        missing = [k for k in need if k.replace(" ", "") not in text]
        if missing:
            fail(f"确认框全文核对缺项 {missing} (读到: {text[:120]})")

        # 数量: 数量行内必须读到纯数字 qty
        q_blocks = self._ocr_blocks_in_box(img, qty_box)
        q_nums = []
        for b in q_blocks:
            m = re.fullmatch(r"\s*(\d+)\s*", str(b.get("text", "")))
            if m:
                q_nums.append(int(m[1]))
        if not q_nums:
            q_nums = [n for n in [self.parse_count_at(self._box_center(qty_box),
                                                      img=img, tol=45)] if n is not None]
        if q_nums and qty not in q_nums:
            fail(f"数量核对不符: 期望 {qty}, 读到 {q_nums}")
        if not q_nums:
            # 实测定点(11-03): 数量「1」为浅灰字压在粉色滑块上, RapidOCR 直读/放大/增强均读不出。
            # 不硬失败也不瞎猜: 数量恒为默认 1(本链不点 +/-), 改由「价格总额 22」+「余额差额 -22」
            # 双重兜底 —— 若数量被改成 2+, 总额会变 44, 价格核对即失败。
            print(f"{pad}[buy_item] WARN: 数量数字 OCR 不可读(浅灰/粉底), 改用总价{price}+差额复核兜底")

        # 价格: 价格行内必须读到数字 price(「消耗22仙豆」或独立 22 均可)
        p_nums = []
        for b in self._ocr_blocks_in_box(img, price_box):
            p_nums += [int(n) for n in re.findall(r"\d+", str(b.get("text", "")))]
        if price not in p_nums:
            fail(f"价格核对不符: 期望 {price}, 读到 {p_nums}")

        # ③ 余额 B0 + 下限/足额守卫
        b0 = self.parse_count_at(bal_center, img=img, tol=bal_tol)
        if b0 is None:
            fail("余额 B0 未读到(拒绝在无法核对余额时下单)")
        cost = price * qty
        if b0 < max(floor, cost):
            fail(f"余额不足: B0={b0} < max(下限{int(floor)}, 本次{cost})")

        # ④ OCR 点「购买」: exact + 区域限定 + no_fallback(不采信任何历史坐标)
        print(f"{pad}[buy_item] 确认框核对通过(B0={b0}), 点击「购买」…")
        ok = self.click_text(["购买"], img=img, exact=True, min_score=0.5,
                             region_rel=list(dialog_box), no_fallback=True)
        if not ok:
            fail("「购买」按钮本次实时 OCR 未命中(no_fallback, 不盲点)")

        # ⑤ 点击后快照读 B1(0.12s 起, 至多 ~1.6s); 再等弹窗消失
        b1_samples = []
        for delay in (0.12, 0.35, 0.75, 1.4):
            time.sleep(delay)
            v = self.parse_count_at(bal_center, img=self.screenshot(), tol=bal_tol)
            if v is not None:
                b1_samples.append(v)
                if b0 - v == cost:
                    break
        gone = self.wait_text_gone(["购买道具"], timeout=5)
        if gone:
            v = self.parse_count_at(bal_center, img=self.screenshot(), tol=bal_tol)
            if v is not None:
                b1_samples.append(v)

        # ⑥ 差额复核: 只认 0 <= B1 <= B0 的读数(余额不应在购买后上升)
        diffs = {b0 - v for v in b1_samples if 0 <= v <= b0 and v != b0}
        if not gone:
            fail(f"点击购买后弹窗未消失(余额样本 {b1_samples})")
        if len(diffs) > 1:
            fail(f"余额读数不一致 {b1_samples}, 无法确认差额")
        if diffs:
            d = diffs.pop()
            if d != cost:
                fail(f"余额差额不符: 期望 -{cost}, 实际 -{d} (B0={b0}, 样本 {b1_samples})")
            print(f"{pad}[buy_item] PASS: 余额 {b0} -> {b0 - cost} (差额 -{cost} 已复核), 弹窗已消失")
        else:
            # B1 不可读/未变化: 不伪造差额, 如实 WARN; 到手与否由调用方行为复核。
            # 此处**不登记失败**(弹窗已消失=购买很可能已生效), 由到货复核与后续 if_count 决定成败;
            # 若到货复核失败, 由流程 fail_flow 如实报错。
            print(f"{pad}[buy_item] WARN: balance_unverified —— 余额样本 {b1_samples} 未见 -{cost}, "
                  f"不伪造差额; 购买是否生效交由后续到货复核")
            time.sleep(step.get("delay", 0.5))
