# -*- coding: utf-8 -*-
"""HTTP 路由 mixin：device。"""
from __future__ import annotations

from .common import *  # noqa: F401,F403
class DeviceRoutes:
    def _connect(self):
        eng = get_engine()
        ok = eng.connect()
        # W1(2026-10-27): 连接结果写入运行日志(此前仅 HTTP 响应, 日志面板无连接记录,
        # 失败时用户在页面上只能看到按钮状态, 排障缺上下文)
        if ok:
            log_append(f"[连接] 手动连接成功 (引擎工作区 {eng.screen_w}x{eng.screen_h})")
        else:
            log_append("[连接] 手动连接失败 —— 请检查模拟器/ADB 地址(127.0.0.1:16384)后重试")
        return self._send_json({"ok": ok, **(_status() if ok else {})}, 200 if ok else 502)

    def _screen(self):
        """预览帧: 只做「JPEG 编码」, **不做 OCR**; 流程运行期直接复用引擎最近一帧, 不再自己截图。

        ⚠ 性能(2026-10-02): 原实现在这里每帧做一次**全屏 OCR** 并返回文字框,
          前端每 1.5s 拉一次 → 单轮 1183 次全屏 OCR, 是「跑一轮 CPU >50%」的主凶。
          文字框已拆到按需接口 GET /api/ocr。
        ⚠ 性能(2026-10-03): 运行期引擎本身在连续截图, 预览再各自 post_screencap 会与引擎
          争抢同一 ADB 控制器(拖慢引擎步骤)。改为: 引擎 2s 内截过帧 → 直接返回其 last_frame
          (只花 JPEG 编码, 不动 ADB); 超过 2s(空闲期)才自己截 —— 空闲期行为与原来一致。
        """
        eng = get_engine()
        if not is_connected(eng):
            return self._send_json({"error": "未连接", "status": _status()}, 503)
        img = getattr(eng, "last_frame", None)
        if img is None or (time.monotonic() - getattr(eng, "last_frame_ts", 0.0)) > 2.0:
            img = eng.screenshot()
        if img is None:
            return self._send_json({"error": "截图失败"}, 500)
        jpg = img_to_jpeg_b64(img)
        return self._send_json({
            "jpeg": jpg,
            "w": eng.screen_w, "h": eng.screen_h,
        })

    def _ocr(self):
        eng = get_engine()
        if not is_connected(eng):
            return self._send_json({"error": "未连接", "status": _status()}, 503)
        img = eng.screenshot()
        if img is None:
            return self._send_json({"error": "截图失败"}, 500)
        return self._send_json({"boxes": ocr_boxes(img)})

    def _click(self):
        eng = get_engine()
        if not is_connected(eng):
            return self._send_json({"error": "未连接"}, 503)
        data = self._read_json()
        if "rel" in data:
            rx, ry = data["rel"]
            eng.click_rel(rx, ry)
        elif "x" in data and "y" in data:
            eng.click_abs(int(data["x"]), int(data["y"]))
        else:
            return self._send_json({"error": "需要 {rel:[rx,ry]} 或 {x,y}"}, 400)
        return self._send_ok()

    def _failures(self):
        after = 0
        try:
            after = max(0, int(self._query("after") or 0))
        except (TypeError, ValueError):
            after = 0
        items, nxt = get_failures(after)
        return self._send_json({"items": items, "next": nxt})
