<div align="center">

# SubCraft (SubCraft 字幕生成器)

视频语音识别、AI 多厂商翻译、双语排版与字幕制作工具。

[中文](#中文) · [English](#english)

</div>

---

## 中文

### 目录
- [功能特性](#功能特性)
- [下载与运行](#下载与运行)
  - [Windows 便携版（推荐）](#windows-便携版推荐)
  - [Linux 运行](#linux-运行)
  - [源码运行（开发模式）](#源码运行开发模式)
- [使用说明](#使用说明)
  - [1. 配置 API](#1-配置-api)
  - [2. 导入视频](#2-导入视频)
  - [3. 语音识别 (ASR)](#3-语音识别-asr)
  - [4. AI 翻译与双语轨道](#4-ai-翻译与双语轨道)
  - [5. 编辑与校对](#5-编辑与校对)
  - [6. 样式调整与画布拖动定位](#6-样式调整与画布拖动定位)
  - [7. 导出字幕与视频](#7-导出字幕与视频)
- [编译与构建](#编译与构建)
- [技术架构](#技术架构)
- [常见问题 (FAQ)](#常见问题-faq)
- [开源协议](#开源协议)

---

### 功能特性

- **语音识别 (ASR)**：支持基于 faster-whisper 的本地离线识别（支持 NVIDIA CUDA GPU 加速），以及 OpenAI Whisper 云端 API。
- **AI 翻译**：支持接入 OpenAI、DeepSeek、Kimi (Moonshot)、通义千问 (Qwen)、智谱 GLM、Claude / OpenRouter 及 DeepL 等服务。采用分批并发与段号对齐机制，保持时间轴与段落对应。
- **双语与多轨道管理**：支持源语言与多个翻译语言轨道，可自由切换主副语言并同屏渲染双语字幕。
- **实时预览与画布拖动**：基于 jassub (libass WASM) 实现播放器内的 ASS 字幕实时渲染；支持直接在视频画面上拖动字幕调整位置（双语各轨道独立定位）。
- **字幕编辑**：支持文本行内编辑、时间码调整、点击跳转试听、当前播放句高亮滚动以及空行清理。
- **多格式导出**：
  - 内嵌硬字幕 (MP4)：使用 ffmpeg 进行画面压制（libx264 CRF 18），支持导出前实时预览真实烧录帧。
  - 软字幕封装 (MKV)：无损封装视频流与 ASS / SRT 字幕轨，无需重新编码。
  - 独立字幕文件：支持导出单轨或双语合并的 SRT / ASS 文件。

---

### 下载与运行

#### Windows 便携版（推荐）
前往 [Releases](../../releases) 页面下载 `SubCraft-x.x.x-win-x64.zip`。
解压后直接运行 `SubCraft.exe` 即可使用。已内置独立 Python 后端与 ffmpeg 运行时，无需单独配置环境。

#### Linux 运行
下载 `SubCraft-x.x.x-x64-linux.tar.gz` 后解压：
```bash
# 1. 解压发布包
tar -xzf SubCraft-x.x.x-x64-linux.tar.gz
cd SubCraft-x.x.x-x64-linux

# 2. 安装系统依赖与后端依赖 (Ubuntu / Debian 示例)
sudo apt update && sudo apt install -y ffmpeg python3 python3-pip
python3 -m pip install -r resources/backend/requirements.txt

# 3. 运行客户端
./subcraft-app
```

#### 源码运行（开发模式）
**环境要求**：
- Python 3.13+
- Node.js 20+
- （可选）NVIDIA 显卡驱动与 CUDA 12 运行环境（用于本地 GPU 识别加速）

```powershell
# 1. 克隆代码仓库
git clone https://github.com/gengsha/subcraft.git
cd subcraft

# 2. 配置 Python 后端环境
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# 3. 安装前端依赖
cd app
npm install
cd ..

# 4. 启动开发模式
cd app
npm run dev
```

---

### 使用说明

#### 1. 配置 API
点击顶部「设置」按钮：
- **AI 翻译服务**：添加并选择翻译厂商，填写 Base URL、API Key 与模型名称（如 `deepseek-chat`、`gpt-4o-mini`、`moonshot-v1-8k`），支持连接测试。
- **DeepL**：填入 DeepL API Key（支持免费版与付费版）。
- **语音识别默认项**：可配置默认 Whisper 模型（如 `large-v3-turbo`）与运行设备（自动 / GPU / CPU）。
- *配置仅保存在本地设备（`%LOCALAPPDATA%\SubCraft\config.json`），不会上传任何第三方。*

#### 2. 导入视频
点击「导入视频」选择音视频文件（支持 mp4, mkv, mov, avi, webm, ts, flv 等主流格式）。

#### 3. 语音识别 (ASR)
点击「1 识别字幕」：
- 选择本地 faster-whisper 或 OpenAI 云端 API。
- 选择模型规格（如 `large-v3-turbo`、`medium`、`small` 等）。
- 可选择自动检测语种或指定语言以提升准确率。
- 识别完成后将自动创建源语言字幕轨 `[SRC]`。

#### 4. AI 翻译与双语轨道
点击「2 翻译」：
- 选择源字幕轨与目标翻译语言。
- 选择已配置的 AI 模型或 DeepL 服务。
- 翻译完成后将生成翻译字幕轨 `[TRN]`。
- 勾选「双语对照」可同屏显示双语字幕，点击轨道页签上的「主 / 设为主」可切换主语言。

#### 5. 编辑与校对
在右侧字幕列表中：
- 直接点击文本框修改字幕内容。
- 双击时间码可精确调整起止时间（格式：`00:00:00.000`）。
- 点击任意字幕行可直接跳转到对应视频时间点。
- 悬停可删除单段字幕；若有空段落可点击「清理空段」一键剔除。

#### 6. 样式调整与画布拖动定位
在左下角样式面板中：
- 可为各个轨道独立设置字体、字号、文字颜色、描边粗细与颜色、阴影等。
- **画布拖动定位**：在视频播放器画面上按住字幕即可自由拖动调整位置，双语各轨支持独立拖动。
- 点击「恢复默认布局」可重置为九宫格居中对齐。

#### 7. 导出字幕与视频
点击「3 导出」：
- **硬字幕内嵌 (MP4)**：将字幕烧录到画面中（libx264 CRF 18），兼容所有播放器与社交平台。面板支持查看真实渲染预览帧。
- **软字幕封装 (MKV)**：无损封装视频流与 ASS / SRT 软字幕轨，秒级完成，画质零损耗。
- **字幕文件**：独立导出单轨或双语合并的 `.srt` / `.ass` 文件。

---

### 编译与构建

```powershell
# 1. 编译独立 Python 后端 (输出至 backend/dist/subcraft-backend.exe)
.\.venv\Scripts\python.exe backend\build_exe.py --no-cuda

# 2. 构建 Windows 安装包与便携包 (输出至 release/)
cd app
npm run pack

# 3. 运行测试
.\.venv\Scripts\python.exe -m pytest backend\tests -v
cd app
npx tsc --noEmit
npx vite build
```

---

### 技术架构

- **宿主进程**：Electron 33 + TypeScript，负责窗口管理、动态端口分配与 Python 子进程守护。
- **前端界面**：React 18 + Zustand + Vite，集成 jassub (libass WASM) 实现字幕实时渲染。
- **后端服务**：Python 3.13 + FastAPI，负责 faster-whisper ASR、多厂商 AI 翻译、ASS/SRT 格式构建与 ffmpeg 封装/压制。
- **数据存储**：本地配置文件 `%LOCALAPPDATA%\SubCraft\config.json`，运行日志 `%APPDATA%\subcraft-app\backend.log`。

---

### 常见问题 (FAQ)

**Q: 导出的 MKV 软字幕视频在部分播放器中看不到样式或字幕？**  
A: Windows 自带播放器对 ASS 特效字幕支持有限。建议使用 VLC、PotPlayer、mpv 或 IINA 打开；若需在网页或手机端通用播放，请在导出时选择「内嵌字幕（烧录进画面）」。

**Q: 本地识别如何启用 GPU 加速？**  
A: 需要配备 NVIDIA 显卡并安装支持 CUDA 12 的驱动程序。若无独立显卡，可在设置中将设备设为「CPU」。

**Q: 字体显示方块（乱码）？**  
A: 选中的字体可能缺少对应语言的字形。请在样式面板中选择支持相应语言的字体（例如微软雅黑、思源黑体、Arial 等）。

---

### 开源协议

本项目基于 MIT License 开源。

---

## English

### Table of Contents
- [Features](#features)
- [Download & Installation](#download--installation)
  - [Windows Portable (Recommended)](#windows-portable-recommended)
  - [Linux](#linux)
  - [From Source (Development)](#from-source-development)
- [Usage Guide](#usage-guide)
  - [1. Configure API Providers](#1-configure-api-providers)
  - [2. Import Video](#2-import-video)
  - [3. Speech Recognition (ASR)](#3-speech-recognition-asr)
  - [4. AI Translation & Bilingual Tracks](#4-ai-translation--bilingual-tracks)
  - [5. Subtitle Editing](#5-subtitle-editing)
  - [6. Styling & Canvas Drag Positioning](#6-styling--canvas-drag-positioning)
  - [7. Export Subtitles & Video](#7-export-subtitles--video)
- [Build & Packaging](#build--packaging)
- [Architecture](#architecture)
- [FAQ](#faq)
- [License](#license)

---

### Features

- **Speech Recognition (ASR)**: Embedded faster-whisper for offline local transcription (with NVIDIA CUDA GPU support), plus OpenAI Whisper API compatibility.
- **AI Translation**: Connects to OpenAI, DeepSeek, Kimi, Qwen, GLM, Claude / OpenRouter, and DeepL. Uses batched concurrency to maintain 1:1 timeline alignment.
- **Bilingual & Multi-Track**: Manage multiple source and translation tracks. Independent font, color, border, and position controls for primary and secondary subtitles.
- **Real-Time Preview & Canvas Dragging**: Built on jassub (libass WASM) for real-time subtitle rendering. Directly drag subtitles across the video canvas to adjust positioning independently per track.
- **Timeline Editor**: In-place text editing, precise timecode tuning, seek-on-click, active sentence highlighting, and blank row cleanup.
- **Multi-Format Export**:
  - Hardsub (MP4): Burns subtitles into video using libx264 CRF 18 with accurate pre-export preview frames.
  - Lossless Softsub (MKV): Direct stream copy with embedded ASS and fallback SRT tracks.
  - Subtitle Files: Standalone or merged bilingual `.srt` / `.ass` files.

---

### Download & Installation

#### Windows Portable (Recommended)
Download `SubCraft-x.x.x-win-x64.zip` from [Releases](../../releases).
Extract and run `SubCraft.exe`. Standalone Python backend and ffmpeg binaries are pre-bundled.

#### Linux
```bash
# 1. Extract package
tar -xzf SubCraft-x.x.x-x64-linux.tar.gz
cd SubCraft-x.x.x-x64-linux

# 2. Install dependencies (Ubuntu / Debian)
sudo apt update && sudo apt install -y ffmpeg python3 python3-pip
python3 -m pip install -r resources/backend/requirements.txt

# 3. Run application
./subcraft-app
```

#### From Source (Development)
**Prerequisites**:
- Python 3.13+
- Node.js 20+
- (Optional) NVIDIA GPU + CUDA 12 for hardware ASR acceleration

```powershell
# 1. Clone repository
git clone https://github.com/gengsha/subcraft.git
cd subcraft

# 2. Setup Python environment
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# 3. Install frontend dependencies
cd app
npm install
cd ..

# 4. Start development mode
cd app
npm run dev
```

---

### Usage Guide

#### 1. Configure API Providers
Click "Settings" in the top bar:
- Add translation providers with Base URL, API Key, and Model name (e.g., `deepseek-chat`, `gpt-4o-mini`, `moonshot-v1-8k`).
- DeepL API key (Free and Pro supported).
- Set default Whisper model and compute device (Auto / GPU / CPU).
- *All keys and configs are stored strictly locally in `%LOCALAPPDATA%\SubCraft\config.json`.*

#### 2. Import Video
Click "Import Video" to open local media files (supports mp4, mkv, mov, avi, webm, ts, flv, etc.).

#### 3. Speech Recognition (ASR)
Click "1 Transcribe":
- Choose local faster-whisper or OpenAI cloud API.
- Select model size (e.g. `large-v3-turbo`, `medium`, `small`).
- Choose automatic language detection or specify language for better accuracy.
- Generates a source track `[SRC]`.

#### 4. AI Translation & Bilingual Tracks
Click "2 Translate":
- Select source track and target language.
- Select configured AI model or DeepL.
- Generates a translation track `[TRN]`.
- Check "Bilingual" to view both languages on screen simultaneously.

#### 5. Subtitle Editing
In the right-hand subtitle panel:
- Edit text inline.
- Adjust timestamps (`00:00:00.000` format).
- Click any row to jump to the corresponding video frame.
- Delete individual rows or clean empty lines across tracks.

#### 6. Styling & Canvas Drag Positioning
In the lower-left style panel:
- Customize font family, font size, text color, outline width/color, shadow depth.
- **Canvas Dragging**: Click and drag subtitles directly on the video player to reposition. Primary and secondary subtitles can be positioned independently.
- Click "Reset Layout" to return to standard 9-cell center alignment.

#### 7. Export Subtitles & Video
Click "3 Export":
- **Hardsub (MP4)**: Burns subtitles into video (libx264 CRF 18) for universal compatibility.
- **Softsub (MKV)**: Lossless multiplexing with ASS/SRT tracks in seconds.
- **Subtitle Files**: Exports individual or merged `.srt` / `.ass` files.

---

### Build & Packaging

```powershell
# Build standalone Python backend
.\.venv\Scripts\python.exe backend\build_exe.py --no-cuda

# Package Windows desktop app
cd app
npm run pack

# Run test suites
.\.venv\Scripts\python.exe -m pytest backend\tests -v
cd app
npx tsc --noEmit
npx vite build
```

---

### Architecture

- **Host (Main Process)**: Electron 33 + TypeScript for process lifecycle, dynamic port binding, and native file dialogs.
- **Frontend (Renderer Process)**: React 18 + Zustand + Vite with jassub (libass WASM) subtitle rendering.
- **Backend Services**: Python 3.13 + FastAPI for faster-whisper ASR, LLM translation, ASS/SRT formatting, and ffmpeg processing.

---

### FAQ

**Q: Subtitles do not appear when opening MKV in default Windows player?**  
A: Default Windows player has limited ASS softsub support. Use VLC, PotPlayer, mpv, or IINA, or choose Hardsub (MP4) during export.

**Q: How to enable GPU acceleration for local transcription?**  
A: Requires an NVIDIA GPU with CUDA 12 compatible drivers. For non-NVIDIA systems, set device to "CPU" in Settings.

**Q: Subtitles render as square tofu blocks?**  
A: The selected font does not contain glyphs for the active language. Switch to a universal font (e.g. Microsoft YaHei, Arial, Noto Sans) in the style panel.

---

### License

Distributed under the MIT License.
