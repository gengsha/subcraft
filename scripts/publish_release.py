import os
import sys
import subprocess
import httpx

REPO = "gengsha/subcraft"
TAG = "v0.1.1"
TITLE = "SubCraft 字幕生成器 v0.1.1"

ASSETS = [
    os.path.abspath(r"release\SubCraft-0.1.1-win-x64.zip"),
    os.path.abspath(r"release\SubCraft-0.1.1-portable.exe"),
    os.path.abspath(r"release\linux\SubCraft-0.1.1-x64-linux.tar.gz"),
]

def get_github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    try:
        proc = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True,
            text=True,
            check=True
        )
        for line in proc.stdout.splitlines():
            if line.startswith("password="):
                return line.split("=", 1)[1].strip()
    except Exception as e:
        print(f"Warning: Could not get credential from git: {e}")
    return ""

BODY = """# SubCraft v0.1.1

视频语音识别、AI 多厂商翻译、双语排版与字幕制作工具。

---

### 资产下载 (Downloads)

| 平台 | 文件名 | 说明 |
|---|---|---|
| **Windows x64** | `SubCraft-0.1.1-win-x64.zip` | 便携免安装版（内置 Python 独立后端与 ffmpeg 运行时，解压即用） |
| **Windows x64** | `SubCraft-0.1.1-portable.exe` | 单文件便携运行版 |
| **Linux x64** | `SubCraft-0.1.1-x64-linux.tar.gz` | Linux 独立安装包（解压后依赖系统 python3 与 ffmpeg） |

#### v0.1.1 更新说明：
- 项目整体更名为 SubCraft：安装包、可执行文件、数据目录与 MCP 工具名统一为 subcraft 系，数据目录迁移至 `%LOCALAPPDATA%\SubCraft`。
- 修复打包环境下 Whisper 语音识别缺失 `cublas64_12.dll` 导致报错的问题。
- 增强 CUDA 动态库检索与真实可用性校验，未配置 CUDA 动态库时自动回退并平滑执行 CPU 识别。
- 识别执行期增加自动容错降级重试机制。

#### Windows 使用提示：
下载后解压到任意目录，双击运行 `SubCraft.exe` 即可使用。首次使用本地语音识别时，将自动按需下载 Whisper 模型权重。

#### Linux 使用提示：
```bash
# 解压
tar -xzf SubCraft-0.1.1-x64-linux.tar.gz
cd SubCraft-0.1.1-x64-linux

# 安装系统与后端依赖 (Ubuntu / Debian 示例)
sudo apt update && sudo apt install -y ffmpeg python3 python3-pip
python3 -m pip install -r resources/backend/requirements.txt

# 运行客户端
./subcraft-app
```

---

### 功能特性

- 语音识别 (ASR)：内置 faster-whisper（支持 NVIDIA CUDA GPU 加速与离线识别），同时兼容 OpenAI Whisper 云端 API。
- AI 翻译：支持 OpenAI、DeepSeek、Kimi (Moonshot)、通义千问 (Qwen)、智谱 GLM、Claude / OpenRouter 及 DeepL，保持时间轴与段落对齐。
- 双语与多轨管理：自由切换源语言与多目标语言轨道；双语对照模式下主副语言独立配置字体、字号、颜色、描边、阴影与摆放位置。
- 实时预览：集成 jassub (libass WASM)，播放与暂停状态下实时呈现 ASS 渲染效果。
- 画布拖动定位：在视频画面上按住字幕即可自由拖动调整位置，双语各轨独立拖动。
- 字幕编辑器：支持文本行内修改与微调时间码，点击跳转试听，播放高亮滚动跟随，一键清理空段落。
- 导出支持：
  - 硬字幕内嵌烧录 (MP4)：libx264 CRF 18 压制，支持真实烧录预览帧。
  - 软字幕 MKV 无损封装：视频音频流直接复制，秒级导出。
  - 独立字幕文件：SRT / ASS 独立及双语合并文件导出。
"""

class ProgressFileReader:
    def __init__(self, filepath, total_size):
        self.f = open(filepath, "rb")
        self.total_size = total_size
        self.uploaded = 0
        self.last_reported = 0

    def read(self, size=-1):
        chunk = self.f.read(size)
        if chunk:
            self.uploaded += len(chunk)
            percent = (self.uploaded / self.total_size) * 100
            if percent - self.last_reported >= 10 or self.uploaded == self.total_size:
                self.last_reported = percent
                print(f"Upload progress: {self.uploaded / (1024*1024):.1f} / {self.total_size / (1024*1024):.1f} MB ({percent:.1f}%)", flush=True)
        return chunk

    def __iter__(self):
        chunk_size = 1024 * 1024 * 4
        while True:
            chunk = self.read(chunk_size)
            if not chunk:
                break
            yield chunk

    def close(self):
        self.f.close()

def main():
    token = get_github_token()
    if not token:
        print("Error: GitHub token not found")
        sys.exit(1)
        
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "subcraft-release-script",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    client = httpx.Client(timeout=600.0)
    
    # 1. Get or create release
    r = client.get(f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}", headers=headers)
    if r.status_code == 200:
        release_data = r.json()
        release_id = release_data["id"]
        # Update body
        client.patch(
            f"https://api.github.com/repos/{REPO}/releases/{release_id}",
            headers=headers,
            json={"name": TITLE, "body": BODY}
        )
    elif r.status_code == 404:
        payload = {
            "tag_name": TAG,
            "target_commitish": "master",
            "name": TITLE,
            "body": BODY,
            "draft": False,
            "prerelease": False,
        }
        r = client.post(f"https://api.github.com/repos/{REPO}/releases", headers=headers, json=payload)
        release_data = r.json()
        release_id = release_data["id"]
    else:
        print(f"Error checking release: {r.status_code}")
        sys.exit(1)
        
    # 2. Upload all assets
    existing_assets = {a["name"]: a["id"] for a in release_data.get("assets", [])}
    
    for path in ASSETS:
        if not os.path.isfile(path):
            print(f"Skipping missing asset: {path}")
            continue
        fname = os.path.basename(path)
        fsize = os.path.getsize(path)
        if fname in existing_assets:
            print(f"Deleting old asset {fname}...")
            client.delete(f"https://api.github.com/repos/{REPO}/releases/assets/{existing_assets[fname]}", headers=headers)
            
        print(f"Uploading {fname} ({fsize / (1024*1024):.2f} MB)...")
        content_type = "application/gzip" if fname.endswith(".tar.gz") else "application/zip"
        upload_url = f"https://uploads.github.com/repos/{REPO}/releases/{release_id}/assets?name={fname}"
        upload_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": content_type,
            "User-Agent": "subcraft-release-script",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Length": str(fsize),
        }
        reader = ProgressFileReader(path, fsize)
        try:
            up_resp = client.post(upload_url, headers=upload_headers, content=reader)
            if up_resp.status_code in (200, 201):
                print(f"Successfully uploaded {fname}!")
            else:
                print(f"Failed to upload {fname}: {up_resp.status_code} - {up_resp.text}")
        finally:
            reader.close()

if __name__ == "__main__":
    main()
