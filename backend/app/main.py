"""FastAPI 入口：REST 路由 + WebSocket 进度推送。"""
from __future__ import annotations

import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .routers import config, export, media, timeline, transcribe
from .security import ALLOWED_ORIGIN_REGEX, TokenAuthMiddleware
from .tasks import manager


def create_app() -> FastAPI:
    app = FastAPI(title="SubCraft Backend", version="0.2.1")
    # 先加令牌校验，再加 CORS（后加的在外层），保证预检请求由 CORS 直接应答
    app.add_middleware(TokenAuthMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=ALLOWED_ORIGIN_REGEX,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-SubCraft-Token", "Range"],
    )
    app.include_router(media.router)
    app.include_router(transcribe.router)
    app.include_router(export.router)
    app.include_router(config.router)
    app.include_router(timeline.router)

    @app.on_event("startup")
    async def _startup() -> None:
        manager.loop = asyncio.get_running_loop()
        from .services.asr import _setup_cuda_dlls

        _setup_cuda_dlls()

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        manager.connections.add(websocket)
        try:
            while True:
                await websocket.receive_text()  # 保持连接（客户端可发 ping）
        except WebSocketDisconnect:
            pass
        finally:
            manager.connections.discard(websocket)

    @app.get("/api/health")
    async def health() -> dict:
        return {"ok": True}

    return app


app = create_app()
