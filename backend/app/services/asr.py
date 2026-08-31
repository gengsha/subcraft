"""语音识别：本地 faster-whisper (GPU 加速) + OpenAI Whisper API 云端备选。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from ..config import store, work_dir
from ..models import Segment
from . import ffmpeg_tool

ProgressCb = Callable[[float, str], None]

# 模型名 -> 说明（供前端展示）
WHISPER_MODELS = {
    "tiny": "tiny (最快，精度低)",
    "base": "base",
    "small": "small",
    "medium": "medium",
    "large-v3-turbo": "large-v3-turbo (推荐：速度快精度高)",
    "large-v3": "large-v3 (最高精度)",
}


def _setup_cuda_dlls() -> None:
    """把 pip 安装的 nvidia-*-cu12 运行库目录加入 DLL 搜索路径（供 ctranslate2 使用）。"""
    import site

    for sp in site.getsitepackages():
        nvidia = Path(sp) / "nvidia"
        if not nvidia.exists():
            continue
        for sub in nvidia.iterdir():
            bin_dir = sub / "bin"
            if bin_dir.exists():
                os.add_dll_directory(str(bin_dir))
                os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


class LocalWhisper:
    """faster-whisper 单例，模型按需加载并缓存。"""

    def __init__(self) -> None:
        self._model = None
        self._loaded_name: str | None = None

    def _resolve_device(self, device: str) -> tuple[str, str]:
        if device == "auto":
            try:
                _setup_cuda_dlls()
                import ctranslate2
                if ctranslate2.get_cuda_device_count() > 0:
                    return "cuda", "float16"
            except Exception:
                pass
            return "cpu", "int8"
        return ("cuda", "float16") if device == "cuda" else ("cpu", "int8")

    def _load(self, model_name: str, device: str, progress_cb: ProgressCb):
        if self._model is not None and self._loaded_name == f"{model_name}:{device}":
            return self._model
        from faster_whisper import WhisperModel

        _setup_cuda_dlls()
        dev, compute = self._resolve_device(device)
        progress_cb(0.02, f"加载模型 {model_name} ({dev})，首次需下载...")
        try:
            self._model = WhisperModel(model_name, device=dev, compute_type=compute)
        except Exception as e:
            if dev == "cuda":
                progress_cb(0.02, f"CUDA 加载失败，回退 CPU: {e}")
                self._model = WhisperModel(model_name, device="cpu", compute_type="int8")
            else:
                raise
        self._loaded_name = f"{model_name}:{device}"
        return self._model

    def transcribe(
        self,
        wav_path: Path,
        duration: float,
        model_name: str,
        language: str | None = None,
        device: str = "auto",
        progress_cb: ProgressCb | None = None,
    ) -> tuple[list[Segment], str]:
        def report(p: float, msg: str) -> None:
            if progress_cb:
                progress_cb(min(p, 0.99), msg)

        model = self._load(model_name, device, report)
        report(0.05, "识别中...")
        segments_iter, info = model.transcribe(
            str(wav_path),
            language=None if language in (None, "auto") else language,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            beam_size=5,
        )
        segments: list[Segment] = []
        for s in segments_iter:
            segments.append(Segment(start=round(s.start, 3), end=round(s.end, 3), text=s.text.strip()))
            if duration > 0:
                report(0.05 + 0.93 * min(s.end / duration, 1.0), f"识别中 {int(s.end)}s / {int(duration)}s")
        return segments, info.language or "und"


def transcribe_openai_api(
    video_path: str,
    api_key: str,
    base_url: str,
    language: str | None = None,
    progress_cb: ProgressCb | None = None,
) -> tuple[list[Segment], str]:
    """OpenAI Whisper API（云端，按用量计费，需联网）。"""
    from openai import OpenAI

    def report(p: float, msg: str) -> None:
        if progress_cb:
            progress_cb(p, msg)

    report(0.05, "提取音频...")
    mp3 = work_dir() / f"upload_{os.getpid()}.mp3"
    ffmpeg_tool.extract_audio_mp3(video_path, mp3)
    if mp3.stat().st_size > 24 * 1024 * 1024:
        mp3.unlink(missing_ok=True)
        raise RuntimeError("音频超过 25MB，超出 Whisper API 限制，请改用本地识别")

    report(0.3, "上传并识别中...")
    client = OpenAI(api_key=api_key, base_url=base_url or None)
    with open(mp3, "rb") as f:
        resp = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
            language=None if language in (None, "auto") else language,
        )
    mp3.unlink(missing_ok=True)
    segments = [
        Segment(start=round(s.start, 3), end=round(s.end, 3), text=s.text.strip())
        for s in (resp.segments or [])
        if s.text.strip()
    ]
    report(0.99, "识别完成")
    return segments, getattr(resp, "language", None) or "und"


_local = LocalWhisper()


def transcribe(
    video_path: str,
    duration: float,
    engine: str = "local",
    model_name: str | None = None,
    language: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    progress_cb: ProgressCb | None = None,
) -> tuple[list[Segment], str]:
    """统一入口。返回 (字幕段, 检测到的语言码)。"""
    if engine == "openai":
        from .translator import get_ai_provider

        p = get_ai_provider() or {}
        key = api_key or p.get("api_key", "")
        if not key:
            raise RuntimeError("未配置 AI 接口的 API Key（设置页中添加厂商后重试）")
        return transcribe_openai_api(video_path, key, base_url or p.get("base_url", ""), language, progress_cb)
    # 本地引擎
    model_name = model_name or store.get("whisper_model", "large-v3-turbo")
    device = store.get("whisper_device", "auto")

    def report(p: float, msg: str) -> None:
        if progress_cb:
            progress_cb(p, msg)

    report(0.0, "提取音频...")
    wav = work_dir() / f"asr_{os.getpid()}.wav"
    ffmpeg_tool.extract_audio(video_path, wav)
    try:
        return _local.transcribe(wav, duration, model_name, language, device, progress_cb)
    finally:
        wav.unlink(missing_ok=True)
