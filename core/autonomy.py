"""Autonomy & agency system for NEO.

The agent acts on its own initiative: it self-schedules improvements,
pursues long-term goals, and reviews its own autonomous actions.

CRITICAL SAFETY: All autonomous actions still go through the permission
system. Nothing destructive happens without explicit user approval.
The autonomy system only *proposes* and *schedules* — it never bypasses
safety checks.

Components:
  - GOALS: long-term objectives the agent is working toward
  - ACTIONS: a log of autonomous actions taken (for review)
  - SCHEDULER: which improvement ideas to work on next
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Where autonomy state is stored (inside the package).
AUTONOMY_FILE = Path(__file__).resolve().parent.parent / ".neo" / "autonomy.json"


def _load() -> Dict[str, Any]:
    if not AUTONOMY_FILE.exists():
        return {"goals": [], "actions": [], "next_improvement_id": None}
    try:
        data = json.loads(AUTONOMY_FILE.read_text(encoding="utf-8"))
        data.setdefault("goals", [])
        data.setdefault("actions", [])
        data.setdefault("next_improvement_id", None)
        return data
    except (json.JSONDecodeError, OSError):
        return {"goals": [], "actions": [], "next_improvement_id": None}


def _save(data: Dict[str, Any]) -> None:
    AUTONOMY_FILE.parent.mkdir(parents=True, exist_ok=True)
    AUTONOMY_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ---- Goals -----------------------------------------------------------------

def set_goal(title: str, description: str, priority: str = "medium") -> Dict[str, Any]:
    """Set a long-term goal for the agent to pursue."""
    data = _load()
    goal = {
        "id": len(data["goals"]) + 1,
        "title": title,
        "description": description,
        "priority": priority,
        "status": "active",
        "created_ts": time.time(),
        "progress": 0,
    }
    data["goals"].append(goal)
    _save(data)
    return goal


def list_goals() -> List[Dict[str, Any]]:
    data = _load()
    return data["goals"]


def update_goal_progress(goal_id: int, progress: int) -> Dict[str, Any]:
    """Update a goal's progress percentage (0-100)."""
    data = _load()
    for g in data["goals"]:
        if g["id"] == goal_id:
            g["progress"] = max(0, min(100, progress))
            if progress >= 100:
                g["status"] = "completed"
            _save(data)
            return g
    raise ValueError(f"No goal with id {goal_id}")


# ---- Actions ---------------------------------------------------------------

def log_action(action_type: str, description: str, status: str = "proposed") -> Dict[str, Any]:
    """Log an autonomous action taken by the agent."""
    data = _load()
    action = {
        "id": len(data["actions"]) + 1,
        "type": action_type,
        "description": description,
        "status": status,
        "ts": time.time(),
    }
    data["actions"].append(action)
    _save(data)
    return action


def list_actions(limit: int = 20) -> List[Dict[str, Any]]:
    data = _load()
    return data["actions"][-limit:]


# ---- Scheduler -------------------------------------------------------------

def get_next_improvement() -> Optional[Dict[str, Any]]:
    """Return the next improvement idea the agent should work on.

    Picks the highest-priority proposed idea with a module path. This is
    the agent's self-scheduling mechanism — but applying it still requires
    user approval via the permission system.
    """
    try:
        from neo_code.tools.self_improve import _load_improvements

        ideas = _load_improvements()
        priority_order = {"high": 0, "medium": 1, "low": 2}
        ideas.sort(key=lambda i: priority_order.get(i.get("priority", "medium"), 1))
        return next(
            (i for i in ideas if i.get("status") == "proposed" and i.get("module")),
            None,
        )
    except Exception:  # noqa: BLE001
        return None


def autonomy_summary() -> Dict[str, Any]:
    """Return a summary of the agent's autonomy state."""
    data = _load()
    active_goals = [g for g in data["goals"] if g["status"] == "active"]
    completed_goals = [g for g in data["goals"] if g["status"] == "completed"]
    next_improvement = get_next_improvement()
    return {
        "active_goals": active_goals,
        "completed_goals": len(completed_goals),
        "total_actions": len(data["actions"]),
        "recent_actions": data["actions"][-5:],
        "next_improvement": next_improvement,
        "safety_note": (
            "All autonomous actions require user approval via the permission "
            "system. Nothing destructive happens without confirmation."
        ),
    }
