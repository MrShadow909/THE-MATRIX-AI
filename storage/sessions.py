"""Session/observability log. Every tool call, command, file change,
and model turn is appended here for traceability. Plain JSON-lines
file — no server, no background thread, opened only when written to.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any


class SessionLog:
    """Appends every event of one agent run to a JSON-lines file
    (`<log_dir>/session_<id>.jsonl`) and keeps an in-memory copy for
    quick summarization — no server, no background thread."""

    def __init__(self, log_dir: str, workspace: str):
        self.session_id = uuid.uuid4().hex[:12]
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.log_dir / f"session_{self.session_id}.jsonl"
        self.workspace = workspace
        self._events: list[dict[str, Any]] = []
        self._write({"event": "session_start", "workspace": workspace, "ts": time.time()})

    def _write(self, record: dict[str, Any]) -> None:
        self._events.append(record)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def log(self, event: str, **data: Any) -> None:
        """Append one event (with a timestamp) to the session log."""
        self._write({"event": event, "ts": time.time(), **data})

    def recent(self, n: int = 20) -> list[dict[str, Any]]:
        """Return the last `n` logged events, oldest of the window first."""
        return self._events[-n:]

    def files_changed(self) -> list[str]:
        """Return the sorted, deduplicated set of file paths touched
        by write_file/edit_file/delete_file tool calls this session."""
        changed = []
        for e in self._events:
            if e.get("event") == "tool_result" and e.get("tool") in (
                "write_file",
                "edit_file",
                "delete_file",
            ):
                out = e.get("output") or {}
                if isinstance(out, dict) and "path" in out:
                    changed.append(out["path"])
        return sorted(set(changed))

    def summary(self) -> dict[str, Any]:
        """A compact end-of-session summary: id, workspace, tool-call
        count, error count, and files changed."""
        tool_calls = [e for e in self._events if e.get("event") == "tool_result"]
        errors = [e for e in tool_calls if not e.get("ok", True)]
        return {
            "session_id": self.session_id,
            "workspace": self.workspace,
            "tool_calls": len(tool_calls),
            "errors": len(errors),
            "files_changed": self.files_changed(),
        }
