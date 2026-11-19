using FAA.WpfGui.Models;

namespace FAA.WpfGui.Services;

/// <summary>
/// 三页共享的应用会话状态(组合根的一部分, 由 MainViewModel 驱动更新):
///   Proxy —— 服务就绪(faa 连上 / free 自起成功)后赋值; 之前为 null, 各页轮询一律先判空跳过。
///   Host  —— FaaProcessHost: 三态探测后 free 时由它 spawn venv python webui.py(契约5)。
///   Logs  —— 运行日志增量缓冲(LogStore), 游标语义与 /api/log 一致(契约4)。
///   LastStatus —— 最近一次 /api/status 快照(状态轮询 1.5s, 对齐 webui.html autoTimer 1500ms)。
/// </summary>
public sealed class AppSession
{
    /// <summary>服务端口(缺省 8765 与 webui_app.py DEFAULT_PORT 一致; 启动参数 --port 可改, 供联调用)。</summary>
    public int Port { get; set; } = 8765;

    /// <summary>
    /// API base url 覆盖(批 21 启动参数 --api-base &lt;url&gt;): 给定时跳过三态探测/服务托管, 直连该地址
    /// (调试/连 Mock 用); 与 --page/--port 共存(此模式下 --port 仅存档不参与连接)。null=按缺省三态流程。
    /// </summary>
    public string? ApiBaseOverride { get; set; }

    public FaaProcessHost Host { get; } = new();

    public LogStore Logs { get; } = new();

    /// <summary>服务代理; 服务就绪前为 null。</summary>
    public FaaProxy? Proxy { get; set; }

    /// <summary>当前服务是否由本窗口托管(free 自起); faa 连上现有实例时为 false —— 关窗不停服务。</summary>
    public bool OwnsService { get; set; }

    /// <summary>最近一次 /api/status 快照; 尚未轮询到时为 null。</summary>
    public StatusSnapshot? LastStatus { get; set; }

    /// <summary>流程是否在跑(以最近快照为准; 无快照=false)。</summary>
    public bool IsRunning => LastStatus?.Running ?? false;

    /// <summary>运行中模块 id(引擎 run_daily 维护; 无= null)。</summary>
    public string? RunningModule => LastStatus?.CurrentModule;

    /// <summary>
    /// 关窗确认开关(confirm_page_close)。缺省 true: webui.html:657 同款初始值,
    /// 首次 /api/status 到达前按"需要确认"处理 —— 宁多确认, 不静默关窗。
    /// </summary>
    public bool ConfirmPageClose { get; set; } = true;

    /// <summary>
    /// 最小化时自动收进托盘(minimize_to_tray)。缺省 false: 最小化保留在任务栏,
    /// 仅在设置页手动开启后才隐藏到托盘(托盘图标不可用时仍保留在任务栏)。
    /// </summary>
    public bool MinimizeToTray { get; set; }

    /// <summary>强制允许关窗(启动失败报错退出路径置位, 绕过契约2确认, 对齐 webui_app.py 报错即退)。</summary>
    public bool ForceClose { get; set; }
}
