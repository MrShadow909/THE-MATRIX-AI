"""Generalization tools: let the agent store and retrieve abstract
patterns that apply across domains. This is transfer learning — the
agent learns once and applies broadly.
"""

from __future__ import annotations

from typing import Any

from neo_code.core.permissions import PermissionLevel
from neo_code.tools.base import Tool


class StorePatternTool(Tool):
    """EXECUTE tool: store a new generalizable pattern."""

    name = "store_pattern"
    description = (
        "Store a generalizable pattern learned from a task. A pattern is an "
        "abstract insight that applies across domains (e.g. 'always reproduce "
        "a bug before editing'). Provide a domain, title, description, and "
        "trigger keywords."
    )
    permission = PermissionLevel.EXECUTE
    parameters = {
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "Which area it applies to (debugging, web, python, ...)."},
            "title": {"type": "string", "description": "Short name for the pattern."},
            "description": {"type": "string", "description": "The generalizable insight."},
            "triggers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Keywords that suggest this pattern applies.",
            },
        },
        "required": ["domain", "title", "description"],
    }

    def describe_action(self, args: dict[str, Any]) -> str:
        return f"store_pattern: record pattern '{args.get('title')}' in domain '{args.get('domain')}'"

    def execute(self, args: dict[str, Any]) -> Any:
        from neo_code.core.generalization import store_pattern

        pattern = store_pattern(
            domain=args["domain"],
            title=args["title"],
            description=args["description"],
            triggers=args.get("triggers", []),
        )
        return {
            "pattern_id": pattern["id"],
            "domain": pattern["domain"],
            "title": pattern["title"],
            "note": "Pattern stored. It will be retrieved for future tasks in this domain.",
        }


class GeneralizeTool(Tool):
    """READ tool: retrieve relevant patterns for a task."""

    name = "generalize"
    description = (
        "Retrieve generalizable patterns relevant to a task. Use this to "
        "apply knNeoedge learned from past tasks to a new problem. Returns "
        "patterns sorted by relevance."
    )
    permission = PermissionLevel.READ
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The task or problem to find relevant patterns for."},
            "max_patterns": {"type": "integer", "description": "Max patterns to return (default 5)."},
        },
        "required": ["query"],
    }

    def describe_action(self, args: dict[str, Any]) -> str:
        return f"generalize: retrieve patterns for '{args.get('query', '')[:50]}'"

    def execute(self, args: dict[str, Any]) -> Any:
        from neo_code.core.generalization import retrieve_patterns

        patterns = retrieve_patterns(args["query"], args.get("max_patterns", 5))
        return {
            "query": args["query"],
            "patterns": patterns,
            "count": len(patterns),
        }


class ViewPatternsTool(Tool):
    """READ tool: view the pattern knNeoedge base."""

    name = "view_patterns"
    description = (
        "View the pattern knNeoedge base: total patterns, domains covered, "
        "and the most-applied patterns. Optionally filter by domain."
    )
    permission = PermissionLevel.READ
    parameters = {
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "Optional domain filter."},
        },
        "required": [],
    }

    def describe_action(self, args: dict[str, Any]) -> str:
        return f"view_patterns: view knNeoedge base (domain={args.get('domain', 'all')})"

    def execute(self, args: dict[str, Any]) -> Any:
        from neo_code.core.generalization import list_patterns, pattern_summary

        domain = args.get("domain")
        if domain:
            return {"domain": domain, "patterns": list_patterns(domain)}
        return pattern_summary()


def build_generalization_tools() -> list[Tool]:
    """Instantiate the generalization tools."""
    return [StorePatternTool(), GeneralizeTool(), ViewPatternsTool()]
