"""
NEO Remote Server (Skeleton)

This is a TEMPLATE for running NEO as a remote service.
It is NOT a production-ready implementation.

To turn this into a real server, you MUST add:
    - Authentication (API keys, JWT, OAuth)
    - Rate limiting
    - Input validation
    - Task queue (e.g., Redis, Celery) for async execution
    - Concurrent request handling (thread/process pool)
    - Logging & monitoring
    - Timeouts and cancellation
    - Sandboxing / containerisation (Docker, gVisor)

Refer to the NEO Connector documentation for the core API.
"""

from __future__ import annotations

# Uncomment when you are ready to build the server:
# from fastapi import FastAPI, HTTPException
# from pydantic import BaseModel
# from neo_code.connector.api import run_task


# ------------------------------
# 1. Define request/response models (Pydantic)
# ------------------------------

# class TaskRequest(BaseModel):
#     task: str
#     workspace: str
#     provider: str | None = None
#     model: str | None = None
#     auto_approve: bool = False
#     max_iterations: int | None = None
#     timeout_s: int | None = None
#
# class TaskResponse(BaseModel):
#     id: str
#     status: str
#     summary: str
#     files_changed: list[str]
#     tests: list[dict]
#     errors: list[str]
#     iterations: int
#     duration_s: float


# ------------------------------
# 2. Create the FastAPI app
# ------------------------------

# app = FastAPI(
#     title="NEO Connector",
#     description="Remote AI coding engine",
#     version="1.0.0",
# )


# ------------------------------
# 3. Endpoints
# ------------------------------

# @app.post("/task", response_model=TaskResponse)
# async def run_task_endpoint(request: TaskRequest) -> Dict[str, Any]:
#     """
#     Execute a coding task synchronously.
#     For async execution, use a background task + task_id polling.
#     """
#     result = run_task(
#         task=request.task,
#         workspace=request.workspace,
#         provider=request.provider,
#         model=request.model,
#         confirm_callback=lambda *_, **__: request.auto_approve,
#     )
#     return result


# @app.get("/health")
# async def health():
#     return {"status": "ok"}


# @app.get("/status")
# async def status():
#     # Return current provider, model, memory usage, etc.
#     return {"status": "ready"}


# ------------------------------
# 4. Run the server (only if executed directly)
# ------------------------------

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8000)


# ------------------------------
# 5. Security & Deployment Notes
# ------------------------------

"""
SECURITY CONSIDERATIONS:

1. **Authentication**: Never expose this server without auth.
   Use API keys, JWT, or mutual TLS.

2. **Workspace isolation**: Each request should run in a dedicated
   workspace or container to avoid cross-contamination.

3. **Timeouts**: Set reasonable timeouts (max_iterations, command_timeout)
   to prevent DoS.

4. **Resource limits**: Limit CPU/memory per task (use process pools
   or containers).

5. **Logging**: Log all requests, tool calls, and errors for audit.

6. **Rate Limiting**: Protect against abuse with sliding window or
   token bucket.

For production, consider:
- Running behind a reverse proxy (nginx)
- Using Docker/Kubernetes for scaling
- Storing session logs in a centralised location
- Implementing a task queue (Celery, RQ) for asynchronous execution
"""
