"""
NEO Hub (Skeleton)

A lightweight coordinator that routes tasks to multiple NEO instances.
This is a TEMPLATE – not a production-ready implementation.

To build a real hub, implement:
    - Service discovery (static list, Consul, etc.)
    - Load balancing (round-robin, least-connections)
    - Health checks
    - Retry logic
    - Authentication & authorisation
    - Task persistence
"""

from typing import Any


class NeoCodeHub:
    """
    Routes tasks to multiple NEO workers.

    Example:
        hub = NeoCodeHub(["http://worker1:8000", "http://worker2:8000"])
        result = hub.dispatch("Fix the failing test", workspace="/path")
    """

    def __init__(self, workers: list[str]):
        self.workers = workers

    def dispatch(self, task: str, workspace: str, **kwargs) -> dict[str, Any]:
        """
        Send a task to one of the workers.
        """
        # Placeholder: round-robin or hash-based worker selection
        # worker = self.workers[hash(task) % len(self.workers)]
        # return self._call_worker(worker, task, workspace, **kwargs)

        raise NotImplementedError(
            "This is a skeleton. Implement worker selection and communication "
            "using connector.api.run_task_subprocess() or HTTP calls."
        )

    def _call_worker(self, worker: str, task: str, workspace: str, **kwargs) -> dict[str, Any]:
        """Send a task to a specific worker."""
        # Option 1: Use subprocess (if worker is same binary)
        # return run_task_subprocess(task, workspace, ...)

        # Option 2: Use HTTP (if worker exposes a server)
        # import requests
        # response = requests.post(f"{worker}/task", json={...})
        # return response.json()

        raise NotImplementedError("Implement communication with the worker.")
