<div align="center">

# SubCraft

视频语音识别、AI 多厂商翻译、双语排版与字幕制作工具。

[![CI](https://github.com/gengsha/subcraft/actions/workflows/ci.yml/badge.svg)](https://github.com/gengsha/subcraft/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/gengsha/subcraft)](https://github.com/gengsha/subcraft/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

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
  - [8. MCP 服务（AI 客户端接入）](#8-mcp-服务ai-客户端接入)
  - [9. 命令行 (CLI)](#9-命令行-cli)
- [编译与构建](#编译与构建)
- [技术架构](#技术架构)
- [常见问题 (FAQ)](#常见问题-faq)
- [开源协议](#开源协议)

---

### 功能特性

- **语音识别 (ASR)**：支持基于 faster-whisper 的本地离线识别（支持 NVIDIA CUDA GPU 加速），以及 OpenAI Whisper 云端 API。
- **AI 翻译**：支持接入 OpenAI、DeepSeek、Kimi (Moonshot)、通义千问 (Qwen)、智谱 GLM、Claude / OpenRouter 及 DeepL 等服务。采用分批并发与段号对齐机制，保持时间轴与段落对应；每批附带前文作为语境，并支持**术语表**（每行「原文=译文」），保证人名与术语前后一致。
- **智能断句**：基于词级时间戳，把 Whisper 过长的识别段按标点与停顿切成适合上屏的短句（默认单条约 21 个汉字 / 42 个英文字符、7 秒以内，可在设置中调整或关闭）。
- **双语与多轨道管理**：支持源语言与多个翻译语言轨道，可自由切换主副语言并同屏渲染双语字幕。
- **实时预览与画布拖动**：基于 jassub (libass WASM) 实现播放器内的 ASS 字幕实时渲染；支持直接在视频画面上拖动字幕调整位置（双语各轨道独立定位）。
- **字幕编辑**：支持文本行内编辑、时间码调整、点击跳转试听、当前播放句高亮滚动以及空行清理。
- **多格式导出**：
  - 内嵌硬字幕 (MP4)：使用 ffmpeg 进行画面压制（libx264 CRF 18），支持导出前实时预览真实烧录帧。
  - 软字幕封装 (MKV)：无损封装视频流与 ASS / SRT 字幕轨，无需重新编码。
  - 独立字幕文件：支持导出单轨或双语合并的 SRT / ASS 文件。
- **MCP 服务**：内置 Model Context Protocol 服务端，把识别/翻译/校对/样式/导出全链路开放给 Claude、Cursor、Qoder 等 AI 客户端，一句话即可驱动字幕生产。

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

#### 8. MCP 服务（AI 客户端接入）

SubCraft 内置 MCP（Model Context Protocol）服务端，把「识别 → 翻译 → 校对 → 样式 → 导出」整条链路开放给
Claude Desktop / Cursor / Qoder / Cline 等 AI 客户端，用自然语言即可驱动字幕生产。

```powershell
# 1. 安装 MCP 依赖（桌面客户端不需要，仅 MCP 服务需要）
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-mcp.txt

# 2. 自检：打印全部工具清单
.\.venv\Scripts\python.exe backend\mcp_server.py --list-tools

# 3. 端到端冒烟测试（真实拉起 MCP 子进程跑完整链路）
.\.venv\Scripts\python.exe scripts\mcp_smoke_test.py            # 导入/编辑/样式/导出/封装/预览帧
.\.venv\Scripts\python.exe scripts\mcp_smoke_test.py --asr      # 追加真实语音识别（TTS 合成语音）
```

在 AI 客户端的 MCP 配置中登记（路径按实际仓库位置修改）：

```json
{
  "mcpServers": {
    "subcraft": {
      "command": "E:\\projects\\subcraft\\.venv\\Scripts\\python.exe",
      "args": ["E:\\projects\\subcraft\\backend\\mcp_server.py"]
    }
  }
}
```

**工具一览（27 个）**

| 分类 | 工具 |
| --- | --- |
| 环境 | `subcraft_status` 自检（ffmpeg/CUDA/已配厂商）、`subcraft_probe_media` 媒体探测、`subcraft_list_fonts` 字体列表 |
| 生成 | `subcraft_transcribe` 语音识别、`subcraft_translate` AI 翻译、`subcraft_add_translation` 写入调用方 AI 自己的译文（免 API Key）、`subcraft_load_subtitle_file` 导入 srt/vtt/ass、`subcraft_generate_subtitles` 一键流水线 |
| 编辑 | `subcraft_list_tracks`、`subcraft_get_segments`（分页/搜索）、`subcraft_edit_segments`（批量改文本与时间码）、`subcraft_delete_segments`、`subcraft_clean_empty_segments`、`subcraft_set_style` |
| 时间轴 | `subcraft_split_segment` 拆分（支持「前半\|后半」与指定切点）、`subcraft_merge_segments` 合并、`subcraft_shift_track` 整轨/区间平移与缩放、`subcraft_snap_to_cuts` 检测镜头切点让字幕不跨镜头、`subcraft_check_timing` 检查重叠/过短/过长/阅读速度并可一键修重叠 |
| 导出 | `subcraft_build_ass`、`subcraft_export_subtitle_files`（srt/ass 单语+双语）、`subcraft_export_video`（soft 无损封装 / hard 烧录）、`subcraft_preview_frame`（真实烧录预览图） |
| 任务/会话 | `subcraft_job_status`（长任务轮询）、`subcraft_save_project` / `subcraft_load_project`、`subcraft_clear_session` |

要点：

- **配置复用**：翻译厂商 API Key 直接复用桌面客户端「设置」里保存的 `%LOCALAPPDATA%\SubCraft\config.json`，MCP 只读不写；也可在调用时临时传 `api_key` / `base_url`。
- **让 AI 自己当翻译（免 API Key）**：这是 GUI 没有的能力。没配置翻译厂商时，接入的 AI（Claude、Cursor 等）可以用 `subcraft_get_segments` 分页读原文，自己结合全片语境翻译，再通过 `subcraft_add_translation` 分批写回一条逐段对齐的翻译轨，然后照常导出或压制。人名、梗和语气的统一通常比逐批调接口更好；`subcraft_translate` 报「未配置」时也会提示走这条路。
- **时间轴由 AI 精修**：结构操作（拆分、合并、平移）会自动同步到与之逐段对齐的译文轨，双语不会错位；`subcraft_edit_segments` 改完会校验重叠、过短、过长和阅读速度，因重排导致序号变化时也会返回新旧序号对照。典型用法：先 `subcraft_snap_to_cuts` 自动贴齐镜头切点，剩下跨镜头的长句按返回的 `need_split` 用 `subcraft_split_segment` 在切点处拆开。
- **长任务**：识别/翻译/压制支持 `wait=false` 立即返回 `job_id`，再用 `subcraft_job_status` 轮询；`wait=true` 时按 MCP 协议上报进度。
- **会话态**：字幕轨保存在 MCP 进程内存中（`t1`/`t2`...），跨会话用 `subcraft_save_project` / `subcraft_load_project` 落盘恢复。
- **传输**：默认 stdio；`--transport streamable-http --port 47660` 可切换为 HTTP。

#### 9. 命令行 (CLI)

不启动桌面客户端、也不接 AI 客户端，直接在终端跑通全链路（适合脚本化与批处理）：

```powershell
.\.venv\Scripts\python.exe backend\cli.py status                                  # 环境自检
.\.venv\Scripts\python.exe backend\cli.py gen video.mp4 -t zh --video soft        # 一条龙：识别+翻译+导出+封装
.\.venv\Scripts\python.exe backend\cli.py gen video.mp4 -t zh --primary-target    # 双语以译文为主行
.\.venv\Scripts\python.exe backend\cli.py transcribe video.mp4 -o out             # 只识别
.\.venv\Scripts\python.exe backend\cli.py translate in.en.srt -t zh -o out        # 只翻译（含双语导出）
.\.venv\Scripts\python.exe backend\cli.py dump in.en.srt -o src.txt               # 列出「序号. 原文」，交给 AI 自己翻译
.\.venv\Scripts\python.exe backend\cli.py translate in.en.srt -t zh --translations zh.txt -o out  # 写回 AI 的译文，不调 API
.\.venv\Scripts\python.exe backend\cli.py retime in.srt --snap-cuts --media v.mp4 --split "6@9.54:前半|后半"  # 时间轴精修
.\.venv\Scripts\python.exe backend\cli.py export -s zh.srt -s en.srt --media v.mp4 --video hard -o out
.\.venv\Scripts\python.exe backend\cli.py preview -s zh.srt -s en.srt --media v.mp4 --time 12.5 -o f.jpg
```

| 命令 | 说明 |
| --- | --- |
| `status` / `probe` / `fonts` | 环境自检（ffmpeg/CUDA/厂商）、媒体探测、系统字体列表 |
| `transcribe` | 语音识别并导出字幕文件（`--engine` / `--model` / `--lang`） |
| `translate` | 翻译字幕文件并导出单语+双语（`--provider` / `--primary-target` / `--glossary`；`--translations` 直接使用 AI 自己翻好的译文） |
| `retime` | 调整时间轴：`--split N@秒:前半\|后半`、`--merge N-M`、`--shift` / `--scale` / `--from-time`、`--snap-cuts --media v.mp4` 贴齐镜头切点、`--fix-overlaps`、`--check` 只检查 |
| `dump` | 按「序号. 文本」列出字幕，供 Codex / Claude Code 等终端 AI 读取后自行翻译 |
| `gen` | 一条龙：识别 → 可选翻译 → 导出字幕 / 软封装 / 硬烧录 |
| `export` | 用已有字幕文件导出字幕 / 封装 / 烧录（`-s` 可重复，`--primary` 指定主行） |
| `preview` | 渲染指定时间点的真实烧录预览图（与硬字幕同一 ffmpeg 管线） |

约定：进度走 stderr、结果走 stdout；`--json` 输出机器可读 JSON；预期内错误退出码 2；
翻译凭据复用桌面客户端本地配置；非主轨自动套副语言样式（字号 0.7 倍 + 淡黄）。

---

### 编译与构建

```powershell
# 1. 编译独立 Python 后端 (输出至 backend/dist/subcraft-backend.exe)
.\.venv\Scripts\python.exe backend\build_exe.py --no-cuda

# 2. 构建 Windows 安装包与便携包 (输出至 release/)
cd app
npm run pack

# 3. 运行测试（先安装开发依赖：pip install -r backend\requirements-dev.txt）
.\.venv\Scripts\python.exe -m pytest -v
cd app
npx tsc --noEmit
npx vite build
```

---

### 技术架构

- **宿主进程**：Electron 33 + TypeScript，负责窗口管理、动态端口分配与 Python 子进程守护。
- **前端界面**：React 18 + Zustand + Vite，集成 jassub (libass WASM) 实现字幕实时渲染。
- **后端服务**：Python 3.13 + FastAPI，负责 faster-whisper ASR、多厂商 AI 翻译、ASS/SRT 格式构建与 ffmpeg 封装/压制。
- **MCP 服务**：`backend/mcp_server.py`（stdio），复用后端 services 层把全链路暴露为 27 个 MCP 工具；会话轨道与后台任务池在 `backend/app/mcp/`。
- **数据存储**：本地配置文件 `%LOCALAPPDATA%\SubCraft\config.json`，运行日志 `%APPDATA%\subcraft-app\backend.log`。
- **本地安全**：后端只监听 `127.0.0.1`，并且每次启动由 Electron 生成随机令牌（`SUBCRAFT_TOKEN`），所有请求需携带令牌；CORS 只放行应用自身来源并校验 Host，防止浏览器中的网页跨站访问本地接口。手动 `python backend/run.py` 调试时不设令牌即不校验。

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
  - [8. MCP Server (AI Client Integration)](#8-mcp-server-ai-client-integration)
  - [9. Command Line (CLI)](#9-command-line-cli)
- [Build & Packaging](#build--packaging)
- [Architecture](#architecture)
- [FAQ](#faq)
- [License](#license)

---

### Features

- **Speech Recognition (ASR)**: Embedded faster-whisper for offline local transcription (with NVIDIA CUDA GPU support), plus OpenAI Whisper API compatibility.
- **AI Translation**: Connects to OpenAI, DeepSeek, Kimi, Qwen, GLM, Claude / OpenRouter, and DeepL. Uses batched concurrency to maintain 1:1 timeline alignment; each batch carries preceding lines as context, and a **glossary** (one `source=target` per line) keeps names and terms consistent.
- **Smart Line Splitting**: Uses word-level timestamps to split overly long Whisper segments at punctuation and pauses into readable subtitle lines (default ~21 CJK / 42 Latin characters and 7 s per line; adjustable or off in Settings).
- **Bilingual & Multi-Track**: Manage multiple source and translation tracks. Independent font, color, border, and position controls for primary and secondary subtitles.
- **Real-Time Preview & Canvas Dragging**: Built on jassub (libass WASM) for real-time subtitle rendering. Directly drag subtitles across the video canvas to adjust positioning independently per track.
- **Timeline Editor**: In-place text editing, precise timecode tuning, seek-on-click, active sentence highlighting, and blank row cleanup.
- **Multi-Format Export**:
  - Hardsub (MP4): Burns subtitles into video using libx264 CRF 18 with accurate pre-export preview frames.
  - Lossless Softsub (MKV): Direct stream copy with embedded ASS and fallback SRT tracks.
  - Subtitle Files: Standalone or merged bilingual `.srt` / `.ass` files.
- **MCP Server**: Built-in Model Context Protocol server exposing the whole pipeline (ASR, translation, editing, styling, export) to AI clients such as Claude, Cursor and Qoder.

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

#### 8. MCP Server (AI Client Integration)

SubCraft ships an MCP (Model Context Protocol) server so AI clients (Claude Desktop, Cursor, Qoder, Cline, ...)
can drive the full pipeline — transcribe → translate → proofread → style → export — with natural language.

```powershell
# 1. Install MCP dependencies (only needed for the MCP server, not the desktop app)
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-mcp.txt

# 2. Self-check: print the registered tool list
.\.venv\Scripts\python.exe backend\mcp_server.py --list-tools

# 3. End-to-end smoke test (spawns a real MCP subprocess and runs the full chain)
.\.venv\Scripts\python.exe scripts\mcp_smoke_test.py            # import/edit/style/export/mux/preview frame
.\.venv\Scripts\python.exe scripts\mcp_smoke_test.py --asr      # plus real speech recognition (TTS-generated voice)
```

Register it in your AI client's MCP config (adjust paths to your checkout):

```json
{
  "mcpServers": {
    "subcraft": {
      "command": "E:\\projects\\subcraft\\.venv\\Scripts\\python.exe",
      "args": ["E:\\projects\\subcraft\\backend\\mcp_server.py"]
    }
  }
}
```

**Tools (21)**

| Group | Tools |
| --- | --- |
| Environment | `subcraft_status` self-check (ffmpeg/CUDA/configured providers), `subcraft_probe_media`, `subcraft_list_fonts` |
| Generation | `subcraft_transcribe` ASR, `subcraft_translate` AI translation, `subcraft_load_subtitle_file` (srt/vtt/ass), `subcraft_generate_subtitles` one-shot pipeline |
| Editing | `subcraft_list_tracks`, `subcraft_get_segments` (paging/search), `subcraft_edit_segments` (batch text & timecode edits), `subcraft_delete_segments`, `subcraft_clean_empty_segments`, `subcraft_set_style` |
| Export | `subcraft_build_ass`, `subcraft_export_subtitle_files` (mono + bilingual srt/ass), `subcraft_export_video` (lossless softsub / burned hardsub), `subcraft_preview_frame` (real burn-in preview image) |
| Jobs & session | `subcraft_job_status` (poll long tasks), `subcraft_save_project` / `subcraft_load_project`, `subcraft_clear_session` |

Notes:

- **Config reuse**: translation provider API keys are read from the desktop app's local config (`%LOCALAPPDATA%\SubCraft\config.json`); the MCP server never writes it. Per-call `api_key` / `base_url` overrides are also accepted.
- **Long tasks**: ASR/translation/encoding accept `wait=false` to return a `job_id` immediately (poll with `subcraft_job_status`); with `wait=true` progress is reported over the MCP protocol.
- **Session state**: tracks live in the MCP process memory (`t1`, `t2`, ...); persist across sessions with `subcraft_save_project` / `subcraft_load_project`.
- **Transport**: stdio by default; `--transport streamable-http --port 47660` switches to HTTP.

#### 9. Command Line (CLI)

Run the whole pipeline straight from a terminal — no desktop app, no AI client required
(ideal for scripting and batch jobs):

```powershell
.\.venv\Scripts\python.exe backend\cli.py status                                  # environment self-check
.\.venv\Scripts\python.exe backend\cli.py gen video.mp4 -t zh --video soft        # one-shot: ASR+translate+export+mux
.\.venv\Scripts\python.exe backend\cli.py gen video.mp4 -t zh --primary-target    # translation as the primary bilingual line
.\.venv\Scripts\python.exe backend\cli.py transcribe video.mp4 -o out             # ASR only
.\.venv\Scripts\python.exe backend\cli.py translate in.en.srt -t zh -o out        # translate only (plus bilingual export)
.\.venv\Scripts\python.exe backend\cli.py export -s zh.srt -s en.srt --media v.mp4 --video hard -o out
.\.venv\Scripts\python.exe backend\cli.py preview -s zh.srt -s en.srt --media v.mp4 --time 12.5 -o f.jpg
```

| Command | Description |
| --- | --- |
| `status` / `probe` / `fonts` | Self-check (ffmpeg/CUDA/providers), media probe, system font list |
| `transcribe` | Speech recognition and subtitle file export (`--engine` / `--model` / `--lang`) |
| `translate` | Translate a subtitle file, export mono + bilingual (`--provider` / `--primary-target`) |
| `gen` | One-shot pipeline: ASR → optional translation → subtitle files / softsub / hardsub |
| `export` | Export/mux/burn from existing subtitle files (`-s` repeatable, `--primary` picks the main line) |
| `preview` | Render a real burn-in preview frame (same ffmpeg pipeline as hardsub) |

Conventions: progress on stderr, results on stdout; `--json` for machine-readable output;
expected errors exit with code 2; translation credentials are reused from the desktop app's
local config; non-primary tracks automatically get the secondary style (0.7x size, pale yellow).

---

### Build & Packaging

```powershell
# Build standalone Python backend
.\.venv\Scripts\python.exe backend\build_exe.py --no-cuda

# Package Windows desktop app
cd app
npm run pack

# Run test suites (install dev deps first: pip install -r backend\requirements-dev.txt)
.\.venv\Scripts\python.exe -m pytest -v
cd app
npx tsc --noEmit
npx vite build
```

---

### Architecture

- **Host (Main Process)**: Electron 33 + TypeScript for process lifecycle, dynamic port binding, and native file dialogs.
- **Frontend (Renderer Process)**: React 18 + Zustand + Vite with jassub (libass WASM) subtitle rendering.
- **Backend Services**: Python 3.13 + FastAPI for faster-whisper ASR, LLM translation, ASS/SRT formatting, and ffmpeg processing.
- **MCP Server**: `backend/mcp_server.py` (stdio) reuses the backend service layer to expose 21 MCP tools; session tracks and the background job pool live in `backend/app/mcp/`.
- **Local Security**: The backend binds to `127.0.0.1` and requires a random per-launch token (`SUBCRAFT_TOKEN`) generated by Electron; CORS only allows the app's own origins and the Host header is validated, so web pages in your browser cannot call the local API. When running `python backend/run.py` manually without the token, auth is skipped for debugging.

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
