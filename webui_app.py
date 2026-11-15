"""
FlowerAutoAssistant - 原生窗口外壳（WebView2 / pywebview）
=======================================================
把现有的 Web UI 装进一个独立桌面窗口。webui.py / webui.html 的既有逻辑**一行不改**。

行为:
- 端口已有 FAA 实例在跑 -> 直接连上, 不再起第二个服务(避免端口冲突/重复进程)
- 端口空闲 -> 在本进程内起一个与 webui.py **完全相同**的 HTTP 服务
- 端口被别的程序占用 -> 明确提示后退出, 不静默失败
- 菜单「🌐 切回浏览器」-> 用系统默认浏览器打开同一地址(只开一次)
- 启动时**不**额外打开浏览器
- **下载桥(2026-11-09, zcode-20261109-15)**: WebView2 无下载管理器, 页面 `_downloadBlob` 的
  a.download 触发的下载会被静默丢弃 → 「保存日志」等导出功能失效。壳以 js_api 暴露 `save_file`,
  并在每次页面加载后注入 JS 覆盖 `_downloadBlob`: blob→base64→壳内**原生另存为对话框**(SAVE_DIALOG,
  失败兜底写 ~/Downloads)落盘。webui.html / webui.py **零改动**; 桥未就绪时回落原浏览器下载路径。

用法:
    python webui_app.py [--port 8765]
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).parent
DEFAULT_PORT = 8765
APP_TITLE = "FAA 小花仙挂机助手"

# 进程内状态: 是否自己托管服务 / 窗口对象 / 浏览器是否已打开(保证只开一次)
_STATE = {"owns_server": False, "server": None, "window": None,
          "browser_opened": False, "port": DEFAULT_PORT,
          "close_confirmed": False, "ask_in_progress": False}
_LOCK = threading.Lock()


def _url(port: int) -> str:
    return f"http://127.0.0.1:{port}/"


def _msgbox(title: str, text: str, icon: int = 0x40) -> None:
    """原生消息框(窗口尚未建立或建立失败时也能提示)。icon: 0x10=错误, 0x30=警告, 0x40=信息。"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, title, icon)
    except Exception:
        print(f"[FAA] {title}: {text}")


def _probe(port: int, timeout: float = 3.0) -> str:
    """探测端口归属: 'faa'=已有 FAA 实例 / 'other'=被别的程序占 / 'free'=空闲。"""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            pass
    except OSError:
        return "free"
    # 端口在监听: 用 /api/status 的独有字段判断是不是 FAA Web UI
    try:
        with urllib.request.urlopen(_url(port) + "api/status", timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if isinstance(data, dict) and "flow_dir" in data and "ui_build" in data:
            return "faa"
    except Exception:
        pass
    return "other"


def _start_server(port: int):
    """在本进程内复用 webui.py 的 Handler 起服务(等效于 python webui.py --port N)。

    只调用 webui 的既有函数, 不改其逻辑; 服务跑在 daemon 线程, 窗口关闭即随进程退出。
    """
    if str(BASE) not in sys.path:
        sys.path.insert(0, str(BASE))
    import webui  # 延迟导入: 只连现有实例时不必加载 OCR 相关依赖
    from http.server import ThreadingHTTPServer

    webui._log_reset_history()          # 与 webui.main() 同样从干净日志状态起步
    webui._set_running(False)
    srv = ThreadingHTTPServer(("127.0.0.1", port), webui.Handler)
    webui._SERVER = srv                 # 让页面「关闭服务」按钮照常生效
    threading.Thread(target=srv.serve_forever, daemon=True, name="faa-webui-http").start()
    webui.log_append(f"[webui] 服务启动 {time.strftime('%Y-%m-%d %H:%M:%S')} "
                     f"-> {_url(port)} (原生窗口外壳)\n")
    _STATE["owns_server"] = True
    _STATE["server"] = srv
    return srv


def _stop_server() -> None:
    """关窗口时把本进程托管的服务退干净(释放 8765, 不留孤儿监听)。"""
    srv, _STATE["server"] = _STATE["server"], None
    if srv is None:
        return
    try:
        srv.shutdown()      # 等 serve_forever 退出(轮询间隔 <1s)
    except Exception:
        pass
    try:
        srv.server_close()  # 关监听 socket, 端口立刻可复用
    except Exception:
        pass


class _Bridge:
    """暴露给页面 JS 的保存桥(js_api)。

    WebView2/pywebview 窗口没有浏览器下载管理器: webui.html `_downloadBlob` 的
    `a.download` 点击不会产生任何用户可见的下载 → 「保存日志」(服务端导出与页面快照
    两条路径都经它)在原生窗口里失效。此桥由注入 JS 把 blob 转 base64 后回传壳进程,
    壳用**原生另存为对话框**落盘; 对话框不可用时兜底写 ~/Downloads(重名自动加序号)。
    与服务归属无关(连已有实例模式同样可用); webui.html / webui.py 零改动。
    """

    def save_file(self, filename: str, data_b64: str) -> str:
        import base64
        # W2-004: 页面传入的文件名只取 basename, 并限制扩展名, 防止 ../ 或绝对路径写出下载目录。
        name = Path(str(filename or "")).name
        if not name or name in (".", ".."):
            name = "faa_download.txt"
        allowed = {".txt", ".log", ".json", ".csv", ".png", ".jpg", ".jpeg",
                   ".webp", ".html", ".md", ".zip"}
        if Path(name).suffix.lower() not in allowed:
            name += ".txt"
        try:
            data = base64.b64decode(data_b64)
        except Exception as e:
            print(f"[FAA] save_file: base64 解码失败: {e}")
            return "__error__"
        win = _STATE["window"]
        if win is not None:
            try:
                import webview
                r = win.create_file_dialog(webview.SAVE_DIALOG, save_filename=name)
                if r:
                    path = r if isinstance(r, str) else r[0]
                    Path(path).write_bytes(data)
                    return path
                return "__cancelled__"          # 用户在另存为框点了取消
            except Exception as e:
                print(f"[FAA] save_file: 原生另存为不可用({e}), 兜底写下载目录")
        try:
            dl = Path(os.path.expanduser("~")) / "Downloads"
            dl.mkdir(exist_ok=True)
            path = dl / name
            stem, suf, i = path.stem, path.suffix, 1
            while path.exists():
                path = dl / f"{stem}_{i}{suf}"
                i += 1
            path.write_bytes(data)
            return str(path)
        except Exception as e:
            print(f"[FAA] save_file: 兜底写入也失败: {e}")
            return "__error__"


_BRIDGE = _Bridge()


def _inject_download_bridge() -> None:
    """页面每次加载完成后注入下载桥(覆盖 _downloadBlob)。

    pywebview 每次导航(go_page / 页内跳转)都会重新触发 loaded, 新 document 里
    __FAA_DL_BRIDGE__ 标记已重置, 故每次都会重新覆盖 —— 幂等且覆盖切页场景。
    桥未就绪(pywebview.api 缺失)时回落原实现, 行为同浏览器。
    """
    win = _STATE["window"]
    if win is None:
        return
    js = r"""
(function(){
  if (window.__FAA_DL_BRIDGE__) return;
  if (typeof window._downloadBlob !== 'function') return;
  window.__FAA_DL_BRIDGE__ = true;
  const orig = window._downloadBlob;
  function toast(msg, ok){
    try{
      const t = document.createElement('div');
      t.textContent = msg;
      t.style.cssText = 'position:fixed;top:14px;right:14px;z-index:99999;max-width:46ch;'
        + 'padding:10px 14px;border-radius:8px;font-size:13px;line-height:1.5;'
        + 'box-shadow:0 4px 16px rgba(0,0,0,.25);'
        + (ok ? 'background:#2e7d32;color:#fff' : 'background:#c62828;color:#fff');
      document.body.appendChild(t);
      setTimeout(function(){ t.remove(); }, ok ? 4000 : 7000);
    }catch(e){}
  }
  window._downloadBlob = async function(blob, filename){
    try{
      const api = window.pywebview && window.pywebview.api;
      if(!(api && typeof api.save_file === 'function')){
        return orig.call(window, blob, filename);      // 桥未就绪 -> 原行为
      }
      const buf = new Uint8Array(await blob.arrayBuffer());
      let bin = '';
      const CH = 0x8000;
      for(let i = 0; i < buf.length; i += CH){
        bin += String.fromCharCode.apply(null, buf.subarray(i, i + CH));
      }
      const r = await api.save_file(filename, btoa(bin));
      if(r === '__cancelled__'){ toast('已取消保存'); return; }
      if(r === '__error__'){ toast('保存失败(壳侧写入错误), 请查看控制台', false); return; }
      toast('已保存: ' + r, true);
    }catch(e){
      toast('原生保存失败, 回退浏览器下载', false);
      try{ orig.call(window, blob, filename); }catch(e2){}
    }
  };
})();
"""
    try:
        win.evaluate_js(js)
    except Exception as e:
        print(f"[FAA] 注入下载桥失败: {e}")


def open_in_browser() -> bool:
    """用系统默认浏览器打开当前地址。同一进程内只开一次。"""
    with _LOCK:
        if _STATE["browser_opened"]:
            print("[FAA] 浏览器已打开过, 本次不再重复弹出")
            return False
        _STATE["browser_opened"] = True
    url = _url(_STATE["port"])
    try:
        os.startfile(url)               # Windows 默认浏览器
    except Exception:
        import webbrowser
        webbrowser.open(url)
    print(f"[FAA] 已用默认浏览器打开 {url}")
    return True


def go_page(path: str) -> None:
    """菜单里直接切页(主界面 / 模板标注工具), 与页内链接落到同一地址。"""
    win = _STATE["window"]
    if win is None:
        return
    try:
        win.load_url(_url(_STATE["port"]) + path.lstrip("/"))
    except Exception as e:
        print(f"[FAA] 切换页面失败: {e}")


def _exit_soon(delay: float = 0.4) -> None:
    """兜底退出。

    pywebview 6 + WebView2 在关窗时 FormClosing 虽然走完(服务已停), 但
    WinForms 消息循环可能不退出导致进程僵留。这里在短暂延时后硬退出,
    保证「关窗 = 进程结束」, 不留僵尸进程。
    """
    time.sleep(delay)
    os._exit(0)


def _page_confirm_enabled() -> bool:
    """读取 data/config.json 的 confirm_page_close, 与页面「关闭页面确认」保持同一口径。

    页面默认每次关闭都确认(默认 True); 用户在前端取消勾选后写回该键, 壳也跟随。
    读文件而不是起引擎, 避免为了一个开关在本进程里再建一份 OCREngine。
    """
    try:
        cfg = json.loads((BASE / "data" / "config.json").read_text(encoding="utf-8"))
        return bool(cfg.get("confirm_page_close", True))
    except Exception:
        return True


def _ask_close_dialog(text: str) -> bool:
    """原生「确定/取消」框(挂在主窗口上, 置顶), 返回 True = 确定关闭。"""
    try:
        import ctypes
        u = ctypes.windll.user32
        u.FindWindowW.restype = ctypes.c_void_p                 # 64 位句柄必须声明, 否则会被截断
        u.FindWindowW.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p)
        u.MessageBoxW.restype = ctypes.c_int
        u.MessageBoxW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint)
        hwnd = u.FindWindowW(None, APP_TITLE)                   # 以主窗为 owner, 保证显示在前
        rc = u.MessageBoxW(hwnd, text, APP_TITLE,
                           0x1 | 0x30 | 0x40000 | 0x10000)      # OKCANCEL|WARNING|TOPMOST|SETFOREGROUND
        return rc == 1                                          # 1 = IDOK
    except Exception:
        return True


def _finish_close() -> None:
    _stop_server()                  # 关闭窗口 = 服务一起退出, 不留孤儿端口
    threading.Thread(target=_exit_soon, daemon=True).start()


def _ask_then_close(text: str) -> None:
    ok = _ask_close_dialog(text)
    _STATE["ask_in_progress"] = False
    if ok:
        _STATE["close_confirmed"] = True
        _finish_close()


def _on_closing() -> bool:
    """关窗确认: 还原页面「每次关闭都确认」; 流程运行中始终确认(即使关了提醒)。

    注意: pywebview 的 closing 事件是「返回 False 才取消关闭」; 且不能在 FormClosing
    里直接弹模态框(WebView2 卸载流程会把 UI 线程占住)。所以先返回 False 拦下本次关闭,
    由后台线程弹框; 确认后硬退出, 取消则窗口原样保留。
    """
    if _STATE["close_confirmed"]:
        _finish_close()
        return True                 # 允许关闭

    running = False
    if _STATE["owns_server"]:
        try:
            import webui
            running = bool(webui._running())
        except Exception:
            running = False

    if not (running or _page_confirm_enabled()):
        _finish_close()
        return True                 # 无需确认, 允许关闭

    if _STATE["ask_in_progress"]:
        return False                # 已有确认框, 继续拦截, 不叠弹

    text = ("流程正在运行中, 关闭窗口将失去实时监控。" if running
            else "确定要关闭 FAA 窗口吗?")
    if _STATE["owns_server"]:
        text += "\n\n关闭窗口会同时停止本窗口托管的 Web 服务。"

    _STATE["ask_in_progress"] = True
    threading.Thread(target=_ask_then_close, args=(text,), daemon=True).start()
    return False                    # 取消本次关闭, 等对话框结果


def _boot_window(url: str) -> int:
    """建立原生窗口; 任何失败都降级为「提示 + 默认浏览器」, 绝不直接崩掉。"""
    try:
        import webview
        from webview.menu import Menu, MenuAction
    except Exception as e:
        return _fallback(url, f"pywebview 不可用: {e}")

    try:
        win = webview.create_window(
            APP_TITLE,
            url=url,
            width=1400, height=880, min_size=(1000, 640),
            js_api=_BRIDGE,
            menu=[Menu("界面", [
                MenuAction("🏠 主界面（使用 / 测试）", lambda: go_page("/")),
                MenuAction("🎯 模板标注工具", lambda: go_page("/tpltool")),
            ]), Menu("🌐 切回浏览器", [
                MenuAction("用默认浏览器打开当前地址", open_in_browser),
            ])],
        )
        _STATE["window"] = win
        win.events.closing += _on_closing
        win.events.loaded += lambda *a, **k: _inject_download_bridge()   # 每次导航完成都注入(幂等)
        webview.start()
        return 0
    except Exception as e:
        return _fallback(url, f"WebView2 窗口创建失败: {e}")


def _fallback(url: str, reason: str) -> int:
    """降级方案: 明确提示原因, 再用默认浏览器打开原页面。"""
    text = f"{reason}\n\n无法建立原生窗口, 将改用系统默认浏览器打开:\n{url}"
    if _STATE["owns_server"]:
        text += "\n\n注意: Web 服务由本进程托管, 关闭此控制台窗口会同时停止服务。"
    print("[FAA] " + text)
    _msgbox("FAA 原生窗口不可用", text, 0x30)
    if not _STATE["browser_opened"]:
        try:
            os.startfile(url)
        except Exception:
            import webbrowser
            webbrowser.open(url)
        _STATE["browser_opened"] = True
    if _STATE["owns_server"]:           # 托管服务时必须留在前台, 否则浏览器里的页面会失联
        print("[FAA] 服务运行中... 按 Ctrl+C 退出")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    return 1


def main() -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)   # 关窗是硬退出, 行缓冲保证控制台信息不丢
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="FAA 原生窗口外壳")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    port = args.port
    _STATE["port"] = port

    state = _probe(port)
    if state == "other":
        text = (f"端口 {port} 已被占用, 但未能识别为 FAA Web UI(可能正在启动, 或是别的程序)。\n\n"
                f"请稍后重试, 或先关闭占用该端口的程序; 也可用 --port 指定其它端口。")
        print("[FAA] " + text)
        _msgbox("FAA 原生窗口", text, 0x10)
        return 2
    if state == "free":
        try:
            _start_server(port)
        except OSError as e:
            text = f"无法在端口 {port} 启动 Web 服务: {e}"
            print("[FAA] " + text)
            _msgbox("FAA 原生窗口", text, 0x10)
            return 3
        print(f"[FAA] 未发现运行中的实例, 已在端口 {port} 启动服务")
    else:
        print(f"[FAA] 已连接现有实例 {_url(port)}, 不重复起服务")

    try:
        return _boot_window(_url(port))
    finally:
        _stop_server()              # 任何退出路径都不留监听端口


if __name__ == "__main__":
    raise SystemExit(main())
