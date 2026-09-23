"""
NEO Connector API

In-process and subprocess entry points for external systems.

Transports:
    1. In-process: run_task()
    2. Subprocess: run_task_subprocess()
    3. Stdin/Stdout: run_from_stdin() (used by neo --task-json)
    4. HTTP (demo): serve_http()

All functions return the same structured report:
    {
        "status": "completed" | "completed_with_errors" | "failed",
        "summary": "...",
        "files_changed": [...],
        "tests": [...],
        "errors": [...]
    }
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any


def run_task(
    task: str,
    workspace: str,
    provider: str | None = None,
    model: str | None = None,
    confirm_callback=None,
) -> dict[str, Any]:
    """In-process entry point. Call this from the same Python process."""
    from pathlib import Path

    from neo_code.config import Config
    from neo_code.core.agent import Agent
    from neo_code.providers import create_provider

    config = Config.load(workspace=workspace)
    if provider:
        config.provider = provider
    if model:
        config.model = model

    prov = create_provider(config)
    unavailable = prov.is_available()
    if unavailable:
        return {
            "status": "failed",
            "summary": f"Provider unavailable: {unavailable}",
            "files_changed": [],
            "tests": [],
            "errors": [unavailable],
        }

    skills_dir = Path(__file__).resolve().parent.parent / "skills"
    agent = Agent(config, prov, str(skills_dir), confirm_callback=confirm_callback)
    return agent.run_task(task)


def run_task_subprocess(
    task: str,
    workspace: str,
    neo_code_executable: str = "neo",
    timeout_s: int = 600,
) -> dict[str, Any]:
    """Out-of-process entry point. Shells out to the NEO CLI."""
    payload = json.dumps({"task": task, "workspace": workspace})
    try:
        proc = subprocess.run(
            [neo_code_executable, "--task-json", "-"],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        return {
            "status": "failed",
            "summary": f"Could not launch NEO subprocess: {exc}",
            "files_changed": [],
            "tests": [],
            "errors": [str(exc)],
        }

    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {
            "status": "failed",
            "summary": "NEO subprocess did not return valid JSON.",
            "files_changed": [],
            "tests": [],
            "errors": [proc.stderr[-2000:] or "no stderr captured"],
        }


def run_from_stdin() -> None:
    """Reads a single JSON task from stdin, runs it, writes JSON report to stdout.
    Used by: neo --task-json -
    """
    raw = sys.stdin.read()
    try:
        request = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "summary": f"Invalid JSON: {exc}",
                    "files_changed": [],
                    "tests": [],
                    "errors": [str(exc)],
                }
            )
        )
        return

    result = run_task(
        task=request["task"],
        workspace=request.get("workspace", "."),
        provider=request.get("provider"),
        model=request.get("model"),
        confirm_callback=lambda *_, **__: bool(request.get("auto_approve", False)),
    )
    print(json.dumps(result))


def serve_http(host: str = "127.0.0.1", port: int = 8765) -> None:
    """
    Minimal local HTTP server (DEMO ONLY — not for production).

    This is a lightweight demonstration of how NEO can be exposed
    over HTTP. For production, you MUST add:
        - Authentication
        - Rate limiting
        - Input validation
        - Concurrency control
        - Timeouts
        - Logging & monitoring
    """
    import json as jsonlib
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = jsonlib.loads(self.rfile.read(length))
                result = run_task(
                    task=body["task"],
                    workspace=body.get("workspace", "."),
                    provider=body.get("provider"),
                    model=body.get("model"),
                    confirm_callback=lambda *_, **__: bool(body.get("auto_approve", False)),
                )
                payload = jsonlib.dumps(result).encode("utf-8")
                self.send_response(200)
            except Exception as exc:
                payload = jsonlib.dumps(
                    {
                        "status": "failed",
                        "summary": str(exc),
                        "files_changed": [],
                        "tests": [],
                        "errors": [str(exc)],
                    }
                ).encode("utf-8")
                self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, fmt, *args):
            pass  # Silence default logging

    print(f"[NEO Connector] HTTP server running at http://{host}:{port}")
    print("  POST /task — JSON task in, JSON result out")
    print("  This is a DEMO server. Not for production use.")
    HTTPServer((host, port), Handler).serve_forever()
