"""OCR 识别服务（单例复用版）。

设计目标：
- 模型只加载一次（模块级单例），避免每次调用重复初始化、重复触发权限。
- 提供函数式 API：`ocr_image(path_or_ndarray) -> list[OCRResult]`
- 提供 CLI 模式：`python ocr_ui.py <截图.png>` 打印文字+坐标（兼容旧用法）
- 提供常驻服务模式：`python ocr_ui.py --serve`，从 stdin 逐行读图片路径，返回 JSON，
  引擎只初始化一次，适合被主程序以子进程方式反复调用。

OCRResult 结构: {"text": str, "center": [cx, cy], "box": [x1,y1,x2,y2], "score": float}
坐标基准: 输入图片像素坐标（尺寸以实际输入图为准, 不假定固定分辨率）。
"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

import numpy as np

# ---------- 单例引擎 ----------
_engine = None
_engine_region = None   # 裁片专用实例(小 det limit, zcode-20261031-13; 由配置闸门 det_region_limit 启用)
_engine_mixed = None    # OCR4(batch-09): 混合路由 split/refine 腿 P2C 自适应实例(det 8192/max;
                        # 由灰度键 mixed_route.enabled 启用, 默认 false = 本实例永不构建)
# Q02(batch-05, 2026-11-14): 单例 check-and-init 原先无锁 —— 运行线程(_timed_ocr→ocr_image)
# 与 HTTP 线程(webui /api/ocr)首触并发时存在双模型加载窗口(三会话×2, 数十 MB + 首次 OCR
# 1-3s 延迟×2)。同库对照: webui ENGINE_LOCK(webui.py:31)、引擎 _FAIL_LOCK(_failures.py:17)
# 齐全, 唯 OCR 底层漏(08 笔记)。加锁不改单线程行为(快路径无锁读)。
_ENGINE_LOCK = threading.Lock()
_session_options_patched = False   # Q02: SessionOptions 全局补丁幂等 guard(只做一次)

# RapidOCR 1.2.3 未暴露 ONNX 会话线程数配置(OrtInferSession 内部自建 SessionOptions,
# 默认吃满全部物理核: 720p 全屏 OCR 实测瞬时占用 ~13 核、CPU 时间 ~5.3s/次,
# 是「跑一轮 CPU >50%」的主力)。这里把每个会话的 intra_op 线程压到 2:
# 实测识别结果与默认**完全一致**(同批实机截图文字块零差异), 单次 CPU 时间 ~1.0s(-81%), 耗时仅 +11%。
# 可用环境变量 FAA_OCR_THREADS 或 data/config.json 的 ocr_threads 调整; 0 = 不限制(旧行为)。
_thread_limit = int(os.environ.get("FAA_OCR_THREADS", "2") or 0)


def set_thread_limit(n) -> None:
    """设置 RapidOCR 每会话 intra_op 线程数(0=不限制, 用系统默认)。须在首次 OCR 前调用。"""
    global _thread_limit
    _thread_limit = int(n or 0)


def _apply_session_options_patch() -> None:
    """Q02(batch-05): SessionOptions 全局 monkeypatch 模块级单次化。

    原先 get_engine()/get_engine_region() 各自内嵌一份补丁(两次全局写, 且 region 档
    会把 get_engine 已补丁的函数再包一层 —— 等值幂等但结构混乱); 现移到模块级只做
    一次(幂等 guard), 两 getter 共用。补丁闭包**动态读** _thread_limit(原版在打补丁时
    捕获定值), 与既有调用序对齐: OCREngine.__init__ 先 set_thread_limit(配置 ocr_threads)
    再首次 OCR → 会话仍按最终值创建; _thread_limit<=0 时原样返回缺省 SessionOptions
    (=「0 不限制」旧语义, 此时旧版不打补丁, 两者对会话参数的效果逐字节一致)。
    时序约束与旧版相同: 须在首次 get_engine()/get_engine_region() 前完成 set_thread_limit。
    """
    global _session_options_patched
    if _session_options_patched:
        return
    import rapidocr_onnxruntime.utils as _ru
    _orig_so = _ru.SessionOptions

    def _limited_session_options():
        so = _orig_so()
        if _thread_limit > 0:
            so.intra_op_num_threads = _thread_limit
            so.inter_op_num_threads = 1
        return so

    # det/cls/rec 三个 ONNX 会话都由此创建(utils.OrtInferSession 在调用时才解析该名字)
    _ru.SessionOptions = _limited_session_options
    _session_options_patched = True


# ---------- OCR3(batch-08, 2026-11-14): 执行后端三档开关 (ocr_execution_provider) ----------
# 用户形态要求(HANDOFF.md:412-413): 做成开关 + 核显/集显兼容 —— ocr_execution_provider
# ∈ {cpu, dml, cuda}, **默认 cpu**(默认关灰度铁律; cpu 档 = 改动前行为逐字节一致)。
# 三档语义(裁定四, 评估报告 §2):
#   cpu  默认安全档: RapidOCR 默认 use_cuda=false, 构建体即本文件原有调用零改动。
#   cuda 唯一有实锤的 GPU 档(=P2E 实验链): 与基线 5014 裁片逐块 text+box 0 diff、
#        region 3.105×、L6 三遍 l6_bad=[](MIXED_ROUTE.md §0/§1)。集成条件
#        (DECISION.md §4.1)全部随行: 独立 venv 自举(onnxruntime-gpu 1.31.1 +
#        cudnn 9.28.1.4, 缺位如实 WARN 不静默)、**TF32 必须显式关**(否则 17 裁片稳定把
#        「超过-」读成「超过」, probe_tf32.py)且构建后断言、cls 留 CPU(-21%)、
#        CUDA session 建不起来自动回退 cpu 档(拔卡场景)。
#   dml  推荐档形态位(DML 兼容任意 DX12 GPU 含核显、免 CUDA venv): rapidocr 1.2.3 无
#        DML 原生路径(utils.OrtInferSession 只构造 CUDAExecutionProvider)→ **自管
#        session**(InferenceSession 包装: det/rec 强制 DmlExecutionProvider, cls 留 CPU)。
#        「推荐档」地位须以 dml 档 0-diff A/B 数据兑现(数据落盘 → batch-12 判定;
#        过不了 0-diff 门则推荐档=cuda), 不凭形态授予(裁定四)。
# 配置面: data/config.json 键 ocr_execution_provider(缺省/非法值一律按 cpu, 非法值如实
#         WARN 不静默); env FAA_OCR_EXECUTION_PROVIDER 可临时覆盖(优先级最高, 单机实验用);
#         GPU 独立 venv 路径 env FAA_OCR_CUDA_VENV / FAA_OCR_DML_VENV 可重指(缺省探测
#         <项目根>/_lab/ocr/prototypes/{P2E|OCR3_DML}/venv)。
# 时序: 与 ocr_threads 同口径 —— 单例在首次 get_engine() 时按当时档位一次性构建,
#       **改后重启生效**(webui 常驻单例 ⇒ 重启 webui; CLI 每次进程即新构建)。
# 注(OCR4/batch-09 更新): get_engine_region()(32/min 裁片专用实例)仍不随档位、CPU 构建
#     (32/min 是 OCR5 双闸门实验实例, 与 P2E GPU det736 是两回事); batch-08 预留的
#     「region 路径 GPU 接线」已由 OCR4 混合路由批按 kind 落地 —— 引擎 _timed_ocr 的
#     kind=="region" 腿在灰度键 mixed_route.enabled 开启时改用 get_engine()(本文件
#     batch-08 档位实例, cuda/dml=P2E GPU 与基线 0 diff), get_engine_region 通道不变。
_EXEC_PROVIDERS = ("cpu", "dml", "cuda")
_execution_provider: str | None = None  # None=未定(首次 get_engine 按解析链定档); 显式 set 后以此为准
_gpu_fallback_reason: str | None = None  # GPU 档构建失败自动回退 cpu 的原因(如实留档, 不静默)
_last_tf32_records: list = []            # 最近一次 cuda 构建的 (模型名, use_tf32) 断言记录(可观测)


def set_execution_provider(v) -> None:
    """显式设置执行后端档位(cpu/dml/cuda)。须在首次 get_engine() 前调用; 改后重启生效。"""
    global _execution_provider
    s = str(v or "").strip().lower()
    if s not in _EXEC_PROVIDERS:
        print(f"[OCR-GPU] ocr_execution_provider 非法值 {v!r}"
              f"(仅接受 {'/'.join(_EXEC_PROVIDERS)}), 按 cpu 处理")
        s = "cpu"
    _execution_provider = s


def _resolve_execution_provider() -> str:
    """档位解析链: set_execution_provider(显式) > env FAA_OCR_EXECUTION_PROVIDER >
    data/config.json 的 ocr_execution_provider > cpu。缺省/缺文件/非法值一律 cpu(零行为),
    非法值打印 WARN 不静默。"""
    if _execution_provider:
        return _execution_provider
    env = (os.environ.get("FAA_OCR_EXECUTION_PROVIDER") or "").strip().lower()
    if env:
        if env in _EXEC_PROVIDERS:
            return env
        print(f"[OCR-GPU] FAA_OCR_EXECUTION_PROVIDER 非法值 {env!r}"
              f"(仅接受 {'/'.join(_EXEC_PROVIDERS)}), 按 cpu 处理")
        return "cpu"
    try:  # data/config.json(与引擎 _load_config 同一文件; 读完即弃, 不缓存——重启语义)
        p = Path(__file__).resolve().parent / "data" / "config.json"
        if p.exists():
            with open(p, encoding="utf-8") as fp:
                v = str(json.load(fp).get("ocr_execution_provider") or "").strip().lower()
            if v in _EXEC_PROVIDERS:
                return v
            if v:
                print(f"[OCR-GPU] config ocr_execution_provider 非法值 {v!r}"
                      f"(仅接受 {'/'.join(_EXEC_PROVIDERS)}), 按 cpu 处理")
    except Exception as e:
        print(f"[OCR-GPU] ocr_execution_provider 读取失败({type(e).__name__}: {e}), 按 cpu 处理")
    return "cpu"


# ---------- OCR2(batch-10, 2026-11-15): cls 方向分类器开关 (use_angle_cls) ----------
# 立项清单 P1 引擎升级线 OCR2(**条件开工**: det736 口径配对 A/B 先行, 实验执行入 batch-12)。
# RapidOCR 的文字方向分类器(cls, ch_ppocr_v2_cls)在包默认 `use_angle_cls: true`
# (rapidocr_onnxruntime/config.yaml:3)下对每个 det crop 先跑一次方向分类 —— 主仓 grep
# use_angle_cls 零命中, 即生产每帧全图/裁片 OCR 都在付 cls 成本且无配置面。本键把该
# RapidOCR 构造参数透传出来:
#   true  **默认 = 改动前行为逐字节等价**(包默认同值; 构造 kwargs 显式传 True 经
#         utils.UpdateParameters.update_global_params 落 Global 同值, 对构建结果零影响);
#   false 跳过 cls(rapid_ocr_api.py:48-52 不建 cls 会话、:91-95 __call__ 逐帧跳分类 ——
#         引擎 API 层 ocr_image/块结构零变化, 仅块集合可能变化: 被旋转方向拖累的低分块恢复)。
# **默认 true 是本批终态**: H7 收益口径(cls 关 median 快 11.0~11.3%、恢复 79 个被 0.5 线
# 吞掉的数字, 但整配置 L1 FAIL)只在 det32/det64 下配对测过 —— 证据边界(DECISION §4.4):
# 默认 det736 生产口径未测, **不得凭 det32/64 数字默认关**(负清单 N8); det736 配对 A/B
# 新数据落盘(_lab/ocr/reports/, batch-12 实机授权批)且过 0 退化门后才允许翻 false
# (独立 commit 可回退; 无收益则关闭本项)。
# 配置面: data/config.json 键 use_angle_cls(缺省/缺文件 = true, 零行为); env
# FAA_OCR_USE_ANGLE_CLS 可临时覆盖(优先级最高, 单机实验/A/B 用: 1/true/yes/on=开,
# 0/false/no/off=关); 非法值如实 WARN 不静默, 一律按默认 true 处理。
# 时序: 与 ocr_threads / ocr_execution_provider 同口径 —— 单例在首次 get_engine() 时按
# 当时值一次性构建, **改后重启生效**(webui 常驻单例 ⇒ 重启 webui; CLI 每次进程即新构建)。
# 适用面: 仅 get_engine() 主引擎构建链(cpu/cuda/dml 三档构建体, 改动点一明文)。
# get_engine_region()(32/min, OCR5 双闸门实验实例)与 get_engine_mixed()(8192/max, OCR4
# P2C 实验实例)配方冻结(「cls 保持库默认(实验同款)」), **不随本键**。
# 0.5 线冲击监控(OCR7 口径, batch-07 脚手架): cls 关 = 低分块恢复, 可能冲击 min_score=0.5
# 判据面(_findtext/_steps/_judges/_buy 等 40+ 处) —— score∈[0.5,0.55] 近线块计数随本批
# cls-off 冒烟与 batch-12 det736 配对 A/B 落盘; 生产 0.5 线本身不动(负清单 N9)。
_use_angle_cls: bool | None = None   # None=未定(首次 get_engine 按解析链定值); 显式 set 后以此为准
_CLS_TRUE = ("1", "true", "yes", "on")
_CLS_FALSE = ("0", "false", "no", "off")


def set_use_angle_cls(v) -> None:
    """显式设置 cls 方向分类器开关(True=开/False=关)。须在首次 get_engine() 前调用;
    改后重启生效。None=不置(保持解析链); 其余无法识别的值按默认 true 处理并如实 WARN。"""
    global _use_angle_cls
    if v is None:
        return
    if isinstance(v, bool):
        _use_angle_cls = v
        return
    s = str(v).strip().lower()
    if s in _CLS_TRUE:
        _use_angle_cls = True
    elif s in _CLS_FALSE:
        _use_angle_cls = False
    else:
        print(f"[OCR-CLS] use_angle_cls 非法值 {v!r}(仅接受 true/false), 按默认 true 处理")


def _resolve_use_angle_cls() -> bool:
    """cls 开关解析链: set_use_angle_cls(显式) > env FAA_OCR_USE_ANGLE_CLS >
    data/config.json 的 use_angle_cls > 默认 True(=包 config.yaml 默认, 改动前行为)。
    缺省/缺文件/缺键一律 True(零行为); 非法值如实 WARN 不静默, 按默认 True 处理。"""
    if _use_angle_cls is not None:
        return _use_angle_cls
    env = (os.environ.get("FAA_OCR_USE_ANGLE_CLS") or "").strip().lower()
    if env:
        if env in _CLS_TRUE:
            return True
        if env in _CLS_FALSE:
            return False
        print(f"[OCR-CLS] FAA_OCR_USE_ANGLE_CLS 非法值 {env!r}(仅接受 true/false), 按默认 true 处理")
        return True
    try:  # data/config.json(与引擎 _load_config 同一文件; 读完即弃, 不缓存——重启语义)
        p = Path(__file__).resolve().parent / "data" / "config.json"
        if p.exists():
            with open(p, encoding="utf-8") as fp:
                v = json.load(fp).get("use_angle_cls")
            if isinstance(v, bool):
                return v
            if v is None or (isinstance(v, str) and v.strip() == ""):
                return True   # 缺键/空串 = 默认(零行为)
            s = str(v).strip().lower()
            if s in _CLS_TRUE:
                return True
            if s in _CLS_FALSE:
                return False
            print(f"[OCR-CLS] config use_angle_cls 非法值 {v!r}(仅接受 true/false), 按默认 true 处理")
    except Exception as e:
        print(f"[OCR-CLS] use_angle_cls 读取失败({type(e).__name__}: {e}), 按默认 true 处理")
    return True


def _gpu_venv_candidates(kind: str) -> list[Path]:
    """GPU 独立 venv 探测路径: env 重指(FAA_OCR_CUDA_VENV / FAA_OCR_DML_VENV)优先,
    缺省 = <项目根>/_lab/ocr/prototypes/{P2E|OCR3_DML}/venv(P2E 实验链 venv 形态;
    项目根 = 本文件上两级, 正式仓布局 FlowerAutoAssistant/ 与 _lab/ 同级)。"""
    root = Path(__file__).resolve().parent.parent.parent  # FlowerAutoAssistant/.. = 项目根
    cands: list[Path] = []
    env_v = (os.environ.get("FAA_OCR_CUDA_VENV" if kind == "cuda" else "FAA_OCR_DML_VENV")
             or "").strip()
    if env_v:
        cands.append(Path(env_v))
    cands.append(root / "_lab" / "ocr" / "prototypes" / ("P2E" if kind == "cuda" else "OCR3_DML") / "venv")
    return cands


def _ep_marker_dll(kind: str) -> str:
    """onnxruntime capi 目录里目标 EP 的 DLL 标记(不 import 即可判别 wheel 形态):
    cuda 轮子带 onnxruntime_providers_cuda.dll, DirectML 轮子带 DirectML.dll, CPU 轮子两者皆无。"""
    return "onnxruntime_providers_cuda.dll" if kind == "cuda" else "DirectML.dll"


def _find_gpu_venv(kind: str) -> Path:
    """探测含目标 EP onnxruntime 的 GPU 独立 venv(capi DLL 标记判别, 不 import); 全部缺位 →
    RuntimeError(如实上抛走回退链, 不静默 —— 计划「venv 探测→缺位如实 WARN 不静默」)。"""
    probed = []
    marker = _ep_marker_dll(kind)
    for c in _gpu_venv_candidates(kind):
        sp = c / "Lib" / "site-packages"
        ok = ((sp / "onnxruntime" / "capi" / marker).exists()
              and ((c / "Scripts" / "python.exe").exists() or (c / "bin" / "python").exists()))
        probed.append(f"{c}({'✓' if ok else '✗'})")
        if ok:
            return c
    raise RuntimeError(f"{kind} 档 GPU 独立 venv 探测缺位(探测路径: {'; '.join(probed)})")


def _add_nvidia_dll_dirs(venv_dir: Path) -> int:
    """把 nvidia-*-cu13 pip 轮子的 DLL 目录加入本进程搜索路径(P2E p2e.py:36-51 同款)。"""
    n = 0
    sp = venv_dir / "Lib" / "site-packages" / "nvidia"
    if sp.exists():
        for sub in sp.glob("*"):
            for cand in (sub / "bin", sub / "lib"):
                if cand.exists():
                    try:
                        os.add_dll_directory(str(cand))
                        n += 1
                    except (OSError, AttributeError):
                        pass
                    os.environ["PATH"] = str(cand) + os.pathsep + os.environ.get("PATH", "")
    return n


def _bootstrap_gpu_runtime(kind: str) -> str:
    """让 onnxruntime 从 GPU 独立 venv 解析(P2E venv 自举)。返回来源标签(供日志/断言)。

    三分支: ① 当前解释器自身即目标 GPU venv(capi DLL 标记判别, 不 import 不污染 sys.modules)
              → 直接可用(整个进程跑在 GPU venv 里的部署形态, A/B 同此);
            ② onnxruntime 已 import: 已带目标 EP → 直接可用; 否则不可换库, 如实上抛
              (档位须在进程启动前选定, 改配置后重启);
            ③ onnxruntime 未加载 → 前插 GPU venv site-packages(cuda 另加 nvidia DLL 目录),
              后续 `from rapidocr_onnxruntime import RapidOCR` 即从 GPU venv 解析
              onnxruntime(-gpu / -directml)。"""
    capi = Path(sys.executable).resolve().parent.parent / "Lib" / "site-packages" / "onnxruntime" / "capi"
    if capi.exists() and (capi / _ep_marker_dll(kind)).exists():
        if kind == "cuda":
            # venv 直跑也要补 nvidia DLL 目录: cudnn/cublas 在 pip 轮子的 site-packages/nvidia
            # 下, 不在系统 PATH(S6 冒烟实证: 缺它 = LoadLibrary cudnn64_9.dll 失败)。
            _add_nvidia_dll_dirs(Path(sys.executable).resolve().parent.parent)
        return f"当前进程解释器即 {kind} venv(无需自举)"
    need_ep = "CUDAExecutionProvider" if kind == "cuda" else "DmlExecutionProvider"
    existing = sys.modules.get("onnxruntime")
    if existing is not None:
        provs = list(existing.get_available_providers())
        if need_ep in provs:
            return "当前进程 onnxruntime 已含目标 EP(无需自举)"
        raise RuntimeError(f"onnxruntime 已以 {provs} 构建加载, 无法再换 {kind} 后端 —— "
                           f"{kind} 档须在进程启动前选定(改配置后重启)")
    venv = _find_gpu_venv(kind)
    if kind == "cuda":
        _add_nvidia_dll_dirs(venv)
    sys.path.insert(0, str(venv / "Lib" / "site-packages"))
    return f"已自举独立 venv: {venv}"


def _session_providers(eng) -> dict:
    """读取 RapidOCR 实例 det/cls/rec 三个 ONNX 会话的实际 providers(p2e.py build 同位)。"""
    out: dict = {}
    try:
        out["det"] = list(eng.text_detector.infer.session.get_providers())
    except Exception as e:
        out["det"] = [f"<读取失败 {type(e).__name__}: {e}>"]
    try:
        out["rec"] = list(eng.text_recognizer.session.session.get_providers())
    except Exception as e:
        out["rec"] = [f"<读取失败 {type(e).__name__}: {e}>"]
    cls = getattr(eng, "text_cls", None)
    if cls is None:
        out["cls"] = None
    else:
        try:
            out["cls"] = list(cls.infer.session.get_providers())
        except Exception as e:
            out["cls"] = [f"<读取失败 {type(e).__name__}: {e}>"]
    return out


def _build_cpu_engine(use_angle_cls: bool | None = None):
    """cpu 档构建体 = 改动前 get_engine() 的构建调用逐字节平移(默认档零行为)。

    检测参数调优: 关闭膨胀(use_dilation=False), 避免「半透明按钮/相邻文字」被膨胀成
    一个合并块导致子串命中整块中心而误点。box_thresh 降、unclip_ratio 降, 检测框更紧贴文字。
    注意: 传任意 det_* 参数时该库强制读取 det_model_path, 需显式传 None 以沿用默认模型路径。
    (检测边长 limit_side_len 不下调: 实测 960/max 会在好友列表等界面丢块, 影响采粉, 见协作区基准)
    OCR3 时序注记: SessionOptions 补丁移到各构建器内(补丁 import rapidocr → 会连带加载
    onnxruntime; GPU 档的独立 venv 自举必须发生在任何 onnxruntime import 之前, 故补丁
    不能留在 get_engine 的档位分派之前)。
    OCR2(batch-10): use_angle_cls 构造参数透传(默认 None=按 _resolve_use_angle_cls() 解析,
    解析结果默认 True = 包 config.yaml 默认同值, 与改动前构建结果逐字节等价); False 时
    RapidOCR 不建 cls 会话、逐帧跳方向分类(rapid_ocr_api.py:48-52/:91-95)。"""
    ua = _resolve_use_angle_cls() if use_angle_cls is None else bool(use_angle_cls)
    _apply_session_options_patch()
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR(
        det_model_path=None,
        det_use_dilation=False,
        det_thresh=0.2,
        det_box_thresh=0.3,
        det_unclip_ratio=1.4,
        use_angle_cls=ua,
    )


def _build_cuda_engine(use_angle_cls: bool | None = None):
    """cuda 档构建 = P2E gpu_cuda_det736 配方逐字平移(_lab/ocr/harness/configs.py:126-210
    + probe_tf32.py), 附构建后断言。

    - Det/Rec 走 CUDA EP、**cls 留 CPU**(cls 模型极小, GPU 每次调用固定开销 ~50ms 反而比
      CPU 4ms 慢; 且 CPU cls 与基线逐字一致, -21% —— DECISION.md §4.1);
    - **TF32 显式关 + 断言**: ORT CUDA EP 默认允许 TF32(conv 降精度), 同一 refine 裁片
      CPU 读「超过-」、CUDA 默认读「超过」, use_tf32=0 后与 CPU 逐字/逐分一致 —— 断言失败
      = 配置性错误, 上抛走回退链, 绝不带病上岗(验收线「TF32 显式关有断言」);
    - cudnn_conv_algo_search=HEURISTIC(覆盖库内默认 EXHAUSTIVE, 不逐形状 benchmark);
    - read_yaml / InferenceSession 两处一次性包装在构建完立即恢复(同进程随后建 CPU
      引擎不受影响, P2E 同款)。
    时序: venv 自举(→ onnxruntime-gpu 从 GPU venv 解析)必须先于一切 rapidocr/onnxruntime
    import, SessionOptions 线程补丁在自举后、包装前打(补丁落到 GPU venv 的 rapidocr 副本上,
    与 P2E configs._apply_thread_limit 同型)。
    OCR2(batch-10): use_angle_cls 透传同 cpu 档(默认 None=解析链, True=包默认同值零影响);
    False 时 cls 会话不建 —— 构建后断言改按「cls 预期缺席」校验(不再是「cls 模块缺席」
    配置性错误); read_yaml 包装对 Cls 段的 use_cuda=False 写入在 cls 关时无害(Cls 配置段
    仍在 yaml, 只是 TextClassifier 不再实例化)。"""
    ua = _resolve_use_angle_cls() if use_angle_cls is None else bool(use_angle_cls)
    src = _bootstrap_gpu_runtime("cuda")
    _apply_session_options_patch()
    import rapidocr_onnxruntime.rapid_ocr_api as _api
    import rapidocr_onnxruntime.utils as _ru
    _orig_read_yaml = _api.read_yaml

    def _read_yaml_cuda(path):
        c = _orig_read_yaml(path)
        c["Det"]["use_cuda"] = True
        c["Rec"]["use_cuda"] = True
        c["Cls"]["use_cuda"] = False    # cls 留 CPU(DECISION.md §4.1)
        return c

    _api.read_yaml = _read_yaml_cuda
    _orig_is = _ru.InferenceSession
    tf32_records: list[tuple[str, str]] = []  # (模型文件名, use_tf32) —— 供构建后断言

    def _is_cuda_opts(model, sess_options=None, providers=None, **kw):
        newp = []
        for p in (providers or []):
            if isinstance(p, tuple) and p[0] == "CUDAExecutionProvider":
                o = dict(p[1])
                o["use_tf32"] = "0"   # P2E gpu_cuda_det736: det/rec TF32 全关(rec 保文本)
                o["cudnn_conv_algo_search"] = "HEURISTIC"
                tf32_records.append((str(model), o["use_tf32"]))
                newp.append((p[0], o))
            else:
                newp.append(p)
        return _orig_is(model, sess_options=sess_options, providers=newp, **kw)

    _ru.InferenceSession = _is_cuda_opts
    try:
        from rapidocr_onnxruntime import RapidOCR
        eng = RapidOCR(
            det_model_path=None,
            det_use_dilation=False,
            det_thresh=0.2,
            det_box_thresh=0.3,
            det_unclip_ratio=1.4,
            use_angle_cls=ua,
        )
    finally:
        _api.read_yaml = _orig_read_yaml
        _ru.InferenceSession = _orig_is
    # TF32 断言记录留档(模块级可观测: 诊断/冒烟消费; 只增不改判定)
    global _last_tf32_records
    _last_tf32_records = list(tf32_records)

    # ---- 构建后断言(OCR3 验收线「TF32 显式关有断言」+「cls 留 CPU」;
    #      OCR2: cls 显式关时改按「cls 预期缺席」校验, 不是配置性错误) ----
    provs = _session_providers(eng)
    problems = []
    if "CUDAExecutionProvider" not in provs["det"]:
        problems.append(f"det providers={provs['det']}")
    if "CUDAExecutionProvider" not in provs["rec"]:
        problems.append(f"rec providers={provs['rec']}")
    if len(tf32_records) < 2:
        problems.append(f"TF32 记录数={len(tf32_records)}(<2: det/rec 未都经 CUDA EP 建会话)")
    if any(v != "0" for _m, v in tf32_records):
        problems.append(f"TF32 未全部显式关: {tf32_records}")
    if ua is False:
        # OCR2(batch-10): cls 显式关 = cls 会话缺席是**预期形态**, 反而要防「该关没关」
        if provs["cls"] is not None:
            problems.append(f"use_angle_cls=false 但 cls 会话仍被构建: {provs['cls']}")
    elif provs["cls"] is None:
        problems.append("cls 模块缺席(use_angle_cls 被意外关闭?)")
    elif "CUDAExecutionProvider" in provs["cls"]:
        problems.append(f"cls 未留 CPU: {provs['cls']}")
    if problems:
        raise RuntimeError("cuda 档会话断言失败: " + "; ".join(problems) + f"({src})")
    print(f"[OCR-GPU] cuda 档引擎就绪: det={provs['det']} rec={provs['rec']} "
          f"cls={provs['cls']} TF32=off cudnn=HEURISTIC ({src})")
    return eng


def _build_dml_engine(use_angle_cls: bool | None = None):
    """dml 档构建(自管 session, 推荐档形态位): rapidocr 1.2.3 无 DML 原生路径 ——
    utils.OrtInferSession 只构造 CUDAExecutionProvider(utils.py:21-50), 且
    onnxruntime-directml 无 CUDA EP → 库内 use_cuda 门(get_device()=='GPU')不成立。
    故以 InferenceSession 包装**强制** det/rec 走 DmlExecutionProvider(cls 留 CPU,
    与 cuda 档同型), 并断言实际 providers。DML 兼容任意 DX12 GPU 含核显/集显
    (HANDOFF.md:412-413 用户形态)。推荐档地位须以 0-diff A/B 数据兑现(→batch-12)。
    时序: venv 自举先于一切 rapidocr/onnxruntime import(与 cuda 档同型), SessionOptions
    线程补丁在自举后打。
    OCR2(batch-10): use_angle_cls 透传同 cpu/cuda 档(默认 None=解析链); False 时 cls
    会话不建 —— 构建后断言改按「cls 预期缺席」校验(与 cuda 档同型)。"""
    ua = _resolve_use_angle_cls() if use_angle_cls is None else bool(use_angle_cls)
    src = _bootstrap_gpu_runtime("dml")
    _apply_session_options_patch()
    import rapidocr_onnxruntime.utils as _ru
    _orig_is = _ru.InferenceSession
    dml_swaps: list[str] = []  # 被强制 DML 的会话模型名(构建后断言 det/rec 都被换过)

    def _is_dml(model, sess_options=None, providers=None, **kw):
        name = str(model).lower().replace("\\", "/").rsplit("/", 1)[-1]
        if "cls" in name:   # cls 留 CPU(与 cuda 档同型)
            return _orig_is(model, sess_options=sess_options, providers=providers, **kw)
        dml_swaps.append(name)
        return _orig_is(model, sess_options=sess_options,
                        providers=["DmlExecutionProvider", "CPUExecutionProvider"], **kw)

    _ru.InferenceSession = _is_dml
    try:
        from rapidocr_onnxruntime import RapidOCR
        eng = RapidOCR(
            det_model_path=None,
            det_use_dilation=False,
            det_thresh=0.2,
            det_box_thresh=0.3,
            det_unclip_ratio=1.4,
            use_angle_cls=ua,
        )
    finally:
        _ru.InferenceSession = _orig_is

    # ---- 构建后断言: det/rec 实际 providers 含 DmlExecutionProvider + cls 留 CPU;
    #      OCR2: cls 显式关时改按「cls 预期缺席」校验(与 cuda 档同型) ----
    provs = _session_providers(eng)
    problems = []
    if "DmlExecutionProvider" not in provs["det"]:
        problems.append(f"det providers={provs['det']}")
    if "DmlExecutionProvider" not in provs["rec"]:
        problems.append(f"rec providers={provs['rec']}")
    if len(dml_swaps) < 2:
        problems.append(f"DML 换轨记录数={len(dml_swaps)}(<2: det/rec 未都被强制 DML)")
    if ua is False:
        if provs["cls"] is not None:
            problems.append(f"use_angle_cls=false 但 cls 会话仍被构建: {provs['cls']}")
    elif provs["cls"] is None:
        problems.append("cls 模块缺席(use_angle_cls 被意外关闭?)")
    elif "DmlExecutionProvider" in provs["cls"]:
        problems.append(f"cls 未留 CPU: {provs['cls']}")
    if problems:
        raise RuntimeError("dml 档会话断言失败: " + "; ".join(problems) + f"({src})")
    print(f"[OCR-GPU] dml 档引擎就绪: det={provs['det']} rec={provs['rec']} "
          f"cls={provs['cls']} ({src})")
    return eng


def _build_gpu_engine(prov: str, use_angle_cls: bool | None = None):
    """档位 → 构建器分派(未知档位视为配置错误, 上抛走回退链)。
    OCR2(batch-10): use_angle_cls 透传给目标构建器(默认 None=构建器内自解析)。"""
    if prov == "cuda":
        return _build_cuda_engine(use_angle_cls)
    if prov == "dml":
        return _build_dml_engine(use_angle_cls)
    raise RuntimeError(f"未知执行后端档位 {prov!r}")


def get_engine():
    """获取全局唯一 OCR 引擎实例（首次调用时初始化）。
    Q02(batch-05): check-and-init 经 _ENGINE_LOCK 原子化(双检: 快路径无锁读)。
    OCR3(batch-08): 构建前按 ocr_execution_provider(默认 cpu=零行为)分派三档; cuda/dml
    档构建失败(venv 缺位/onnxruntime 已被 CPU 版占用/session 建不起来/断言不过 ——
    含拔卡场景)→ 捕获、如实 WARN 并自动回退 cpu 档(DECISION.md §4.1 回退链)。注意回退
    在锁内直接调 _build_cpu_engine() 而非递归 get_engine()(threading.Lock 不可重入, 递归
    即死锁); 回退即粘住(单例语义, 不逐帧重试 GPU), 改配置重启后重试。
    OCR3 时序: SessionOptions 补丁在**各构建器内部**打(cpu 原位不变; GPU 档在 venv 自举后
    打) —— 补丁 import rapidocr 会连带加载 onnxruntime, 若先于档位分派执行, GPU 档的独立
    venv 自举将永远撞上「onnxruntime 已以 CPU 构建加载」(S3 冒烟实证后修正)。
    OCR2(batch-10): 构建前另按 use_angle_cls 解析链(默认 true=零行为)定值一次并透传给
    目标构建器(回退 cpu 分支同值, 两侧解析同源); 与 ocr_threads/ocr_execution_provider
    同口径 —— 改后重启生效。"""
    global _engine, _gpu_fallback_reason
    if _engine is None:
        with _ENGINE_LOCK:
            if _engine is None:
                prov = _resolve_execution_provider()
                ua = _resolve_use_angle_cls()
                if prov == "cpu":
                    _engine = _build_cpu_engine(ua)
                else:
                    try:
                        _engine = _build_gpu_engine(prov, ua)
                    except Exception as e:
                        _gpu_fallback_reason = f"{type(e).__name__}: {e}"
                        print(f"[OCR-GPU] {prov} 档构建失败({_gpu_fallback_reason}), "
                              f"已自动回退 cpu 档(单例粘住; 改配置重启后重试 GPU)")
                        _engine = _build_cpu_engine(ua)
    return _engine


def get_engine_region():
    """裁片专用 OCR 实例(zcode-20261031-13): det_limit_side_len=32/min —— 小裁片不再被库内
    默认 min/736 预处理反向放大(短边被拉到 736, 宽扁裁片 det 耗时反而高于全图 —— -9 实证)。
    离线微基准(_explore_1028/det_region_bench.txt, v9_popup 帧): 标题带 896x216 1329→782ms、
    页脚带 768x108 1971→445ms, 关键词检出保持。**全图路径不受影响**(仍走 get_engine();
    实测 960/max 在好友列表丢块, 故全图严禁动 limit —— 本文件 L62 既有结论)。
    由 ocr_engine 配置闸门 det_region_limit(默认 false)启用; 关闭时本函数不被调用,
    引擎走 get_engine(), 行为与旧版逐字节一致。线程限制与 get_engine 同型(共用同一份
    模块级 SessionOptions 补丁, Q02)。
    OCR3(batch-08): 本实例**不随** ocr_execution_provider 档位, 仍 CPU 构建(region 路径
    的 GPU 接线属 OCR4 混合路由批); 时序注记: 若先于 get_engine() 构建本实例, SessionOptions
    补丁会连带加载 CPU 版 onnxruntime —— 该进程随后请求 cuda/dml 档将如实回退 cpu
    (生产时序 full 先于 region, 不触此路径)。
    Q02(batch-05): check-and-init 同样经 _ENGINE_LOCK 原子化(与 get_engine 互斥)。"""
    global _engine_region
    if _engine_region is None:
        with _ENGINE_LOCK:
            if _engine_region is None:
                _apply_session_options_patch()
                # 传任意 det_* 参数时该库强制读取 det_model_path, 需显式传 None 沿用默认模型路径(同 get_engine)
                from rapidocr_onnxruntime import RapidOCR
                _engine_region = RapidOCR(
                    det_model_path=None,
                    det_limit_side_len=32,
                    det_limit_type="min",
                    det_use_dilation=False,
                    det_thresh=0.2,
                    det_box_thresh=0.3,
                    det_unclip_ratio=1.4,
                )
    return _engine_region


def get_engine_mixed():
    """混合路由 split/refine 腿专用 P2C 自适应实例(OCR4/batch-09, 灰度键
    mixed_route.enabled 启用, **默认 false = 本函数不被调用、实例永不构建**)。

    配方 = 实验 harness prototypes/P2C/p2c.py Engines.adaptive 逐字同参:
    det_limit_side_len=8192 / det_limit_type=max(det 自身不再做短边反向放大 —— 缩放
    由混合路由管线按 charh 字高估计完成, 见引擎 _mixed_route_sr), 其余 det 参数与
    get_engine() 逐字一致(use_dilation=False, thresh=0.2/0.3, unclip_ratio=1.4),
    cls 保持库默认(实验同款)。
    **CPU 构建, 不随 ocr_execution_provider 档位**: P2C 实验数据(15.67×/15.88×, L1'/L2'/L3/
    L4/L6)全部产自正式 venv CPU 口径, GPU 收益只落 region 腿(裁定二 region=复用 batch-08
    GPU 实例); 给本实例接 GPU 无实验背书, 不做。
    Q02(batch-05) 同型: check-and-init 经 _ENGINE_LOCK 原子化(与 get_engine/get_engine_region
    互斥); SessionOptions 线程补丁共用模块级单次版本(与实验 configs._apply_thread_limit 同型)。"""
    global _engine_mixed
    if _engine_mixed is None:
        with _ENGINE_LOCK:
            if _engine_mixed is None:
                _apply_session_options_patch()
                # 传任意 det_* 参数时该库强制读取 det_model_path, 需显式传 None 沿用默认模型路径(同 get_engine)
                from rapidocr_onnxruntime import RapidOCR
                _engine_mixed = RapidOCR(
                    det_model_path=None,
                    det_limit_side_len=8192,
                    det_limit_type="max",
                    det_use_dilation=False,
                    det_thresh=0.2,
                    det_box_thresh=0.3,
                    det_unclip_ratio=1.4,
                )
    return _engine_mixed


def ocr_image(image, engine=None) -> list[dict]:
    """对图片执行 OCR。image 可为路径字符串 / Path / numpy 数组 (BGR)。
    engine=None 时用全局默认实例(与旧版逐字节一致); 裁片路径在配置闸门开启时由调用方传入
    get_engine_region() 实例(小 limit, 见其 docstring)。调用方不传 = 旧行为。
    返回按 上->下、左->右 排序的文字块列表。
    """
    eng = engine if engine is not None else get_engine()
    res, _ = eng(image)
    if not res:
        return []
    out = []
    for box, text, score in res:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        out.append(
            {
                "text": text,
                "center": [int(sum(xs) / 4), int(sum(ys) / 4)],
                "box": [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))],
                "score": float(score),
            }
        )
    # 按 y 优先（上->下）、x 次之（左->右）排序
    out.sort(key=lambda r: (r["box"][1], r["box"][0]))
    return out


def ocr_find(blocks, keyword: str, exact=False) -> list[dict]:
    """在 OCR 结果中筛选包含 keyword 的文字块。keyword 可为 str 或 str 列表（任一命中）。
    exact=True 时要求块文本与 keyword 完全相等(去掉首尾空白), 避免『家园』误命中『勇气国花园』等子字符串。
    返回命中块列表。
    """
    if isinstance(keyword, str):
        keyword = [keyword]
    if exact:
        return [b for b in blocks if any(b["text"].strip() == k for k in keyword)]
    return [b for b in blocks if any(k in b["text"] for k in keyword)]


# ---------- CLI ----------
def _print_human(blocks):
    if not blocks:
        print("未识别到文字")
        return
    print(f"{len(blocks)} 个文字块:\n")
    print(f"{'文字':<16}{'中心X':<8}{'中心Y':<8}  框x1 y1 x2 y2")
    print("-" * 60)
    for b in blocks:
        cx, cy = b["center"]
        x1, y1, x2, y2 = b["box"]
        print(f"{b['text']:<16}{cx:<8}{cy:<8}  {x1} {y1} {x2} {y2}")


def _serve_loop():
    """常驻服务：逐行读图片路径，每行输出一条 JSON 结果。引擎只初始化一次。"""
    engine = get_engine()  # 提前初始化，权限只需一次
    print("[OCR-Server] ready", flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            blocks = ocr_image(line)
            print(json.dumps(blocks, ensure_ascii=False), flush=True)
        except Exception as e:
            print(json.dumps({"error": str(e)}), flush=True)


def main():
    args = sys.argv[1:]
    if args and args[0] == "--serve":
        _serve_loop()
        return
    if not args:
        print("用法: python ocr_ui.py <截图.png> | --serve")
        sys.exit(1)
    blocks = ocr_image(args[0])
    _print_human(blocks)


if __name__ == "__main__":
    main()
