"""Planning & sub-goals system for NEO.

Lets the agent break a complex task into a structured plan of sub-goals,
track progress through each one, and re-plan when blocked. This is the
foundation of autonomous, goal-directed work.

A plan is a list of sub-goals, each with:
  - id: unique within the plan
  - title: short description
  - description: what needs to be done
  - status: pending | in_progress | done | blocked
  - depends_on: ids of sub-goals that must be done first

Plans are stored in a JSON file so they persist across the session.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Where plans are stored (inside the package).
PLANS_FILE = Path(__file__).resolve().parent.parent / ".neo" / "plans.json"


def _load_plans() -> List[Dict[str, Any]]:
    if not PLANS_FILE.exists():
        return []
    try:
        return json.loads(PLANS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_plans(plans: List[Dict[str, Any]]) -> None:
    PLANS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PLANS_FILE.write_text(
        json.dumps(plans, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def create_plan(task: str, sub_goals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Create a new plan for a task with the given sub-goals.

    Each sub-goal: {"title": str, "description": str, "depends_on": [ids]}
    """
    plans = _load_plans()
    plan_id = len(plans) + 1

    goals = []
    for i, g in enumerate(sub_goals, start=1):
        goals.append(
            {
                "id": i,
                "title": g.get("title", f"Sub-goal {i}"),
                "description": g.get("description", ""),
                "status": "pending",
                "depends_on": g.get("depends_on", []),
            }
        )

    plan = {
        "id": plan_id,
        "task": task,
        "created_ts": time.time(),
        "sub_goals": goals,
        "current_goal": 1,
        "status": "active",
    }
    plans.append(plan)
    _save_plans(plans)
    return plan


def get_plan(plan_id: int) -> Optional[Dict[str, Any]]:
    plans = _load_plans()
    for p in plans:
        if p["id"] == plan_id:
            return p
    return None


def update_goal(plan_id: int, goal_id: int, status: str) -> Dict[str, Any]:
    """Update a sub-goal's status and return the updated plan.

    status: pending | in_progress | done | blocked
    """
    plans = _load_plans()
    for p in plans:
        if p["id"] != plan_id:
            continue
        for g in p["sub_goals"]:
            if g["id"] == goal_id:
                g["status"] = status
                break
        # Advance current_goal to the next pending goal.
        pending = [g for g in p["sub_goals"] if g["status"] == "pending"]
        if pending:
            p["current_goal"] = pending[0]["id"]
        else:
            p["current_goal"] = None
        # Mark plan complete if all goals done.
        if all(g["status"] == "done" for g in p["sub_goals"]):
            p["status"] = "completed"
        _save_plans(plans)
        return p
    raise ValueError(f"No plan with id {plan_id}")


def get_next_goal(plan_id: int) -> Optional[Dict[str, Any]]:
    """Return the next actionable sub-goal (all dependencies done)."""
    plan = get_plan(plan_id)
    if not plan:
        return None
    for g in plan["sub_goals"]:
        if g["status"] != "pending":
            continue
        deps = g.get("depends_on", [])
        if all(
            any(dg["id"] == d and dg["status"] == "done" for dg in plan["sub_goals"])
            for d in deps
        ):
            return g
    return None


def list_plans() -> List[Dict[str, Any]]:
    return _load_plans()


def plan_summary(plan_id: int) -> Dict[str, Any]:
    """Return a compact summary of a plan's progress."""
    plan = get_plan(plan_id)
    if not plan:
        return {"error": f"No plan with id {plan_id}"}
    goals = plan["sub_goals"]
    done = sum(1 for g in goals if g["status"] == "done")
    return {
        "plan_id": plan_id,
        "task": plan["task"],
        "status": plan["status"],
        "total_goals": len(goals),
        "done_goals": done,
        "progress_pct": round(done / len(goals) * 100) if goals else 0,
        "current_goal": plan["current_goal"],
        "next_actionable": get_next_goal(plan_id),
        "sub_goals": goals,
    }
