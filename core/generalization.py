"""Generalization system for NEO.

The agent abstracts patterns from past tasks into generalizable knNeoedge
that can be applied to novel problems across domains. This is the
foundation of transfer learning — learning once, applying broadly.

A pattern is:
  - domain: which area it applies to (debugging, web, python, ...)
  - title: short name
  - description: the generalizable insight
  - triggers: keywords that suggest this pattern applies
  - applications: count of times it has been successfully applied

Patterns are stored in a JSON file so they persist and grow over time.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Where patterns are stored (inside the package).
PATTERNS_FILE = Path(__file__).resolve().parent.parent / ".neo" / "patterns.json"


def _load_patterns() -> List[Dict[str, Any]]:
    if not PATTERNS_FILE.exists():
        return []
    try:
        return json.loads(PATTERNS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_patterns(patterns: List[Dict[str, Any]]) -> None:
    PATTERNS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PATTERNS_FILE.write_text(
        json.dumps(patterns, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def store_pattern(
    domain: str,
    title: str,
    description: str,
    triggers: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Store a new generalizable pattern. Returns the stored pattern."""
    patterns = _load_patterns()
    pattern = {
        "id": len(patterns) + 1,
        "domain": domain,
        "title": title,
        "description": description,
        "triggers": triggers or [],
        "applications": 0,
        "ts": time.time(),
    }
    patterns.append(pattern)
    _save_patterns(patterns)
    return pattern


def retrieve_patterns(query: str, max_patterns: int = 5) -> List[Dict[str, Any]]:
    """Retrieve the most relevant patterns for a task query.

    Relevance is scored by keyword/trigger matching against the query.
    Returns patterns sorted by relevance (and application count as a
    tiebreaker — proven patterns rank higher).
    """
    patterns = _load_patterns()
    q = query.lower()
    scored = []
    for p in patterns:
        score = 0
        # Match against title and description
        if p["title"].lower() in q or q in p["title"].lower():
            score += 3
        if p["description"].lower() in q or q in p["description"].lower():
            score += 2
        # Match against triggers
        for t in p.get("triggers", []):
            if t.lower() in q:
                score += 2
        # Proven patterns rank higher
        score += min(p.get("applications", 0), 5) * 0.1
        if score > 0:
            scored.append((score, p))
    scored.sort(key=lambda x: (-x[0], -x[1].get("applications", 0)))
    return [p for _, p in scored[:max_patterns]]


def record_application(pattern_id: int) -> None:
    """Increment the application count for a pattern (it was used)."""
    patterns = _load_patterns()
    for p in patterns:
        if p["id"] == pattern_id:
            p["applications"] = p.get("applications", 0) + 1
            break
    _save_patterns(patterns)


def list_patterns(domain: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all patterns, optionally filtered by domain."""
    patterns = _load_patterns()
    if domain:
        return [p for p in patterns if p["domain"] == domain]
    return patterns


def pattern_summary() -> Dict[str, Any]:
    """Return a summary of the knNeoedge base."""
    patterns = _load_patterns()
    domains = {}
    for p in patterns:
        domains[p["domain"]] = domains.get(p["domain"], 0) + 1
    return {
        "total_patterns": len(patterns),
        "domains": domains,
        "most_applied": sorted(patterns, key=lambda p: -p.get("applications", 0))[:3],
    }
