# AGENTS.md — SubCraft 字幕生成器

## 项目结构

- `backend/` — Python FastAPI 后端（Electron 以子进程拉起，HTTP+WebSocket 通信）
  - `app/services/` — 核心业务：asr(识别)、translator(翻译)、ass_builder/srt_builder(字幕)、ffmpeg_tool(封装)、fonts(系统字体)
  - `app/routers/` — media / transcribe(+translate) / export / config
  - `app/tasks.py` — 线程池任务 + WS 进度广播；长任务一律走 `manager.submit(job)`，job 接收 `progress_cb(p, msg)`
  - `run.py` — 入口（sys.path 自举，任意 cwd 可运行）
  - `build_exe.py` — PyInstaller 打包（`--no-cuda` 精简版）
- `app/` — Electron + React18 + TS + Vite 前端
  - `electron/main.cjs` — 拉起后端(随机空闲端口)、文件对话框 IPC；生产模式用 `process.resourcesPath/backend/subcraft-backend.exe` 并设 `SubCraft_TOOLS_DIR`
  - `src/components/` — TopBar(流程按钮+各对话框) / VideoPlayer(jassub) / SubtitleList / StylePanel / TrackTabs
  - `src/store.ts` — zustand 全局状态（tracks 为核心数据）
  - `src/api.ts` — fetch 封装 + `waitTask` 轮询 + `connectWs`
  - `scripts/cdp_smoke_test.mjs` — CDP 驱动的真实窗口冒烟测试
- `tools/ffmpeg/` — 运行时自动下载的新版 ffmpeg（gyan.dev essentials）
- 数据/配置目录：`%LOCALAPPDATA%/SubCraft`（可用 `SubCraft_DATA_DIR` 覆盖）

## 构建/测试命令

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -v   # 后端测试
cd app; npx tsc --noEmit && npx vite build              # 前端检查+构建
cd app; npm run dev                                     # 开发启动
```

## 关键约定

- 字幕段模型：`{start, end, text}`（秒，float）；轨道含独立 `style`（ASS 七字段对齐/颜色为 #RRGGBB，转换在 ass_builder.ass_color）
- 双语 ASS：单个 Dialogue 内 `主文本\N{\fn..\fs..}副文本`（行内覆盖实现双字体）
- 翻译必须保持段数对齐：批量编号发送 → 解析；数量不齐降级逐条（translator.parse_numbered_lines）
- ffmpeg 兼容性：必须兼容无 `-disposition` 的旧版（`_supports_disposition` 按 libavformat>=58 判断）
- Python 3.13 + Windows 中文环境：子进程输出一律 `encoding="utf-8", errors="replace"`
- 前端注释与 UI 文案使用中文
