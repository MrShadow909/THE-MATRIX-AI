"""Builds a compact ProjectContext object describing the workspace,
used to seed the system prompt without loading every file into the
model (spec §11 — targeted inspection only).
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from neo_code.tools.project import detect_project


@dataclass
class ProjectContext:
    root: str
    detected: List[str] = field(default_factory=list)
    important_files: List[str] = field(default_factory=list)
    dependencies: Dict[str, Any] = field(default_factory=dict)
    git_branch: str | None = None
    git_dirty: bool = False
    top_level_entries: List[str] = field(default_factory=list)

    def as_prompt_block(self) -> str:
        lines = [
            f"Workspace root: {self.root}",
            f"Detected: {', '.join(self.detected) if self.detected else 'unknown project type'}",
        ]
        if self.git_branch:
            lines.append(f"Git branch: {self.git_branch} ({'dirty' if self.git_dirty else 'clean'})")
        if self.top_level_entries:
            lines.append("Top-level entries: " + ", ".join(self.top_level_entries[:25]))
        return "\n".join(lines)


def build_project_context(root: str) -> ProjectContext:
    info = detect_project(root)
    root_path = Path(root)

    top_level = []
    try:
        for entry in sorted(root_path.iterdir()):
            if entry.name.startswith(".") and entry.name != ".env.example":
                continue
            top_level.append(entry.name + ("/" if entry.is_dir() else ""))
    except OSError:
        pass

    branch = None
    dirty = False
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=root, capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0:
            branch = proc.stdout.strip()
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root, capture_output=True, text=True, timeout=5,
            )
            dirty = bool(status.stdout.strip())
    except (subprocess.SubprocessError, OSError):
        pass

    return ProjectContext(
        root=info["root"],
        detected=info["detected"],
        important_files=info["important_files"],
        dependencies=info["dependencies"],
        git_branch=branch,
        git_dirty=dirty,
        top_level_entries=top_level,
    )
