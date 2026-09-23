"""Memory layer for NEO.

Three tiers:
  SHORT-TERM  — in-process list, cleared with /clear or on exit.
  LONG-TERM   — persistent, user-level, JSON file at ~/.neo/memory.json.
                Coding preferences, cross-project lessons learned.
  PROJECT     — persistent, per-workspace, JSON file at
                <workspace>/.neo/project_memory.json.
                Architecture notes, conventions, decisions for THIS repo.

Deliberately file-backed (no DB) per spec §6 — lightweight, human
readable, diffable, and trivial to inspect or edit by hand.

If BOSS Neo already has a working long-term memory implementation,
prefer routing through integrations/memory_adapter.py instead of this
module — see REUSE_AUDIT.md.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


class _JSONMemoryStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: List[Dict[str, Any]] = self._load()

    def _load(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

    def _save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    def add(self, category: str, content: str, tags: Optional[List[str]] = None) -> Dict[str, Any]:
        entry = {
            "id": len(self._data) + 1,
            "category": category,
            "content": content,
            "tags": tags or [],
            "ts": time.time(),
        }
        self._data.append(entry)
        self._save()
        return entry

    def all(self) -> List[Dict[str, Any]]:
        return list(self._data)

    def search(self, query: str) -> List[Dict[str, Any]]:
        q = query.lower()
        return [
            e
            for e in self._data
            if q in e["content"].lower() or any(q in t.lower() for t in e.get("tags", []))
        ]

    def clear(self) -> None:
        self._data = []
        self._save()


class MemoryManager:
    def __init__(self, long_term_path: str, workspace_root: str):
        self.long_term = _JSONMemoryStore(long_term_path)
        self.project = _JSONMemoryStore(str(Path(workspace_root) / ".neo" / "project_memory.json"))
        self.short_term: List[Dict[str, Any]] = []

    def remember(self, content: str, scope: str = "project", category: str = "note", tags=None):
        if scope == "long_term":
            return self.long_term.add(category, content, tags)
        if scope == "shared":
            # Cross-project lessons: stored in the user-level long-term
            # store (~/.neo/memory.json), which is shared across all
            # workspaces. Tagged so they can be distinguished from
            # personal preferences.
            tags = list(tags or [])
            if "shared" not in tags:
                tags.append("shared")
            return self.long_term.add(category, content, tags)
        if scope == "project":
            return self.project.add(category, content, tags)
        entry = {"category": category, "content": content, "tags": tags or [], "ts": time.time()}
        self.short_term.append(entry)
        return entry

    def clear_short_term(self) -> None:
        self.short_term = []

    def recall(self, query: str) -> Dict[str, List[Dict[str, Any]]]:
        return {
            "short_term": [
                e for e in self.short_term if query.lower() in e["content"].lower()
            ],
            "project": self.project.search(query),
            "long_term": self.long_term.search(query),
        }

    def recall_shared(self, query: str) -> List[Dict[str, Any]]:
        """Recall cross-project lessons (entries tagged 'shared' in the
        user-level long-term store)."""
        return [
            e
            for e in self.long_term.search(query)
            if "shared" in e.get("tags", [])
        ]

    def context_snapshot(self, max_items: int = 8) -> str:
        """A compact block injected into the system prompt so the model
        has continuity without re-reading everything each turn.

        Includes cross-project (shared) lessons first, then project
        memory, then personal preferences."""
        lines = []
        # Cross-project lessons learned (shared across all workspaces).
        for e in self.long_term.all()[-max_items:]:
            if "shared" in e.get("tags", []):
                lines.append(f"- [lesson] {e['content']}")
        # Project-specific memory.
        for e in self.project.all()[-max_items:]:
            lines.append(f"- [project] {e['content']}")
        # Personal preferences (non-shared long-term entries).
        for e in self.long_term.all()[-max_items:]:
            if "shared" not in e.get("tags", []):
                lines.append(f"- [preference] {e['content']}")
        return "\n".join(lines) if lines else "(no stored memory yet)"

    def status(self) -> Dict[str, int]:
        return {
            "short_term": len(self.short_term),
            "project": len(self.project.all()),
            "long_term": len(self.long_term.all()),
        }
