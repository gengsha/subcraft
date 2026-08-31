import os
import sys
import subprocess
import httpx

REPO = "gengsha/subcraft"
TAG = "v0.1.0"
TITLE = "SubCraft 字幕生成器 v0.1.0"
ZIP_PATH = os.path.abspath(r"release\SubCraft-0.1.0-win-x64.zip")

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

BODY = """# SubCraft v0.1.0 (Windows x64)

视频语音识别、AI 多厂商翻译、双语排版与字幕制作工具。

---

### 资产下载 (Downloads)

| 文件名 | 文件大小 | 平台 | 说明 |
|---|---|---|---|
| `SubCraft-0.1.0-win-x64.zip` | ~281 MB | Windows x64 | 便携免安装版（内置 Python 独立后端与 ffmpeg 运行时，解压即用） |

使用提示：下载后解压到任意目录，双击运行 `SubCraft.exe` 即可使用。首次使用本地语音识别时，将自动按需下载 Whisper 模型权重。

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

def main():
    token = get_github_token()
    if not token:
        print("Error: GitHub token not found from env or git credential helper")
        sys.exit(1)
        
    if not os.path.isfile(ZIP_PATH):
        print(f"Error: Zip file not found at {ZIP_PATH}")
        sys.exit(1)
    
    file_size = os.path.getsize(ZIP_PATH)
    file_name = os.path.basename(ZIP_PATH)
    print(f"Found asset: {file_name} ({file_size / (1024*1024):.2f} MB)")
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "subcraft-release-script",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    
    client = httpx.Client(timeout=600.0)
    
    # 1. Check if release for tag already exists
    print(f"Checking existing release for tag {TAG}...")
    r = client.get(f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}", headers=headers)
    if r.status_code == 200:
        release_data = r.json()
        release_id = release_data["id"]
        print(f"Release already exists with ID: {release_id}")
    elif r.status_code == 404:
        print("Creating new release...")
        payload = {
            "tag_name": TAG,
            "target_commitish": "master",
            "name": TITLE,
            "body": BODY,
            "draft": False,
            "prerelease": False,
        }
        r = client.post(f"https://api.github.com/repos/{REPO}/releases", headers=headers, json=payload)
        if r.status_code not in (200, 201):
            print(f"Failed to create release: {r.status_code} - {r.text}")
            sys.exit(1)
        release_data = r.json()
        release_id = release_data["id"]
        print(f"Created release with ID: {release_id}, URL: {release_data.get('html_url')}")
    else:
        print(f"Unexpected status checking release: {r.status_code} - {r.text}")
        sys.exit(1)

    # 2. Check if asset already exists in the release
    assets = release_data.get("assets", [])
    for a in assets:
        if a.get("name") == file_name:
            print(f"Asset {file_name} already exists (ID: {a.get('id')}). Deleting old asset first...")
            del_r = client.delete(f"https://api.github.com/repos/{REPO}/releases/assets/{a.get('id')}", headers=headers)
            print(f"Delete result: {del_r.status_code}")

    # 3. Upload asset with streaming
    upload_url = f"https://uploads.github.com/repos/{REPO}/releases/{release_id}/assets?name={file_name}"
    print(f"Uploading {file_name} ({file_size / (1024*1024):.2f} MB) to {upload_url}...")

    upload_headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/zip",
        "User-Agent": "subcraft-release-script",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Length": str(file_size),
    }

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
                if percent - self.last_reported >= 5 or self.uploaded == self.total_size:
                    self.last_reported = percent
                    print(f"Upload progress: {self.uploaded / (1024*1024):.1f} / {self.total_size / (1024*1024):.1f} MB ({percent:.1f}%)", flush=True)
            return chunk

        def __iter__(self):
            chunk_size = 1024 * 1024 * 4  # 4MB chunks
            while True:
                chunk = self.read(chunk_size)
                if not chunk:
                    break
                yield chunk

        def close(self):
            self.f.close()

    reader = ProgressFileReader(ZIP_PATH, file_size)
    try:
        up_resp = client.post(upload_url, headers=upload_headers, content=reader)
        if up_resp.status_code in (200, 201):
            asset_data = up_resp.json()
            print(f"Successfully uploaded {file_name}!")
            print(f"Download URL: {asset_data.get('browser_download_url')}")
            print(f"Release URL: {release_data.get('html_url')}")
        else:
            print(f"Upload failed: {up_resp.status_code} - {up_resp.text}")
            sys.exit(1)
    finally:
        reader.close()

if __name__ == "__main__":
    main()
