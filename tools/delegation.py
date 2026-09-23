"""Multi-agent delegation system for NEO.

Allows the main agent to spawn specialized sub-agents for different
task types. Each sub-agent runs in its own subprocess (isolated),
with its own workspace and provider configuration.

Agent roles:
    - python:    Python coding tasks
    - web:       Web/frontend (HTML/CSS/JS) tasks
    - test:      Testing and QA
    - admin:     OS-level file organization and system tasks
    - research:  Searching and analysis
    - general:   Any other task (default)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from neo_code.core.permissions import PermissionLevel
from neo_code.tools.base import Tool

# Role definitions: name -> description of what that agent specializes in
AGENT_ROLES = {
    "python": {
        "description": "Specialized in Python coding, debugging, and refactoring.",
        "model_hint": None,
    },
    "web": {
        "description": "Specialized in HTML, CSS, JavaScript, and frontend development.",
        "model_hint": None,
    },
    "test": {
        "description": "Specialized in writing and running tests, QA, and verification.",
        "model_hint": None,
    },
    "admin": {
        "description": "Specialized in OS-level tasks: file organization, system info, cleanup.",
        "model_hint": None,
    },
    "research": {
        "description": "Specialized in searching, reading, and analyzing code or data.",
        "model_hint": None,
    },
    "general": {
        "description": "General-purpose agent for any task.",
        "model_hint": None,
    },
}


class DelegateTaskTool(Tool):
    """EXECUTE tool: spawns a specialized sub-agent to handle a task."""

    name = "delegate_task"
    description = (
        "Delegate a sub-task to a specialized sub-agent. Choose a role from: "
        + ", ".join(AGENT_ROLES.keys())
        + ". The sub-agent runs in its own isolated subprocess."
    )
    permission = PermissionLevel.EXECUTE
    parameters = {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "The sub-task to delegate."},
            "role": {
                "type": "string",
                "enum": list(AGENT_ROLES.keys()),
                "description": "Which specialized agent should handle this.",
            },
            "workspace": {
                "type": "string",
                "description": "Workspace for the sub-agent (default: current workspace).",
            },
            "timeout_s": {
                "type": "integer",
                "description": "Timeout in seconds (default 600).",
            },
        },
        "required": ["task", "role"],
    }

    def __init__(self, workspace_root: str, default_timeout: int = 600):
        self.workspace_root = workspace_root
        self.default_timeout = default_timeout

    def describe_action(self, args: dict[str, Any]) -> str:
        role = args.get("role", "general")
        return f"delegate_task: spawn {role} agent for '{args.get('task', '')[:50]}...'"

    def execute(self, args: dict[str, Any]) -> Any:
        task = args["task"]
        role = args.get("role", "general")
        workspace = args.get("workspace", self.workspace_root)
        timeout = min(int(args.get("timeout_s", self.default_timeout)), 3600)

        if role not in AGENT_ROLES:
            raise ValueError(f"Unknown role '{role}'. Choose from: {', '.join(AGENT_ROLES.keys())}")

        # Build a role-specific system prompt to inject into the sub-agent
        role_prompt = AGENT_ROLES[role]["description"]

        # Prepare the task JSON payload
        payload = json.dumps({
            "task": task,
            "workspace": workspace,
            "role": role,
            "role_prompt": role_prompt,
        })

        # Find the neo executable
        neo_code_exe = self._find_executable()

        try:
            proc = subprocess.run(
                [sys.executable, "-m", "neo_code.cli", "--task-json", "-"],
                input=payload,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.workspace_root,
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "failed",
                "summary": f"{role} agent timed out after {timeout}s",
                "role": role,
                "files_changed": [],
                "tests": [],
                "errors": [f"Timeout after {timeout}s"],
            }
        except (subprocess.SubprocessError, FileNotFoundError) as exc:
            return {
                "status": "failed",
                "summary": f"Could not launch {role} agent: {exc}",
                "role": role,
                "files_changed": [],
                "tests": [],
                "errors": [str(exc)],
            }

        # Parse the JSON report from the last line of stdout
        try:
            lines = proc.stdout.strip().splitlines()
            report = json.loads(lines[-1]) if lines else {}
            report["role"] = role
            return report
        except (json.JSONDecodeError, IndexError):
            return {
                "status": "failed",
                "summary": f"{role} agent did not return valid JSON.",
                "role": role,
                "files_changed": [],
                "tests": [],
                "errors": [proc.stderr[-2000:] or "no stderr captured"],
            }

    def _find_executable(self) -> str:
        """Find the neo executable (installed script or module)."""
        # Try the installed console script first
        import shutil
        exe = shutil.which("neo")
        if exe:
            return exe
        # Fall back to running as a module
        return sys.executable


class ListAgentsTool(Tool):
    """READ tool: lists available agent roles and their descriptions."""

    name = "list_agents"
    description = "List all available specialized agent roles and what each one does."
    permission = PermissionLevel.READ
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def execute(self, args: dict[str, Any]) -> Any:
        return {
            "agent_count": len(AGENT_ROLES),
            "agents": [
                {"role": role, "description": info["description"]}
                for role, info in AGENT_ROLES.items()
            ],
        }


def build_delegation_tools(workspace_root: str) -> list[Tool]:
    """Build and return the delegation tool set."""
    return [
        DelegateTaskTool(workspace_root),
        ListAgentsTool(),
    ]
