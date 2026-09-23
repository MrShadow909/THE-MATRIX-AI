"""
NEO Connector — programmatic access to the NEO agent.

Provides in-process and subprocess entry points for external systems.
"""

from neo_code.connector.api import run_task, run_task_subprocess

__all__ = ["run_task", "run_task_subprocess"]
