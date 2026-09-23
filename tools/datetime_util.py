"""Datetime utility tool for NEO.

Provides the current date/time and timestamp formatting. Useful for
logging, naming files, or any task needing the current time.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from neo_code.core.permissions import PermissionLevel
from neo_code.tools.base import Tool


class DateTimeUtilTool(Tool):
    """READ tool: get the current date/time and format timestamps."""

    name = "datetime_util"
    description = (
        "Get the current date/time and format timestamps. Useful for "
        "logging, naming files, or any task needing the current time."
    )
    permission = PermissionLevel.READ
    parameters = {
        "type": "object",
        "properties": {
            "format": {
                "type": "string",
                "description": "Optional strftime format (default: %Y-%m-%d %H:%M:%S).",
            }
        },
        "required": [],
    }

    def execute(self, args: dict[str, Any]) -> Any:
        fmt = args.get("format", "%Y-%m-%d %H:%M:%S")
        now = datetime.now()
        return {
            "now": now.strftime(fmt),
            "unix_timestamp": int(time.time()),
            "iso": now.isoformat(),
        }


def build_datetime_tools() -> list[Tool]:
    """Instantiate the datetime utility tool."""
    return [DateTimeUtilTool()]
