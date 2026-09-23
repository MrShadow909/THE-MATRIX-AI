"""Git tools. status/diff/log are READ level (informational only).
Anything that mutates history (commit/push/reset) must go through
execute_command, which independently escalates dangerous git
operations (force-push, reset --hard) to SYSTEM confirmation.
"""

from __future__ import annotations

import subprocess
from typing import Any

from neo_code.core.permissions import PermissionLevel
from neo_code.tools.base import Tool


class _GitReadTool(Tool):
    """Base for the read-only git tools: runs a fixed `git <git_args>`
    command and reports `is_git_repo: False` gracefully if the
    workspace isn't a git repository, instead of raising."""

    permission = PermissionLevel.READ
    git_args: list[str] = []

    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root

    def execute(self, args: dict[str, Any]) -> Any:
        proc = subprocess.run(
            ["git", *self.git_args],
            cwd=self.workspace_root,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if proc.returncode != 0 and "not a git repository" in proc.stderr.lower():
            return {"is_git_repo": False}
        return {"is_git_repo": True, "output": proc.stdout.strip() or proc.stderr.strip()}


class GitStatusTool(_GitReadTool):
    name = "git_status"
    description = "Show git working-tree status (staged/unstaged/untracked files)."
    parameters = {"type": "object", "properties": {}, "required": []}
    git_args = ["status", "--short", "--branch"]


class GitDiffTool(_GitReadTool):
    name = "git_diff"
    description = "Show unstaged git diff for the working tree."
    parameters = {"type": "object", "properties": {}, "required": []}
    git_args = ["diff"]


class GitLogTool(_GitReadTool):
    name = "git_log"
    description = "Show recent git commit history (last 15 commits, one line each)."
    parameters = {"type": "object", "properties": {}, "required": []}
    git_args = ["log", "-15", "--oneline"]


def build_git_tools(workspace_root: str) -> list[Tool]:
    """Instantiate the three read-only git tools bound to `workspace_root`."""
    return [GitStatusTool(workspace_root), GitDiffTool(workspace_root), GitLogTool(workspace_root)]
