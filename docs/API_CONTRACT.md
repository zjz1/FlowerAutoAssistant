# FAA 服务 API 契约清单（Stage 0 基线）

> 2026-11-17 建立。当前为 **v0 清单**：把 `webui.py` 现有 HTTP/SSE 面完整盘出，
> 作为 Stage 1 提取应用服务、后续 golden test 的对照基线。
> 原则：**本文件只描述现状，不定义新行为**；任何字段变更必须先改本文件与测试。
>
> 服务本质：本地 HTTP 服务，不是“网页专属后端”。浏览器 / pywebview / WPF
> 都是它的客户端；CLI `main.py` 直连引擎，不走 HTTP。

## 1. 通用约定

| 项 | 约定 |
|---|---|
| 默认地址 | `http://127.0.0.1:8765` |
| 内容类型 | JSON 响应 `application/json`；页面 HTML；SSE `text/event-stream` |
| 认证 | 无（仅绑定本机回环） |
| 成功 | 绝大多数为 `{"ok": true}` 或业务对象 |
| 失败 | `{"error": "..."}` + 4xx/5xx；未连接常带 `"status": {...}` |
| 运行互斥 | 已有流程运行时，新运行请求返回 `409` |
| 未连接 | 需要设备的接口返回 `503` |
| 连接失败 | `/api/connect` 返回 `502` |

## 2. 页面路由

| 方法 | 路径 | 响应 | 说明 |
|---|---|---|---|
| GET | `/` | `text/html` | 注入 `__UI_BUILD__` 版本戳；页面缺失 500 |
| GET | `/tpltool` | `text/html` | 模板标注工具页；页面缺失 500 |

## 2.1 服务健康与就绪（Stage 4）

### GET `/api/health`

客户端（pywebview / WPF / 脚本）探测“端口上是不是 FAA 服务”的唯一握手点；
`app/lifecycle_service.probe` 以 `service == "faa"` 判定端口归属。

```json
{"service": "faa", "ok": true, "pid": 1234, "port": 8765,
 "uptime_s": 12.3, "running": false, "engine_loaded": false}
```

- 绝不创建引擎：`engine_loaded` 只反映当前是否已懒加载；
- `running` 供壳在关窗时判断“流程运行中”；
- health 不可达时，探测回退 `/api/status` 的 `flow_dir`+`ui_build` 两键（兼容旧实例）。

### GET `/api/ready`

```json
{"ready": true, "connected": false, "engine_loaded": false, "running": false}
```

`ready=true` 表示 HTTP 服务已可接收请求；`connected` / `engine_loaded` 仅信息性
（引擎按需加载，连接设备是客户端动作，不代表服务未就绪）。

## 3. 状态与配置

### GET `/api/status`

返回服务/引擎状态：

```json
{
  "connected": true,
  "screen": [1920, 1080],
  "work": [1280, 720],
  "flow_dir": ".../flows",
  "debug_click": false,
  "running": false,
  "current_module": null,
  "confirm_page_close": true,
  "ui_build": "...",
  "fail_cache": {
    "mb": 0.0, "count": 0, "sessions": 0, "oldest": null,
    "threshold_mb": 100, "exceed": false, "prompt": false,
    "archived": null
  }
}
```

### GET `/api/flows`

```json
{"flows": [{"name": "...", "file": "...", "description": "...", "modules": []}]}
```

### GET `/api/kb`

返回知识库（点击日志 / 关闭按钮）内容；字段以当前 `_kb()` 为准。

### GET `/api/daily`

```json
{
  "name": "每日挂机编排",
  "modules": [
    {"id": "startup", "flow": "...", "name": "开始启动",
     "required": false,
     "settings": [{"key": "...", "type": "switch|text",
                   "label": "...", "desc": "...", "value": true}]}
  ],
  "log_click_pos": false,
  "use_cache_pos": false,
  "ocr_threads": 2,
  "ocr_execution_provider": "cpu",
  "use_angle_cls": true,
  "plant_rare_confirm": true,
  "plant_harvest_allowed": ["白色桃花", "粉色桃花"],
  "plant_seed_name": "白色桃花",
  "plant_seed_rare": false
}
```

`plant_harvest_allowed` 仅由 WPF 种植模块面板编辑；无 `meta`，不进 WebUI ⚙ 面板。

### GET `/api/plant_presets`

返回 `data/plant_presets.json` 的种子库（花名 → 颜色 → 种子全称 / 稀有标记 / 肥力消耗）。

### POST `/api/set_config`

请求：配置键值对象（只处理 `_CONFIG_KEYS` 白名单内键）。

```json
{"plant_flower": true, "plant_flower_type": "白色桃花", "ocr_threads": 2}
```

响应：配置回显（`_config_echo`）；非法 enum/值返回 `400`，已应用键保持已应用。
bool 键仅接受 JSON 布尔值 `true/false`（字符串 `"false"` 也返回 `400`）。

> Stage 2（2026-11-17）：配置键的唯一事实源是 `config/schema.py`。
> `app/config_service.py` 只保留校验/日志/回显逻辑；示例配置、flow `if_config`、
> WebUI ⚙、WPF `SetConfigKeys` 均由 schema 校验。
> 可用 `python -m config.schema --check` 单独校验示例配置。

## 4. 运行控制

### POST `/api/connect`

请求：空对象。响应 `200`：`{"ok": true, ...status}`；失败 `502`：`{"ok": false}`。

### POST `/api/set_mode`

请求：`{"mode": "use" | "test"}`。响应：`{"ok": true}`。

### POST `/api/click`

请求二选一：

```json
{"rel": [0.5, 0.5]}
{"x": 960, "y": 540}
```

响应：`{"ok": true}`；未连接 `503`；参数缺失 `400`。

### POST `/api/run`

请求：`{"flow": "<flow 文件名或流程名>", "mode": "use" | "test"}`。
响应：`{"ok": true, "started": "<name>"}`；未找到 `400`；已有运行 `409`。

### POST `/api/run_daily`

请求：

```json
{"selected": ["startup", "plant"], "mode": "use", "finish_action": "none"}
```

`finish_action` 仅接受 `none` / `close_client`，其它值 `400`。
响应：`{"ok": true, "started": "<name>", "count": N}`；
未勾选 `400`；`daily.json` 缺失/解析失败 `500`；已有运行 `409`。

### POST `/api/preflight`

请求：`{"modules": ["startup", "plant"]}`（未知模块 `400`）。

```json
{"enabled": ["开始启动", "..."], "disabled": ["..."],
 "risks": ["..."], "text": "本次运行时开启了以下功能：\n..."}
```

`text` 由后端拼好，WPF 统一确认框只负责展示；取消则不启动。

### POST `/api/stop`

响应：`{"ok": true, "message": "已请求停止当前流程"}`。

### POST `/api/shutdown`

响应：`{"ok": true, "message": "服务已关闭"}`，随后停服务。

## 5. 日志与事件流

### GET `/api/log?after=N`

```json
{"next": 123, "lines": ["...", "..."]}
```

`next` 为全局游标；`after` 为负数按 0 处理；游标落后于已丢弃头部时从现存最早续读。

### GET `/api/log_download`

返回 `text/plain` 附件；导出本次会话全量日志，并归档 fail_cache 截图 + manifest。

### POST `/api/log_clear`

响应：`{"ok": true, "next": 0}`。

### GET `/api/stream?frames=0|1`（SSE）

| event | 频率 | data |
|---|---|---|
| `log` | 0.8s，有增量才推 | `{"next": N, "lines": [...]}` |
| `status` | 1.5s，变化才推；连上先推首帧 | 与 `GET /api/status` 同形 |
| `failures` | 0.8s，有新增才推 | `{"items": [...], "next": N}` |
| `frame` | 仅 `frames=1`；引擎 last_frame 指纹变化才推 | `{"jpeg": "...", "w": W, "h": H}` |
| 心跳 | 每 15s | 注释行 `: ping` |

## 6. 失败清单与截图缓存

### GET `/api/failures?after=N`

```json
{"items": [...], "next": N}
```

### POST `/api/failures_clear`

响应：`{"ok": true}`。

### GET `/api/fail_cache_info`

```json
{"mb": 0.0, "count": 0, "sessions": 0, "oldest": null,
 "threshold_mb": 100, "exceed": false, "files": ["..."]}
```

### POST `/api/fail_cache_clean`

请求：`{"mode": "all" | "<其它模式>", "days": 7}`（可选）。
响应：`{"ok": true, ...清理统计}`。

### POST `/api/fail_cache_open`

响应：`{"ok": true, "dir": "..."}`；打开失败 `500`。

## 7. 画面与 OCR

### GET `/api/screen`

```json
{"jpeg": "<base64>", "w": 1920, "h": 1080}
```

未连接 `503`；截图失败 `500`。运行期优先复用引擎 `last_frame`，空闲期才自行截图。

### GET `/api/ocr`

```json
{"boxes": [{"text": "...", "score": 0.98,
            "rel": [0.5, 0.5], "box": [0.4, 0.4, 0.6, 0.6]}]}
```

未连接 `503`；截图失败 `500`。

## 8. 模板标注工具

| 方法 | 路径 | 请求 | 成功响应 |
|---|---|---|---|
| GET | `/api/tplt_init` | — | `{jpeg,w,h}`；未连接 503；截图失败 500 |
| POST | `/api/tplt_load` | `{file?}` | `{jpeg,w,h,loaded}`；文件不存在/越界/读图失败 400 |
| POST | `/api/tplt_contour` | `{...}` | `{ok,points,n}`；矩形过小 400；未连接 503 |
| POST | `/api/tplt_submit` | `{...}` | `{ok,annotation_id}`；缺尺寸 400；记录失败 500 |

## 9. 全局状态清单（Stage 1 已迁移）

> 2026-11-17 Stage 1：模块级状态已迁到 `app/` 服务层；`webui.py` 只保留
> `_SERVER`、`_POST_ROUTES` 与 HTTP Handler。

| 状态 | 现位置 | 归属 |
|---|---|---|
| `ENGINE` / `ENGINE_LOCK` | `app/engine_service.py` | 引擎单例 / `get_engine` / `peek_engine` |
| `_RUNNING` / `_LOCK` | `app/run_service.py` | 运行状态与互斥门 |
| `LOGS` / `LOG_LOCK` / `LOG_BASE` | `app/log_service.py` | 日志环形缓冲与游标 |
| `FAIL_CACHE_*` / `_CACHE_PROMPT_PENDING` / `LAST_ARCHIVE` | `app/failcache_service.py` | 截图缓存统计/清理/归档 |
| `_CONFIG_KEYS` / `_MODULE_SETTINGS` | `app/config_service.py` | 配置元数据与回显 |
| `_status` / `_ui_build` | `app/status_service.py` | 状态聚合 |
| 服务进程生命周期 | `app/lifecycle_service.py` | 探测/拉起/就绪等待/优雅停/父进程看护（Stage 4） |
| `_SERVER` / `_POST_ROUTES` | `transport/http/common.py` | HTTP 适配器自身 |
| Handler 路由 | `transport/http/*.py` | base/router/pages/template/device/status/run/log mixin |

> Stage 3 第二阶段（2026-11-17）：`webui.py` 已收薄为 31 行兼容入口；
> Handler 由 `transport/http/handler.py` 组合各路由 mixin，API 路径/字段不变。

## 10. 生命周期与客户端（Stage 4 统一）

口径：**一个后台服务进程 + 多客户端**；服务实例由端口绑定保证唯一。

| 客户端 | 启动方式 | 与服务关系 |
|---|---|---|
| 浏览器 | 直接访问 `http://127.0.0.1:8765/` | 纯 HTTP/SSE |
| pywebview (`webui_app.py`) | 端口空闲则 `lifecycle.ensure_service` 拉起独立进程 `webui.py --port N --parent-pid 壳PID`；已有实例则直连 | 壳只做 HTTP 客户端，不 import webui / 不持有引擎；关窗只停自己拉起的服务 |
| WPF (`FAA.WpfGui`) | `FaaProcessHost.StartAsync` spawn 同一命令（带 `--parent-pid`） | 同左；`ProbeService` 以 `/api/health` 握手 |
| CLI (`main.py`) | 直连引擎 | 不走 HTTP |

服务端 `--parent-pid P`：父进程退出（含被强杀）时服务自动 `shutdown`，
不留孤儿监听端口；端口被占时服务以退出码 2 结束，客户端应先 probe 复用。
并发拉起竞态由 `ensure_service` 收口：抢先绑定者胜出，落败方重探后按“复用已有实例”处理。

客户端接入顺序：探测（faa/other/free）→ free 则拉起 → 等 `/api/health` 就绪 → 订阅 `/api/stream`。

## 11. 待办（Stage 0 后续批次）

- 用 golden test 固化每个端点的字段集合与错误码；
- 把本清单拆成机器可读的 `contracts.py`（DTO/TypedDict）；
- 补充 SSE 事件时序测试；
- 在 `check_project --with-tests` 中运行契约测试。
