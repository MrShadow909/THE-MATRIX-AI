"""Terminal tools. All shell commands run with a timeout and are
gated by the permission system. Commands matching known destructive
patterns are escalated to SYSTEM level regardless of the base level.
"""

from __future__ import annotations

import re
import subprocess
from typing import Any

from neo_code.core.permissions import PermissionLevel
from neo_code.tools.base import Tool

DANGEROUS_PATTERNS = [
    r"\brm\s+-rf\s+/",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r">\s*/dev/sd",
    r"\bchmod\s+-R\s+777\s+/",
    r":\(\)\s*\{\s*:\|:&\s*\};:",
    r"\bgit\s+push\s+.*--force",
    r"\bgit\s+reset\s+--hard",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\brmdir\s+/s\b",
    r"\brd\s+/s\b",
    r"\bdel\s+/[fsq]+\b",
    r"\bformat\s+[a-zA-Z]:",
    r"\bRemove-Item\b.*-Recurse.*-Force",
    r"\bRemove-Item\b.*-Force.*-Recurse",
    r"\bStop-Computer\b",
    r"\bRestart-Computer\b",
]


class ExecuteCommandTool(Tool):
    name = "execute_command"
    description = (
        "Execute a shell command inside the workspace directory. "
        "Use `background: true` for long‑running servers/daemons."
    )
    permission = PermissionLevel.EXECUTE
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to run."},
            "timeout_s": {"type": "integer", "description": "Optional override, capped by config."},
            "background": {
                "type": "boolean",
                "description": "Run in background (does not wait for completion). Default false."
            },
        },
        "required": ["command"],
    }

    def __init__(self, workspace_root: str, default_timeout: int = 60):
        self.workspace_root = workspace_root
        self.default_timeout = default_timeout

    def describe_action(self, args: dict[str, Any]) -> str:
        return f"execute_command: `{args.get('command')}`"

    def _is_dangerous(self, command: str) -> bool:
        return any(re.search(p, command, re.IGNORECASE) for p in DANGEROUS_PATTERNS)

    def run(self, args, permissions):
        command = args.get("command", "")
        if self._is_dangerous(command):
            self.permission = PermissionLevel.SYSTEM
        else:
            self.permission = PermissionLevel.EXECUTE
        return super().run(args, permissions)

    def execute(self, args: dict[str, Any]) -> Any:
        command = args["command"]
        background = args.get("background", False)

        if background:
            # Start process in background – do NOT wait
            proc = subprocess.Popen(
                command,
                shell=True,
                cwd=self.workspace_root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return {
                "command": command,
                "pid": proc.pid,
                "status": "started_in_background",
                "note": "Process is running in background. Use ps/kill to manage it."
            }

        # Normal blocking execution
        timeout = min(args.get("timeout_s", self.default_timeout), self.default_timeout * 3)
        proc = subprocess.run(
            command,
            shell=True,
            cwd=self.workspace_root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "command": command,
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-8000:],
            "stderr": proc.stderr[-4000:],
        }


class RunTestsTool(Tool):
    name = "run_tests"
    description = (
        "Run the project's test suite. Auto-detects pytest/npm test/go test "
        "based on project files, or runs a provided command."
    )
    permission = PermissionLevel.EXECUTE
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Optional explicit test command override.",
            }
        },
        "required": [],
    }

    def __init__(self, workspace_root: str, default_timeout: int = 120):
        self.workspace_root = workspace_root
        self.default_timeout = default_timeout

    def describe_action(self, args: dict[str, Any]) -> str:
        return f"run_tests: {args.get('command', '(auto-detect)')}"

    def _detect_command(self) -> str:
        from pathlib import Path
        root = Path(self.workspace_root)
        if (root / "pytest.ini").exists() or (root / "pyproject.toml").exists():
            return "python -m pytest -q"
        if (root / "manage.py").exists():
            return "python manage.py test"
        if (root / "package.json").exists():
            return "npm test --silent"
        if (root / "go.mod").exists():
            return "go test ./..."
        return "python -m pytest -q"

    def execute(self, args: dict[str, Any]) -> Any:
        command = args.get("command") or self._detect_command()
        proc = subprocess.run(
            command,
            shell=True,
            cwd=self.workspace_root,
            capture_output=True,
            text=True,
            timeout=self.default_timeout,
        )
        return {
            "command": command,
            "exit_code": proc.returncode,
            "passed": proc.returncode == 0,
            "stdout": proc.stdout[-8000:],
            "stderr": proc.stderr[-4000:],
        }


def build_terminal_tools(workspace_root: str, command_timeout: int) -> list[Tool]:
    return [
        ExecuteCommandTool(workspace_root, command_timeout),
        RunTestsTool(workspace_root, max(command_timeout * 2, 120)),
    ]