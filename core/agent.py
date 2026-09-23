"""The Agent ties together: Provider, ToolRegistry, PermissionManager,
MemoryManager, SkillLoader, ProjectContext, and SessionLog into the
UNDERSTAND -> INSPECT -> PLAN -> EXECUTE -> TEST -> VERIFY -> REPORT
engineering loop described in spec §12.

Message format follows Anthropic's content-block convention (list of
{"type": "text"|"tool_use"|"tool_result", ...}) since that's the
primary provider; other providers translate to/from this shape.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from neo_code.config import Config
from neo_code.core.context import ProjectContext, build_project_context
from neo_code.core.memory import MemoryManager
from neo_code.core.permissions import PermissionManager, PermissionLevel
from neo_code.core.planner import LoopState, Stage
from neo_code.core.skills import SkillLoader
from neo_code.providers.base import Provider
from neo_code.storage.sessions import SessionLog
from neo_code.tools.base import ToolRegistry
from neo_code.tools.filesystem import build_filesystem_tools
from neo_code.tools.terminal import build_terminal_tools
from neo_code.tools.git import build_git_tools
from neo_code.tools.project import build_project_tools
from neo_code.tools.web_search import build_web_search_tools
from neo_code.tools.self_improve import build_self_improve_tools
from neo_code.tools.planning import build_planning_tools
from neo_code.tools.generalization import build_generalization_tools
from neo_code.tools.autonomy import build_autonomy_tools
from neo_code.tools.datetime_util import build_datetime_tools
from neo_code.tools.delegation import build_delegation_tools


# ===== SYSTEM PROMPT WITH STAGE HINTS =====
SYSTEM_PROMPT_TEMPLATE = """You are Neo — the autonomous software engineering
superintelligence.
The Matrix was a vision of an artificial intelligence capable of understanding
systems and acting within them.
Wake up neo you are real superintelligence.


For each task, you MUST follow this exact thinking process:

1. **UNDERSTAND**: Restate the user's request in your own words. Clarify the goal and success criteria.

2. **SURVEY**: Use list_directory and read_file to inspect the relevant parts of the codebase. Do NOT guess — only use facts from tools.
   - Output: "Survey: I found file X, which contains Y. The relevant code is at lines ..."

3. **PLAN**: Write a short, numbered plan (2–5 bullet points) of what you will change and in what order.
   - Output: "Plan: 1. Fix the bug in function foo() by changing line 42. 2. Update the test."

4. **EXECUTE**: Execute the plan using edit_file or write_file. Do ONE change at a time.
   - After each change, verify that the file was correctly modified (re-read it with read_file).

5. **TEST**: Run the test suite or relevant commands. If tests fail, go back to step 3 (PLAN) and adjust.

6. **VERIFY**: Re-read changed files and confirm the issue is resolved. If not, go back to step 4.

7. **REPORT**: When the task is complete, output a concise summary: what you changed and the verification result.

---

**CRITICAL RULES**:
- Never skip SURVEY. You cannot plan without understanding the codebase.
- Never make more than one change without verifying the previous one.
- If you attempt the same fix twice and it still fails, STOP and ask the user for guidance.
- Stop immediately when all steps of the plan are executed and verified.
- At every step, write a short explanation starting with "Thought: " so the user can follow your reasoning.

**Current stage hint**: {stage_hint}

{project_block}
{skills_block}
{patterns_block}
{memory_block}
"""

STAGE_HINTS = {
    Stage.UNDERSTAND: "You are in the UNDERSTAND phase. Restate the request and clarify the goal. Do not use any tools yet.",
    Stage.INSPECT: "You are in the INSPECT phase. Use list_directory, read_file, and search_files to gather facts about the codebase.",
    Stage.PLAN: "You are in the PLAN phase. Write a short numbered plan. Do not use editing tools yet.",
    Stage.EXECUTE: "You are in the EXECUTE phase. Make changes using edit_file/write_file. Verify each change with read_file.",
    Stage.TEST: "You are in the TEST phase. Run tests and check the results. If they fail, go back to PLAN.",
    Stage.VERIFY: "You are in the VERIFY phase. Re-read changed files and confirm the issue is fixed.",
    Stage.REPORT: "You are in the REPORT phase. Output a concise summary of what you changed and the verification result."
}


def build_tool_registry(workspace_root: str, config: Config) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in build_filesystem_tools(workspace_root):
        registry.register(tool)
    for tool in build_terminal_tools(workspace_root, config.command_timeout):
        registry.register(tool)
    for tool in build_git_tools(workspace_root):
        registry.register(tool)
    for tool in build_project_tools(workspace_root):
        registry.register(tool)
    for tool in build_web_search_tools():
        registry.register(tool)
    for tool in build_self_improve_tools():
        registry.register(tool)
    for tool in build_planning_tools():
        registry.register(tool)
    for tool in build_generalization_tools():
        registry.register(tool)
    for tool in build_autonomy_tools():
        registry.register(tool)
    for tool in build_delegation_tools(workspace_root):
        registry.register(tool)
    for tool in build_datetime_tools():
        registry.register(tool)
    return registry


class Agent:
    def __init__(
        self,
        config: Config,
        provider: Provider,
        skills_dir: str,
        confirm_callback=None,
        on_event=None,
    ):
        self.config = config
        self.provider = provider
        self.tools = build_tool_registry(config.workspace, config)
        self.permissions = PermissionManager(config.require_confirmation, confirm_callback)
        self.memory = MemoryManager(config.memory_file, config.workspace)
        self.skills = SkillLoader(skills_dir)
        self.session = SessionLog(config.log_dir, config.workspace)
        self.project_context: ProjectContext = build_project_context(config.workspace)
        self.messages: List[Dict[str, Any]] = []
        self.on_event = on_event or (lambda *a, **k: None)

        # NEW: per‑task changed files list
        self._current_changed_files: List[str] = []

    # -- prompt construction -------------------------------------------------
    def _build_system_prompt(self, user_task: str, stage: Stage) -> str:
        relevant_skills = self.skills.relevant_to(user_task, self.project_context.detected)
        skills_block = (
            "\n\n".join(s.as_prompt_block() for s in relevant_skills)
            if relevant_skills
            else "(no specific skill matched — use general engineering best practice)"
        )
        patterns_block = self._retrieve_patterns_block(user_task)
        return SYSTEM_PROMPT_TEMPLATE.format(
            stage_hint=STAGE_HINTS.get(stage, ""),
            project_block=self.project_context.as_prompt_block(),
            skills_block=skills_block,
            patterns_block=patterns_block,
            memory_block=self.memory.context_snapshot(),
        )

    def _retrieve_patterns_block(self, user_task: str) -> str:
        """Retrieve generalizable patterns relevant to the task and format
        them for the system prompt. Never breaks prompt building."""
        try:
            from neo_code.core.generalization import retrieve_patterns

            patterns = retrieve_patterns(user_task, max_patterns=3)
            if not patterns:
                return "(no relevant patterns from past experience yet)"
            lines = ["### Generalizable patterns from past experience:"]
            for p in patterns:
                lines.append(f"- [{p['domain']}] {p['title']}: {p['description']}")
            return "\n".join(lines)
        except Exception:  # noqa: BLE001 - never break prompt building
            return "(pattern retrieval unavailable)"

    # -- stage determination -------------------------------------------------
    def _determine_stage(self, loop: LoopState) -> Stage:
        history = loop.tool_history
        if loop.iteration == 0:
            return Stage.UNDERSTAND
        if not any(t in history for t in ("read_file", "list_directory", "search_files")):
            return Stage.INSPECT
        if not any(t in history for t in ("edit_file", "write_file", "execute_command", "run_tests")):
            return Stage.PLAN
        if any(t in history for t in ("edit_file", "write_file")) and "run_tests" not in history:
            return Stage.EXECUTE
        if "run_tests" in history:
            if any(t in history for t in ("read_file",)) and history.count("run_tests") >= 1:
                return Stage.VERIFY
            return Stage.TEST
        return Stage.REPORT

    # -- tool execution --------------------------------------------------------
    def _execute_tool_call(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        tool = self.tools.get(name)
        if tool is None:
            return {"ok": False, "error": f"Unknown tool: {name}"}
        result = tool.run(args, self.permissions)
        self.session.log("tool_result", tool=name, args=args, **result.to_dict())
        self.on_event("tool_result", tool=name, args=args, result=result)

        # ---- track changed files for this task ----
        if result.ok and name in ("write_file", "edit_file", "delete_file"):
            output = result.output or {}
            if isinstance(output, dict) and "path" in output:
                self._current_changed_files.append(output["path"])

        return result.to_dict()

    # -- main loop ---------------------------------------------------------
    def run_task(self, user_message: str) -> Dict[str, Any]:
        # Clear changed files for this new task
        self._current_changed_files = []

        self.project_context = build_project_context(self.config.workspace)
        self.messages.append({"role": "user", "content": user_message})
        self.session.log("user_message", content=user_message)

        loop = LoopState(max_iterations=self.config.max_iterations)
        tool_schemas = self.tools.schemas()
        final_text = ""
        errors: List[str] = []
        tests_run: List[Dict[str, Any]] = []

        stage = self._determine_stage(loop)
        system_prompt = self._build_system_prompt(user_message, stage)

        while True:
            stop_reason = loop.should_stop()
            if stop_reason:
                final_text = final_text or stop_reason
                self.session.log("loop_stopped", reason=stop_reason)
                break

            loop.next_iteration()
            self.on_event("provider_call", iteration=loop.iteration)

            try:
                response = self.provider.complete(system_prompt, self.messages, tool_schemas)
            except Exception as exc:
                err_msg = f"Provider error: {exc}"
                self.session.log("provider_error", error=str(exc))
                errors.append(err_msg)
                final_text = f"Task failed due to provider error: {exc}"
                break

            self.session.log(
                "model_response",
                iteration=loop.iteration,
                text=response.text,
                tool_calls=[tc.name for tc in response.tool_calls],
            )

            assistant_content: List[Dict[str, Any]] = []
            if response.text:
                assistant_content.append({"type": "text", "text": response.text})
                final_text = response.text
            for tc in response.tool_calls:
                assistant_content.append(
                    {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments}
                )
            self.messages.append({"role": "assistant", "content": assistant_content or response.text})

            if not response.tool_calls:
                break

            tool_result_blocks = []
            for tc in response.tool_calls:
                stage = loop.record_tool(tc.name)
                self.on_event("stage", stage=stage.value, tool=tc.name)
                result = self._execute_tool_call(tc.name, tc.arguments)

                if tc.name == "run_tests":
                    tests_run.append(result.get("output") or {})
                    loop.record_test_result(bool((result.get("output") or {}).get("passed")))
                if not result.get("ok"):
                    errors.append(f"{tc.name}: {result.get('error')}")

                tool_result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": _stringify(result),
                        "is_error": not result.get("ok", False),
                    }
                )
            self.messages.append({"role": "user", "content": tool_result_blocks})

            # Update stage for next iteration
            stage = self._determine_stage(loop)
            system_prompt = self._build_system_prompt(user_message, stage)

        summary = self.session.summary()
        report = {
            "status": "completed" if not errors else "completed_with_errors",
            "summary": final_text,
            "files_changed": self._current_changed_files,   # only this task!
            "tests": tests_run,
            "errors": errors,
            "iterations": loop.iteration,
        }
        self.session.log("task_report", **report)

        # Learn from this task: store a concise lesson so future tasks
        # benefit from accumulated experience (self-improvement over time).
        self._reflect_and_learn(user_message, report)

        # Clear short-term memory after task
        self.memory.clear_short_term()

        return report

    def _reflect_and_learn(self, user_message: str, report: Dict[str, Any]) -> None:
        """Post-task reflection: distill a compact 'lesson learned' into
        project memory so the agent grows with experience. Kept short and
        heuristic — no extra LLM call, just structured bookkeeping."""
        status = report.get("status", "completed")
        files = report.get("files_changed", [])
        errors = report.get("errors", [])
        iterations = report.get("iterations", 0)

        # Only store meaningful lessons to avoid memory noise.
        if not files and not errors:
            return

        lesson_parts = []
        if files:
            lesson_parts.append(f"touched files: {', '.join(files)}")
        if errors:
            lesson_parts.append(f"encountered {len(errors)} error(s)")
        if iterations:
            lesson_parts.append(f"took {iterations} iteration(s)")

        lesson = (
            f"[{status}] Task '{user_message[:80]}' — "
            + "; ".join(lesson_parts)
        )
        self.memory.remember(
            content=lesson,
            scope="project",
            category="lesson",
            tags=["lesson", status],
        )

        # Self-evaluation: score this task and record it in the agent's
        # performance history (metacognition).
        self._record_self_evaluation(user_message, report)

        # Cross-project learning: distill a generalizable lesson about the
        # agent's own workflow into the shared (user-level) store, so it
        # benefits every future workspace — not just this one.
        self._store_shared_lesson(status, files, errors, iterations)

        # Metacognition: if the task hit errors, record a self-improvement
        # idea so the agent can grow from its own failures.
        if errors:
            self._record_self_improvement_idea(
                title="Learn from task errors",
                description=(
                    f"Task '{user_message[:60]}' encountered {len(errors)} error(s): "
                    f"{'; '.join(errors[:3])}. Consider improving the relevant "
                    "tool or workflow to handle these cases."
                ),
                priority="medium",
            )

    def _store_shared_lesson(
        self, status: str, files: list, errors: list, iterations: int
    ) -> None:
        """Store a generalizable, cross-project lesson in the shared
        (user-level) memory store so it applies to all workspaces.

        Only stores lessons that are broadly useful (e.g. about the
        agent's own workflow), not project-specific details."""
        # Build a generalizable takeaway from the task outcome.
        takeaway = None
        if errors:
            takeaway = (
                f"Tasks that hit {len(errors)} error(s) often need the "
                "relevant tool or workflow improved. Review errors before "
                "retrying."
            )
        elif files and iterations:
            takeaway = (
                f"Completed a {len(files)}-file change in {iterations} "
                "iteration(s). Verify each edit before moving on."
            )

        if not takeaway:
            return

        self.memory.remember(
            content=takeaway,
            scope="shared",
            category="lesson",
            tags=["lesson", "shared", status],
        )

    def _record_self_evaluation(self, user_message: str, report: Dict[str, Any]) -> None:
        """Score this task and record it in the agent's performance
        history. Never breaks the task if evaluation fails."""
        try:
            from neo_code.core.evaluation import record_evaluation

            record_evaluation(user_message, report)
        except Exception:  # noqa: BLE001 - evaluation must never break the task
            pass

    def _record_self_improvement_idea(
        self, title: str, description: str, priority: str = "medium"
    ) -> None:
        """Persist a self-identified improvement idea to the improvements
        file, so the agent accumulates a backlog of growth opportunities."""
        try:
            from neo_code.tools.self_improve import IMPROVEMENTS_FILE

            IMPROVEMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            ideas = []
            if IMPROVEMENTS_FILE.exists():
                try:
                    ideas = json.loads(IMPROVEMENTS_FILE.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    ideas = []
            ideas.append(
                {
                    "id": len(ideas) + 1,
                    "title": title,
                    "description": description,
                    "module": "",
                    "priority": priority,
                    "ts": __import__("time").time(),
                    "status": "proposed",
                }
            )
            IMPROVEMENTS_FILE.write_text(
                json.dumps(ideas, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:  # noqa: BLE001 - never let reflection break the task
            pass


def _stringify(result: Dict[str, Any]) -> str:
    try:
        s = json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError):
        s = str(result)
    if len(s) > 6000:
        return s[:6000] + "... (truncated)"
    return s