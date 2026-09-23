"""Project detection: framework/language/dependency sniffing without
blindly loading every file into the model.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from neo_code.core.permissions import PermissionLevel
from neo_code.tools.base import Tool

# (marker file, project type / framework label)
MARKERS = [
    ("pyproject.toml", "Python"),
    ("requirements.txt", "Python"),
    ("manage.py", "Django"),
    ("app.py", "Flask (possible)"),
    ("package.json", "Node.js"),
    ("next.config.js", "Next.js"),
    ("next.config.ts", "Next.js"),
    ("angular.json", "Angular"),
    ("vue.config.js", "Vue"),
    ("Dockerfile", "Docker"),
    ("docker-compose.yml", "Docker Compose"),
    ("go.mod", "Go"),
    ("Cargo.toml", "Rust"),
    ("Gemfile", "Ruby"),
    ("pom.xml", "Java/Maven"),
    ("build.gradle", "Java/Gradle"),
    (".git", "Git repository"),
]


def detect_project(root: str) -> dict[str, Any]:
    """Sniff `root` for known marker files (pyproject.toml,
    package.json, go.mod, ...) and, where present, parse package.json /
    requirements.txt to flag common frameworks (React, Flask, Django,
    ...). Returns {"root", "detected", "important_files", "dependencies"}.
    Malformed dependency files are skipped silently rather than raising."""
    root_path = Path(root)
    detected: list[str] = []
    important_files: list[str] = []

    for marker, label in MARKERS:
        if (root_path / marker).exists():
            detected.append(label)
            important_files.append(marker)

    dependencies: dict[str, Any] = {}

    pkg_json = root_path / "package.json"
    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            dependencies["node"] = deps
            if "react" in deps:
                detected.append("React")
            if "express" in deps:
                detected.append("Express")
        except (json.JSONDecodeError, OSError):
            pass

    req_txt = root_path / "requirements.txt"
    if req_txt.exists():
        try:
            lines = [
                line.strip()
                for line in req_txt.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")
            ]
            dependencies["python"] = lines
            joined = " ".join(lines).lower()
            if "flask" in joined:
                detected.append("Flask")
            if "fastapi" in joined:
                detected.append("FastAPI")
            if "django" in joined:
                detected.append("Django")
        except OSError:
            pass

    return {
        "root": str(root_path.resolve()),
        "detected": sorted(set(detected)),
        "important_files": important_files,
        "dependencies": dependencies,
    }


class DetectProjectTool(Tool):
    """READ tool wrapping `detect_project()` for the agent's tool
    registry."""

    name = "detect_project_type"
    description = "Detect project type, framework(s), and key dependency files in the workspace."
    permission = PermissionLevel.READ
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root

    def execute(self, args: dict[str, Any]) -> Any:
        return detect_project(self.workspace_root)


def build_project_tools(workspace_root: str) -> list[Tool]:
    """Instantiate the single `detect_project_type` tool."""
    return [DetectProjectTool(workspace_root)]
