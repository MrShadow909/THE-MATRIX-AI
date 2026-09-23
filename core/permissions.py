"""Permission system for NEO.

Every tool declares a PermissionLevel. Dangerous operations
(WRITE/EXECUTE/SYSTEM by default) are gated behind an explicit
confirmation callback before they run. Nothing destructive happens
silently.
"""
from __future__ import annotations

from enum import IntEnum
from typing import Callable, Optional


class PermissionLevel(IntEnum):
    READ = 0
    WRITE = 1
    EXECUTE = 2
    SYSTEM = 3

    @classmethod
    def from_str(cls, value: str) -> "PermissionLevel":
        return cls[value.upper()]


ConfirmCallback = Callable[[str, PermissionLevel], bool]


def default_confirm(prompt: str, level: PermissionLevel) -> bool:
    """Fallback CLI confirmation (used if no UI callback is wired up)."""
    answer = input(f"[neo] CONFIRM ({level.name}) {prompt} [y/N]: ").strip().lower()
    return answer in ("y", "yes")


class PermissionManager:
    """Central gate for every tool call that touches the filesystem,
    a shell, or the OS. Auto-approves READ. Everything else consults
    `require_confirmation` config + a confirm callback, with an optional
    "always approve this session" override set via /approve.
    """

    def __init__(
        self,
        require_confirmation: dict,
        confirm_callback: Optional[ConfirmCallback] = None,
    ):
        self._require = {
            PermissionLevel.WRITE: require_confirmation.get("write", True),
            PermissionLevel.EXECUTE: require_confirmation.get("execute", True),
            PermissionLevel.SYSTEM: require_confirmation.get("system", True),
        }
        self._confirm = confirm_callback or default_confirm
        self._session_approved: set[PermissionLevel] = set()
        self.audit_log: list[dict] = []

    def approve_for_session(self, level: PermissionLevel) -> None:
        """Called by the /approve command to skip prompts for a level
        for the rest of the session."""
        self._session_approved.add(level)

    def revoke_session_approval(self, level: PermissionLevel) -> None:
        self._session_approved.discard(level)

    def check(self, action_description: str, level: PermissionLevel) -> bool:
        """Returns True if the action is permitted to proceed."""
        allowed: bool
        if level == PermissionLevel.READ:
            allowed = True
        elif level in self._session_approved:
            allowed = True
        elif not self._require.get(level, True):
            allowed = True
        else:
            allowed = self._confirm(action_description, level)

        self.audit_log.append(
            {"action": action_description, "level": level.name, "allowed": allowed}
        )
        return allowed