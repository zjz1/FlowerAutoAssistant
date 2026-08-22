# FlowerAutoAssistant (FAA)

面向页游《小花仙》的**一键挂机**自动化框架。基于 **OCR 文字识别 + 相对坐标** 的数据驱动方案，实现"识别界面 → 定位按钮 → 点击执行 → 循环挂机"。

> ⚠️ **仅供学习与个人使用。** 本项目不包含任何游戏素材、资源包或解包工具，仅含通用自动化逻辑。请遵守游戏服务条款及所在地区法律法规，由此产生的账号风险由使用者自行承担。

---

## 技术路线

与传统的"模板匹配"（如 MAA）不同，本项目采用 **“OCR 文字定位 + 相对坐标”** 方案：

- **每次运行时**用 OCR 识别界面文字 → 定位文字中心坐标
- 坐标归一化为**相对坐标**（`x/屏宽, y/屏高`），**屏幕尺寸变化时相对位置不变**
- 坐标锚点存入本地知识库，OCR 瞬时失败时可用缓存兜底点击

### 核心循环

```
连接模拟器 → 截图 → OCR识别文字 → 按关键字定位按钮
→ 计算相对坐标 → 点击 → 回退缓存 → 循环
```

### 三通道识别（`click_text` 自动回退）

| 通道 | 适用 | 原理 |
|---|---|---|
| ① OCR 文字定位 | 有文字的按钮 | RapidOCR 识别文字 → 中心坐标 |
| ② 颜色特征定位 | 无文字的图形按钮 | HSV 颜色过滤 + 连通区域分析 |
| ③ 坐标锚点回退 | 任意已记录按钮 | 知识库相对坐标兜底 |

---

## 目录结构

```
FlowerAutoAssistant/
├── main.py            # 主入口：连接、选流程、循环执行、断线重连
├── ocr_engine.py      # 核心引擎：连接/截图/OCR定位/颜色定位/点击/知识库/流程执行
├── ocr_ui.py          # RapidOCR 单例服务（模型只初始化一次）
├── requirements.txt   # 依赖
├── PROGRESS.md        # 项目活文档（每次运行前先读）
├── flows/*.json       # 数据驱动流程定义（改 JSON 不改代码）
└── data/click_log.json# 按钮知识库（相对坐标，自动积累）
```

> `debug/`、`legacy/`、`resource/`、`.venv/` 等已加入 `.gitignore`，不参与版本控制。

---

## 依赖安装

```bash
pip install -r requirements.txt
# maafw, opencv-python, Pillow, RapidOCR（随 maafw/opencv 附带相关依赖）
```

## 使用

```bash
# 列出可用流程
python main.py --list

# 执行"每日挂机"流程 1 次（默认）
python main.py

# 无限循环执行（Ctrl+C 停止）
python main.py --flow 每日 --loop 0

# 执行 5 次
python main.py --loop 5

# 指定 ADB 地址 / adb 路径
python main.py --address 127.0.0.1:16384 --adb "D:\\...\\adb.exe"
```

## 环境

- Python 3.11+
- MuMu 模拟器 12（ADB 端口默认 `127.0.0.1:16384`）
- 画面：1280×720 横屏（相对坐标自动适配其它尺寸）

---

## 流程 JSON 示例

`flows/enter_home.json`：

```json
{
  "name": "进入家园",
  "steps": [
    { "type": "wait_text",  "text": ["家园"], "timeout": 15, "interval": 1.0 },
    { "type": "click_text", "text": ["家园"], "delay": 2.0 },
    { "type": "sleep",      "seconds": 3.0 }
  ]
}
```

支持步骤类型：`wait_text` / `click_text` / `click_rel` / `sleep`

---

## License

For learning and personal use only. No affiliation with the game's developer/publisher.