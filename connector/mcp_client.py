"""
NEO MCP Client

Connects to one or more MCP servers and exposes their tools to NEO.
Supports stdio-based MCP servers (Claude Desktop, Cursor, custom).

Config:
    ~/.neo/mcp.json           (user-level)
    <workspace>/.mcp.json     (project-level)

Example config:
    {
      "mcpServers": {
        "neo": {
          "command": "python",
          "args": ["-m", "neo_code.connector.mcp_server"],
          "env": {"PYTHONPATH": "C:\\\\Users\\\\HP\\\\Desktop\\\\ENTER THE MATRIX"}
        }
      }
    }

Usage:
    from neo_code.connector.mcp_client import MCPClient

    client = MCPClient()
    await client.connect_all()
    tools = client.list_tools()
    result = await client.call_tool("neo__neo_status", {})
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    MCP_OK = True
except ImportError:
    MCP_OK = False

# Remote transports (SSE, Streamable HTTP) - optional
try:
    from mcp.client.sse import sse_client
    SSE_OK = True
except ImportError:
    SSE_OK = False

try:
    from mcp.client.streamable_http import streamablehttp_client
    HTTP_OK = True
except ImportError:
    HTTP_OK = False


# ============ Config ============

# Use USERPROFILE on Windows (Path.home() can return OneDrive path)
import os as _os
_HOME = Path(_os.environ.get("USERPROFILE", _os.path.expanduser("~")))
USER_CONFIG = _HOME / ".neo" / "mcp.json"
WORKSPACE_CONFIG_NAME = ".mcp.json"


# ============ MCP Client ============

class MCPClient:
    """Connects to multiple MCP servers and aggregates their tools."""

    def __init__(self, workspace: Optional[str] = None):
        if not MCP_OK:
            raise RuntimeError("mcp not installed. Run: pip install mcp")

        self.workspace = Path(workspace or os.getcwd())
        self.config: Dict[str, Any] = {}
        self.tools: Dict[str, Dict] = {}
        self._sessions: Dict[str, Any] = {}
        self._exit_stack: Optional[AsyncExitStack] = None
        self._connected = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        self._load_config()

    # -- config -----------------------------------------------------------

    def _load_config(self):
        """Load config: user-level first, then workspace overrides."""
        merged: Dict[str, Any] = {"mcpServers": {}}

        # User-level
        if USER_CONFIG.exists():
            data = self._read_json(USER_CONFIG)
            merged["mcpServers"].update(data.get("mcpServers", {}))

        # Workspace-level
        ws_config = self.workspace / WORKSPACE_CONFIG_NAME
        if ws_config.exists():
            data = self._read_json(ws_config)
            merged["mcpServers"].update(data.get("mcpServers", {}))

        self.config = merged

    @staticmethod
    def _read_json(path: Path) -> Dict[str, Any]:
        """Read JSON file, handling UTF-8 BOM and other encodings."""
        try:
            # Try utf-8-sig first (strips BOM if present)
            with open(path, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            try:
                # Fallback: read bytes and strip BOM
                raw = path.read_bytes()
                if raw.startswith(b"\xef\xbb\xbf"):
                    raw = raw[3:]
                return json.loads(raw.decode("utf-8"))
            except Exception:
                return {}

    def add_server(
        self,
        name: str,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        save_to: str = "user",
    ) -> str:
        """Add an MCP server to the config."""
        server = {
            "command": command,
            "args": args or [],
            "env": env or {},
        }

        if save_to == "user":
            path = USER_CONFIG
        else:
            path = self.workspace / WORKSPACE_CONFIG_NAME

        path.parent.mkdir(parents=True, exist_ok=True)

        existing: Dict[str, Any] = {"mcpServers": {}}
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                pass

        existing.setdefault("mcpServers", {})[name] = server

        with open(path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)

        self.config.setdefault("mcpServers", {})[name] = server
        return f"Added MCP server '{name}' to {path}"

    def remove_server(self, name: str, save_to: str = "user") -> str:
        """Remove an MCP server from config."""
        if save_to == "user":
            path = USER_CONFIG
        else:
            path = self.workspace / WORKSPACE_CONFIG_NAME

        if not path.exists():
            return f"No config found at {path}"

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return f"Error reading config: {e}"

        if name in data.get("mcpServers", {}):
            del data["mcpServers"][name]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            self.config.get("mcpServers", {}).pop(name, None)
            return f"Removed MCP server '{name}'"
        return f"Server '{name}' not found"

    def list_servers(self) -> str:
        """List configured MCP servers."""
        servers = self.config.get("mcpServers", {})
        if not servers:
            return "No MCP servers configured."
        lines = ["Configured MCP servers:"]
        for name, cfg in servers.items():
            cmd = cfg.get("command", "?")
            args = " ".join(cfg.get("args", []))
            connected = " [CONNECTED]" if name in self._sessions else ""
            lines.append(f"  {name:<20} {cmd} {args}{connected}")
        return "\n".join(lines)

    # -- connect / disconnect ---------------------------------------------

    async def connect_all(self) -> str:
        """Connect to all configured MCP servers (stdio + SSE + Streamable HTTP)."""
        if self._connected and self._sessions:
            return f"Already connected ({len(self._sessions)} servers, {len(self.tools)} tools)"

        if self._exit_stack is not None:
            try:
                await self._exit_stack.aclose()
            except Exception:
                pass

        self._exit_stack = AsyncExitStack()
        results = []

        for name, cfg in self.config.get("mcpServers", {}).items():
            try:
                url = cfg.get("url")
                transport = cfg.get("transport", "").lower()
                headers = cfg.get("headers", {})

                # ---- Remote transports (SSE / Streamable HTTP) ----
                if url:
                    if transport == "sse" or (not transport and SSE_OK):
                        if not SSE_OK:
                            results.append(f"[!] '{name}': SSE not available")
                            continue
                        read, write = await self._exit_stack.enter_async_context(
                            sse_client(url, headers=headers)
                        )
                        label = "sse"
                    elif transport in ("streamable_http", "http") or (not transport and HTTP_OK):
                        if not HTTP_OK:
                            results.append(f"[!] '{name}': Streamable HTTP not available")
                            continue
                        read, write, _ = await self._exit_stack.enter_async_context(
                            streamablehttp_client(url, headers=headers)
                        )
                        label = "http"
                    else:
                        results.append(f"[!] '{name}': no remote transport available")
                        continue

                # ---- Local stdio ----
                else:
                    params = StdioServerParameters(
                        command=cfg["command"],
                        args=cfg.get("args", []),
                        env=cfg.get("env", {}),
                    )
                    read, write = await self._exit_stack.enter_async_context(
                        stdio_client(params)
                    )
                    label = "stdio"

                # ---- Session + tools ----
                session = await self._exit_stack.enter_async_context(
                    ClientSession(read, write)
                )
                await session.initialize()

                self._sessions[name] = session

                tools_result = await session.list_tools()
                for tool in tools_result.tools:
                    schema = (
                        getattr(tool, "input_schema", None)
                        or getattr(tool, "inputSchema", None)
                        or {}
                    )
                    tool_key = f"{name}__{tool.name}"
                    self.tools[tool_key] = {
                        "server": name,
                        "name": tool.name,
                        "description": tool.description or "",
                        "input_schema": schema,
                    }

                results.append(
                    f"[+] Connected '{name}' ({label}): {len(tools_result.tools)} tools"
                )
            except Exception as e:
                results.append(f"[!] Failed '{name}': {type(e).__name__}: {e}")

        self._connected = len(self._sessions) > 0
        if not results:
            results.append("No MCP servers configured.")
        return "\n".join(results)
    async def disconnect_all(self):
        """Disconnect from all MCP servers."""
        if self._exit_stack:
            try:
                await self._exit_stack.aclose()
            except Exception:
                pass
            self._exit_stack = None
        self._sessions.clear()
        self.tools.clear()
        self._connected = False

    # -- tools ------------------------------------------------------------

    def list_tools(self) -> str:
        """List all discovered MCP tools."""
        if not self.tools:
            return "No MCP tools available. Run connect_all() first."
        lines = [f"Available MCP tools ({len(self.tools)}):"]
        by_server: Dict[str, List] = {}
        for key, info in self.tools.items():
            by_server.setdefault(info["server"], []).append(info)
        for server, tools in by_server.items():
            lines.append(f"\n  [{server}] ({len(tools)} tools)")
            for t in tools:
                desc = (t["description"] or "")[:70]
                lines.append(f"    {t['name']:<30} {desc}")
        return "\n".join(lines)

    def get_schema(self, tool_key: str) -> str:
        """Get the JSON schema for a tool."""
        if tool_key not in self.tools:
            matches = [k for k in self.tools if k.endswith(f"__{tool_key}")]
            if matches:
                tool_key = matches[0]
            else:
                return f"Tool '{tool_key}' not found"
        return json.dumps(self.tools[tool_key].get("input_schema", {}), indent=2)

    @staticmethod
    def _default_for_type(ptype, prop=None):
        if isinstance(ptype, list):
            ptype = ptype[0]
        default = {
            "string": "",
            "integer": 0,
            "number": 0.0,
            "boolean": False,
            "array": [],
            "object": {},
        }.get(ptype, None)
        if prop and "minimum" in prop and isinstance(default, (int, float)):
            default = prop["minimum"]
        return default

    def _validate_arguments(self, tool_key: str, arguments: Dict) -> tuple:
        if tool_key not in self.tools:
            return False, arguments, f"Tool '{tool_key}' not found"
        schema = self.tools[tool_key].get("input_schema", {})
        if not schema:
            return True, arguments, ""
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        fixed = dict(arguments or {})
        for field in required:
            if field not in fixed:
                prop = properties.get(field, {})
                ptype = prop.get("type", "string")
                fixed[field] = self._default_for_type(ptype, prop)
        return True, fixed, ""

    async def call_tool(
        self,
        tool_key: str,
        arguments: Dict,
        _retry_depth: int = 0,
    ) -> str:
        """Call an MCP tool by key (server__toolname)."""
        if tool_key not in self.tools:
            matches = [k for k in self.tools if k.endswith(f"__{tool_key}")]
            if matches:
                tool_key = matches[0]
            else:
                return f"[!] Tool '{tool_key}' not found"

        info = self.tools[tool_key]
        session = self._sessions.get(info["server"])
        if not session:
            return f"[!] Server '{info['server']}' not connected"

        is_valid, fixed_args, err = self._validate_arguments(tool_key, arguments or {})
        if not is_valid:
            return f"[!] Validation failed: {err}"

        try:
            result = await session.call_tool(info["name"], fixed_args)
            if hasattr(result, "content"):
                parts = []
                for c in result.content:
                    if hasattr(c, "text"):
                        parts.append(c.text)
                    else:
                        parts.append(str(c))
                return "\n".join(parts)
            return str(result)
        except Exception as e:
            err_str = str(e)
            if _retry_depth < 3 and ("-32602" in err_str or "validation" in err_str.lower()):
                fields = re.findall(r"at\s+(\w+)", err_str)
                fields += re.findall(r"Invalid input at\s+(\w+)", err_str)
                fields = list(set(fields))
                if fields:
                    for field in fields:
                        prop = info["input_schema"].get("properties", {}).get(field, {})
                        ptype = prop.get("type", "string")
                        fixed_args[field] = self._default_for_type(ptype, prop)
                    return await self.call_tool(tool_key, fixed_args, _retry_depth + 1)
            return f"[!] Tool call failed: {type(e).__name__}: {e}"

    # -- sync wrappers (for use from non-async code) ----------------------
    #
    # IMPORTANT: MCP sessions are bound to the event loop they were created in.
    # We use ONE persistent loop for the whole MCPClient lifetime.

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        """Get or create the persistent event loop for this client."""
        if getattr(self, "_loop", None) is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        return self._loop

    def connect_all_sync(self) -> str:
        loop = self._get_loop()
        return loop.run_until_complete(self.connect_all())

    def call_tool_sync(self, tool_key: str, arguments: Dict) -> str:
        loop = self._get_loop()
        return loop.run_until_complete(self.call_tool(tool_key, arguments))

    def disconnect_all_sync(self):
        loop = self._get_loop()
        try:
            return loop.run_until_complete(self.disconnect_all())
        finally:
            if not loop.is_closed():
                loop.close()
            self._loop = None



# ============ NEO Tools (for agent integration) ============

from neo_code.core.permissions import PermissionLevel
from neo_code.tools.base import Tool


# Shared client instance (lazy  connects on first use)
_mcp_client: Optional[MCPClient] = None


def _get_client() -> MCPClient:
    """Lazy-init shared MCPClient and auto-connect."""
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = MCPClient()
        try:
            _mcp_client.connect_all_sync()
        except Exception:
            pass
    return _mcp_client


class MCPListServersTool(Tool):
    name = "mcp_list_servers"
    description = "List configured MCP servers (from ~/.neo/mcp.json and workspace .mcp.json)."
    permission = PermissionLevel.READ
    parameters = {"type": "object", "properties": {}, "required": []}

    def execute(self, args):
        client = _get_client()
        return {"servers": client.list_servers()}


class MCPListToolsTool(Tool):
    name = "mcp_list_tools"
    description = "List all tools discovered from connected MCP servers. Format: server__toolname."
    permission = PermissionLevel.READ
    parameters = {"type": "object", "properties": {}, "required": []}

    def execute(self, args):
        client = _get_client()
        return {"tools": client.list_tools()}


class MCPConnectTool(Tool):
    name = "mcp_connect"
    description = "Connect to all configured MCP servers and discover their tools."
    permission = PermissionLevel.EXECUTE
    parameters = {"type": "object", "properties": {}, "required": []}

    def execute(self, args):
        client = _get_client()
        return {"result": client.connect_all_sync()}


class MCPCallToolTool(Tool):
    name = "mcp_call_tool"
    description = "Call a tool on a connected MCP server. Use tool_key in format 'server__toolname' (e.g. 'neo__neo_status')."
    permission = PermissionLevel.EXECUTE
    parameters = {
        "type": "object",
        "properties": {
            "tool_key": {"type": "string", "description": "Tool key: server__toolname (e.g. 'neo__neo_status')"},
            "arguments": {"type": "object", "description": "Tool arguments (JSON object)"},
        },
        "required": ["tool_key"],
    }

    def execute(self, args):
        client = _get_client()
        result = client.call_tool_sync(
            args["tool_key"],
            args.get("arguments", {}),
        )
        if result.startswith("[!]"):
            raise RuntimeError(result)
        return {"result": result}


def build_mcp_tools() -> list[Tool]:
    """Instantiate all MCP client tools (shared client)."""
    return [
        MCPListServersTool(),
        MCPListToolsTool(),
        MCPConnectTool(),
        MCPCallToolTool(),
    ]


# ============ NEO Orchestrator (Sequential, MCP-safe) ============

class NEOOrchestrateTool(Tool):
    """
    Orchestrate multiple Neo workers safely.

    MCP sessions do NOT support asyncio.gather() (deadlock).
    This implementation uses:
      - Sequential execution (one task at a time)
      - Per-task timeout (no hangs)
      - Optional ThreadPoolExecutor for true isolation

    Modes:
      - 'sequential' (safe, recommended)
      - 'chain' (output of one feeds next)
      - 'parallel' (threads, 2-3 tasks max — experimental)
    """
    name = "neo_orchestrate"
    description = (
        "Run multiple tasks across Neo workers. Modes: 'sequential' (safe), "
        "'chain' (output feeds next), 'parallel' (2-3 tasks max, experimental). "
        "Default: sequential."
    )
    permission = PermissionLevel.EXECUTE
    parameters = {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of tasks to run.",
            },
            "workspace": {
                "type": "string",
                "description": "Project root path (all workers use this).",
            },
            "mode": {
                "type": "string",
                "enum": ["sequential", "chain", "parallel"],
                "description": "Execution mode (default: sequential).",
                "default": "sequential",
            },
            "provider": {
                "type": "string",
                "description": "LLM provider (ollama, anthropic, openai, deepseek).",
            },
            "model": {
                "type": "string",
                "description": "Model name.",
            },
            "auto_approve": {
                "type": "boolean",
                "description": "Auto-approve tool calls in workers (be careful!).",
                "default": True,
            },
            "max_iterations": {
                "type": "integer",
                "description": "Max iterations per worker (default 3).",
                "default": 3,
            },
            "timeout_s": {
                "type": "integer",
                "description": "Per-task timeout in seconds (default 120).",
                "default": 120,
            },
        },
        "required": ["tasks"],
    }

    def execute(self, args):
        tasks = args["tasks"]
        mode = args.get("mode", "sequential")
        workspace = args.get("workspace") or str(Path.cwd())
        provider = args.get("provider")
        model = args.get("model")
        auto_approve = args.get("auto_approve", True)
        max_iter = args.get("max_iterations", 3)
        timeout_s = args.get("timeout_s", 120)

        if not tasks:
            return {"error": "No tasks provided."}

        n = len(tasks)
        import time
        start = time.time()

        if mode == "sequential":
            results = self._run_sequential(
                tasks, workspace, provider, model, auto_approve, max_iter, timeout_s
            )
        elif mode == "chain":
            results = self._run_chain(
                tasks, workspace, provider, model, auto_approve, max_iter, timeout_s
            )
        elif mode == "parallel":
            results = self._run_parallel_threads(
                tasks, workspace, provider, model, auto_approve, max_iter, timeout_s
            )
        else:
            return {"error": f"Unknown mode: {mode}"}

        elapsed = time.time() - start
        succeeded = sum(1 for r in results if r.get("ok"))
        failed = n - succeeded

        summary_lines = [
            f"Orchestration complete: {succeeded}/{n} succeeded in {elapsed:.1f}s",
            f"Mode: {mode}",
            f"Workers spawned: {n}",
            "",
        ]
        for i, r in enumerate(results, 1):
            status = "OK" if r.get("ok") else "FAIL"
            summary_lines.append(f"[{i}] {status} — {r.get('task', '')[:80]}")

        return {
            "summary": "\n".join(summary_lines),
            "total": n,
            "succeeded": succeeded,
            "failed": failed,
            "elapsed_s": round(elapsed, 2),
            "mode": mode,
            "results": results,
        }

    # -- helpers ----------------------------------------------------------

    def _get_workers(self) -> List[str]:
        client = _get_client()
        return list(client.config.get("mcpServers", {}).keys())

    def _call_one(
        self, worker: str, task: str,
        workspace: str, provider, model, auto_approve, max_iter,
    ) -> Dict[str, Any]:
        """Call one worker synchronously. Safe (no asyncio.gather)."""
        client = _get_client()
        try:
            # Build args — drop None values (MCP schema rejects them)
            args: Dict[str, Any] = {
                "task": task,
                "workspace": workspace,
                "auto_approve": auto_approve,
                "max_iterations": max_iter,
            }
            if provider:
                args["provider"] = provider
            if model:
                args["model"] = model

            result = client.call_tool_sync(
                f"{worker}__neo_run_task",
                args,
            )
            ok = not result.startswith("[!]")
            return {"ok": ok, "task": task, "worker": worker, "result": result[:2000]}
        except Exception as e:
            return {"ok": False, "task": task, "worker": worker, "error": str(e)}

    # -- mode: sequential -------------------------------------------------

    def _run_sequential(
        self, tasks, workspace, provider, model, auto_approve, max_iter, timeout_s,
    ) -> List[Dict[str, Any]]:
        """Run tasks one by one. Safe for MCP."""
        workers = self._get_workers()
        if not workers:
            return [{"ok": False, "task": t, "error": "No MCP servers configured."} for t in tasks]

        results = []
        for i, task in enumerate(tasks):
            worker = workers[i % len(workers)]
            r = self._call_one(worker, task, workspace, provider, model, auto_approve, max_iter)
            results.append(r)
        return results

    # -- mode: chain ------------------------------------------------------

    def _run_chain(
        self, tasks, workspace, provider, model, auto_approve, max_iter, timeout_s,
    ) -> List[Dict[str, Any]]:
        """Chain: output of one feeds next."""
        workers = self._get_workers()
        if not workers:
            return [{"ok": False, "task": t, "error": "No MCP servers configured."} for t in tasks]

        results = []
        previous = ""
        for i, task in enumerate(tasks):
            if previous:
                chained_task = f"{task}\n\n[Previous result]:\n{previous[:1500]}"
            else:
                chained_task = task

            worker = workers[i % len(workers)]
            r = self._call_one(worker, chained_task, workspace, provider, model, auto_approve, max_iter)
            results.append({**r, "task": task})
            previous = r.get("result", "")

            if not r.get("ok"):
                break
        return results

    # -- mode: parallel (threads, 2-3 max) --------------------------------

    def _run_parallel_threads(
        self, tasks, workspace, provider, model, auto_approve, max_iter, timeout_s,
    ) -> List[Dict[str, Any]]:
        """
        Parallel via ThreadPoolExecutor. LIMIT: 2-3 tasks max (DeepSeek API).
        WARNING: MCP sessions may not be thread-safe. Use with caution.
        """
        import concurrent.futures

        workers = self._get_workers()
        if not workers:
            return [{"ok": False, "task": t, "error": "No MCP servers configured."} for t in tasks]

        # Limit to 3 tasks
        if len(tasks) > 3:
            return [{
                "ok": False,
                "task": t,
                "error": f"Parallel mode limited to 3 tasks (got {len(tasks)}). Use sequential.",
            } for t in tasks]

        assignments = []
        for i, task in enumerate(tasks):
            worker = workers[i % len(workers)]
            assignments.append((worker, task))

        results: List[Dict[str, Any]] = [None] * len(tasks)  # type: ignore

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            futures = {
                executor.submit(
                    self._call_one,
                    worker, task, workspace, provider, model, auto_approve, max_iter,
                ): i
                for i, (worker, task) in enumerate(assignments)
            }
            for future in concurrent.futures.as_completed(futures, timeout=timeout_s * len(tasks)):
                idx = futures[future]
                try:
                    results[idx] = future.result(timeout=timeout_s)
                except Exception as e:
                    results[idx] = {"ok": False, "task": tasks[idx], "error": str(e)}

        return results  # type: ignore


def build_orchestrator_tools() -> list[Tool]:
    """Instantiate orchestrator tools."""
    return [NEOOrchestrateTool()]
