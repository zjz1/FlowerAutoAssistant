# -*- coding: utf-8 -*-
"""HTTP 路由 mixin：template。"""
from __future__ import annotations

from .common import *  # noqa: F401,F403
class TemplateRoutes:
    def _tplt_init(self):
        """复用主界面已连引擎截图, 返回 jpeg + 尺寸。未连接则提示先到主界面连接。"""
        eng = get_engine()
        if not is_connected(eng):
            return self._send_json({"error": "未连接: 请先到主界面完成「连接设备」后再使用", "status": _status()}, 503)
        img = eng.screenshot()
        if img is None:
            return self._send_json({"error": "截图失败"}, 500)
        jpg = img_to_jpeg_b64(img)
        return self._send_json({"jpeg": jpg, "w": int(img.shape[1]), "h": int(img.shape[0])})

    def _tplt_load(self):
        """可选: 按已知图片载入(仅允许 debug/ 下文件路径), 返回其 base64 jpeg 供标注。不做探测回填。"""
        data = self._read_json()
        path = str(data.get("path") or "")
        target = (BASE / path).resolve()
        allow = (BASE / "debug").resolve()
        try:
            target.relative_to(allow)
        except ValueError:
            return self._send_json({"error": "仅允许载入 debug/ 目录下的图片"}, 400)
        if not target.is_file():
            return self._send_json({"error": "文件不存在"}, 400)
        import cv2
        img = cv2.imread(str(target))
        if img is None:
            return self._send_json({"error": "读取图片失败"}, 400)
        jpg = img_to_jpeg_b64(img)
        return self._send_json({"jpeg": jpg, "w": int(img.shape[1]), "h": int(img.shape[0]),
                                "loaded": target.name})

    def _tplt_contour(self):
        """在截图指定矩形(abs 像素)内自动提取主轮廓, 返回有序闭合点列(绝对像素)。
        用于 tpltool 闭环: 用户框选后请求一次, 回填为可调整的连续水线轮廓底稿。
        """
        data = self._read_json()
        eng = get_engine()
        if not is_connected(eng):
            return self._send_json({"error": "未连接: 请先到主界面完成「连接设备」后再使用"}, 503)
        img = eng.screenshot()
        if img is None:
            return self._send_json({"error": "截图失败"}, 500)
        h, w = img.shape[:2]
        try:
            x0, y0, x1, y1 = [int(data[k]) for k in ("x0", "y0", "x1", "y1")]
        except Exception:
            return self._send_json({"error": "缺少矩形 x0/y0/x1/y1"}, 400)
        # 收窄到画面并保证最小尺寸
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(w, x1), min(h, y1)
        if x1 - x0 < 4 or y1 - y0 < 4:
            return self._send_json({"error": "矩形过小"}, 400)
        import cv2
        import numpy as np
        roi = img[y0:y1, x0:x1]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        # 均值漂移+OTSU 突出前景主体, 形态闭合联通碎块
        blur = cv2.pyrMeanShiftFiltering(roi, 7, 21)
        g2 = cv2.cvtColor(blur, cv2.COLOR_BGR2GRAY)
        _, th = cv2.threshold(g2, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, kern, iterations=2)
        cnts, _ = cv2.findContours(th[:, :], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            return self._send_json({"error": "未在区域内检测到前景轮廓"}, 404)
        c = max(cnts, key=cv2.contourArea)
        # 缺省时外周: 用轮廓 + 外接矩形合成封闭环, 降低阈值退化风险
        if cv2.contourArea(c) < 8:
            return self._send_json({"error": "前景占比过小, 请扩大框选"}, 404)
        c = c[:, 0, :]  # Nx2
        # 平滑: 用 approxPolyDP 适度简化, 返回绝对坐标
        eps = 0.5
        ap = cv2.approxPolyDP(c, eps, True).reshape(-1, 2)
        pts = [[int(x0 + p[0]), int(y0 + p[1])] for p in ap]
        return self._send_json({"ok": True, "points": pts, "n": len(pts)})

    def _tplt_submit(self):
        """提交标注(画面尺寸 + 关注矩形 + 重点坐标集 + 每标注意图 + 本次标注id), 后端只记录坐标, 不直接存模板。"""
        data = self._read_json()
        try:
            w, h = int(data.get("w") or 0), int(data.get("h") or 0)
        except Exception:
            w = h = 0
        if w <= 0 or h <= 0:
            return self._send_json({"error": "缺少画面尺寸"}, 400)
        # W2-004: annotation_id 只保留安全字符, 防止 ../ 或绝对路径写出 annot_shots 之外。
        raw_id = str(data.get("annotation_id") or "")
        annotation_id = "".join(ch for ch in raw_id if ch.isalnum() or ch in "-_")[:80] or "ann"
        # 方案A: 附带原始截图, 保存到 data/annot_shots/{annotation_id}.png, 坐标与画面绑定
        shot_saved = ""
        shot = str(data.get("shot") or "")
        if shot and "," in shot and shot.startswith("data:image/"):
            try:
                import base64 as _b64
                b64 = shot.split(",", 1)[1]
                raw = _b64.b64decode(b64)
                shot_dir = BASE / "data" / "annot_shots"
                shot_dir.mkdir(parents=True, exist_ok=True)
                shot_name = annotation_id + ".png"
                (shot_dir / shot_name).write_bytes(raw)
                shot_saved = str(Path("data") / "annot_shots" / shot_name)
            except Exception as e:
                log_append(f"[tpltool] 保存标注截图失败: {e}")
        record = {
            "annotation_id": annotation_id,
            "ts": int(time.time()),
            "image_size": [w, h],
            "shot": shot_saved,
            "rects": data.get("rects") or [],
            "points": data.get("points") or [],
            "strokes": data.get("strokes") or [],
            # 每标注可含一条有序闭合轮廓 points 序列(绝对像素, 保留顺序), 供模型沿轮廓生成 mask 模板
            "contours": data.get("contours") or [],
            # 综合标注: 每项含 id/intent/rect+points(+points_rel)+contour(+contour_rel), 见 coord_note
            "annotations": data.get("annotations") or [],
            "coord_note": data.get("coord_note") or "",
            "meta": data.get("meta") or {},
        }
        try:
            with _ANNOT_LOCK:
                _ANNOT_FILE.parent.mkdir(parents=True, exist_ok=True)
                with _ANNOT_FILE.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            return self._send_json({"error": f"记录标注失败: {e}"}, 500)
        log_append(f"[tpltool] 接收标注 #{record['annotation_id']} "
                   f"矩形{len(record['rects'])}, 重点笔画{len(record['strokes'])}, 描边轮廓{len(record['contours'])}")
        return self._send_json({"ok": True, "annotation_id": record["annotation_id"]})
