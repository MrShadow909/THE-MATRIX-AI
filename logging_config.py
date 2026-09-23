"""Central logging configuration for NEO.

NEO is primarily a terminal application whose user-facing output
goes through :mod:`neo_code.ui.terminal` (Rich-formatted panels,
prompts, and reports) — that is intentional UI, not debug output, and
is untouched here.

This module provides a single ``logging.Logger`` (``"neo_code"``) for
internal diagnostics: provider HTTP errors, unexpected exceptions,
and anything a maintainer would want in a log file rather than mixed
into the interactive session. It is silent by default (only ``WARNING``
and above go to stderr) so normal CLI usage stays clean; verbosity is
controlled via the ``NEO_LOG_LEVEL`` environment variable.

Usage:
    from neo_code.logging_config import get_logger
    logger = get_logger(__name__)
    logger.debug("provider payload: %s", payload)
"""

from __future__ import annotations

import logging
import os

_CONFIGURED = False
_ROOT_NAME = "neo_code"


def _configure_once() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    level_name = os.environ.get("NEO_LOG_LEVEL", "WARNING").upper()
    level = getattr(logging, level_name, logging.WARNING)

    root = logging.getLogger(_ROOT_NAME)
    root.setLevel(level)

    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("[%(name)s] %(levelname)s: %(message)s"))
        root.addHandler(handler)
        root.propagate = False

    _CONFIGURED = True


def get_logger(name: str = _ROOT_NAME) -> logging.Logger:
    """Return a logger namespaced under ``neo_code``.

    Safe to call at import time from any module; configuration only
    happens once, on first use, per the "no side effects at import
    time" rule that also applies to :mod:`neo_code.config`.
    """
    _configure_once()
    if name == _ROOT_NAME or name.startswith(f"{_ROOT_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_ROOT_NAME}.{name}")