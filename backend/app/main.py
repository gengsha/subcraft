"""FastAPI 入口：REST 路由 + WebSocket 进度推送。"""
from __future__ import annotations

import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .routers import config, export, media, transcribe
from .tasks import manager


def create_app() -> FastAPI:
    app = FastAPI(title="SubCraft Backend", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(media.router)
    app.include_router(transcribe.router)
    app.include_router(export.router)
    app.include_router(config.router)

    @app.on_event("startup")
    async def _startup() -> None:
        manager.loop = asyncio.get_running_loop()

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
