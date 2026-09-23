"""
Delegate Tool (Skeleton)

This tool allows an NEO agent to delegate sub-tasks to another
NEO instance (local subprocess, remote worker, or hub).

To use:
    1. Place this file in neo_code/tools/delegate.py
    2. Register it in agent.py: build_tool_registry()
    3. The agent can now call `delegate_task` as a tool.

SECURITY: This tool can run arbitrary code. Use with caution.
"""

from typing import Any

from neo_code.core.permissions import PermissionLevel
from neo_code.tools.base import Tool


class DelegateTaskTool(Tool):
    name = "delegate_task"
    description = (
        "Delegate a sub-task to another NEO instance. "
        "Useful for parallel execution or when a task requires a separate workspace."
    )
    permission = PermissionLevel.EXECUTE
    parameters = {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "The sub-task to delegate."},
            "workspace": {"type": "string", "description": "Workspace for the sub-task."},
            "provider": {"type": "string", "description": "Optional provider override."},
            "model": {"type": "string", "description": "Optional model override."},
            "auto_approve": {"type": "boolean", "default": False},
        },
        "required": ["task"],
    }

    def __init__(
        self, workspace_root: str, default_provider: str = None, default_model: str = None
    ):
        self.workspace_root = workspace_root
        self.default_provider = default_provider
        self.default_model = default_model

    def execute(self, args: dict[str, Any]) -> Any:
        """
        Execute the delegated task.
        """
        from neo_code.connector.api import run_task_subprocess

        workspace = args.get("workspace", self.workspace_root)
        provider = args.get("provider", self.default_provider)
        model = args.get("model", self.default_model)

        # Option 1: Subprocess (isolated)
        result = run_task_subprocess(
            task=args["task"],
            workspace=workspace,
            neo_code_executable="neo",
            timeout_s=600,
        )

        # Option 2: HTTP (if a remote hub/server is available)
        # result = self._call_remote_server(args["task"], workspace, provider, model)

        # Option 3: In-process (same process – beware of recursion)
        # from neo_code.connector.api import run_task
        # result = run_task(...)

        return result

    def _call_remote_server(
        self, task: str, workspace: str, provider: str, model: str
    ) -> dict[str, Any]:
        """Placeholder for remote HTTP dispatch."""
        raise NotImplementedError(
            "To delegate to a remote server, implement HTTP calls here "
            "or use the Hub class from connector/hub.py."
        )
