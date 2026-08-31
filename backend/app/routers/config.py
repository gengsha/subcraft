"""配置路由：API Key 等设置读写（key 以掩码形式回显）。"""
from __future__ import annotations

from fastapi import APIRouter

from ..config import store
from ..services import ffmpeg_tool

router = APIRouter(prefix="/api/config", tags=["config"])

_MASKED = {"deepl_api_key"}


def _mask_secret(v: str) -> str:
    return ("****" + v[-4:]) if len(v) > 4 else ("****" if v else "")


def _masked(cfg: dict) -> dict:
    out = dict(cfg)
    v = out.get("deepl_api_key") or ""
    out["deepl_api_key"] = _mask_secret(v)
    out["deepl_api_key_set"] = bool(v)
    # AI 厂商列表：逐个掩码 api_key
    providers = []
    for p in out.get("ai_providers", []) or []:
        p2 = dict(p)
        k = p2.get("api_key") or ""
        p2["api_key"] = _mask_secret(k)
        p2["api_key_set"] = bool(k)
        providers.append(p2)
    out["ai_providers"] = providers
    return out


@router.get("")
def get_config() -> dict:
    return _masked(store.all())


@router.post("")
def update_config(body: dict) -> dict:
    updates: dict = {}
    for k, v in body.items():
        if k in _MASKED and isinstance(v, str) and v.startswith("****"):
            continue  # 掩码原样回传 → 不覆盖
        if k == "ai_providers" and isinstance(v, list):
            old = {p.get("id"): p for p in store.get("ai_providers", []) or []}
            merged = []
            for i, p in enumerate(v):
                if not isinstance(p, dict):
                    continue
                pid = p.get("id") or f"p{i}_{abs(hash(p.get('name', ''))) % 99999}"
                key = p.get("api_key") or ""
                if key.startswith("****"):  # 掩码回传 → 沿用旧 key
                    key = old.get(pid, {}).get("api_key", "")
                merged.append({
                    "id": pid,
                    "name": p.get("name", ""),
                    "base_url": p.get("base_url", ""),
                    "api_key": key,
                    "model": p.get("model", ""),
                })
            updates["ai_providers"] = merged
            continue
        updates[k] = v
    return _masked(store.update(updates))


@router.get("/system")
def system_status() -> dict:
    found = ffmpeg_tool.find_ffmpeg()
    cuda = False
    try:
        import ctranslate2
        cuda = ctranslate2.get_cuda_device_count() > 0
    except Exception:
        pass
    return {
        "ffmpeg": found[0] if found else None,
        "ffmpeg_ready": found is not None,
        "cuda_available": cuda,
    }
