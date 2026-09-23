"""System admin tools — OS-level capabilities for NEO.

These tools let the agent operate beyond the workspace root, giving it
admin-like powers to inspect and organize the user's system. All
operations are gated behind the SYSTEM permission level, so the user
must explicitly approve each one.

NOTE: These tools intentionally escape the workspace sandbox. They are
only registered when the user opts in (see build_system_admin_tools).
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

from neo_code.core.permissions import PermissionLevel
from neo_code.tools.base import Tool

# File categories for organizing a folder
CATEGORIES = {
    "Images": {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp", ".ico", ".tiff"},
    "Documents": {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt", ".xls", ".xlsx", ".ppt", ".pptx", ".csv"},
    "Videos": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v"},
    "Audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
    "Code": {".py", ".js", ".ts", ".html", ".css", ".java", ".c", ".cpp", ".h", ".go", ".rs", ".rb", ".php", ".json", ".xml", ".yaml", ".yml", ".sh", ".bat", ".ps1"},
    "Installers": {".exe", ".msi", ".dmg", ".pkg", ".deb", ".rpm", ".appimage"},
    "Other": set(),
}


class SystemInfoTool(Tool):
    """SYSTEM tool: returns OS, CPU, RAM, disk, and user info."""

    name = "system_info"
    description = "Get OS-level system information: OS, CPU, RAM, disk usage, and current user."
    permission = PermissionLevel.SYSTEM
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def describe_action(self, args: dict[str, Any]) -> str:
        return "system_info: read OS/CPU/RAM/disk information"

    def execute(self, args: dict[str, Any]) -> Any:
        info = {
            "os": platform.system(),
            "os_release": platform.release(),
            "os_version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python_version": platform.python_version(),
            "hostname": platform.node(),
            "user": os.environ.get("USERNAME") or os.environ.get("USER") or "unknown",
            "home_dir": str(Path.home()),
        }

        # CPU count
        try:
            info["cpu_count"] = os.cpu_count()
        except Exception:
            info["cpu_count"] = None

        # RAM (Windows via wmic, else /proc/meminfo)
        try:
            if platform.system() == "Windows":
                out = subprocess.run(
                    "wmic OS get TotalVisibleMemorySize,FreePhysicalMemory /Value",
                    shell=True, capture_output=True, text=True, timeout=10,
                ).stdout
                total = free = None
                for line in out.splitlines():
                    if "TotalVisibleMemorySize" in line:
                        total = int(line.split("=")[1].strip()) // 1024  # KB -> MB
                    elif "FreePhysicalMemory" in line:
                        free = int(line.split("=")[1].strip()) // 1024
                info["ram_total_mb"] = total
                info["ram_free_mb"] = free
            else:
                with open("/proc/meminfo") as f:
                    mem = {}
                    for line in f:
                        k, _, v = line.partition(":")
                        mem[k.strip()] = int(v.strip().split()[0])
                info["ram_total_mb"] = mem.get("MemTotal", 0) // 1024
                info["ram_free_mb"] = mem.get("MemAvailable", mem.get("MemFree", 0)) // 1024
        except Exception:
            info["ram_total_mb"] = None
            info["ram_free_mb"] = None

        # Disk usage of home / C:
        try:
            disk_path = "C:\\" if platform.system() == "Windows" else "/"
            usage = shutil.disk_usage(disk_path)
            info["disk_total_gb"] = round(usage.total / (1024 ** 3), 2)
            info["disk_used_gb"] = round(usage.used / (1024 ** 3), 2)
            info["disk_free_gb"] = round(usage.free / (1024 ** 3), 2)
        except Exception:
            pass

        return info


class ListDesktopTool(Tool):
    """SYSTEM tool: lists files in a directory (default: Desktop)."""

    name = "list_desktop"
    description = (
        "List files and folders in a directory (default: the user's Desktop). "
        "Returns name, type (file/dir), and size for each entry."
    )
    permission = PermissionLevel.SYSTEM
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Optional absolute path to list. Defaults to the Desktop.",
            }
        },
        "required": [],
    }

    def describe_action(self, args: dict[str, Any]) -> str:
        return f"list_desktop: list files in '{args.get('path', 'Desktop')}'"

    def execute(self, args: dict[str, Any]) -> Any:
        target = args.get("path") or str(Path.home() / "Desktop")
        path = Path(target)
        if not path.exists():
            raise FileNotFoundError(f"Path does not exist: {target}")
        if not path.is_dir():
            raise ValueError(f"Not a directory: {target}")

        entries = []
        try:
            for item in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                try:
                    size = item.stat().st_size if item.is_file() else None
                except OSError:
                    size = None
                entries.append({
                    "name": item.name,
                    "type": "dir" if item.is_dir() else "file",
                    "size_bytes": size,
                    "size_human": _human_size(size) if size is not None else None,
                })
        except PermissionError:
            raise PermissionError(f"Access denied reading: {target}")

        return {
            "path": str(path),
            "entry_count": len(entries),
            "entries": entries,
        }


class OrganizeFolderTool(Tool):
    """SYSTEM tool: sorts files in a folder into category subfolders."""

    name = "organize_folder"
    description = (
        "Organize files in a folder by moving them into category subfolders "
        "(Images, Documents, Videos, Audio, Archives, Code, Installers, Other). "
        "Folders are left alone. Returns a summary of what was moved."
    )
    permission = PermissionLevel.SYSTEM
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path of the folder to organize. Defaults to Desktop.",
            },
            "dry_run": {
                "type": "boolean",
                "description": "If true, only report what WOULD be moved without moving anything.",
            },
        },
        "required": [],
    }

    def describe_action(self, args: dict[str, Any]) -> str:
        mode = " (dry run)" if args.get("dry_run") else ""
        return f"organize_folder: sort files in '{args.get('path', 'Desktop')}'{mode}"

    def execute(self, args: dict[str, Any]) -> Any:
        target = args.get("path") or str(Path.home() / "Desktop")
        dry_run = bool(args.get("dry_run", False))
        path = Path(target)
        if not path.exists():
            raise FileNotFoundError(f"Path does not exist: {target}")
        if not path.is_dir():
            raise ValueError(f"Not a directory: {target}")

        moved = []
        skipped = []
        for item in path.iterdir():
            if item.is_dir():
                continue  # don't touch folders
            category = _categorize(item.suffix)
            dest_dir = path / category
            if category == "Other":
                # Only move Other files if there are enough to bother
                continue
            try:
                if not dry_run:
                    dest_dir.mkdir(exist_ok=True)
                    dest = dest_dir / item.name
                    # Avoid overwriting
                    if dest.exists():
                        dest = dest_dir / (item.stem + "_dup" + item.suffix)
                    shutil.move(str(item), str(dest))
                moved.append({"file": item.name, "category": category})
            except Exception as e:
                skipped.append({"file": item.name, "error": str(e)})

        return {
            "path": str(path),
            "dry_run": dry_run,
            "moved_count": len(moved),
            "moved": moved,
            "skipped_count": len(skipped),
            "skipped": skipped,
        }


class SearchSystemTool(Tool):
    """SYSTEM tool: searches for files by name pattern across a path."""

    name = "search_system"
    description = (
        "Search for files by name pattern (supports * wildcards) starting from "
        "a directory. Returns matching file paths."
    )
    permission = PermissionLevel.SYSTEM
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Filename pattern, e.g. '*.pdf' or 'report*'."},
            "path": {
                "type": "string",
                "description": "Directory to search from. Defaults to the user's home directory.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default 50).",
            },
        },
        "required": ["pattern"],
    }

    def describe_action(self, args: dict[str, Any]) -> str:
        return f"search_system: find '{args.get('pattern')}' under '{args.get('path', 'home')}'"

    def execute(self, args: dict[str, Any]) -> Any:
        pattern = args["pattern"]
        start = args.get("path") or str(Path.home())
        max_results = min(int(args.get("max_results", 50)), 200)
        root = Path(start)
        if not root.exists():
            raise FileNotFoundError(f"Path does not exist: {start}")

        import fnmatch

        results = []
        # Walk the tree, skipping common heavy/system dirs
        skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv",
                     "System Volume Information", "$RECYCLE.BIN", "Windows",
                     "Program Files", "Program Files (x86)", "AppData"}
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d not in skip_dirs]
                for fname in filenames:
                    if fnmatch.fnmatch(fname.lower(), pattern.lower()):
                        results.append(str(Path(dirpath) / fname))
                        if len(results) >= max_results:
                            return {
                                "pattern": pattern,
                                "search_path": str(root),
                                "result_count": len(results),
                                "truncated": True,
                                "results": results,
                            }
        except PermissionError:
            pass  # skip dirs we can't read

        return {
            "pattern": pattern,
            "search_path": str(root),
            "result_count": len(results),
            "truncated": False,
            "results": results,
        }


# ---- Helpers ----
def _categorize(ext: str) -> str:
    ext = ext.lower()
    for category, exts in CATEGORIES.items():
        if ext in exts:
            return category
    return "Other"


def _human_size(num: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024:
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} PB"


def build_system_admin_tools() -> list[Tool]:
    """Build and return the system admin tool set."""
    return [
        SystemInfoTool(),
        ListDesktopTool(),
        OrganizeFolderTool(),
        SearchSystemTool(),
    ]
