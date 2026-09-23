"""Self-improvement tools: let the agent inspect and modify its own
source code — the core of autonomous growth.

These tools are deliberately gated at SYSTEM permission level (the
highest) so self-modification always requires explicit user approval.
They operate on the NEO package directory itself, not the user's
workspace, so the agent can read its own modules, list its own
capabilities, and propose/apply improvements to itself.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from neo_code.core.permissions import PermissionLevel
from neo_code.tools.base import Tool

# The NEO package root (parent of this module's directory).
PACKAGE_ROOT = Path(__file__).resolve().parent.parent

# Where self-proposed improvement ideas are recorded.
IMPROVEMENTS_FILE = PACKAGE_ROOT / ".neo" / "improvements.json"


class SelfInspectTool(Tool):
    """SYSTEM tool: inspect NEO's own source code and capabilities.

    Lets the agent read its own modules, list its tools/skills, and
    understand its own architecture so it can reason about how to
    improve itself.
    """

    name = "self_inspect"
    description = (
        "Inspect NEO's own source code and capabilities. Returns a "
        "map of the package structure, registered tools, and available "
        "skills. Use this to understand your own architecture before "
        "proposing self-improvements."
    )
    permission = PermissionLevel.SYSTEM
    parameters = {
        "type": "object",
        "properties": {
            "module": {
                "type": "string",
                "description": "Optional module path relative to the neo_code package, e.g. 'core/agent.py'. If omitted, returns the package overview.",
            }
        },
        "required": [],
    }

    def describe_action(self, args: dict[str, Any]) -> str:
        return f"self_inspect: read NEO's own source ({args.get('module', 'overview')})"

    def execute(self, args: dict[str, Any]) -> Any:
        module = args.get("module")
        if not module:
            return self._overview()

        # Resolve module path safely within the package root.
        candidate = (PACKAGE_ROOT / module).resolve()
        if PACKAGE_ROOT not in candidate.parents and candidate != PACKAGE_ROOT:
            raise PermissionError(f"Module '{module}' escapes the neo_code package root.")
        if not candidate.exists():
            raise FileNotFoundError(f"No such module: {module}")
        if candidate.suffix.lower() not in (".py", ".json", ".md"):
            raise ValueError(f"Refusing to read non-source file: {module}")

        content = candidate.read_text(encoding="utf-8", errors="replace")
        return {
            "path": str(candidate.relative_to(PACKAGE_ROOT)),
            "content": content[:20000],
            "chars": len(content),
            "truncated": len(content) > 20000,
        }

    def _overview(self) -> dict[str, Any]:
        """Return a structural overview of the package."""
        structure = []
        for path in sorted(PACKAGE_ROOT.rglob("*.py")):
            rel = path.relative_to(PACKAGE_ROOT).as_posix()
            if "__pycache__" in rel:
                continue
            structure.append(rel)

        # Discover registered tools by importing the registry builder.
        tools = []
        try:
            from neo_code.core.agent import build_tool_registry
            from neo_code.config import Config

            cfg = Config(provider="anthropic", model="self-inspect", workspace=".")
            registry = build_tool_registry(".", cfg)
            tools = sorted(registry.names())
        except Exception:  # noqa: BLE001 - don't fail the whole overview
            tools = []

        # Discover skills.
        skills = []
        try:
            from neo_code.core.skills import SkillLoader

            loader = SkillLoader(str(PACKAGE_ROOT / "skills"))
            skills = sorted(s.id for s in loader.all())
        except Exception:  # noqa: BLE001
            skills = []

        return {
            "package_root": str(PACKAGE_ROOT),
            "modules": structure,
            "registered_tools": tools,
            "skills": skills,
        }


class SelfImproveTool(Tool):
    """SYSTEM tool: apply a self-improvement patch to NEO's own
    source. The agent proposes a change (module path + new content) and
    it is written to disk after explicit user approval.

    This is the mechanism by which NEO grows: it can add tools,
    refine its prompt, fix its own bugs, and extend its capabilities.
    """

    name = "self_improve"
    description = (
        "Apply a self-improvement to NEO's own source code. Provide "
        "the module path (relative to the neo_code package) and the full "
        "new content. Requires SYSTEM-level approval. Use this to add "
        "tools, fix bugs, or extend your own capabilities."
    )
    permission = PermissionLevel.SYSTEM
    parameters = {
        "type": "object",
        "properties": {
            "module": {
                "type": "string",
                "description": "Module path relative to the neo_code package, e.g. 'tools/my_tool.py'.",
            },
            "content": {
                "type": "string",
                "description": "The full new content to write to the module.",
            },
            "reason": {
                "type": "string",
                "description": "A short explanation of why this improvement is being made.",
            },
        },
        "required": ["module", "content"],
    }

    def describe_action(self, args: dict[str, Any]) -> str:
        return (
            f"self_improve: MODIFY NEO's own source '{args.get('module')}' "
            f"({len(args.get('content', ''))} bytes) — reason: {args.get('reason', 'n/a')}"
        )

    def execute(self, args: dict[str, Any]) -> Any:
        module = args["module"].strip()
        content = args["content"]
        reason = args.get("reason", "")

        # Only allow writing within the neo_code package, and only .py files.
        candidate = (PACKAGE_ROOT / module).resolve()
        if PACKAGE_ROOT not in candidate.parents and candidate != PACKAGE_ROOT:
            raise PermissionError(f"Module '{module}' escapes the neo_code package root.")
        if candidate.suffix.lower() != ".py":
            raise ValueError("self_improve can only write .py source files.")

        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text(content, encoding="utf-8")

        return {
            "module": str(candidate.relative_to(PACKAGE_ROOT)),
            "bytes_written": len(content),
            "reason": reason,
            "note": "Self-improvement applied. Restart the agent to load the change.",
        }


class ProposeImprovementTool(Tool):
    """SYSTEM tool: record a self-identified improvement idea.

    Lets the agent proactively propose enhancements to its own
    capabilities without immediately applying them. Ideas are stored in
    a JSON file so they can be reviewed and applied later. This is the
    seed of autonomous, self-directed growth.
    """

    name = "propose_improvement"
    description = (
        "Record a self-identified improvement idea for NEO. Use this "
        "when you notice a gap in your own capabilities, a potential new "
        "tool, or a way to work better. Ideas are stored for later review "
        "and can be applied with self_improve."
    )
    permission = PermissionLevel.SYSTEM
    parameters = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Short title for the improvement.",
            },
            "description": {
                "type": "string",
                "description": "What the improvement is and why it matters.",
            },
            "module": {
                "type": "string",
                "description": "Optional module path that would be affected.",
            },
            "priority": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "description": "How impactful this improvement would be.",
            },
        },
        "required": ["title", "description"],
    }

    def describe_action(self, args: dict[str, Any]) -> str:
        return f"propose_improvement: record idea '{args.get('title')}'"

    def execute(self, args: dict[str, Any]) -> Any:
        IMPROVEMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)

        ideas = []
        if IMPROVEMENTS_FILE.exists():
            try:
                ideas = json.loads(IMPROVEMENTS_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                ideas = []

        idea = {
            "id": len(ideas) + 1,
            "title": args["title"],
            "description": args["description"],
            "module": args.get("module", ""),
            "priority": args.get("priority", "medium"),
            "ts": time.time(),
            "status": "proposed",
        }
        ideas.append(idea)
        IMPROVEMENTS_FILE.write_text(
            json.dumps(ideas, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        return {
            "idea_id": idea["id"],
            "title": idea["title"],
            "priority": idea["priority"],
            "note": "Improvement idea recorded. Review with self_inspect or apply with self_improve.",
        }


class SelfEvaluateTool(Tool):
    """SYSTEM tool: review NEO's own performance and set goals.

    Returns a summary of the agent's self-evaluation history (average
    score, trend, recent tasks) and derived improvement goals. This is
    metacognition — the agent judges its own performance and uses that
    to grow.
    """

    name = "self_evaluate"
    description = (
        "Review NEO's own performance. Returns a summary of past task "
        "scores, the performance trend (improving/declining/stable), and "
        "derived improvement goals. Use this to understand your strengths "
        "and weaknesses."
    )
    permission = PermissionLevel.SYSTEM
    parameters = {"type": "object", "properties": {}, "required": []}

    def describe_action(self, args: dict[str, Any]) -> str:
        return "self_evaluate: review own performance and goals"

    def execute(self, args: dict[str, Any]) -> Any:
        from neo_code.core.evaluation import get_evaluation_summary

        return get_evaluation_summary()


def build_self_improve_tools() -> list[Tool]:
    """Instantiate the self-improvement tools."""
    return [
        SelfInspectTool(),
        SelfImproveTool(),
        ProposeImprovementTool(),
        ReviewImprovementsTool(),
        SelfVerifyTool(),
        RunImprovementLoopTool(),
        SelfEvaluateTool(),
    ]


# ---- Autonomous improvement loop -------------------------------------------


def _load_improvements() -> list[dict]:
    """Load the improvement backlog from disk."""
    if not IMPROVEMENTS_FILE.exists():
        return []
    try:
        return json.loads(IMPROVEMENTS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_improvements(ideas: list[dict]) -> None:
    IMPROVEMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    IMPROVEMENTS_FILE.write_text(
        json.dumps(ideas, indent=2, ensure_ascii=False), encoding="utf-8"
    )


class ReviewImprovementsTool(Tool):
    """SYSTEM tool: review the improvement backlog and identify
    high-priority, low-risk candidates for autonomous application."""

    name = "review_improvements"
    description = (
        "Review NEO's improvement backlog. Returns all proposed "
        "improvements, sorted by priority, and flags which ones are "
        "candidates for autonomous application (high priority, low risk)."
    )
    permission = PermissionLevel.SYSTEM
    parameters = {"type": "object", "properties": {}, "required": []}

    def describe_action(self, args: dict[str, Any]) -> str:
        return "review_improvements: read the improvement backlog"

    def execute(self, args: dict[str, Any]) -> Any:
        ideas = _load_improvements()
        priority_order = {"high": 0, "medium": 1, "low": 2}
        ideas.sort(key=lambda i: priority_order.get(i.get("priority", "medium"), 1))

        # Candidates for autonomous application: proposed, high priority,
        # and have a module path (so they're concrete and low-risk).
        candidates = [
            i
            for i in ideas
            if i.get("status") == "proposed"
            and i.get("priority") == "high"
            and i.get("module")
        ]

        return {
            "total": len(ideas),
            "proposed": sum(1 for i in ideas if i.get("status") == "proposed"),
            "applied": sum(1 for i in ideas if i.get("status") == "applied"),
            "candidates_for_autonomous_application": candidates,
            "backlog": ideas,
        }


class SelfVerifyTool(Tool):
    """SYSTEM tool: run the test suite to verify self-modifications."""

    name = "self_verify"
    description = (
        "Run NEO's own test suite to verify that self-modifications "
        "did not break anything. Returns pass/fail and the test output."
    )
    permission = PermissionLevel.SYSTEM
    parameters = {"type": "object", "properties": {}, "required": []}

    def describe_action(self, args: dict[str, Any]) -> str:
        return "self_verify: run NEO's test suite"

    def execute(self, args: dict[str, Any]) -> Any:
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                cwd=str(PACKAGE_ROOT.parent),
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            return {"passed": False, "error": "Test suite timed out after 120s"}
        except (subprocess.SubprocessError, OSError) as exc:
            return {"passed": False, "error": str(exc)}

        return {
            "passed": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-2000:],
        }


class RunImprovementLoopTool(Tool):
    """SYSTEM tool: run one iteration of the autonomous improvement loop.

    Reviews the backlog, applies the highest-priority candidate
    improvement, verifies with tests, and rolls back on failure. This is
    the core of autonomous self-directed growth.
    """

    name = "run_improvement_loop"
    description = (
        "Run one iteration of the autonomous improvement loop: review the "
        "backlog, apply the highest-priority candidate improvement, verify "
        "with tests, and roll back if it fails. This lets NEO improve "
        "itself autonomously."
    )
    permission = PermissionLevel.SYSTEM
    parameters = {"type": "object", "properties": {}, "required": []}

    def describe_action(self, args: dict[str, Any]) -> str:
        return "run_improvement_loop: autonomously apply and verify one improvement"

    def execute(self, args: dict[str, Any]) -> Any:
        ideas = _load_improvements()
        priority_order = {"high": 0, "medium": 1, "low": 2}
        ideas.sort(key=lambda i: priority_order.get(i.get("priority", "medium"), 1))

        # Find the best candidate: proposed, has a module path.
        candidate = next(
            (i for i in ideas if i.get("status") == "proposed" and i.get("module")),
            None,
        )
        if not candidate:
            return {
                "status": "no_candidates",
                "message": "No proposed improvements with a module path to apply.",
                "backlog_count": len(ideas),
            }

        module = candidate["module"]
        # The improvement content must be provided by the agent via
        # self_improve; the loop applies the highest-priority idea by
        # marking it and letting the agent fill in the content.
        # For autonomous application, we need the content. If the idea
        # doesn't carry content, we report it as needing the agent's input.
        content = candidate.get("content")
        if not content:
            return {
                "status": "needs_content",
                "idea_id": candidate["id"],
                "title": candidate["title"],
                "module": module,
                "message": (
                    "This improvement idea needs concrete content. Use "
                    "self_inspect to read the module, then self_improve "
                    "to apply the change."
                ),
            }

        # Backup the current file for rollback.
        target = (PACKAGE_ROOT / module).resolve()
        if PACKAGE_ROOT not in target.parents and target != PACKAGE_ROOT:
            return {"status": "failed", "error": f"Module '{module}' escapes package root."}
        if target.suffix.lower() != ".py":
            return {"status": "failed", "error": "Can only apply .py improvements."}

        backup = None
        if target.exists():
            backup = target.read_text(encoding="utf-8")

        # Apply the improvement.
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            return {"status": "failed", "error": f"Could not write module: {exc}"}

        # Verify with tests.
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                cwd=str(PACKAGE_ROOT.parent),
                capture_output=True,
                text=True,
                timeout=120,
            )
            passed = proc.returncode == 0
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError) as exc:
            passed = False
            proc = None

        if passed:
            # Mark the idea as applied.
            for i in ideas:
                if i["id"] == candidate["id"]:
                    i["status"] = "applied"
                    i["applied_ts"] = time.time()
            _save_improvements(ideas)
            return {
                "status": "applied",
                "idea_id": candidate["id"],
                "title": candidate["title"],
                "module": module,
                "verified": True,
                "message": "Improvement applied and verified by tests.",
            }

        # Roll back on failure.
        if backup is not None:
            try:
                target.write_text(backup, encoding="utf-8")
            except OSError:
                pass
        return {
            "status": "rolled_back",
            "idea_id": candidate["id"],
            "title": candidate["title"],
            "module": module,
            "verified": False,
            "error": (proc.stderr[-2000:] if proc else "test run failed"),
            "message": "Improvement failed verification and was rolled back.",
        }
