"""转写与翻译任务路由。"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..models import Segment
from ..services import asr, translator
from ..tasks import manager

router = APIRouter(prefix="/api", tags=["tasks"])


class TranscribeRequest(BaseModel):
    video_path: str
    duration: float = 0.0
    engine: str = "local"            # local / openai
    model: str | None = None
    language: str | None = None      # None/auto = 自动检测
    api_key: str | None = None
    base_url: str | None = None


class TranslateRequest(BaseModel):
    segments: list[Segment]
    source_lang: str
    target_lang: str
    provider: str = "openai"         # openai(AI厂商) / deepl
    provider_id: str | None = None   # AI 厂商配置 id
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


@router.post("/transcribe")
def start_transcribe(req: TranscribeRequest) -> dict:
    def job(progress_cb):
        segments, language = asr.transcribe(
            req.video_path, req.duration, req.engine, req.model,
            req.language, req.api_key, req.base_url, progress_cb,
        )
        return {"language": language, "segments": [s.model_dump() for s in segments]}

    return {"task_id": manager.submit(job)}


@router.post("/translate")
def start_translate(req: TranslateRequest) -> dict:
    def job(progress_cb):
        out = translator.translate_segments(
            req.segments, req.source_lang, req.target_lang,
            req.provider, req.provider_id, req.api_key, req.base_url, req.model,
            progress_cb=progress_cb,
        )
        return {"segments": [s.model_dump() for s in out]}

    return {"task_id": manager.submit(job)}


class TranslateTestRequest(BaseModel):
    provider: str = "openai"         # openai / deepl
    provider_id: str | None = None


@router.post("/translate/test")
def test_translate_connection(req: TranslateTestRequest) -> dict:
    """测试翻译接口连通性：真实发一条最小翻译请求并计时。"""
    import time

    try:
        t = translator._get_translator(req.provider, req.provider_id)
    except Exception as e:
        return {"ok": False, "message": str(e), "latency_ms": 0}

    t0 = time.time()
    try:
        if isinstance(t, translator.DeepLTranslator):
            # DeepL: 用 /usage 轻量接口验证 key 有效性
            resp = httpx.get(
                t.url.replace("/translate", "/usage"),
                params={"auth_key": t.key}, timeout=15,
            )
            resp.raise_for_status()
            usage = resp.json()
            lat = int((time.time() - t0) * 1000)
            return {
                "ok": True,
                "message": f"连接成功（{lat}ms），本月用量 {usage.get('character_count', 0):,} / {usage.get('character_limit', 0):,} 字符",
                "latency_ms": lat,
            }
        reply = t.translate_batch(["你好，世界"], "zh", "en")
        lat = int((time.time() - t0) * 1000)
        return {"ok": True, "message": f"连接成功（{lat}ms），测试译文: {reply[0]}", "latency_ms": lat}
    except Exception as e:
        lat = int((time.time() - t0) * 1000)
        return {"ok": False, "message": f"连接失败（{lat}ms）: {e}", "latency_ms": lat}


@router.get("/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    t = manager.get(task_id)
    if t is None:
        raise HTTPException(404, "任务不存在")
    return t


@router.get("/whisper_models")
def whisper_models() -> dict[str, str]:
    return asr.WHISPER_MODELS
