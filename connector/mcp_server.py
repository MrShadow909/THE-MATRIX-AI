"""
NEO MCP Server

Exposes NEO as an MCP (Model Context Protocol) server so that
MCP-compatible clients (Claude Desktop, Cursor, Continue, etc.)
can use NEO as a tool.

Usage:
    python -m neo_code.connector.mcp_server

Claude Desktop config:
    {
      "mcpServers": {
        "neo": {
          "command": "python",
          "args": ["-m", "neo_code.connector.mcp_server"],
          "env": {
            "PYTHONPATH": "C:\\Users\\HP\\Desktop\\ENTER THE MATRIX"
          }
        }
      }
    }
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from neo_code.connector.api import run_task


# ============ Server ============

server = Server("neo-connector")


# ============ Tools ============

@server.list_tools()
async def list_tools() -> list[Tool]:
    """Return the list of tools NEO exposes to MCP clients."""
    return [
        Tool(
            name="neo_run_task",
            description=(
                "Run an autonomous software engineering task with NEO. "
                "NEO understands the codebase, plans changes, executes them, "
                "tests, and reports. Use this for code fixes, refactors, "
                "feature additions, or any task requiring file edits and "
                "command execution."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The engineering task to perform",
                    },
                    "workspace": {
                        "type": "string",
                        "description": "Absolute path to the project root",
                    },
                    "provider": {
                        "type": "string",
                        "description": "LLM provider (ollama, anthropic, openai, deepseek)",
                        "enum": ["ollama", "anthropic", "openai", "deepseek"],
                    },
                    "model": {
                        "type": "string",
                        "description": "Model name (e.g. deepseek-chat, claude-sonnet-5)",
                    },
                    "auto_approve": {
                        "type": "boolean",
                        "description": "Auto-approve all tool calls (be careful!)",
                        "default": False,
                    },
                },
                "required": ["task", "workspace"],
            },
        ),
        Tool(
            name="neo_status",
            description="Get the current NEO server status (provider, model, workspace).",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="neo_list_providers",
            description="List available LLM providers supported by NEO.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls from MCP clients."""
    try:
        if name == "neo_run_task":
            result = run_task(
                task=arguments["task"],
                workspace=arguments["workspace"],
                provider=arguments.get("provider"),
                model=arguments.get("model"),
                confirm_callback=(
                    (lambda *_, **__: True)
                    if arguments.get("auto_approve", False)
                    else None
                ),
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "neo_status":
            from neo_code.config import Config
            cfg = Config.load()
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "ready",
                    "provider": cfg.provider,
                    "model": cfg.model,
                    "workspace": cfg.workspace,
                }, indent=2),
            )]

        elif name == "neo_list_providers":
            from neo_code.providers import available_providers
            return [TextContent(
                type="text",
                text=json.dumps({
                    "providers": available_providers(),
                }, indent=2),
            )]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as exc:
        return [TextContent(type="text", text=f"Error: {exc}")]


# ============ Entry point ============

async def main():
    """Run the MCP server over stdio."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
