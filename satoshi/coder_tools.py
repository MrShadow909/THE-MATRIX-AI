"""Workspace-scoped coding tools for SATOSHI.

No wallet, secret/key access, remote shell, network POST, or auto-approve.
Tool execution permissions are enforced by SatoshiCoder, not by prompts.
"""
from __future__ import annotations

import fnmatch
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .web_tools import fetch_public_page, scrape_public_page, github_public_repo

MAX_FILE_BYTES = 120_000
MAX_OUTPUT = 12_000
FORBIDDEN_NAMES = {".env", ".git", ".ssh", ".aws", ".gnupg", "node_modules", "__pycache__", ".venv", "venv", ".satoshi", "wallet.json", "wallets.json", "id_rsa", "id_ed25519"}
FORBIDDEN_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".sqlite", ".db", ".pyc"}


def _parameters(**properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": [k for k, v in properties.items() if not v.get("optional")], "additionalProperties": False}


def _str(description: str, optional: bool = False) -> dict:
    return {"type": "string", "description": description, **({"optional": True} if optional else {})}


@dataclass(frozen=True)
class ToolInfo:
    name: str
    description: str
    safety: str
    params: dict
    fn: Callable[[dict], Any]

    def schema(self) -> dict:
        props = {k: {p: v for p, v in spec.items() if p != "optional"} for k, spec in self.params["properties"].items()}
        return {"name": self.name, "description": self.description,
                "input_schema": {**self.params, "properties": props}}


class WorkspaceTools:
    def __init__(self, root: str | Path | None = None, fetcher=None):
        default = Path.home() / "SATOSHI_Workspace"
        self.root = Path(root or os.getenv("SATOSHI_WORKSPACE", str(default))).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root == Path.home() or self.root == Path("/"):
            raise ValueError("SATOSHI_WORKSPACE cannot be the home or filesystem root")
        self.fetcher = fetcher or fetch_public_page
        self._register()

    def _path(self, relative: str, allow_root: bool = False) -> Path:
        if not isinstance(relative, str) or len(relative) > 220 or not relative or Path(relative).is_absolute():
            raise ValueError("Use a relative workspace path")
        parts = Path(relative).parts
        if any(x in FORBIDDEN_NAMES or x.startswith(".env") or x.endswith("~") for x in parts):
            raise ValueError("Protected path")
        candidate = (self.root / relative).resolve()
        if not candidate.is_relative_to(self.root) or (not allow_root and candidate == self.root):
            raise ValueError("Path escapes workspace")
        if candidate.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise ValueError("Protected file extension")
        return candidate

    def _read_text(self, path: Path) -> str:
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("File missing or larger than 120 KB")
        return path.read_text(encoding="utf-8")

    def _git(self, *argv: str) -> dict:
        p = subprocess.run(["git", "-C", str(self.root), "--no-pager", *argv],
                           capture_output=True, text=True, timeout=20, check=False,
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        if p.returncode:
            return {"ok": False, "code": p.returncode, "error": (p.stderr or p.stdout)[-1200:]}
        return {"ok": True, "output": p.stdout[-MAX_OUTPUT:]}

    def _run_tests(self, args):
        command = args.get("suite", "unittest")
        options = {
            "unittest": ["python", "-m", "unittest", "discover", "-s", "tests", "-q"],
            "pytest": ["python", "-m", "pytest", "-q"],
            "node": ["node", "--test"],
        }
        if command not in options:
            raise ValueError("Only unittest, pytest, or node test runners supported")
        proc = subprocess.run(options[command], cwd=self.root, capture_output=True, text=True,
                              timeout=60, check=False, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        return {"passed": proc.returncode == 0, "exit_code": proc.returncode,
                "stdout": proc.stdout[-7000:], "stderr": proc.stderr[-3500:]}

    def _register(self):
        self.registry: dict[str, ToolInfo] = {}

        def add(name, description, safety, params, fn):
            self.registry[name] = ToolInfo(name, description, safety, params, fn)

        add("list_directory", "List workspace files", "read", _parameters(path=_str("Relative directory, use . for root")),
            lambda a: self._list(a["path"]))
        add("read_file", "Read UTF-8 source text in workspace (not secrets)", "read", _parameters(path=_str("Relative path")),
            lambda a: {"path": a["path"], "content": self._read_text(self._path(a["path"]))})
        add("search_files", "Find text within allowed UTF-8 workspace files", "read",
            _parameters(pattern=_str("Literal substring to search")), lambda a: self._search(a["pattern"]))
        add("write_file", "Create a new UTF-8 file; never silently overwrite", "write",
            _parameters(path=_str("Relative new file"), content=_str("Full file content")), lambda a: self._write(a["path"], a["content"]))
        add("edit_file", "Replace one unique exact UTF-8 snippet within an existing source file", "write",
            _parameters(path=_str("Relative existing file"), old=_str("Exact text to replace"), new=_str("Replacement text")),
            lambda a: self._edit(a["path"], a["old"], a["new"]))
        add("delete_file", "Remove one regular file within workspace (requires approval)", "write",
            _parameters(path=_str("Relative existing file")), lambda a: self._delete(a["path"]))
        add("git_status", "Read local Git status", "read", _parameters(), lambda a: self._git("status", "--short"))
        add("git_diff", "Read local Git diff", "read", _parameters(), lambda a: self._git("diff", "--", "."))
        add("git_log", "Read recent Git commits", "read", _parameters(), lambda a: self._git("log", "-5", "--oneline"))
        add("git_add", "Stage one named workspace file, never all files", "write", _parameters(path=_str("Relative file path")),
            lambda a: self._git("add", "--", str(self._path(a["path"]).relative_to(self.root))))
        add("git_commit", "Commit previously staged changes locally (no push)", "write",
            _parameters(message=_str("Human-readable commit message")), lambda a: self._commit(a["message"]))
        add("run_tests", "Run selected project tests; requires approval because test code executes", "execute",
            _parameters(suite=_str("unittest, pytest or node", optional=True)), self._run_tests)
        add("web_fetch", "Open a public HTTPS page as read-only text; returns links for next navigation", "read",
            _parameters(url=_str("Public HTTPS URL")), lambda a: self.fetcher(a["url"]))
        add("web_scrape", "Extract headings, links and page text from public HTTPS page", "read",
            _parameters(url=_str("Public HTTPS URL")), lambda a: scrape_public_page(a["url"], fetcher=self.fetcher))
        add("github_repo", "Public GitHub repository metadata (read-only)", "read",
            _parameters(repo=_str("owner/name public repository")), lambda a: github_public_repo(a["repo"], fetcher=self.fetcher))

    def _list(self, path: str):
        d = self._path(path, allow_root=True)
        if not d.is_dir():
            raise ValueError("Not a directory")
        return {"path": path, "entries": [
            {"name": p.name, "type": "dir" if p.is_dir() else "file"}
            for p in sorted(d.iterdir()) if not p.name in FORBIDDEN_NAMES and not p.name.startswith(".env")
        ][:120]}

    def _search(self, pattern: str):
        if not isinstance(pattern, str) or not (1 <= len(pattern) <= 180):
            raise ValueError("Invalid search pattern")
        matches = []
        seen = 0
        for root, dirs, files in os.walk(self.root, followlinks=False):
            dirs[:] = [d for d in dirs if d not in FORBIDDEN_NAMES and not d.startswith(".env")]
            for name in files:
                if name in FORBIDDEN_NAMES or name.startswith(".env") or Path(name).suffix in FORBIDDEN_SUFFIXES:
                    continue
                p = Path(root) / name
                try:
                    self._path(str(p.relative_to(self.root)))
                    if not p.is_file() or p.stat().st_size > MAX_FILE_BYTES:
                        continue
                    for n, line in enumerate(self._read_text(p).splitlines(), 1):
                        if pattern.lower() in line.lower():
                            matches.append({"file": str(p.relative_to(self.root)), "line": n, "text": line[:180]})
                            if len(matches) >= 50:
                                return {"matches": matches, "truncated": True}
                except (OSError, UnicodeError, ValueError):
                    continue
                seen += 1
                if seen >= 300:
                    return {"matches": matches, "truncated": True}
        return {"matches": matches, "truncated": False}

    def _write(self, relative: str, content: str):
        if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError("Source must be UTF-8 and under 120 KB")
        p = self._path(relative)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("x", encoding="utf-8") as f:
            f.write(content)
        return {"created": relative, "bytes": len(content.encode("utf-8"))}

    def _edit(self, relative: str, old: str, new: str):
        if not isinstance(old, str) or not old or not isinstance(new, str):
            raise ValueError("Exact old/new text is required")
        p = self._path(relative)
        original = self._read_text(p)
        if original.count(old) != 1:
            raise ValueError("Old text must occur exactly once")
        changed = original.replace(old, new, 1)
        if len(changed.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError("File would be too large")
        p.write_text(changed, encoding="utf-8")
        return {"edited": relative}

    def _delete(self, relative: str):
        p = self._path(relative)
        if not p.is_file() or p.is_symlink():
            raise ValueError("Can delete only regular files")
        p.unlink()
        return {"deleted": relative}

    def _commit(self, message: str):
        if not isinstance(message, str) or not (3 <= len(message.strip()) <= 200) or "\n" in message:
            raise ValueError("Invalid commit message")
        return self._git("commit", "-m", message)

    def schemas(self) -> list[dict]:
        return [info.schema() for info in self.registry.values()]

    def execute(self, name: str, args: dict) -> Any:
        if name not in self.registry or not isinstance(args, dict):
            raise ValueError("Unknown tool or invalid arguments")
        required = set(self.registry[name].params["required"])
        allowed = set(self.registry[name].params["properties"])
        if not required <= set(args) or not set(args) <= allowed:
            raise ValueError("Missing or unsupported tool arguments")
        if any(not isinstance(v, str) for v in args.values()):
            raise ValueError("Tool values must be strings")
        return self.registry[name].fn(args)
