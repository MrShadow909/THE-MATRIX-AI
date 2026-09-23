"""Planning tools: let the agent create and track structured plans with
sub-goals. This is the foundation of autonomous, goal-directed work —
breaking a complex task into manageable steps and executing them in order.
"""

from __future__ import annotations

from typing import Any

from neo_code.core.permissions import PermissionLevel
from neo_code.tools.base import Tool


class CreatePlanTool(Tool):
    """EXECUTE tool: create a structured plan with sub-goals for a task."""

    name = "create_plan"
    description = (
        "Create a structured plan for a complex task by breaking it into "
        "sub-goals. Each sub-goal has a title, description, and optional "
        "dependencies. Returns the plan with a plan_id for tracking."
    )
    permission = PermissionLevel.EXECUTE
    parameters = {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "The overall task being planned."},
            "sub_goals": {
                "type": "array",
                "description": "List of sub-goals, each with title, description, and optional depends_on.",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "depends_on": {"type": "array", "items": {"type": "integer"}},
                    },
                },
            },
        },
        "required": ["task", "sub_goals"],
    }

    def describe_action(self, args: dict[str, Any]) -> str:
        return f"create_plan: plan '{args.get('task', '')[:50]}' with {len(args.get('sub_goals', []))} sub-goals"

    def execute(self, args: dict[str, Any]) -> Any:
        from neo_code.core.planning import create_plan

        task = args["task"]
        sub_goals = args["sub_goals"]
        if not sub_goals:
            raise ValueError("sub_goals must not be empty.")
        plan = create_plan(task, sub_goals)
        return {
            "plan_id": plan["id"],
            "task": plan["task"],
            "sub_goals": plan["sub_goals"],
            "note": "Plan created. Track progress with track_plan.",
        }


class TrackPlanTool(Tool):
    """EXECUTE tool: update progress on a plan's sub-goals."""

    name = "track_plan"
    description = (
        "Update the status of a sub-goal in a plan (pending, in_progress, "
        "done, blocked). Returns the updated plan summary with progress."
    )
    permission = PermissionLevel.EXECUTE
    parameters = {
        "type": "object",
        "properties": {
            "plan_id": {"type": "integer", "description": "The plan to update."},
            "goal_id": {"type": "integer", "description": "The sub-goal to update."},
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "done", "blocked"],
                "description": "New status for the sub-goal.",
            },
        },
        "required": ["plan_id", "goal_id", "status"],
    }

    def describe_action(self, args: dict[str, Any]) -> str:
        return f"track_plan: set goal {args.get('goal_id')} of plan {args.get('plan_id')} to {args.get('status')}"

    def execute(self, args: dict[str, Any]) -> Any:
        from neo_code.core.planning import plan_summary, update_goal

        updated = update_goal(args["plan_id"], args["goal_id"], args["status"])
        return plan_summary(updated["id"])


class ViewPlanTool(Tool):
    """READ tool: view a plan's summary and progress."""

    name = "view_plan"
    description = (
        "View a plan's summary: progress percentage, current goal, next "
        "actionable sub-goal, and all sub-goal statuses."
    )
    permission = PermissionLevel.READ
    parameters = {
        "type": "object",
        "properties": {
            "plan_id": {"type": "integer", "description": "The plan to view."},
        },
        "required": ["plan_id"],
    }

    def describe_action(self, args: dict[str, Any]) -> str:
        return f"view_plan: view plan {args.get('plan_id')}"

    def execute(self, args: dict[str, Any]) -> Any:
        from neo_code.core.planning import plan_summary

        return plan_summary(args["plan_id"])


def build_planning_tools() -> list[Tool]:
    """Instantiate the planning tools."""
    return [CreatePlanTool(), TrackPlanTool(), ViewPlanTool()]
