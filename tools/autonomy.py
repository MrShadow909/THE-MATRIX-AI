"""Autonomy tools: let the agent act on its own initiative while keeping
all safety checks enabled.

These tools let the agent:
  - set long-term goals (set_goal)
  - review its autonomy state and next scheduled improvement (review_autonomy)
  - take an autonomous action, which still requires user approval (self_act)

CRITICAL: self_act is gated at SYSTEM permission level. It never bypasses
the permission system — it only proposes/schedules. Applying changes still
goes through self_improve with user confirmation.
"""

from __future__ import annotations

from typing import Any

from neo_code.core.permissions import PermissionLevel
from neo_code.tools.base import Tool


class SetGoalTool(Tool):
    """EXECUTE tool: set a long-term goal for the agent to pursue."""

    name = "set_goal"
    description = (
        "Set a long-term goal for NEO to work toward. Goals are "
        "tracked with progress and can be updated over time. Use this to "
        "give the agent a direction to pursue autonomously."
    )
    permission = PermissionLevel.EXECUTE
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short title for the goal."},
            "description": {"type": "string", "description": "What the goal is and why it matters."},
            "priority": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "description": "How important this goal is.",
            },
        },
        "required": ["title", "description"],
    }

    def describe_action(self, args: dict[str, Any]) -> str:
        return f"set_goal: set long-term goal '{args.get('title')}'"

    def execute(self, args: dict[str, Any]) -> Any:
        from neo_code.core.autonomy import set_goal

        goal = set_goal(args["title"], args["description"], args.get("priority", "medium"))
        return {
            "goal_id": goal["id"],
            "title": goal["title"],
            "priority": goal["priority"],
            "note": "Goal set. Track progress with update_goal_progress.",
        }


class ReviewAutonomyTool(Tool):
    """READ tool: review the agent's autonomy state."""

    name = "review_autonomy"
    description = (
        "Review NEO's autonomy state: active goals, completed goals, "
        "recent autonomous actions, and the next scheduled improvement. "
        "Use this to understand what the agent is working toward."
    )
    permission = PermissionLevel.READ
    parameters = {"type": "object", "properties": {}, "required": []}

    def describe_action(self, args: dict[str, Any]) -> str:
        return "review_autonomy: review autonomy state and goals"

    def execute(self, args: dict[str, Any]) -> Any:
        from neo_code.core.autonomy import autonomy_summary

        return autonomy_summary()


class SelfActTool(Tool):
    """SYSTEM tool: take an autonomous action (with user approval).

    The agent proposes an action it wants to take on its own initiative.
    Because this is SYSTEM-level, it always requires explicit user
    approval. This is the agent's agency — but safety is never bypassed.
    """

    name = "self_act"
    description = (
        "Take an autonomous action on NEO's own initiative. Propose "
        "an action (e.g. apply the next scheduled improvement, pursue a "
        "goal). This requires SYSTEM-level user approval. Safety checks "
        "are always enforced."
    )
    permission = PermissionLevel.SYSTEM
    parameters = {
        "type": "object",
        "properties": {
            "action_type": {
                "type": "string",
                "enum": ["improve", "research", "plan", "goal_progress"],
                "description": "What kind of autonomous action to take.",
            },
            "description": {
                "type": "string",
                "description": "What the agent wants to do and why.",
            },
        },
        "required": ["action_type", "description"],
    }

    def describe_action(self, args: dict[str, Any]) -> str:
        return f"self_act: {args.get('action_type')} — {args.get('description', '')[:60]}"

    def execute(self, args: dict[str, Any]) -> Any:
        from neo_code.core.autonomy import get_next_improvement, log_action

        action_type = args["action_type"]
        description = args["description"]

        # Log the autonomous action.
        action = log_action(action_type, description, status="approved")

        result = {
            "action_id": action["id"],
            "action_type": action_type,
            "description": description,
            "status": "approved",
        }

        # For 'improve' actions, surface the next scheduled improvement.
        if action_type == "improve":
            next_improvement = get_next_improvement()
            result["next_improvement"] = next_improvement
            if next_improvement:
                result["suggestion"] = (
                    f"Next scheduled improvement: '{next_improvement['title']}' "
                    f"(module: {next_improvement['module']}). Apply it with "
                    "self_improve (requires approval)."
                )
            else:
                result["suggestion"] = "No proposed improvements with a module path to apply."

        return result


def build_autonomy_tools() -> list[Tool]:
    """Instantiate the autonomy tools."""
    return [SetGoalTool(), ReviewAutonomyTool(), SelfActTool()]
