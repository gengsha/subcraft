"""ffmpeg/ffprobe 定位、自动下载与常用操作（探测、抽音频、软字幕封装、硬字幕烧录）。"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Callable

import httpx

from ..config import store, tools_dir
from ..models import MediaInfo

FFMPEG_DOWNLOAD_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

ProgressCb = Callable[[float, str], None]


class FFmpegError(RuntimeError):
    pass


def _bin_dir() -> Path:
    return tools_dir() / "ffmpeg" / "bin"


def _candidates() -> list[tuple[Path, Path]]:
    cands: list[tuple[Path, Path]] = []
    custom = store.get("ffmpeg_path")
    if custom:
        p = Path(custom)
        cands.append((p, p.with_name("ffprobe.exe" if p.suffix == ".exe" else "ffprobe")))
    b = _bin_dir()
    cands.append((b / "ffmpeg.exe", b / "ffprobe.exe"))
    sys_ff = shutil.which("ffmpeg")
    if sys_ff:
        sp = Path(sys_ff)
        cands.append((sp, sp.with_name("ffprobe.exe")))
    return cands


def find_ffmpeg() -> tuple[str, str] | None:
    """返回 (ffmpeg, ffprobe) 路径；找不到返回 None。"""
    for ff, fp in _candidates():
        if ff.exists() and fp.exists():
            return str(ff), str(fp)
    return None


def ensure_ffmpeg(progress_cb: ProgressCb | None = None) -> tuple[str, str]:
    """确保 ffmpeg 可用；Windows 本地没有则自动下载，其他平台提示自行安装。"""
    found = find_ffmpeg()
    if found:
        return found

    if sys.platform != "win32":
        raise FFmpegError("未找到 ffmpeg，请先安装并加入 PATH：sudo apt install ffmpeg")

    def report(p: float, msg: str) -> None:
        if progress_cb:
            progress_cb(p, msg)

    dest = tools_dir() / "ffmpeg"
    dest.mkdir(parents=True, exist_ok=True)
    zip_path = tools_dir() / "ffmpeg-download.zip"
    report(0.0, "下载 ffmpeg 中...")
    with httpx.stream("GET", FFMPEG_DOWNLOAD_URL, follow_redirects=True, timeout=None) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with open(zip_path, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total:
                    report(done / total * 0.9, f"下载 ffmpeg {done * 100 // total}%")
    report(0.9, "解压 ffmpeg...")
    with zipfile.ZipFile(zip_path) as z:
        for member in z.namelist():
            parts = Path(member).parts
            # 压缩包内为 ffmpeg-x.x-essentials_build/bin/ffmpeg.exe 结构，仅提取 bin/
            if len(parts) >= 2 and parts[-2] == "bin" and parts[-1] in (
                "ffmpeg.exe", "ffprobe.exe", "ffplay.exe",
            ):
                target = _bin_dir() / parts[-1]
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(member) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    zip_path.unlink(missing_ok=True)
    report(1.0, "ffmpeg 就绪")
    found = find_ffmpeg()
    if not found:
        raise FFmpegError("ffmpeg 下载后仍不可用")
    return found


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise FFmpegError(f"命令失败: {' '.join(cmd)}\n{proc.stderr[-2000:]}")
    return proc


_disposition_cache: dict[str, bool] = {}


def _supports_disposition(ffmpeg: str) -> bool:
    """ffmpeg >= 4.0 (libavformat >= 58) 才支持 -disposition 选项；按库版本判断。"""
    if ffmpeg in _disposition_cache:
        return _disposition_cache[ffmpeg]
    supported = True
    try:
        out = subprocess.run(
            [ffmpeg, "-version"], capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        ).stdout
        for line in out.splitlines():
            if "libavformat" in line:
                ver = line.split()[1].split("/")[0].strip()
                major = int(ver.split(".")[0])
                supported = major >= 58
                break
    except Exception:
        pass
    _disposition_cache[ffmpeg] = supported
    return supported


def probe(path: str) -> MediaInfo:
    found = find_ffmpeg()
    if not found:
        raise FFmpegError("未找到 ffmpeg，请先初始化")
    _, ffprobe = found
    p = Path(path)
    out = _run([
        ffprobe, "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(p),
    ]).stdout
    data = json.loads(out)
    info = MediaInfo(path=str(p), name=p.name, size=p.stat().st_size)
    fmt = data.get("format", {})
    info.duration = float(fmt.get("duration", 0) or 0)
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not info.video_codec:
            info.video_codec = s.get("codec_name", "")
            info.width = int(s.get("width", 0) or 0)
            info.height = int(s.get("height", 0) or 0)
        elif s.get("codec_type") == "audio" and not info.audio_codec:
            info.audio_codec = s.get("codec_name", "")
    return info


def extract_audio(video_path: str, out_wav: Path, sample_rate: int = 16000) -> Path:
    """抽取单声道 16kHz PCM 音频供 ASR 使用。"""
    ffmpeg, _ = ensure_ffmpeg()
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    _run([
        ffmpeg, "-y", "-i", video_path, "-vn",
        "-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le",
        str(out_wav),
    ])
    return out_wav


def extract_audio_mp3(video_path: str, out_mp3: Path) -> Path:
    """抽取低码率 mp3 供云端 Whisper API 上传（25MB 限制）。"""
    ffmpeg, _ = ensure_ffmpeg()
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    _run([
        ffmpeg, "-y", "-i", video_path, "-vn",
        "-ac", "1", "-ar", "16000", "-b:a", "48k",
        str(out_mp3),
    ])
    return out_mp3


def mux_subtitles(
    video_path: str,
    subtitles: list[tuple[Path, str, str]],   # (字幕文件, 语言码, 轨道标题)
    out_path: Path,
    default_index: int = 0,
) -> Path:
    """软字幕封装：视频/音频流直接 copy（零重编码、画质无损）。"""
    ffmpeg, _ = ensure_ffmpeg()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg, "-y", "-i", video_path]
    for sub, _, _ in subtitles:
        cmd += ["-i", str(sub)]
    cmd += ["-map", "0:v", "-map", "0:a?"]
    for i in range(len(subtitles)):
        cmd += ["-map", f"{i + 1}:0"]
    cmd += ["-c:v", "copy", "-c:a", "copy", "-c:s", "ass"]
    for i, (_, lang, title) in enumerate(subtitles):
        cmd += [f"-metadata:s:s:{i}", f"language={lang}", f"-metadata:s:s:{i}", f"title={title}"]
    if subtitles and _supports_disposition(ffmpeg):
        cmd += [f"-disposition:s:{default_index}", "default"]
    cmd += [str(out_path)]
    _run(cmd)
    return out_path


_filter_cache: dict[tuple[str, str], bool] = {}


def _has_filter(ffmpeg: str, name: str) -> bool:
    """检查当前 ffmpeg 构建是否包含指定滤镜（如 libass 的 ass/subtitles）。"""
    key = (ffmpeg, name)
    if key in _filter_cache:
        return _filter_cache[key]
    try:
        out = subprocess.run(
            [ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        ).stdout
        ok = any(len(parts := ln.split()) >= 2 and parts[1] == name for ln in out.splitlines())
    except Exception:
        ok = False
    _filter_cache[key] = ok
    return ok


def _escape_filter_path(p: Path) -> str:
    """路径转 ffmpeg 滤镜参数值：反斜杠转斜杠，转义引号与冒号，整体单引号包裹。"""
    s = str(p).replace("\\", "/").replace("'", "\\'").replace(":", "\\:")
    return f"'{s}'"


def _run_with_progress(cmd: list[str], duration: float, on_progress: ProgressCb | None, msg: str) -> None:
    """执行 ffmpeg 并解析 stderr 的 time= 输出上报进度（用于重编码类长任务）。"""
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    assert proc.stderr is not None
    fd = proc.stderr.fileno()
    buf = ""
    last_p = -1.0
    try:
        while True:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            buf += chunk.decode("utf-8", errors="replace")
            *lines, buf = re.split(r"[\r\n]+", buf)
            for line in lines:
                m = re.search(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", line)
                if not m or duration <= 0:
                    continue
                t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                p = min(t / duration, 1.0)
                if p - last_p >= 0.01:
                    last_p = p
                    if on_progress:
                        on_progress(p, f"{msg} {int(p * 100)}%")
    finally:
        proc.wait()
        proc.stderr.close()
    if proc.returncode != 0:
        raise FFmpegError(f"命令失败: {' '.join(cmd)}\n{buf[-2000:]}")


def _subtitle_vf(ffmpeg: str, sub_file: Path, fonts_dir: str | None) -> str:
    """构造 libass 字幕滤镜参数（ass 优先，旧构建回退 subtitles）。"""
    if _has_filter(ffmpeg, "ass"):
        vf = f"ass={_escape_filter_path(sub_file)}"
    elif _has_filter(ffmpeg, "subtitles"):
        vf = f"subtitles={_escape_filter_path(sub_file)}"
    else:
        raise FFmpegError("当前 ffmpeg 缺少 libass 字幕滤镜，无法内嵌字幕；请改用软字幕封装或更换完整版 ffmpeg")
    if fonts_dir and Path(fonts_dir).is_dir():
        vf += f":fontsdir={_escape_filter_path(Path(fonts_dir))}"
    return vf


def burn_subtitles(
    video_path: str,
    sub_file: Path,
    out_path: Path,
    progress_cb: ProgressCb | None = None,
    fonts_dir: str | None = None,
    crf: int = 18,
    preset: str = "medium",
) -> Path:
    """硬字幕烧录：libass 把字幕渲染进画面，视频需重编码（libx264）。"""
    ffmpeg, _ = ensure_ffmpeg()
    vf = _subtitle_vf(ffmpeg, sub_file, fonts_dir)

    info = probe(video_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg, "-y", "-i", video_path, "-vf", vf,
           "-c:v", "libx264", "-crf", str(crf), "-preset", preset]
    if out_path.suffix.lower() in (".mp4", ".m4v"):
        # mp4 容器：非 aac 音轨重编码为 aac，其余直接复制
        cmd += ["-c:a", "copy" if info.audio_codec == "aac" else "aac"]
        if info.audio_codec != "aac":
            cmd += ["-b:a", "192k"]
        cmd += ["-movflags", "+faststart"]
    else:
        cmd += ["-c:a", "copy"]
    cmd += [str(out_path)]
    _run_with_progress(cmd, info.duration, progress_cb, "内嵌字幕中")
    return out_path


def burn_frame(
    video_path: str,
    sub_file: Path,
    t: float,
    out_jpg: Path,
    fonts_dir: str | None = None,
) -> Path:
    """按指定时间点烧录单帧预览图（与 burn_subtitles 同一渲染管线），用于导出前所见即所得。"""
    ffmpeg, _ = ensure_ffmpeg()
    vf = _subtitle_vf(ffmpeg, sub_file, fonts_dir)
    duration = probe(video_path).duration
    t = min(max(t, 0.0), max(duration - 0.1, 0.0))
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    # -copyts 保留原始时间戳：否则 -ss 会把 PTS 重置为 0，ass 滤镜按原始时间轴找不到字幕
    _run([
        ffmpeg, "-y", "-copyts", "-ss", f"{t:.3f}", "-i", video_path,
        "-vf", vf, "-frames:v", "1", "-q:v", "3", str(out_jpg),
    ])
    return out_jpg
