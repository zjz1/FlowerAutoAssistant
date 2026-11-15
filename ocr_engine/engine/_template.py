"""模板匹配定位/多命中/点击。

E01(batch-03, 2026-11-14) 自单文件 ocr_engine.py 机械拆包: 本文件各段为原文件对应
行段的**逐行原文**(唯 __file__ 锚点因包层级 +1 机械重锚定, 见 ast_hash_compare.py
allowlist)。行为等价口径: 帧集回归 0 退化 + 闸门全绿 + import 面零改动。
原行段映射: evidence/batch-03/tiles_manifest.json。
"""
from __future__ import annotations

import numpy as np

from pathlib import Path

from .._constants import TEMPLATE_DIR
from .._geometry import Point

# V01-a(batch-11): 低灰度std模板观测阈值 —— 07_fragility 笔记 V01 实测口径(gray_std<25 的
# 模板在低对比背景上 TM_SQDIFF 分数塌缩: 12 真实模板按引擎同款协议实测 6/12 最佳分=0.0000,
# 其中 num_bar 18.9 / collapse_menu 20.0 / chat_collapse 21.9 属本档)。**纯观测阈值**,
# 不参与任何命中/未命中判定(方案红线); batch-12 采样标定数据回填前仅作观测分档。
TM_LOWSTD_OBSERVE_TH = 25.0


def _template_gray_std(tpl) -> float:
    """模板灰度std(V01-a 观测用; 与 07_fragility 笔记 V01 实测表同口径: BGR→GRAY 全像素 std)。"""
    import cv2
    return float(cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY).std())


class _TemplateMixin:
    # ---- 模板匹配识别(纯图形/无文字按钮, 借鉴 MAA TemplateMatch) ----
    @staticmethod
    def _template_path(template: str):
        """解析模板文件名 -> 绝对路径(resource/template/ 下); 不存在返回 None。
        支持省略扩展名(自动补 .png)与子路径(相对 TEMPLATE_DIR)。
        """
        p = Path(template).expanduser()
        if not p.name.lower().endswith(".png"):
            p = p.with_suffix(".png")
        if p.is_absolute():
            return str(p) if p.exists() else None
        full = TEMPLATE_DIR / p
        return str(full) if full.exists() else None

    def locate_template(self, template: str, img=None, threshold=0.8,
                        region_rel=None, scale_range=(0.7, 1.0),
                        metric: str = "sqdiff", return_score: bool = False, quiet: bool = False):
        """模板匹配定位: 在截图中查找与模板图最匹配的位置(多尺度缩放), 返回模板中心 Point。
        借鉴 MAA TemplateMatch, 用于「纯图形(无文字)按钮」如花形关闭钮/折角切换钮等
        颜色或文字难以唯一化的图形。template: 模板文件名(资源根 resource/template/<template>)。
        region_rel: [x1,y1,x2,y2](0~1) 限定搜索区域提速/避干扰。最高分 < threshold 判未命中。
        return_score(2026-10-24, P1-2 批1): True 时返回 `(Point, score)` —— 供关闭按钮候选
        按分数比较/打印; False(默认) 行为与旧版逐字节一致。
        尺度自适应(2026-10-03): 模板均从 1280x720 截图裁切, 引擎按 screen_w/1280 把 scale_range
        整体缩放 —— 720p 下行为与旧版完全一致; 1080p 等更高分辨率自动等效放大搜索尺度
        (实测 close_family 在 1080p 需 scale≈1.5, 旧版 0.7~1.0 全部漏检)。
        metric(2026-10-03): "sqdiff"(默认, 与旧版一致) | "ccoeff"。可选能力, 本项目模板
        (同源截图裁切)实测 sqdiff 即精确命中(里程碑77 七块新模板 源图 0.99+ / 异图 0.33~0.99
        均低于各自阈值, 无假阳性; 早期引用的 b1_switch_down 已随登录页改版失效, 不再作证据);
        ccoeff 保留给「模板与当前背景明暗相反」的场景(相关系数对亮度偏移不敏感)。
        ⚠ 取分注意(2026-10-04 教训): TM_SQDIFF_NORMED 的结果图要取 minMaxLoc 的
        minVal/minLoc 才是最佳命中, 误用 maxVal/maxLoc 会把最差点当成命中 ——
        分析脚本与流程代码各踩过一次; 自测先怀疑自己的解包, 再下「假阳性」结论。
        """
        import cv2
        import numpy as np
        tpl_path = self._template_path(template)
        if tpl_path is None:
            print(f"[模板匹配] 模板不存在: {template}")
            return None
        tpl = cv2.imread(tpl_path, cv2.IMREAD_COLOR)
        if tpl is None:
            print(f"[模板匹配] 读取模板失败: {template}")
            return None
        # V01-a(batch-11): 模板灰度std(观测用, 见 _note_tm_lowcontrast; 计算不改变任何匹配数学)
        tpl_std = _template_gray_std(tpl)
        img = img if img is not None else self.screenshot()
        if img is None:
            return None
        th, tw = tpl.shape[:2]
        if th >= img.shape[0] or tw >= img.shape[1]:
            print(f"[模板匹配] 模板({tw}x{th})不小于截图({img.shape[1]}x{img.shape[0]}), 无法定位")
            return None
        lo, hi = scale_range
        ref = (self.screen_w or img.shape[1]) / 1280.0  # 模板基准分辨率宽 1280
        scales = sorted(set(round(float(s * ref), 2) for s in np.linspace(lo, hi, 4)), reverse=True)
        higher = (metric == "ccoeff")  # ccoeff: max=最佳; sqdiff: min=最佳
        flag = cv2.TM_CCOEFF_NORMED if higher else cv2.TM_SQDIFF_NORMED
        best = None  # (score, mx, my, tw_r, th_r)  mx/my 为原图上命中左上角, tw_r/th_r 为该尺度模板宽高
        for sc in scales:
            tw_r, th_r = max(1, int(tw * sc)), max(1, int(th * sc))
            if th_r >= img.shape[0] or tw_r >= img.shape[1]:
                continue
            rtpl = cv2.resize(tpl, (tw_r, th_r))
            # sqdiff: 模板源自截图(同源抠图), 值越小越匹配, score=1-sqdiff 归一为「越大越匹配」
            shot = cv2.matchTemplate(img, rtpl, flag)
            if region_rel is not None:
                w, h = img.shape[1], img.shape[0]
                rx1, ry1 = int(region_rel[0] * w), int(region_rel[1] * h)
                rx2, ry2 = int(region_rel[2] * w), int(region_rel[3] * h)
                rx1, ry1 = max(0, rx1), max(0, ry1)
                rx2, ry2 = min(shot.shape[1], rx2), min(shot.shape[0], ry2)
                if rx2 <= rx1 or ry2 <= ry1:
                    continue
                sub = shot[ry1:ry2, rx1:rx2]
            else:
                rx1 = ry1 = 0
                sub = shot
            if higher:
                # minMaxLoc 返回 (minVal, maxVal, minLoc, maxLoc): ccoeff 取 maxVal/maxLoc
                _, mval, _, mlo = cv2.minMaxLoc(sub)   # max=最佳
                score = float(mval)
            else:
                mval, _, mlo, _ = cv2.minMaxLoc(sub)   # min=最佳
                score = 1.0 - float(mval)
            mmloc = (mlo[0] + rx1, mlo[1] + ry1)
            if best is None or score > best[0]:
                best = (score, mmloc[0], mmloc[1], tw_r, th_r)
        # V01-a(batch-11): 低对比塌缩观测层(纯观测, 零判定变化 —— 下方命中/未命中分支照旧)。
        # 仅低灰度std模板(<TM_LOWSTD_OBSERVE_TH, 07 笔记 V01 实测口径)触发 WARN+score 入统计;
        # 高std模板零观测零输出(常态零漂移)。
        top_score = best[0] if best else 0.0
        if tpl_std < TM_LOWSTD_OBSERVE_TH:
            self._note_tm_lowcontrast(template, tpl_std, top_score,
                                      hit=best is not None and best[0] >= threshold, quiet=quiet)
        if best is None or best[0] < threshold:
            top = best[0] if best else 0.0
            if not quiet:
                print(f"[模板匹配] {template} 最高分 {top:.3f} < 阈值 {threshold}, 未命中")
            return None
        mval, mx, my, tw_r, th_r = best
        sw, sh = img.shape[1], img.shape[0]
        cx, cy = mx + tw_r // 2, my + th_r // 2  # 原图模板中心
        cx = max(0, min(sw - 1, cx))
        cy = max(0, min(sh - 1, cy))
        if not quiet:
            print(f"[模板匹配] {template} score={mval:.3f} -> ({cx},{cy})")
        point = Point(cx, cy, sw, sh)
        return (point, float(mval)) if return_score else point

    def locate_template_all(self, template: str, img=None, threshold=0.8,
                            region_rel=None, scale_range=(0.7, 1.0),
                            nms_gap_rel=0.05) -> "list[Point]":
        """模板匹配多命中: 一次匹配返回**所有**高于阈值的局部峰值点(跨尺度 NMS 去重)。

        与 locate_template 的区别: 后者只返回最高分单点; 本方法用于「一屏多个同形图标」
        的场景(如好友列表多个可采粉角标), 避免调用方逐带扫描重复做多尺度全图匹配(极大提速)。
        region_rel/scale_range 语义同 locate_template; 尺度同样按 screen_w/1280 自适应(见彼处注)。
        nms_gap_rel: 峰值去重半径(相对截图宽高), 多尺度会重复命中同一目标, 按此合并。
        """
        import cv2
        import numpy as np
        tpl_path = self._template_path(template)
        if tpl_path is None:
            print(f"[模板匹配] 模板不存在: {template}")
            return []
        tpl = cv2.imread(tpl_path, cv2.IMREAD_COLOR)
        if tpl is None:
            print(f"[模板匹配] 读取模板失败: {template}")
            return []
        img = img if img is not None else self.screenshot()
        if img is None:
            return []
        th, tw = tpl.shape[:2]
        if th >= img.shape[0] or tw >= img.shape[1]:
            print(f"[模板匹配] 模板({tw}x{th})不小于截图({img.shape[1]}x{img.shape[0]}), 无法定位")
            return []
        w, h = img.shape[1], img.shape[0]
        rx1 = ry1 = rx2 = ry2 = None
        if region_rel is not None:
            rx1, ry1 = int(region_rel[0] * w), int(region_rel[1] * h)
            rx2, ry2 = int(region_rel[2] * w), int(region_rel[3] * h)
            rx1, ry1 = max(0, rx1), max(0, ry1)
            rx2, ry2 = min(w, rx2), min(h, ry2)
            if rx2 <= rx1 or ry2 <= ry1:
                return []
        lo, hi = scale_range
        ref = (self.screen_w or img.shape[1]) / 1280.0  # 模板基准分辨率宽 1280 (尺度自适应, 见 locate_template)
        scales = sorted(set(round(float(s * ref), 2) for s in np.linspace(lo, hi, 4)), reverse=True)
        cands = []  # (score, cx, cy)
        for sc in scales:
            tw_r, th_r = max(1, int(tw * sc)), max(1, int(th * sc))
            if th_r >= img.shape[0] or tw_r >= img.shape[1]:
                continue
            rtpl = cv2.resize(tpl, (tw_r, th_r))
            shot = cv2.matchTemplate(img, rtpl, cv2.TM_SQDIFF_NORMED)
            sub = shot if region_rel is None else shot[ry1:ry2, rx1:rx2]
            smap = 1.0 - sub  # 越大越匹配
            # 找局部峰值(膨胀后等于自身)且过阈值
            kernel = np.ones((3, 3), np.uint8)
            dilated = cv2.dilate(smap, kernel)
            peak_mask = (smap >= dilated) & (smap >= threshold)
            ys, xs = np.nonzero(peak_mask)
            ox, oy = (rx1, ry1) if region_rel is not None else (0, 0)
            for yy, xx in zip(ys, xs):
                cx = ox + int(xx) + tw_r // 2
                cy = oy + int(yy) + th_r // 2
                cands.append((float(smap[yy, xx]), cx, cy))
        if not cands:
            print(f"[模板匹配] {template} 多命中: 无 (阈值 {threshold})")
            return []
        # 跨尺度 NMS: 高分优先, 与已接受点距离 < nms_gap 则跳过
        gap_x, gap_y = max(1, int(nms_gap_rel * w)), max(1, int(nms_gap_rel * h))
        cands.sort(key=lambda c: -c[0])
        accepted = []
        for s, cx, cy in cands:
            if all(abs(cx - ax) >= gap_x or abs(cy - ay) >= gap_y for ax, ay, _ in accepted):
                accepted.append((cx, cy, s))
        accepted.sort(key=lambda c: (c[1], c[0]))  # 按 y 从上到下
        print(f"[模板匹配] {template} 多命中 {len(accepted)} 个: "
              + ", ".join(f"({cx},{cy}@{s:.3f})" for cx, cy, s in accepted))
        return [Point(cx, cy, w, h) for cx, cy, _ in accepted]

    # ---- V01-a(batch-11): TM_SQDIFF 低对比塌缩观测层(纯观测, 零判定变化; 方案锚点 07 笔记 V01-a) ----
    def _note_tm_lowcontrast(self, template: str, tpl_std: float, score: float,
                             hit: bool, quiet: bool = False) -> None:
        """低灰度std模板命中/未命中时打 WARN + score 入统计(纯观测, 不改判定)。

        背景(07_fragility 笔记 V01 实测): TM_SQDIFF_NORMED 的 1.0−minVal 取分协议在
        「低灰度std模板 × 低对比背景」上整体塌缩 —— 12 真实模板 6/12 最佳分=0.0000,
        「负样本最高分」式标定数据在低对比帧上是噪声, 观测化后才可信。
        本层只把该场景观测出来: WARN 打印 + 分数累计进 _ocr_stat(tm_low_* 键, 随
        _print_ocr_stat 模块行汇总), 供下次逐模板标定(batch-12 采样);
        命中/未命中判定与调用方返回值和旧版逐字节一致(方案红线: 不改判定)。
        quiet=True(点后复检)不打 WARN, 统计照记 —— 与其它观测键的口径一致。
        """
        st = self._ocr_stat
        st["tm_low_n"] = st.get("tm_low_n", 0) + 1
        if hit:
            st["tm_low_hit_n"] = st.get("tm_low_hit_n", 0) + 1
        st["tm_low_score_sum"] = st.get("tm_low_score_sum", 0.0) + float(score)
        by = st.setdefault("tm_low_by_tpl", {})
        rec = by.setdefault(str(template), {"n": 0, "hit": 0, "sum": 0.0})
        rec["n"] += 1
        rec["sum"] += float(score)
        if hit:
            rec["hit"] += 1
        if not quiet:
            print(f"[模板观测] {template} 模板灰度std={tpl_std:.1f}<{TM_LOWSTD_OBSERVE_TH:.0f} "
                  f"{'命中' if hit else '未命中'} score={score:.4f} —— 低灰度std模板的 SQDIFF 分数"
                  f"在低对比背景下可能塌缩失真(07 笔记 V01 实测 6/12 最佳分=0.0000), 本行纯观测不改判定")

    def click_template(self, template: str, img=None, threshold=0.8,
                       region_rel=None, scale_range=(0.7, 1.0), fallback_rel=None,
                       no_fallback=False, metric: str = "sqdiff",
                       offset_rel=None) -> "Point | None":
        """模板匹配点击: locate_template 命中则点击并记知识库(method=template)。
        未命中且有 fallback_rel 时回退到该相对坐标点击。返回命中的 Point, 否则 None。
        no_fallback=True 时忽略 fallback_rel: 未命中就如实返回 None, 不用回退坐标盲点
        (高危按钮「切换账号」类, 见 click_text 同名参数)。
        metric: 透传 locate_template("sqdiff"|"ccoeff"), 低对比模板用 ccoeff 防空白假阳性。
        offset_rel(2026-10-24): 命中后按屏幕相对比例偏移再点, 如 [-0.033,0.033]。
        用于「先匹配小徽标定位、再点它旁边的实体按钮」——点击点仍由**本次实时命中推导**,
        不是写死坐标(规则 6 合规); 偏移日志会明确标注。
        """
        pt = self.locate_template(template, img=img, threshold=threshold,
                                  region_rel=region_rel, scale_range=scale_range,
                                  metric=metric)
        if pt is not None:
            self._last_locate_source = "template"
            if offset_rel:
                px = int(pt.x + offset_rel[0] * (self.screen_w or 1280))
                py = int(pt.y + offset_rel[1] * (self.screen_h or 720))
                print(f"[模板匹配] {template} 命中({pt.x},{pt.y}) + 偏移{offset_rel} "
                      f"-> ({px},{py}) (偏移点由本次命中推导, 非写死坐标)")
                pt = Point(px, py, self.screen_w, self.screen_h)
            self.click_abs(pt.x, pt.y)
            self._log_click(template, [template], pt, "template", category=self._step_category)
            return pt
        if fallback_rel is not None and no_fallback:
            print(f"[未命中] 模板 {template} (no_fallback=True: 虽有回退坐标 {fallback_rel} 也不盲点)")
            return None
        if fallback_rel is not None:
            self._last_locate_source = "fallback"
            print(f"[回退缓存] 模板 {template} 未命中, 用回退坐标 {fallback_rel}")
            self.click_rel(*fallback_rel)
            pt = Point.from_rel(fallback_rel[0], fallback_rel[1], self.screen_w, self.screen_h)
            self._log_click(template, [template], pt, "fallback", category=self._step_category)
            return pt
        return None
