"""领取成功与奖励弹窗统一原语。

E01(batch-03, 2026-11-14) 自单文件 ocr_engine.py 机械拆包: 本文件各段为原文件对应
行段的**逐行原文**(唯 __file__ 锚点因包层级 +1 机械重锚定, 见 ast_hash_compare.py
allowlist)。行为等价口径: 帧集回归 0 退化 + 闸门全绿 + import 面零改动。
原行段映射: evidence/batch-03/tiles_manifest.json。
"""
from __future__ import annotations

import time

from .._exceptions import stop_requested
from .._failures import report_failure

class _RewardMixin:
    # ---- 领取成功界面 (2026-10-20 D13, 方案A): 统一判定原语 ----
    # 背景(用户 2026-10-19 裁定 + 本轮日志实证): 全项目共 13 处「点领取 -> 关成功弹窗」,
    #   写成 5 种不同样子, 且**没有一处判断"是否真的领取成功"** —— 多是"点领取返回 ok 就当成功"。
    #   实证: `[OCR未命中]['恭喜获得']` 27 次 / `[if_text]['恭喜获得'] -> MISS` 6 次, 甚至在活动列表
    #   画面也去查成功弹窗 => 「点击成功」≠「真领取到」。且多数落点把**页脚**「点击任意处关闭」当关闭点,
    #   弹窗已消失时会**点击穿透**到底层 UI(矿洞页曾误开「我的背包」)。
    # 本原语统一三件事: ①判据(标题或页脚在屏=成功界面出现) ②收尾(标题优先点击, 页脚仅兜底)
    #   ③上报(未见/关不掉如实 print, required=true 时登记软失败)。范式取自 pollin.dismiss_reward_popup。
    REWARD_TITLE_KW = "恭喜获得"
    REWARD_FOOTER_KW = "点击任意处关闭"
    # 性能批 zcode-20261028-9(两段式区域化): 默认搜索带(相对坐标 [x1,y1,x2,y2], 0~1)。
    # 依据=三源实测落点一致:「恭喜获得」rel(0.499,0.237) —— 10-27 日志「领取成功界面 @(639,171)」
    # 与 _recon_daily/v9_popup.png (0.499,0.237)、v10_like_popup.png (0.500,0.239);
    # 「点击任意处关闭」rel(0.500,0.938) —— v9/v10 两帧一致。标题带面积 0.70*0.30=0.21、
    # 页脚带面积 0.60*0.15=0.09, 均满足批C 区域化闸门(<=0.40, 见 _ocr_frame_region)。
    # ⚠ 收益重估(离线实测, 证据见本批 evidence/): 本项目 det 固定 rapidocr 默认
    #   limit_side_len=736/limit_type=min(venv 内 rapidocr_onnxruntime/config.yaml),
    #   短边<736px 的宽扁裁片会先被**反向放大**再进 det —— 标题带裁片(984x236→约3069x736)
    #   耗时≈全图的 0.8~0.95 倍(几乎不省), 页脚带裁片(844x113→约5497x736)为全图的
    #   1.1~2.4 倍(反而更慢); 「小裁片更快」前提不成立, 故加配置闸门 reward_region_ocr
    #   **默认关闭**, 保持与旧版全图路径逐字节一致, 待实机 A/B(开闸跑一轮看 [OCR统计])
    #   复核后再定默认值。仅 region_rel=None(调用方未显式限定)时才可能启用;
    #   显式 region_rel 依旧原样透传不受影响。
    REWARD_TITLE_REGION = [0.15, 0.10, 0.85, 0.40]
    REWARD_FOOT_REGION = [0.20, 0.85, 0.80, 1.0]

    def _reward_popup_point(self, img=None, region_rel=None, kws=None, need_refine: bool = True,
                            log_miss: bool = True):
        """定位奖励弹窗的文字块(标题优先, 页脚兜底)。标题落在弹窗内, 点击无穿透风险。
        O2: `need_refine=False` 供「只判是否存在」的守卫使用(has_reward_popup), 点击路径保持 True。
        E1: `log_miss=False` 供 required=false 的弹窗守卫静默(见 reward_dialog)。
        性能批 zcode-20261028-9: region_rel=None 且配置 reward_region_ocr=true 时, 标题/页脚
        改为在各自搜索带内找(两段式区域化); 闸门默认关=全图路径与旧版逐字节一致(原因见
        REWARD_*_REGION 注释的收益重估)。其它自定义关键字即便开闸也维持全图(保守, 无实测落点
        依据不设带)。回退兜底语义(批C find_text): 带区域搜索零命中时自动回退一次全图重试、
        结果仍按**原 region 过滤** —— 挽回的是「文字确在区域内但裁片 det 失读」的场景, 不扩大
        搜索面, 故区域化不制造新 MISS(离线已构造出该挽回实例, 见本批 evidence/)。
        显式传入 region_rel 时行为与旧版逐字节一致。"""
        img = img if img is not None else self.screenshot()
        if img is None:
            return None
        kws = list(kws or [self.REWARD_TITLE_KW, self.REWARD_FOOTER_KW])
        # 显式两段式: locate 只返回首个命中块, 块序不保证按关键字先后 -> 必须标题单独先试
        order = ([self.REWARD_TITLE_KW] if self.REWARD_TITLE_KW in kws else []) \
            + [k for k in kws if k != self.REWARD_TITLE_KW]
        for kw in order:
            # zcode-20261028-9: 仅「未显式限定 + 闸门开」时按关键字选带; 显式 region_rel
            # (含空列表)原样透传, 与旧版行为逐字节一致(_ocr_candidates 对非 4 元素区域本就走全图)。
            kw_region = region_rel
            if kw_region is None and self.config.get("reward_region_ocr", False):
                if kw == self.REWARD_TITLE_KW:
                    kw_region = self.REWARD_TITLE_REGION
                elif kw == self.REWARD_FOOTER_KW:
                    kw_region = self.REWARD_FOOT_REGION
            pt = self.locate([kw], img=img, min_score=0.4, region_rel=kw_region,
                             need_refine=need_refine, log_miss=log_miss)
            if pt is not None:
                return pt
        return None

    def has_reward_popup(self, img=None, region_rel=None, keywords=None) -> bool:
        """当前画面是否在屏奖励弹窗(标题「恭喜获得」或页脚「点击任意处关闭」)。公开给 pollin 守卫复用。
        O2: 只判存在 -> 不拆分(拆分的唯一用途是给点击提供精确坐标)。
        E1: 强静默 —— 调用点都是「有弹窗才做事」的高频守卫, 未命中是常态, 不逐条打印。"""
        return self._reward_popup_point(img=img, region_rel=region_rel, kws=keywords,
                                        need_refine=False, log_miss=False) is not None

    def reward_dialog(self, step: dict) -> bool:
        """步骤 reward_dialog / 公开原语: 等待「领取成功界面」出现 -> 关闭 -> 如实上报。

        参数: wait(秒, 等弹窗出现的窗口, 默认 2.0; 0=立即判定一次) / interval(轮询间隔, 默认 0.6)
              tries(最多点击关闭次数, 默认 2) / required(true=未见或关不掉时登记软失败)
              region_rel(限定搜索区域, 可选) / name(日志标签) / keywords(识别词, 可选)
              quiet(true=完全静默: 未见时既不打日志也不登记失败, 供"可能本就没有弹窗"的守卫复用)
        返回 True=见到并已关闭 / False=未见或关不掉。
        注意: 判据仍是 OCR 读到弹窗文字。真领到了但 OCR 未读到时 required=true 会误报 ——
        故 required 只挂"点击前已用模板/OCR 确认过领取按钮"的领取链; 浇水/抽奖/签到等守卫用 false。
        """
        wait = max(0.0, float(step.get("wait", 2.0)))
        interval = max(0.2, float(step.get("interval", 0.6)))
        tries = max(1, int(step.get("tries", 2)))
        required = bool(step.get("required", False))
        quiet = bool(step.get("quiet", False))
        region = step.get("region_rel")
        kws = step.get("keywords")
        label = step.get("name") or "领取成功界面"
        mod = getattr(self, "current_module", None) or ""

        # 1) 等弹窗出现(轮询 OCR; wait=0 只判定一次)。B1(2026-10-22): 判定/关闭定位一律
        #    need_refine=False —— 本原语只需“弹窗在不在”(关闭点用标题中心, 页脚横贯全屏),
        #    10-22 日志 `拆分: reward_dialog 73` 全是白拆(≈60s/轮)。
        # E1(2026-10-22 方案A): 逐次未命中日志按 required 分流 —— required=true(点击前已 OCR/模板确认
        #    过领取按钮)保留 [OCR未命中] 全量证据; required=false(抽奖/浇水/时间礼包等「可能本就没有」)
        #    逐次静默, 整段结束打一行摘要 + 拟低分提示(见 _near_miss_hint), 避免日志被常态负判定淹没。
        log_miss = bool(required and not quiet)
        probes = 0

        def _probe():
            nonlocal probes
            probes += 1
            return self._reward_popup_point(region_rel=region, kws=kws, need_refine=False,
                                           log_miss=log_miss)

        deadline = time.time() + wait
        pt = _probe()
        while pt is None and time.time() < deadline:
            if stop_requested():
                return False
            time.sleep(interval)
            pt = _probe()
        if pt is None:
            if not quiet:
                if required:
                    print(f"[领取] {label}: 未见到「领取成功」界面(如实上报)")
                else:
                    print(f"[弹窗] {label}: 无(检查 {probes} 次)")
                    hint = self._near_miss_hint(kws)
                    if hint:
                        print(f"[弹窗] {label}: 疑似低分块 {hint}(低于 0.4 阈值, 未计为命中)")
            if required and not quiet:
                report_failure(mod, f"{label}: 未见到「领取成功」界面(点击可能被吞/未达标)")
            return False
        print(f"[领取] {label}: 见到「领取成功」界面 @({pt.x},{pt.y})")

        # 2) 关闭(标题优先; 每次点击后复查, 仍在屏才再点)
        for i in range(1, tries + 1):
            if stop_requested():
                return False
            pt = _probe()
            if pt is None:
                print(f"[领取] {label}: 已关闭")
                return True
            print(f"[领取] {label}: 第{i}次点击关闭 @({pt.x},{pt.y})")
            self.click_abs(pt.x, pt.y)
            time.sleep(1.2)
        gone = _probe() is None
        if gone:
            print(f"[领取] {label}: 已关闭")
        else:
            print(f"[领取] {label}: {tries} 次点击后仍在屏, 如实上报")
            if required and not quiet:
                report_failure(mod, f"{label}: 成功界面 {tries} 次点击后仍在屏")
        return gone

    def _near_miss_hint(self, kws, lo=0.2, hi=0.4) -> str:
        """E1: 静默未命中后的一行「疑似低分」提示。

        静默的前提是「画面里确实没有弹窗」；若有块文字与关键字互为子串、但 OCR 分低于 0.4 阈值
        (弹窗文字被读残/半透明过渡态), 则可能是**漏判真弹窗**。长期观察名单(B9)靠这行发现。
        只返回前 3 条, 不改变任何判定结果。
        """
        out = []
        for b in (self._last_miss_blocks or []):
            txt = (b.get("text") or "").strip()
            sc = float(b.get("score", 0.0) or 0.0)
            if not txt or not (lo <= sc < hi):
                continue
            if any(kw and (kw in txt or (len(txt) >= 4 and txt in kw)) for kw in (kws or [])):
                out.append(f"'{txt[:10]}'@{sc:.2f}")
        return " | ".join(out[:3])
