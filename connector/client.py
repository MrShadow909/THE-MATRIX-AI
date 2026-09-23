"""
NEO Remote Client (Skeleton)

A TEMPLATE for a Python client that talks to the remote server
defined in `connector/server.py`. It is NOT a functional client
out-of-the-box: the server it targets is itself commented-out
scaffolding (see server.py), so there is nothing live to call yet.

Once you have implemented and deployed `server.py` (or any HTTP
service that speaks the same request/response shape as
`neo_code.connector.api.run_task`), fill in the pieces below.

Refer to the NEO Connector documentation for the core API.
"""

from __future__ import annotations

# Uncomment when you are ready to build the client:
# import requests


# ------------------------------
# 1. Client configuration
# ------------------------------

# DEFAULT_TIMEOUT_S = 600


# ------------------------------
# 2. Client class
# ------------------------------

# class NeoCodeClient:
#     """Thin HTTP client for a deployed NEO Connector server.
#
#     Mirrors the shape of `neo_code.connector.api.run_task` so callers
#     can swap between in-process and remote execution with minimal
#     code changes.
#     """
#
#     def __init__(
#         self,
#         base_url: str,
#         api_key: str | None = None,
#         timeout_s: int = DEFAULT_TIMEOUT_S,
#     ):
#         self.base_url = base_url.rstrip("/")
#         self.api_key = api_key
#         self.timeout_s = timeout_s
#
#     def _headers(self) -> dict[str, str]:
#         headers = {"Content-Type": "application/json"}
#         if self.api_key:
#             headers["Authorization"] = f"Bearer {self.api_key}"
#         return headers
#
#     def run_task(
#         self,
#         task: str,
#         workspace: str,
#         provider: str | None = None,
#         model: str | None = None,
#         auto_approve: bool = False,
#     ) -> dict:
#         """POST /task — mirrors neo_code.connector.api.run_task's
#         signature and return shape (status/summary/files_changed/
#         tests/errors), but executes on the remote server instead of
#         in this process."""
#         response = requests.post(
#             f"{self.base_url}/task",
#             json={
#                 "task": task,
#                 "workspace": workspace,
#                 "provider": provider,
#                 "model": model,
#                 "auto_approve": auto_approve,
#             },
#             headers=self._headers(),
#             timeout=self.timeout_s,
#         )
#         response.raise_for_status()
#         return response.json()
#
#     def health(self) -> dict:
#         """GET /health — basic liveness check."""
#         response = requests.get(
#             f"{self.base_url}/health", headers=self._headers(), timeout=10
#         )
#         response.raise_for_status()
#         return response.json()
#
#     def status(self) -> dict:
#         """GET /status — current provider/model/memory info."""
#         response = requests.get(
#             f"{self.base_url}/status", headers=self._headers(), timeout=10
#         )
#         response.raise_for_status()
#         return response.json()


# ------------------------------
# 3. Example usage (only if executed directly)
# ------------------------------

# if __name__ == "__main__":
#     client = NeoCodeClient(base_url="http://localhost:8000", api_key="change-me")
#     result = client.run_task(
#         task="Add input validation to the signup form",
#         workspace="/remote/path/to/project",
#         auto_approve=False,
#     )
#     print(result["status"], result["summary"])


# ------------------------------
# 4. Usage Notes
# ------------------------------

"""
USAGE NOTES:

1. **Matching the server**: This client assumes a server shaped like
   the FastAPI skeleton in `server.py` (POST /task, GET /health,
   GET /status). If you build a different server contract, update
   this client to match it.

2. **Auth**: Pass whatever credential your server expects (API key,
   bearer token, mTLS client cert) — do not hardcode secrets here.

3. **Long-running tasks**: `run_task` is synchronous in this
   skeleton. For tasks that may exceed reasonable HTTP timeouts,
   pair this with an async job-submission + polling pattern on the
   server side (submit -> task_id -> poll /status/{task_id}).

4. **Retries**: Network calls to a remote NEO instance can fail
   transiently. Add retry/backoff logic appropriate to your
   deployment before relying on this in production.
"""
