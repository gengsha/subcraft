"""后台任务管理：线程池执行长任务，进度经 WebSocket 广播。"""
from __future__ import annotations

import asyncio
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable


class TaskManager:
    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, Any]] = {}
        self.connections: set[Any] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.executor = ThreadPoolExecutor(max_workers=2)

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
        task_id = uuid.uuid4().hex[:12]
        self.tasks[task_id] = {"status": "running", "progress": 0.0, "message": "排队中", "result": None, "error": None}

        def progress_cb(p: float, msg: str) -> None:
            self.tasks[task_id]["progress"] = round(p, 3)
            self.tasks[task_id]["message"] = msg
            self._notify(task_id)

        def runner() -> None:
            try:
                result = fn(*args, progress_cb=progress_cb, **kwargs)
                self.tasks[task_id].update(status="done", progress=1.0, result=result)
            except Exception as e:
                traceback.print_exc()
                self.tasks[task_id].update(status="error", error=str(e))
            self._notify(task_id)

        if self.loop is None:
            raise RuntimeError("事件循环未就绪")
        self.loop.run_in_executor(self.executor, runner)
        self._notify(task_id)
        return task_id

    def _notify(self, task_id: str) -> None:
        if self.loop and self.connections:
            payload = {"type": "task", "task_id": task_id, **{k: v for k, v in self.tasks[task_id].items() if k != "result"}}
            self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._broadcast(payload)))

    async def _broadcast(self, payload: dict) -> None:
        dead = []
        for ws in list(self.connections):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.connections.discard(ws)

    def get(self, task_id: str) -> dict[str, Any] | None:
        return self.tasks.get(task_id)


manager = TaskManager()
