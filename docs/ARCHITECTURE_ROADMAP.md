# FAA 架构演进与短期开发计划

> 2026-11-17 定稿。本文是长期架构方向与短期开发计划的权威参考；
> 与 `PROGRESS.md`（里程碑记录）、`docs/FLOWS.md`（功能流程）分工不同：
> 本文只回答“代码如何分层、依赖朝哪走、先做什么”。

## 一、问题定性

`webui.py` 的问题不是单文件行数，而是缺少分层：

| 问题 | 现状 | 后果 |
|---|---|---|
| 缺应用服务层 | `Handler` 直接操作 `ENGINE`、`_RUNNING`、`_LOGS`、fail_cache | HTTP 逻辑与业务编排纠缠，无法独立测试/复用 |
| 缺契约层 | API 字段散落在 `Handler`、`webui.html`、WPF `FaaProxy` | 多客户端靠人工对账，改一处漏两处 |
| 配置 schema 重复 | flow `if_config`、`config.example`、`_CONFIG_KEYS`、⚙ meta、WPF `SetConfigKeys` | 历史 `enable_mine` 漏白名单即此类问题 |
| 生命周期归属不清 | CLI 直连引擎；pywebview 进程内起服务；WPF spawn `webui.py` | 端口、单实例、优雅停服、日志归属各自实现 |
| 核心与业务耦合 | 业务模块拿整个 `eng`；`OCREngine` 为 Mixin 大对象；`pollin.py` 1499 行（Stage 5 已分包） | 难替换、难 mock、难分包 |
| 可观测性内嵌 | 日志缓冲、fail_cache、metrics 与 HTTP 混在 `webui.py` | CLI/原生壳无法复用 |
| 测试缺位 | 仓库内无 `tests/`，只有 `_coagent` 桩测 | 重构只能“拆一点跑一点” |

因此：**反对反复做文件级拆分；按“核心 → 应用服务 → 适配器 → 客户端”分层迁移。**

## 二、目标架构

```text
Clients: webui.html / pywebview / WPF / CLI
    │ 契约：HTTP JSON / SSE（或进程内调用）
Adapters: transport/http、cli、native shells
    │ 只做解析请求 → 调服务 → 序列化响应
Application Services:
    RunService / ConfigService / StatusService /
    LogService / FailCacheService / TemplateService
    │ 状态机、运行锁、编排、配置校验、事件流
Core:
    FlowEngine / Device / OCR / Locator /
    Business modules（plant / buy_seed / fairyland / pollin / community_like）/
    Metrics / Failures
    │
Platform: ADB/MuMu、文件、配置存储
```

四条硬规则：

1. Core 不 import 应用服务/适配器；业务模块逐步只依赖窄接口 `EnginePort`。
2. Application Services 不 import `http.server`，可在 CLI、原生壳、测试中复用。
3. Adapters 不含业务判断；`Handler` 只做路由、反序列化、调服务、序列化。
4. Clients 只依赖契约，不依赖 Python 内部模块。

### 契约三件套

- **API contract**：DTO、错误模型、SSE 事件类型；路径保持 `/api/*`，字段由 golden test 固化。
- **config schema**：key/type/default/validator/label/group 单源；WebUI/WPF/example/flow 由它生成或校验。
- **flow schema**：步骤类型、参数约束、required 语义。

## 三、短期开发计划（Stage 0-2）

### Stage 0：测试基线与契约清单（当前阶段）

目标：先把“现在是什么”固化，不改生产行为。

交付：

- `tests/`（stdlib `unittest`，无新依赖）：
  - 假引擎、纯函数测试、UI 原语、导航、配置键/路由静态契约、pollin 公共符号清单。
- `docs/API_CONTRACT.md`：
  - 全量 `/api/*` 端点、请求/响应主字段、错误形态、SSE 事件、页面路由；
  - 全局状态与生命周期路径（CLI / pywebview / WPF）。
- `tools/check_project.py`：
  - `tests` 纳入语法闸门；
  - 增加可选的测试执行入口（`--with-tests` 或独立命令）。

验收：

- `python -m unittest discover -s tests -v` 全绿，不联网、不连 ADB。
- `check_project.py` 全绿。
- 契约文档与现有 `Handler` 路由一一对应，允许字段标注“待 golden 固化”。

### Stage 1：提取应用服务（关键一步）

目标：把 `webui.py` 从“业务大文件”降为“HTTP 适配器”。

交付：

```text
app/
├── run_service.py       # run/stop/mode/run_daily、运行锁、状态机、事件发布
├── config_service.py    # schema、校验、apply、持久化、回显
├── status_service.py    # status 聚合
├── log_service.py       # 环形缓冲、落盘、增量拉取、SSE 发布
├── failcache_service.py
└── template_service.py
```

`Handler` 每个路由改为“解析 → 调服务 → 序列化”；不改变任何 URL/字段。

验收：

- API golden test 全绿；WPF/pywebview 实连冒烟；
- `webui.py` 行数自然下降；若 `Handler` 仍大，再按路由组拆 mixin（可选）。

### Stage 2：配置 schema 单源

目标：消除五处配置键重复。

交付：

- `config/schema.py`：唯一事实源；
- WebUI ⚙ meta、`config.example.json`、WPF `SetConfigKeys`、flow `if_config` 由 schema 生成或校验；
- `check_project` 增加“禁止手写配置键”的规则。

验收：

- 新增配置键只改一处；闸门能报出任意一侧缺口；
- 现有 18 个 flow 键零漂移。

## 四、中长期计划（Stage 3-5）

### Stage 3：核心端口化

- 定义 `EnginePort` Protocol（`screenshot/ocr_blocks/click_abs/locate/click_text/update_config/...`）。
- 业务模块类型标注改为 `EnginePort`，运行时不改，先获得可 mock 边界。
- 逐步拆 `OCREngine` Mixin 为 `device/ocr/locator/actions/flowexec`，每次只搬一个职责。

### Stage 4：客户端与生命周期统一

- 统一为“一个后台服务进程 + 多客户端”；
- 单实例锁、health/ready、端口探测、优雅停服收敛到服务层；
- WPF/pywebview 改为“连接已有服务 → 否则拉起 → 等待就绪 → 订阅事件”。

### Stage 5：`pollin.py` 分包

```text
pollin/
├── constants.py / primitives.py
├── popups.py / navigation.py
├── list_panel.py / collect.py
└── runner.py
```

依赖单向：`constants → primitives → navigation/list_panel → popups/collect → runner`；
`pollin.py` 保留为兼容 shim，`python pollin.py state|all` 仍可用。

## 五、与 P2 三任务的对应关系

| 原 P2 | 新定位 |
|---|---|
| P2-11 测试入仓 | Stage 0，必须先做 |
| P2-9 `webui.py` 拆分 | Stage 1 应用服务提取；文件拆分是结果，不是目标 |
| P2-10 `pollin.py` 分包 | Stage 5，独立推进，按 facade 分批 |

## 六、架构护栏

1. 不再向 `webui.py` 新增业务逻辑；新功能先加服务与契约测试。
2. 任何提取必须同时建立接口/契约，纯代码搬家不算完成。
3. 每次迁移一个批次，保持闸门/测试全绿，不与其它重构混批。
4. 文件名 `webui.py` 暂不改；内部演进为服务包，保留兼容入口。
5. 不以行数作为拆分依据；以职责、依赖方向和独立消费方为依据。

## 七、当前状态

- Stage 0 已完成：`tests/` 基线、`docs/API_CONTRACT.md` v0 清单；
  `check_project.py --with-tests` 已接入。
- Stage 1 已完成（2026-11-17）：`app/` 服务层已落地
  （engine/log/failcache/config/status/run），`webui.py` 降为 HTTP 适配器；
  38 个离线测试、API 契约冒烟、闸门全绿。
- Stage 2 已完成（2026-11-17）：`config/schema.py` 成为配置唯一事实源；
  `app/config_service.py` 只保留应用逻辑；`config.example` / flow `if_config` /
  WebUI ⚙ / WPF `SetConfigKeys` 全部对照 schema 校验。
- Stage 3 第一阶段已完成（2026-11-17）：`core/ports.py` 定义 EnginePort 及
  Ui/Template/Judge/Device/Config/Flow 子端口；plant/buy_seed/fairyland/pollin/
  community_like 的 `eng` 参数已标注；48 个离线测试兜底；运行时未改。
- Stage 3 第二阶段已完成（2026-11-17）：`OCREngine` 的 19 个 Mixin 收敛为
  Device/Ocr/Locator/Action/Flow 五个职责层；Handler 拆为
  `transport/http/` 的 base/router/pages/template/device/status/run/log mixin，
  `webui.py` 收薄为 31 行兼容入口；54 个离线测试、HTTP 冒烟、闸门全绿。
- Stage 4 已完成（2026-11-17）：`app/lifecycle_service.py` 收敛服务进程探测/拉起/
  就绪等待/优雅停/父进程看护；新增 `GET /api/health`、`GET /api/ready`；
  `webui_app.py` 改为拉起独立服务进程（壳不再 import webui、不持有引擎），
  WPF 探测改用 health；65 个离线测试、生命周期冒烟（拉起/复用/并发竞态/
  父进程退出/优雅停）全绿。
- Stage 5 已完成（2026-11-17）：`pollin.py` 1500 → **13 行** CLI shim，实现拆为
  `pollin/` 包（constants → primitives → popups → navigation → list_panel →
  collect → runner，依赖单向无循环）；facade 再导出全部旧公开符号，
  `import pollin` / `python pollin.py state|all` 零改动；68 个离线测试、
  闸门（语法 97/97）全绿。
- 架构路线 Stage 0-5 已全部完成；后续按新需求维护，遵守「四条硬规则 + 架构护栏」。
