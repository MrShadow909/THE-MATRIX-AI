"""Self-evaluation system for NEO.

The agent scores its own performance after each task, tracks that
history over time, and sets improvement goals based on weak areas.
This is metacognition — the agent judges itself and uses that judgment
to grow.

Scores are 0-100, computed heuristically from task outcomes:
  - base 100 for a clean completion
  - penalties for errors, high iteration counts, and failed status
  - small bonus for completing with files changed (real work done)

History is stored in a JSON file so the agent can track its own
improvement over time.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Where self-evaluation history is stored (inside the package).
EVALUATION_FILE = Path(__file__).resolve().parent.parent / ".neo" / "evaluation.json"


def score_task(
    status: str,
    errors: list,
    iterations: int,
    files_changed: list,
) -> Dict[str, Any]:
    """Compute a 0-100 performance score for a completed task, plus a
    breakdown of the contributing factors."""
    score = 100.0

    # Status penalty
    if status == "failed":
        score -= 40
    elif status == "completed_with_errors":
        score -= 20

    # Error penalty (up to -30)
    score -= min(len(errors) * 10, 30)

    # Iteration efficiency: fewer iterations = better (up to -20)
    if iterations > 10:
        score -= 20
    elif iterations > 5:
        score -= 10
    elif iterations > 3:
        score -= 5

    # Bonus for real work done
    if files_changed:
        score += 5

    score = max(0, min(100, round(score)))

    return {
        "score": score,
        "status": status,
        "errors": len(errors),
        "iterations": iterations,
        "files_changed": len(files_changed),
    }


def _load_history() -> List[Dict[str, Any]]:
    if not EVALUATION_FILE.exists():
        return []
    try:
        return json.loads(EVALUATION_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_history(history: List[Dict[str, Any]]) -> None:
    EVALUATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    EVALUATION_FILE.write_text(
        json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def record_evaluation(task: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """Record a self-evaluation for a completed task and return it."""
    scored = score_task(
        status=result.get("status", "completed"),
        errors=result.get("errors", []),
        iterations=result.get("iterations", 0),
        files_changed=result.get("files_changed", []),
    )
    entry = {
        "ts": time.time(),
        "task": task[:120],
        **scored,
    }
    history = _load_history()
    history.append(entry)
    _save_history(history)
    return entry


def get_evaluation_summary() -> Dict[str, Any]:
    """Return a summary of the agent's self-evaluation history."""
    history = _load_history()
    if not history:
        return {
            "total_tasks": 0,
            "average_score": None,
            "best_score": None,
            "worst_score": None,
            "trend": "no_data",
            "recent": [],
            "goals": [],
        }

    scores = [h["score"] for h in history]
    avg = round(sum(scores) / len(scores))
    best = max(scores)
    worst = min(scores)

    # Trend: compare recent half vs earlier half
    mid = len(history) // 2
    earlier = scores[:mid] or [avg]
    recent = scores[mid:] or [avg]
    recent_avg = round(sum(recent) / len(recent))
    earlier_avg = round(sum(earlier) / len(earlier))
    if recent_avg > earlier_avg:
        trend = "improving"
    elif recent_avg < earlier_avg:
        trend = "declining"
    else:
        trend = "stable"

    # Goals: identify weak areas from recent tasks
    goals = _derive_goals(history[-10:])

    return {
        "total_tasks": len(history),
        "average_score": avg,
        "best_score": best,
        "worst_score": worst,
        "trend": trend,
        "recent": history[-5:],
        "goals": goals,
    }


def _derive_goals(recent: List[Dict[str, Any]]) -> List[str]:
    """Derive improvement goals from recent weak areas."""
    goals = []
    error_tasks = [h for h in recent if h["errors"] > 0]
    slow_tasks = [h for h in recent if h["iterations"] > 5]
    failed_tasks = [h for h in recent if h["status"] == "failed"]

    if error_tasks:
        goals.append(
            f"Reduce errors: {len(error_tasks)} of last {len(recent)} tasks had errors."
        )
    if slow_tasks:
        goals.append(
            f"Improve efficiency: {len(slow_tasks)} of last {len(recent)} tasks took >5 iterations."
        )
    if failed_tasks:
        goals.append(
            f"Avoid failures: {len(failed_tasks)} of last {len(recent)} tasks failed."
        )
    if not goals:
        goals.append("Maintain current performance and continue learning.")
    return goals
