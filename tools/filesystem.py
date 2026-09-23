"""Filesystem tools. All paths are resolved and constrained to the
active workspace root to prevent path-escape (e.g. ../../etc/passwd).
"""

from __future__ import annotations

import fnmatch
import os
import shutil
from pathlib import Path
from typing import Any

from neo_code.core.permissions import PermissionLevel
from neo_code.tools.base import Tool

MAX_READ_BYTES = 300_000
MAX_LIST_ENTRIES = 500
BINARY_EXT = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".exe",
    ".dll",
    ".so",
    ".pyc",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
}
IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".neo"}


class WorkspaceBoundTool(Tool):
    """Base for any tool that operates on paths relative to a fixed
    workspace root; `_resolve()` enforces that resolved paths never
    escape that root."""

    def __init__(self, workspace_root: str):
        self.root = Path(workspace_root).resolve()

    def _resolve(self, rel_path: str) -> Path:
        """Resolve `rel_path` against the workspace root, raising
        PermissionError if the result would fall outside it."""
        candidate = (self.root / rel_path).resolve()
        if self.root not in candidate.parents and candidate != self.root:
            raise PermissionError(f"Path '{rel_path}' escapes the workspace root ({self.root}).")
        return candidate


class ReadFileTool(WorkspaceBoundTool):
    """READ tool: returns a file's text content, optionally restricted
    to a 1-based inclusive line range. Refuses known binary extensions
    and files over MAX_READ_BYTES."""

    name = "read_file"
    description = "Read the text content of a file relative to the workspace root."
    permission = PermissionLevel.READ
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path relative to workspace root."},
            "start_line": {"type": "integer", "description": "Optional 1-based start line."},
            "end_line": {
                "type": "integer",
                "description": "Optional 1-based end line (inclusive).",
            },
        },
        "required": ["path"],
    }

    def execute(self, args: dict[str, Any]) -> Any:
        path = self._resolve(args["path"])
        if not path.exists():
            raise FileNotFoundError(f"No such file: {args['path']}")
        if path.suffix.lower() in BINARY_EXT:
            raise ValueError(f"Refusing to read binary file: {args['path']}")
        if path.stat().st_size > MAX_READ_BYTES:
            raise ValueError(
                f"File too large ({path.stat().st_size} bytes). Use start_line/end_line."
            )
        text = path.read_text(encoding="utf-8", errors="replace")
        start = args.get("start_line")
        end = args.get("end_line")
        if start or end:
            lines = text.splitlines()
            s = max((start or 1) - 1, 0)
            e = end or len(lines)
            text = "\n".join(lines[s:e])
        return {"path": path.relative_to(self.root).as_posix(), "content": text}


class WriteFileTool(WorkspaceBoundTool):
    """WRITE tool: creates a new file (making parent directories as
    needed) or fully overwrites an existing one."""

    name = "write_file"
    description = "Create a new file or fully overwrite an existing file with new content."
    permission = PermissionLevel.WRITE
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    }

    def describe_action(self, args: dict[str, Any]) -> str:
        return f"write_file: create/overwrite '{args.get('path')}' ({len(args.get('content', ''))} bytes)"

    def execute(self, args: dict[str, Any]) -> Any:
        path = self._resolve(args["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"], encoding="utf-8")
        return {
            "path": path.relative_to(self.root).as_posix(),
            "bytes_written": len(args["content"]),
        }


class EditFileTool(WorkspaceBoundTool):
    """WRITE tool: precise find-and-replace. Requires `old_text` to
    match exactly one location in the file — refuses if it's missing
    or ambiguous, so edits never land somewhere unintended."""

    name = "edit_file"
    description = (
        "Edit an existing file by replacing an exact, unique occurrence of "
        "old_text with new_text (like a precise find-and-replace)."
    )
    permission = PermissionLevel.WRITE
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_text": {"type": "string"},
            "new_text": {"type": "string"},
        },
        "required": ["path", "old_text", "new_text"],
    }

    def describe_action(self, args: dict[str, Any]) -> str:
        return f"edit_file: modify '{args.get('path')}'"

    def execute(self, args: dict[str, Any]) -> Any:
        path = self._resolve(args["path"])
        if not path.exists():
            raise FileNotFoundError(f"No such file: {args['path']}")
        content = path.read_text(encoding="utf-8")
        old, new = args["old_text"], args["new_text"]
        count = content.count(old)
        if count == 0:
            raise ValueError("old_text not found in file.")
        if count > 1:
            raise ValueError(
                f"old_text is not unique ({count} occurrences). "
                "Include more surrounding context."
            )
        path.write_text(content.replace(old, new, 1), encoding="utf-8")
        return {"path": path.relative_to(self.root).as_posix(), "replaced": True}


class DeleteFileTool(WorkspaceBoundTool):
    """SYSTEM tool: permanently deletes a file or directory (recursively
    for directories). Highest permission bar since this is irreversible."""

    name = "delete_file"
    description = "Delete a file or directory. ALWAYS requires explicit user confirmation."
    permission = PermissionLevel.SYSTEM  # highest bar — irreversible
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    def describe_action(self, args: dict[str, Any]) -> str:
        return f"delete_file: PERMANENTLY DELETE '{args.get('path')}'"

    def execute(self, args: dict[str, Any]) -> Any:
        path = self._resolve(args["path"])
        if not path.exists():
            raise FileNotFoundError(f"No such path: {args['path']}")
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return {"path": args["path"], "deleted": True}


class ListDirectoryTool(WorkspaceBoundTool):
    """READ tool: lists entries under a directory, optionally
    recursively, skipping IGNORE_DIRS (.git, node_modules, venvs, ...).
    Caps output at MAX_LIST_ENTRIES and reports if it truncated."""

    name = "list_directory"
    description = "List files and directories under a path relative to the workspace root."
    permission = PermissionLevel.READ
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Defaults to '.'"},
            "recursive": {"type": "boolean", "description": "Defaults to false."},
        },
        "required": [],
    }

    def execute(self, args: dict[str, Any]) -> Any:
        rel = args.get("path", ".")
        path = self._resolve(rel)
        if not path.exists():
            raise FileNotFoundError(f"No such directory: {rel}")
        recursive = args.get("recursive", False)
        entries: list[str] = []
        if recursive:
            for dirpath, dirnames, filenames in os.walk(path):
                dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
                dir_path_obj = Path(dirpath)
                for fname in filenames:
                    # Always report paths with forward slashes, even on
                    # Windows, so tool output is consistent across
                    # platforms (the agent, and downstream tool calls
                    # like read_file/edit_file, expect that convention).
                    rel = (dir_path_obj / fname).relative_to(self.root).as_posix()
                    entries.append(rel)
                    if len(entries) >= MAX_LIST_ENTRIES:
                        break
                if len(entries) >= MAX_LIST_ENTRIES:
                    break
        else:
            for entry in sorted(path.iterdir()):
                if entry.name in IGNORE_DIRS:
                    continue
                suffix = "/" if entry.is_dir() else ""
                entries.append(entry.relative_to(self.root).as_posix() + suffix)
        return {"path": rel, "entries": entries, "truncated": len(entries) >= MAX_LIST_ENTRIES}


class SearchFilesTool(WorkspaceBoundTool):
    """READ tool: simple substring search across text files under a
    subdirectory, with an optional filename glob filter. Skips binary
    extensions and IGNORE_DIRS; caps results at max_results."""

    name = "search_files"
    description = (
        "Search for a text pattern across files in the workspace (simple substring/glob search)."
    )
    permission = PermissionLevel.READ
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Text to search for."},
            "file_glob": {"type": "string", "description": "Optional glob filter, e.g. '*.py'."},
            "path": {"type": "string", "description": "Subdirectory to search. Defaults to '.'"},
            "max_results": {"type": "integer", "description": "Defaults to 50."},
        },
        "required": ["query"],
    }

    def execute(self, args: dict[str, Any]) -> Any:
        query = args["query"]
        file_glob = args.get("file_glob", "*")
        max_results = args.get("max_results", 50)
        start_path = self._resolve(args.get("path", "."))
        results: list[dict[str, Any]] = []

        for dirpath, dirnames, filenames in os.walk(start_path):
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
            for fname in filenames:
                if not fnmatch.fnmatch(fname, file_glob):
                    continue
                fpath = Path(dirpath) / fname
                if fpath.suffix.lower() in BINARY_EXT:
                    continue
                try:
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for lineno, line in enumerate(text.splitlines(), start=1):
                    if query in line:
                        results.append(
                            {
                                "path": fpath.relative_to(self.root).as_posix(),
                                "line": lineno,
                                "text": line.strip()[:200],
                            }
                        )
                        if len(results) >= max_results:
                            return {"query": query, "matches": results, "truncated": True}
        return {"query": query, "matches": results, "truncated": False}


def build_filesystem_tools(workspace_root: str) -> list[Tool]:
    """Instantiate all six filesystem tools bound to `workspace_root`."""
    return [
        ReadFileTool(workspace_root),
        WriteFileTool(workspace_root),
        EditFileTool(workspace_root),
        DeleteFileTool(workspace_root),
        ListDirectoryTool(workspace_root),
        SearchFilesTool(workspace_root),
    ]
