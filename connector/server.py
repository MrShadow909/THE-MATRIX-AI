"""
NEO Remote Server  REST API for the NEO agent.

Run:
    python -m neo_code.connector.server
    # or
    uvicorn neo_code.connector.server:app --host 0.0.0.0 --port 8000

Endpoints:
    GET  /health         health check
    GET  /status         current config
    POST /task           execute a coding task
    POST /task/async     submit task (returns task_id)
    GET  /task/{id}      poll task status
"""

from __future__ import annotations

import uuid
import time
import threading
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

from neo_code.connector.api import run_task


# ============ Models ============

class TaskRequest(BaseModel):
    """Request body for /task."""
    task: str = Field(..., description="Coding task description")
    workspace: str = Field(..., description="Project root path")
    provider: Optional[str] = Field(None, description="LLM provider")
    model: Optional[str] = Field(None, description="Model name")
    auto_approve: bool = Field(False, description="Skip confirmations")
    max_iterations: Optional[int] = Field(None, description="Loop limit")
    timeout_s: Optional[int] = Field(None, description="Timeout seconds")


class TaskResponse(BaseModel):
    """Response body for /task."""
    id: str
    status: str
    summary: str
    files_changed: list[str]
    tests: list[dict]
    errors: list[str]
    iterations: int
    duration_s: float


class AsyncTaskResponse(BaseModel):
    """Response for /task/async."""
    task_id: str
    status: str
    message: str


class HealthResponse(BaseModel):
    status: str
    version: str


# ============ In-memory task store (use Redis in production) ============

_tasks: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()


# ============ App ============

app = FastAPI(
    title="NEO Connector",
    description="Remote AI software engineering engine",
    version="1.0.0",
)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(status="ok", version="1.0.0")


@app.get("/status")
async def status() -> Dict[str, Any]:
    """Return current server status."""
    from neo_code.config import Config
    cfg = Config.load()
    return {
        "status": "ready",
        "provider": cfg.provider,
        "model": cfg.model,
        "workspace": cfg.workspace,
    }


@app.post("/task", response_model=TaskResponse)
async def run_task_endpoint(request: TaskRequest) -> TaskResponse:
    """
    Execute a coding task synchronously.
    WARNING: This blocks until the task completes. Use /task/async for long tasks.
    """
    task_id = str(uuid.uuid4())
    started = time.time()

    try:
        result = run_task(
            task=request.task,
            workspace=request.workspace,
            provider=request.provider,
            model=request.model,
            confirm_callback=(lambda *_, **__: True) if request.auto_approve else None,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return TaskResponse(
        id=task_id,
        status=result.get("status", "completed"),
        summary=result.get("summary", ""),
        files_changed=result.get("files_changed", []),
        tests=result.get("tests", []),
        errors=result.get("errors", []),
        iterations=result.get("iterations", 0),
        duration_s=time.time() - started,
    )


@app.post("/task/async", response_model=AsyncTaskResponse)
async def run_task_async(request: TaskRequest, background: BackgroundTasks) -> AsyncTaskResponse:
    """Submit a task for asynchronous execution. Poll /task/{id}."""
    task_id = str(uuid.uuid4())

    with _lock:
        _tasks[task_id] = {"status": "queued", "result": None, "error": None}

    def _worker():
        try:
            result = run_task(
                task=request.task,
                workspace=request.workspace,
                provider=request.provider,
                model=request.model,
                confirm_callback=(lambda *_, **__: True) if request.auto_approve else None,
            )
            with _lock:
                _tasks[task_id] = {"status": "completed", "result": result, "error": None}
        except Exception as exc:
            with _lock:
                _tasks[task_id] = {"status": "failed", "result": None, "error": str(exc)}

    background.add_task(_worker)

    return AsyncTaskResponse(
        task_id=task_id,
        status="queued",
        message=f"Task submitted. Poll /task/{task_id}",
    )


@app.get("/task/{task_id}")
async def get_task_status(task_id: str) -> Dict[str, Any]:
    """Poll the status of an async task."""
    with _lock:
        entry = _tasks.get(task_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task_id": task_id, **entry}


# ============ Run ============

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
