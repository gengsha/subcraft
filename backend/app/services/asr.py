"""语音识别：本地 faster-whisper (GPU 加速) + OpenAI Whisper API 云端备选。"""
from __future__ import annotations

import os
import sys
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


_CUDA_DLL_CONFIGURED = False


def _setup_cuda_dlls() -> None:
    """把 pip 安装或 PyInstaller 打包的 nvidia-*-cu12 运行库目录加入 DLL 搜索路径（供 ctranslate2 使用）。"""
    global _CUDA_DLL_CONFIGURED
    if _CUDA_DLL_CONFIGURED or sys.platform != "win32":
        return

    candidate_roots: set[Path] = set()

    # 1. PyInstaller 打包环境
    if getattr(sys, "frozen", False):
        if hasattr(sys, "_MEIPASS"):
            candidate_roots.add(Path(sys._MEIPASS))
        exe_dir = Path(sys.executable).parent
        candidate_roots.add(exe_dir)
        candidate_roots.add(exe_dir / "_internal")
        candidate_roots.add(exe_dir / "tools")

    tools_dir = os.environ.get("SubCraft_TOOLS_DIR")
    if tools_dir:
        candidate_roots.add(Path(tools_dir))

    # 2. Python 运行环境
    candidate_roots.add(Path(sys.prefix))
    candidate_roots.add(Path(sys.base_prefix))
    try:
        import site

        for sp in site.getsitepackages():
            candidate_roots.add(Path(sp))
        if hasattr(site, "getusersitepackages"):
            candidate_roots.add(Path(site.getusersitepackages()))
    except Exception:
        pass

    for p in sys.path:
        if p:
            candidate_roots.add(Path(p))

    # 3. 环境变量中的 CUDA 目录
    for k in ("CUDA_PATH", "CUDA_PATH_V12_0", "CUDA_PATH_V12_4", "CUDA_PATH_V12_8", "CUDA_PATH_V12_9"):
        cuda_path = os.environ.get(k)
        if cuda_path:
            candidate_roots.add(Path(cuda_path))

    dll_dirs: set[Path] = set()
    for root in candidate_roots:
        if not root.exists():
            continue
        # 检查根目录及 bin 目录
        if (root / "cublas64_12.dll").exists() or (root / "cublas64_11.dll").exists():
            dll_dirs.add(root)
        bin_dir = root / "bin"
        if bin_dir.exists() and any(bin_dir.glob("*.dll")):
            dll_dirs.add(bin_dir)

        # 检查 nvidia 子包 (nvidia/cublas/bin, nvidia/cudnn/bin, nvidia/cuda_nvrtc/bin 等)
        nvidia = root / "nvidia"
        if nvidia.exists():
            for sub in nvidia.iterdir():
                if sub.is_dir():
                    sub_bin = sub / "bin"
                    if sub_bin.exists():
                        dll_dirs.add(sub_bin)
                    elif any(sub.glob("*.dll")):
                        dll_dirs.add(sub)

        # 检查 Lib/site-packages/nvidia
        sp_nvidia = root / "Lib" / "site-packages" / "nvidia"
        if sp_nvidia.exists():
            for sub in sp_nvidia.iterdir():
                if sub.is_dir():
                    sub_bin = sub / "bin"
                    if sub_bin.exists():
                        dll_dirs.add(sub_bin)

    for d in dll_dirs:
        try:
            os.add_dll_directory(str(d))
        except Exception:
            pass
        os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")

    _CUDA_DLL_CONFIGURED = True


_CUDA_AVAILABLE_CACHE: bool | None = None


def is_cuda_available() -> bool:
    """检查当前环境是否真正支持 CUDA 加速（不仅检查 GPU，还验证 cuBLAS/cuDNN 是否可正常加载）。"""
    global _CUDA_AVAILABLE_CACHE
    if _CUDA_AVAILABLE_CACHE is not None:
        return _CUDA_AVAILABLE_CACHE

    _setup_cuda_dlls()
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() <= 0:
            _CUDA_AVAILABLE_CACHE = False
            return False

        # Windows 下验证 cuBLAS 动态链接库是否可真实加载
        if sys.platform == "win32":
            import ctypes

            try:
                ctypes.CDLL("cublas64_12.dll")
            except Exception:
                try:
                    ctypes.CDLL("cublas64_11.dll")
                except Exception:
                    _CUDA_AVAILABLE_CACHE = False
                    return False

        _CUDA_AVAILABLE_CACHE = True
        return True
    except Exception:
        _CUDA_AVAILABLE_CACHE = False
        return False


class LocalWhisper:
    """faster-whisper 单例，模型按需加载并缓存。"""

    def __init__(self) -> None:
        self._model = None
        self._loaded_name: str | None = None

    def _resolve_device(self, device: str) -> tuple[str, str]:
        if device == "auto":
            return ("cuda", "float16") if is_cuda_available() else ("cpu", "int8")
        if device == "cuda":
            return ("cuda", "float16")
        return ("cpu", "int8")

    def _load(self, model_name: str, device: str, progress_cb: ProgressCb):
        dev, compute = self._resolve_device(device)
        if self._model is not None and self._loaded_name == f"{model_name}:{dev}":
            return self._model
        from faster_whisper import WhisperModel

        _setup_cuda_dlls()
        progress_cb(0.02, f"加载模型 {model_name} ({dev})，首次需下载...")
        try:
            self._model = WhisperModel(model_name, device=dev, compute_type=compute)
            self._loaded_name = f"{model_name}:{dev}"
        except Exception as e:
            if dev == "cuda":
                progress_cb(0.02, f"CUDA 加载失败，回退 CPU: {e}")
                self._model = WhisperModel(model_name, device="cpu", compute_type="int8")
                self._loaded_name = f"{model_name}:cpu"
            else:
                raise
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

        def _do_transcribe(m) -> tuple[list[Segment], str]:
            report(0.05, "识别中...")
            segments_iter, info = m.transcribe(
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

        model = self._load(model_name, device, report)
        try:
            return _do_transcribe(model)
        except Exception as e:
            # 如果在 CUDA 执行阶段（如 GEMM/cuBLAS/cuDNN 运行时异常）失败，自动降级为 CPU 模式重试
            err_msg = str(e).lower()
            is_cuda_err = (
                "cublas" in err_msg
                or "cuda" in err_msg
                or "cudnn" in err_msg
                or "out of memory" in err_msg
            )
            if is_cuda_err and self._loaded_name and ":cuda" in self._loaded_name:
                report(0.02, f"CUDA 执行失败 ({e})，正在自动回退到 CPU 模式重试...")
                from faster_whisper import WhisperModel

                self._model = WhisperModel(model_name, device="cpu", compute_type="int8")
                self._loaded_name = f"{model_name}:cpu"
                return _do_transcribe(self._model)
            raise


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
