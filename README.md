<div align="center">

# SubCraft 字幕生成器 (SubCraft)

**导入视频 → 语音识别 → AI 翻译 → 可视化编辑 → 一键导出**

[中文](#-中文使用说明) · [English](#-english-guide)

基于本地 Whisper 语音识别与 AI 翻译的桌面应用（Electron + Python FastAPI），
支持双语字幕、可视化拖动定位、无损封装与烧录内嵌导出。

</div>

---

## 📖 中文使用说明

### ✨ 功能总览

| 功能 | 说明 |
|---|---|
| 🎙 语音识别 | 本地 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)（GPU 加速、自动检测语言），可选 OpenAI Whisper API 云端识别 |
| 🌐 AI 翻译 | OpenAI 兼容接口（GPT / DeepSeek / Kimi / 通义 / 智谱 / OpenRouter）或 DeepL，批量并发、时间轴严格对齐 |
| 🈶 双语字幕 | 主/副语言同屏显示，每种语言**独立设置**字体、字号、颜色、描边、阴影与位置 |
| 👁 所见即所得 | 内置 [jassub](https://github.com/ThaUnknown/jassub)（libass WebAssembly）实时渲染，暂停状态改样式/拖动立即生效 |
| 🖱 拖动定位 | 在视频画面上**按住字幕拖动**即可摆位置（中心点坐标模式），双语各语言**独立拖动**互不影响 |
| ✏️ 字幕编辑 | 逐条修改文本与时间码，点击行跳转播放，悬停删除单段，一键清理空段落 |
| 💾 视频导出 | **内嵌字幕（烧录进画面）** 或 **MKV 软字幕无损封装**，另有 SRT / ASS 字幕文件导出 |

---

### 📦 安装

#### 方式一：下载安装包（推荐普通用户）

到 [Releases](../../releases) 页面下载：

- **Windows**：`SubCraft-Setup-x.x.x.exe`，双击安装即可（已内置 Python 后端与 ffmpeg）
- **Linux**：`SubCraft-x.x.x-x64-linux.tar.gz`，解压后需系统 `python3`、`ffmpeg`：
  ```bash
  tar -xzf SubCraft-x.x.x-x64-linux.tar.gz
  cd SubCraft-x.x.x-x64-linux
  sudo apt install ffmpeg python3-pip          # 系统依赖
  python3 -m pip install -r resources/backend/requirements.txt
  ./subcraft-app
  ```

#### 方式二：源码运行（开发者）

前置：Python 3.13+、Node 20+、（可选）NVIDIA GPU + CUDA 12 驱动

```powershell
# 1. 后端环境
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# 2. 前端依赖（GitHub 下载 Electron 超时可先设镜像）
$env:ELECTRON_MIRROR = "https://npmmirror.com/mirrors/electron/"
cd app; npm install; cd ..

# 3. 启动（Electron 自动拉起 Python 后端）
cd app; npm run dev
```

首次使用会自动下载新版 ffmpeg（约 80MB）与 whisper 模型（turbo 约 1.6GB）。

---

### 🚀 详细使用指南

#### 第 1 步 · 导入视频

点击左上角「**导入视频**」，支持 `mp4 / mkv / mov / avi / webm / ts / flv / wmv / m4v`。
导入后自动探测分辨率、时长、编码信息。

#### 第 2 步 · 语音识别（①）

点击「**① 识别字幕**」，在对话框中选择：

| 选项 | 说明 |
|---|---|
| 引擎 | `local` 本地 faster-whisper（默认，免费、断网可用）/ `openai` 云端 Whisper API |
| 模型 | `large-v3-turbo`（默认，推荐）/ `large-v3` / `medium` / `small` 等，首次使用自动下载 |
| 设备 | `auto` 自动（有 NVIDIA 显卡用 GPU）/ 强制 `cuda` / `cpu` |
| 语言 | 自动检测，或手动指定源语言提高准确率 |

识别过程有实时进度条；云端引擎会自动抽取低码率音频上传（受 25MB 限制，长视频建议本地识别）。

#### 第 3 步 · AI 翻译（②）

1. 先到「**⚙ 设置**」添加 AI 厂商：内置 OpenAI / DeepSeek / Kimi / 通义千问 / 智谱 GLM / OpenRouter
   预设，填入 API Key 与模型名即可（Key 只保存在本机）；
2. 点击「**② 翻译**」，选择目标语言与厂商；
3. 支持批量并发翻译，并**保证段数与时间轴严格对齐**（解析异常自动降级逐条重试）。

#### 第 4 步 · 字幕校对与编辑

- **改文本 / 时间码**：直接在右侧列表编辑，时间码格式 `00:00:01.250`；
- **跳转试听**：点击任意字幕行，视频跳到该句起点；
- **跟随高亮**：播放时当前行自动高亮并滚动跟随；
- **删除单段**：鼠标悬停字幕行，点击行尾「✕」；
- **清理空段**：编辑后留下的空段落，轨道栏会出现红色「清理空段 N」按钮，一键删除所有轨道的空段。

#### 第 5 步 · 字体样式与拖动定位

左下角样式面板对**当前选中的轨道**（点轨道页签切换语言）生效，每种语言独立保存：

**字体样式**：字体（系统字体列表）、字号、颜色、描边色、描边宽、阴影、粗体、斜体。

**位置有两种模式**：

1. **对齐 + 边距**（默认）：九宫格位置（左下/底部居中/右下…）+ 垂直边距 + 左/右边距；
2. **中心点坐标**（拖动自动进入）：以字幕**中心点**在视频中的坐标（视频原始像素）定位，
   面板可直接输入 X / Y 精确调整；点击「**恢复默认布局**」回到模式 1。

**拖动操作**：在视频画面上**按住字幕拖动**，字幕中心实时跟随鼠标（高帧率本地渲染，暂停时也即时生效）。
双语字幕**每条语言独立拖动**：点轨道页签选中要摆位的语言，拖动只影响该语言，另一条保持不动。

> 💡 双语对照：标签栏勾选「双语对照」，两行合并渲染；点页签上的「主」设置双语中显示在上方的语言。

#### 第 6 步 · 导出（③）

导出对话框可同时勾选多项：

| 导出项 | 说明 | 适用场景 |
|---|---|---|
| **内嵌字幕（烧录进画面）** | 字幕渲染进画面，**任何播放器可见**；libx264 crf 18 高质量重编码，实时进度；导出前可查看**真实烧录预览帧**（与最终导出同一渲染管线） | 分发成品视频、社交平台投稿 |
| **软字幕封装（MKV）** | ASS 样式轨（默认显示）+ SRT 兼容轨打包进 MKV，视频流直接复制，**画质 100% 无损、秒级完成** | 归档、后期可开关/修改字幕 |
| **SRT / ASS 字幕文件** | 每种语言单独导出 + 双语合并文件（可选） | 投稿平台字幕、播放器外挂 |

> ⚠ 软字幕封装的视频，Windows 自带播放器不显示 ASS 轨（文件本身正常），请用 VLC / PotPlayer / mpv；
> 需要"到处都能看到字幕"请选**内嵌字幕**。

---

### 🛠 打包发布

```powershell
# 后端 → backend\dist\subcraft-backend.exe（--no-cuda 为仅 CPU 精简版）
.\.venv\Scripts\python.exe backend\build_exe.py --no-cuda

# Windows → NSIS 安装包（release/ 目录）
cd app; npm run pack

# Linux → tar.gz 免安装包（release/linux/ 目录）
cd app; npm run pack:linux
```

> Linux 版后端以源码随包，需系统 `python3` + `pip install -r resources/backend/requirements.txt`，
> ffmpeg 用系统包管理器安装（`sudo apt install ffmpeg`），语音识别仅 CPU 模式。

### 🧪 测试

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -v   # 后端单元测试
cd app; npx tsc --noEmit; npx vite build                 # 前端类型检查 + 构建
# Electron 冒烟测试（CDP 驱动真实窗口）
cd app
Start-Process node_modules\.bin\electron.cmd "--remote-debugging-port=9333 ."
node scripts\cdp_smoke_test.mjs 9333 <测试视频路径>
```

### 🏗 架构

```
┌────────────────────────────────────────────┐
│ Electron 前端 (React 18 + TypeScript + Vite) │
│  播放器(jassub) · 拖动定位 · 字幕编辑          │
│  样式面板 · 导出对话框(烧录预览帧)             │
└───────────────┬────────────────────────────┘
                │ HTTP + WebSocket（本地随机端口）
┌───────────────▼────────────────────────────┐
│ Python FastAPI 后端（Electron 子进程）        │
│  ASR(faster-whisper/OpenAI)                 │
│  翻译(LLM/DeepL) · ASS/SRT 生成              │
│  ffmpeg 软字幕封装 / 硬字幕烧录                │
└────────────────────────────────────────────┘
```

- 配置与 API Key：`%LOCALAPPDATA%\SubCraft\config.json`（**只存在本机**）
- 后端日志：`%APPDATA%\subcraft-app\backend.log`

### ❓ 常见问题

<details>
<summary><b>软字幕封装的视频看不到字幕？</b></summary>

Windows 自带播放器不支持内嵌 ASS 软字幕（文件本身没问题，已附带 SRT 兼容轨）。请用
VLC / PotPlayer / mpv 播放；或改用「内嵌字幕（烧录）」导出。
</details>

<details>
<summary><b>GPU 没有被使用？</b></summary>

设置中把「识别设备」改为强制 CPU 交叉验证；GPU 识别需要 CUDA 12 运行库。
</details>

<details>
<summary><b>云端识别报错 25MB 限制？</b></summary>

OpenAI 云端引擎对上传音频有 25MB 限制（程序会自动抽低码率 mp3），长视频请用本地识别。
</details>

<details>
<summary><b>预览字幕变成方块（豆腐块）？</b></summary>

字体接口异常或系统字体注册表异常时会出现，重启应用通常可恢复；仍异常请提交
`%APPDATA%\subcraft-app\backend.log` 的 issue。
</details>

<details>
<summary><b>拖动字幕位置有偏移？</b></summary>

请更新到最新版本；中心点坐标以视频原始像素为准，旧版本存在屏幕像素与视频像素未换算的问题。
</details>

---

## 🌐 English Guide

<div align="center"><a href="#-中文使用说明">⬆ 回到中文说明 / Back to Chinese</a></div>

### ✨ Features

| Feature | Description |
|---|---|
| 🎙 Speech recognition | Local [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (GPU-accelerated, auto language detection), optional OpenAI Whisper API |
| 🌐 AI translation | OpenAI-compatible APIs (GPT / DeepSeek / Kimi / Qwen / GLM / OpenRouter) or DeepL; batch concurrent translation with strict timeline alignment |
| 🈶 Bilingual subtitles | Primary/secondary lines on screen; per-language font, size, color, outline, shadow and position |
| 👁 WYSIWYG preview | Real-time [jassub](https://github.com/ThaUnknown/jassub) (libass WebAssembly) rendering; style changes apply instantly even when paused |
| 🖱 Drag to position | **Drag subtitles directly on the video** (center-point mode); each language moves independently |
| ✏️ Editing | Edit text and timecodes inline, click a row to seek, delete segments, clean up empty rows |
| 💾 Export | **Burned-in subtitles** (visible in any player) or **lossless MKV soft-subs**, plus SRT/ASS files |

### 📦 Installation

**Option 1 — Download** from [Releases](../../releases):

- **Windows**: run `SubCraft-Setup-x.x.x.exe` (Python backend and ffmpeg bundled)
- **Linux**: extract `SubCraft-x.x.x-x64-linux.tar.gz`, then:
  ```bash
  sudo apt install ffmpeg python3-pip
  python3 -m pip install -r resources/backend/requirements.txt
  ./subcraft-app
  ```

**Option 2 — From source** (Python 3.13+, Node 20+):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
cd app; npm install; cd ..
cd app; npm run dev        # Electron starts the Python backend automatically
```

ffmpeg (~80MB) and the whisper model (~1.6GB for turbo) download automatically on first use.

### 🚀 Usage

#### 1 · Import video
Click **Import Video**; supports `mp4 / mkv / mov / avi / webm / ts / flv / wmv / m4v`. Resolution, duration and codecs are probed automatically.

#### 2 · Speech recognition (①)
Pick an engine and options:

| Option | Description |
|---|---|
| Engine | `local` faster-whisper (default, free, offline) or `openai` cloud API |
| Model | `large-v3-turbo` (recommended) / `large-v3` / `medium` / `small`; downloaded automatically |
| Device | `auto` (use CUDA when available) / `cuda` / `cpu` |
| Language | Auto-detect, or set the source language for better accuracy |

Cloud transcription auto-extracts a low-bitrate audio track (25MB upload limit — prefer local for long videos).

#### 3 · AI translation (②)
1. Open **⚙ Settings** and add a provider: presets for OpenAI / DeepSeek / Kimi / Qwen / GLM / OpenRouter, enter API key + model (keys stay on your machine); DeepL is also supported (free keys ending with `:fx` use the free endpoint).
2. Click **② Translate**, choose target language and provider.
3. Translation runs in batches with concurrency, and **segment count/timeline alignment is guaranteed** (falls back to per-line retry on parse errors).

#### 4 · Proofreading & editing
- Edit text and timecodes (`00:00:01.250`) directly in the list on the right.
- Click any row to seek the video there; the current line highlights during playback.
- Hover a row and click the **✕** to delete it; a red **Clean empty rows** button appears in the tab bar when empty segments exist.

#### 5 · Styling & drag positioning
The style panel edits the **selected track** (switch languages via track tabs); each language is saved independently.

**Fonts**: family (system fonts), size, color, outline color/width, shadow, bold, italic.

**Two positioning modes**:
1. **Alignment + margins** (default): 9-cell alignment (bottom-center, right-bottom…) plus vertical/left/right margins.
2. **Center point** (entered automatically when you drag): the subtitle **center** is placed at video-pixel coordinates; type exact X / Y in the panel; click **Reset layout** to go back to mode 1.

**Dragging**: hold and drag the subtitle on the video — the center follows your cursor in real time (local high-FPS rendering, works while paused). In bilingual mode **each language drags independently**: select its tab first; dragging moves only that language.

> 💡 Bilingual: tick **双语对照 (bilingual)** in the tab bar to stack both lines; click the **主** badge on a tab to choose which language goes on top.

#### 6 · Export (③)
You can tick multiple items in the export dialog:

| Item | Description | Use case |
|---|---|---|
| **Burned-in subtitles** | Rendered into the picture, **visible in any player**; libx264 crf 18, live progress, and a **real burn-in preview frame** (same ffmpeg+libass pipeline as the export) | Publishing finished videos |
| **Soft-subs (MKV)** | Styled ASS track (default) + SRT compatibility track muxed into MKV; streams copied, **100% lossless, instant** | Archiving, switchable subtitles |
| **SRT / ASS files** | Per-language files + merged bilingual file | Platform subtitle upload |

> ⚠ The Windows built-in player does not render embedded ASS soft-subs — use VLC / PotPlayer / mpv for soft-subbed files, or choose **burned-in** export.

### 🛠 Packaging

```powershell
.\.venv\Scripts\python.exe backend\build_exe.py --no-cuda   # backend exe
cd app; npm run pack                                        # Windows NSIS setup
cd app; npm run pack:linux                                  # Linux tar.gz
```

### 🏗 Architecture

```
┌────────────────────────────────────────────┐
│ Electron frontend (React 18 + TS + Vite)   │
│  player(jassub) · drag positioning         │
│  subtitle editing · export w/ preview      │
└───────────────┬────────────────────────────┘
                │ HTTP + WebSocket (random local port)
┌───────────────▼────────────────────────────┐
│ Python FastAPI backend (spawned child)     │
│  ASR(faster-whisper/OpenAI)                │
│  translation(LLM/DeepL) · ASS/SRT builder  │
│  ffmpeg soft-sub mux / hard-sub burn       │
└────────────────────────────────────────────┘
```

- Config & API keys: `%LOCALAPPDATA%\SubCraft\config.json` (**local only**)
- Backend log: `%APPDATA%\subcraft-app\backend.log`

### ❓ FAQ

<details>
<summary><b>No subtitles in the soft-subbed MKV?</b></summary>
The Windows built-in player doesn't render embedded ASS subs (the file is fine, an SRT compatibility track is included). Use VLC / PotPlayer / mpv, or choose burned-in export.
</details>

<details>
<summary><b>GPU not used?</b></summary>
Set the device to force CPU to verify; GPU needs CUDA 12 runtime.
</details>

<details>
<summary><b>25MB cloud transcription error?</b></summary>
OpenAI cloud engine uploads a compressed audio track with a 25MB limit — use local recognition for long videos.
</details>

<details>
<summary><b>Preview shows tofu boxes?</b></summary>
Usually a system font registry hiccup — restarting the app re-enumerates fonts. If it persists, open an issue with `%APPDATA%\subcraft-app\backend.log` attached.
</details>

---

<div align="center">

**License** · 仅供学习交流使用 / For learning purposes

</div>
