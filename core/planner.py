"""Engineering loop bookkeeping (spec §12):

  UNDERSTAND -> INSPECT -> PLAN -> EXECUTE -> TEST -> VERIFY -> REPORT

The Agent doesn't force the model through rigid phases turn-by-turn
(that would fight against how tool-calling models naturally work);
instead this module (a) tracks which stage the loop is conceptually
in for logging/UI purposes, and (b) enforces the iteration ceiling
that prevents runaway fix/test loops.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Any


class Stage(str, Enum):
    UNDERSTAND = "understand"
    INSPECT = "inspect"
    PLAN = "plan"
    EXECUTE = "execute"
    TEST = "test"
    VERIFY = "verify"
    REPORT = "report"


TOOL_STAGE_HINTS = {
    "list_directory": Stage.INSPECT,
    "read_file": Stage.INSPECT,
    "search_files": Stage.INSPECT,
    "detect_project_type": Stage.INSPECT,
    "git_status": Stage.INSPECT,
    "git_diff": Stage.INSPECT,
    "git_log": Stage.INSPECT,
    "write_file": Stage.EXECUTE,
    "edit_file": Stage.EXECUTE,
    "delete_file": Stage.EXECUTE,
    "execute_command": Stage.EXECUTE,
    "run_tests": Stage.TEST,
}


@dataclass
class LoopState:
    max_iterations: int
    iteration: int = 0
    stages_seen: List[Stage] = field(default_factory=list)
    consecutive_test_failures: int = 0
    tool_history: List[str] = field(default_factory=list)

    def record_tool(self, tool_name: str) -> Stage:
        self.tool_history.append(tool_name)
        stage = TOOL_STAGE_HINTS.get(tool_name, Stage.EXECUTE)
        self.stages_seen.append(stage)
        return stage

    def record_test_result(self, passed: bool) -> None:
        self.consecutive_test_failures = 0 if passed else self.consecutive_test_failures + 1

    def should_stop(self) -> str | None:
        if self.iteration >= self.max_iterations:
            return f"Reached max_iterations ({self.max_iterations}); stopping to avoid a runaway loop."
        if self.consecutive_test_failures >= 3:
            return "Same tests failed 3 times in a row; stopping to ask the user for guidance."

        last_three = self.tool_history[-3:] if len(self.tool_history) >= 3 else []
        if last_three and all(t == "read_file" for t in last_three):
            return "Stuck in read-only loop (3 consecutive read_file calls); ask user for direction."

        if self.iteration >= 10 and "edit_file" not in self.tool_history and "write_file" not in self.tool_history:
            return "No write/edit attempts after 10 iterations; stopping to ask user."

        return None

    def next_iteration(self) -> None:
        self.iteration += 1