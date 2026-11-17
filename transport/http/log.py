# -*- coding: utf-8 -*-
"""HTTP 路由 mixin：log。"""
from __future__ import annotations

from .common import *  # noqa: F401,F403
class LogRoutes:
    def _log(self):
        after = max(0, int(self._query("after") or 0))
        end, lines = log_service.get_since(after)
        return self._send_json({"next": end, "lines": lines})

    def _log_download(self):
        """把服务端日志缓冲**全量**导出为 .txt 下载。

        注意: 导出的是服务端缓冲的全部内容(含页面打开之前、**本次会话内**的历史),
        不只是前端 DOM 里已收到的那部分; 因此刷新页面后依然能拿到完整日志。
        服务每次启动都会清空缓冲(_log_reset_history), 故不包含上一次会话的日志 (2026-10-01)。
        """
        lines = log_service.snapshot()
        text = "".join(lines)
        ts = time.strftime("%Y%m%d_%H%M%S")
        # 里程碑 94: 归档本次会话的截图(复制) + manifest, 并把契约写进日志头段
        arc = _fail_cache_archive(ts)
        stat = _fail_cache_stat()
        head = (f"# FlowerAutoAssistant 运行日志\n"
                f"# 导出时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                # _LOGS 存的是 _TeeOut.write() 的写入分片(print 的正文与换行是两次 write),
                # len(_LOGS) 是分片数 ≠ 行数(实测 2113 分片只对应 1202 行), 必须按实际换行数统计。
                f"# 总行数: {text.count(chr(10))}\n"
                f"# 归档目录: data/fail_archives/{ts}\n"
                f"# 归档截图: {arc['count']} 张 / {arc['bytes']/1048576:.2f} MB"
                f" (覆盖 {arc['sessions']} 个会话; 其中本次会话 {arc['session_files']} 张)\n"
                f"# 截图清单: data/fail_archives/{ts}/manifest.txt (文件名 ↔ 中文tag ↔ 时刻)\n"
                f"# 对应关系: 正文 [故障存证] 行末已自带文件名; 若该文件被缓存清理(像素已删), 其\n"
                f"#           存证记录(时间/tag/全量OCR文本)永久保留在 data/fail_cache/index.jsonl\n"
                + "-" * 40 + "\n")
        # 前缀 \ufeff(BOM) 让 Windows 记事本按 UTF-8 打开, 避免中文乱码
        body = ("\ufeff" + head + text).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Disposition",
                         f'attachment; filename="faa_log_{ts}.txt"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream(self):
        """GET /api/stream —— SSE 推送通道(纯新增; 浏览器轮询回退通道不变)。

        事件契约:
        - event: log      内部 _LOGS 游标增量: 0.8s 轮询内部缓冲, 有新分片才推;
                          data = {"next": int, "lines": [str,...]}(与 GET /api/log 同形)。
                          游标从 0 起步(连上即回放本次会话已有分片, 与 /api/log?after=0 同语义);
                          以「已消费末分片指纹」检测缓冲被整体替换(log_clear, 替换后缓冲=[标记行])
                          → 游标归零重放, 保证清除后的日志仍推得出去。
        - event: status   1.5s 检测 /api/status 载荷变化, 变更才推(载荷与 GET /api/status 同形);
                          连接建立后立即推一次首帧状态, 之后仅在实际变化时推送。
        - event: failures 失败游标增量(0.8s; data 与 GET /api/failures 同形 {items,next});
                          仅新增失败才推。
        - event: frame    仅 ?frames=1 时附带: 引擎 last_frame 指纹(hashlib.blake2b)变化才
                          编码 jpeg b64 推送(data 与 GET /api/screen 同形 {jpeg,w,h})。
                          ⚠ 绝不主动 ADB 截帧(不调 eng.screenshot, 只读引擎已有的 last_frame);
                          空闲期引擎不产新帧 → 指纹不变 → 无新帧就不推。
        - 心跳            每 15s 一条 ": ping" 注释行保活。
        - 断开             写失败(BrokenPipeError/ConnectionResetError 等)→ 线程干净退出,
                          无孤儿循环; 本端点不落任何盘、不改任何状态。
        """
        import hashlib   # 局部导入: 对既有 import 块零改动
        frames = (self._query("frames") == "1")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        log_cur = 0          # _LOGS 游标(0=回放已有分片)
        last_chunk = ""      # 已消费末分片指纹: 缓冲被整体替换(log_clear)时据此归零重放
        fail_cur = 0         # 失败游标(0=回放既有失败, 与前端 failSeen 初值一致)
        last_status = None   # 上次推送的 status 载荷指纹
        last_frame_sig = None
        t_log = t_fail = t_status = t_frame = 0.0
        t_beat = time.monotonic()
        while True:
            now = time.monotonic()
            if now - t_log >= 0.8:
                t_log = now
                log_cur, new, last_chunk = log_service.read_increment(last_chunk, log_cur)
                if new and not self._sse_send("log", {"next": log_cur, "lines": new}):
                    return
            if now - t_fail >= 0.8:
                t_fail = now
                try:
                    items, nxt = get_failures(fail_cur)
                except Exception:
                    items, nxt = [], fail_cur
                if items and not self._sse_send("failures", {"items": items, "next": nxt}):
                    return
                if nxt > fail_cur:
                    fail_cur = nxt
            if now - t_status >= 1.5:
                t_status = now
                try:
                    payload = _status()
                except Exception:
                    payload = None
                if payload is not None:
                    fp = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                    if fp != last_status:
                        if not self._sse_send("status", payload):
                            return
                        last_status = fp
            if frames and now - t_frame >= 1.5:
                t_frame = now
                eng = engine_service.peek_engine()  # 只读既有单例: 不误建引擎
                img = getattr(eng, "last_frame", None) if eng is not None else None
                if img is not None:
                    sig = hashlib.blake2b(img.tobytes(), digest_size=16).hexdigest()
                    if sig != last_frame_sig:
                        last_frame_sig = sig
                        if not self._sse_send("frame", {"jpeg": img_to_jpeg_b64(img),
                                                        "w": getattr(eng, "screen_w", 0),
                                                        "h": getattr(eng, "screen_h", 0)}):
                            return
            if now - t_beat >= 15.0:
                t_beat = now
                if not self._sse_send("", None):
                    return
            time.sleep(0.2)

    def _log_clear(self):
        """清空服务端日志缓冲 + 磁盘备份, 让页面从干净状态重看一轮日志。

        与启动时的 `_log_reset_history` 同语义(内存与磁盘一并清), 这里复用同一函数。
        与「保存日志」配对: 只清前端 DOM 会变成"页面空的、导出却还是旧的"(导出读的是服务端缓冲),
        只清服务端又会让下次增量拉取从新缓冲中部开始 —— 故三者必须一起动, 且**回 next=0**,
        前端收到后必须把 logCursor 复位(见 webui.html clearLog)。
        清完补一条标记日志, 让"清理确实生效、何时清理"可被验证(否则清空后页面一片空白, 无从判断)。

        ⚠ 里程碑 94(用户裁决): 本按钮**同时清理截图缓存像素**(日志没了, 截图自然也不需要);
        index.jsonl 元数据墓碑**保留**(记录不死), 被清图标注 evicted。清理行由 _fail_cache_clean 落到日志。
        """
        _log_reset_history()
        log_append(f"[webui] 运行日志已被手动清除 {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        _fail_cache_clean("all")   # 同时清缓存像素(本次会话目录同样清理 —— 用户明确要求"没有日志就不需要截图")
        return self._send_json({"ok": True, "next": 0})
