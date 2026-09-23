"""NEO CLI entry point.

neo                 # interactive REPL in the current directory
neo --workspace P   # interactive REPL rooted at P
neo --task-json -   # JSON task mode: read one task from stdin,
                          # write one JSON report to stdout, then exit.
"""

from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path

from neo_code.config import Config
from neo_code.core.agent import Agent
from neo_code.core.permissions import PermissionLevel
from neo_code.providers import available_providers, create_provider
from neo_code.ui.terminal import TerminalUI


SKILLS_DIR = str(Path(__file__).resolve().parent / "skills")


HELP_TEXT = """\
Commands:
  /help                 show this help
  /setup                provider → model → API key setup
  /status               show provider/model/workspace/memory/tools summary
  /provider <name>      switch provider
  /model <name>         switch model for the current provider
  /apikey               enter/change API key
  /memory [query]       list recent memory, or search it
  /remember <text>      store a note in project memory
  /skills               list loaded skills
  /tools                list registered tools
  /project              show detected project info
  /history              show recent session activity
  /permissions          show current permission requirements
  /approve <level>      auto-approve WRITE|EXECUTE|SYSTEM for this session
  /clear                clear short-term memory + conversation history
  /reset                reset the whole session
  /exit                 quit

Anything else is treated as an engineering task for NEO to carry out.
"""


# ---------------------------------------------------------------------------
# Default model per provider
# ---------------------------------------------------------------------------

PROVIDER_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5",
    "deepseek": "deepseek-chat",
    "openai": "gpt-5",
    "ollama": "llama3.2",
}


# ---------------------------------------------------------------------------
# Provider / API key helpers
# ---------------------------------------------------------------------------

PROVIDER_ENV_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}


def _set_runtime_api_key(
    config: Config,
    provider_name: str,
    api_key: str,
) -> None:
    """
    Put the API key into the current Config object.

    Uses the new `api_keys` dict field.
    Also sets the corresponding environment variable for the
    current process so providers that read environment variables
    continue to work.
    """
    api_key = api_key.strip()

    if not api_key:
        raise ValueError("API key cannot be empty.")

    # Store in config.
    if not hasattr(config, "api_keys"):
        config.api_keys = {}

    config.api_keys[provider_name] = api_key

    # Also set environment variable for this process.
    env_name = PROVIDER_ENV_KEYS.get(provider_name)

    if env_name:
        os.environ[env_name] = api_key


def _save_config(config: Config) -> bool:
    """Save configuration using the project's existing persistence API."""
    try:
        config.save_user()
        return True
    except Exception:
        return False


def _prompt_api_key(
    provider_name: str,
    ui: TerminalUI,
) -> str | None:
    """Secure API-key prompt."""
    env_name = PROVIDER_ENV_KEYS.get(provider_name)

    ui.print("")
    ui.print(f"API KEY — {provider_name.upper()}")
    ui.print("The key will not be displayed while typing.")

    if env_name:
        ui.print(f"Environment variable: {env_name}")

    try:
        key = getpass.getpass("Enter API Key: ").strip()
    except (EOFError, KeyboardInterrupt):
        ui.print("\nAPI key entry cancelled.")
        return None

    if not key:
        ui.print("No API key entered.", style="yellow")
        return None

    return key


def _configure_provider(
    config: Config,
    agent: Agent,
    ui: TerminalUI,
) -> bool:
    """Interactive provider setup."""

    ui.print("")
    ui.print("=" * 54)
    ui.print("             NEO PROVIDER SETUP")
    ui.print("=" * 54)
    ui.print("")

    providers = list(available_providers())

    if not providers:
        ui.print("No providers are registered.", style="red")
        return False

    ui.print("Available providers:")

    for index, provider_name in enumerate(providers, 1):
        marker = " (current)" if provider_name == config.provider else ""
        ui.print(f"  {index}. {provider_name}{marker}")

    ui.print("")

    raw = ui.prompt("Select provider: ").strip()

    try:
        index = int(raw)

        if index < 1 or index > len(providers):
            raise ValueError

    except ValueError:
        ui.print("Invalid provider selection.", style="red")
        return False

    provider_name = providers[index - 1]

    # -----------------------------------------------------------------------
    # Model selection
    # -----------------------------------------------------------------------

    model_options = {
        "anthropic": [
            "claude-sonnet-5",
            "claude-opus-5",
            "Custom model",
        ],
        "openai": [
            "gpt-5",
            "gpt-5-mini",
            "Custom model",
        ],
        "deepseek": [
            "deepseek-chat",
            "deepseek-reasoner",
            "Custom model",
        ],
        "ollama": [
            "llama3.2",
            "qwen2.5-coder",
            "Custom model",
        ],
    }

    models = model_options.get(
        provider_name,
        ["Custom model"],
    )

    ui.print("")
    ui.print(f"Models for {provider_name}:")

    for index, model in enumerate(models, 1):
        ui.print(f"  {index}. {model}")

    ui.print("")

    raw = ui.prompt("Select model: ").strip()

    try:
        model_index = int(raw)

        if model_index < 1 or model_index > len(models):
            raise ValueError

        selected_model = models[model_index - 1]

    except ValueError:
        ui.print("Invalid model selection.", style="red")
        return False

    if selected_model == "Custom model":
        selected_model = ui.prompt(
            "Enter model name: "
        ).strip()

        if not selected_model:
            ui.print(
                "Model name cannot be empty.",
                style="red",
            )
            return False

    # -----------------------------------------------------------------------
    # API key
    # -----------------------------------------------------------------------

    api_key = None

    if provider_name != "ollama":
        api_key = _prompt_api_key(
            provider_name,
            ui,
        )

        if not api_key:
            return False

        try:
            _set_runtime_api_key(
                config,
                provider_name,
                api_key,
            )
        except Exception as exc:
            ui.print(
                f"Could not configure API key: {exc}",
                style="red",
            )
            return False

    # -----------------------------------------------------------------------
    # Apply provider / model
    # -----------------------------------------------------------------------

    config.provider = provider_name
    config.model = selected_model

    ui.print("")
    ui.print("Initializing provider...")

    try:
        new_provider = create_provider(config)

        # Ensure the provider gets the key from config.
        if api_key and hasattr(new_provider, "api_key"):
            new_provider.api_key = api_key

        reason = new_provider.is_available()

        if reason:
            ui.print(
                f"Provider is not ready: {reason}",
                style="red",
            )
            return False

        new_provider.model = selected_model
        agent.provider = new_provider

    except Exception as exc:
        ui.print(
            f"Provider initialization failed: {exc}",
            style="red",
        )
        return False

    ui.print(
        f"✓ Provider initialized: {provider_name}"
    )
    ui.print(
        f"✓ Model selected: {selected_model}"
    )

    # -----------------------------------------------------------------------
    # Test connection
    # -----------------------------------------------------------------------

    ui.print("")
    ui.print("Testing provider connection...")

    try:
        reason = agent.provider.is_available()

        if reason:
            ui.print(
                f"✗ Provider test failed: {reason}",
                style="red",
            )
            return False

        ui.print(
            "✓ Provider connection looks good."
        )

    except Exception as exc:
        ui.print(
            f"✗ Provider test failed: {exc}",
            style="red",
        )
        return False

    # -----------------------------------------------------------------------
    # Save
    # -----------------------------------------------------------------------

    ui.print("")

    save = ui.prompt(
        "Save this configuration? [Y/n]: "
    ).strip().lower()

    if save in ("", "y", "yes"):
        if _save_config(config):
            ui.print("✓ Configuration saved.")
        else:
            ui.print(
                "[!] Provider works for this session, "
                "but configuration could not be saved.",
                style="yellow",
            )
    else:
        ui.print(
            "Configuration kept for this session only."
        )

    return True


# ---------------------------------------------------------------------------
# Agent creation
# ---------------------------------------------------------------------------

def _make_agent(
    config: Config,
    ui: TerminalUI,
) -> Agent:

    provider = create_provider(config)

    reason = provider.is_available()

    if reason:
        ui.print(
            f"[!] Provider '{config.provider}' is not ready: {reason}",
            style="red",
        )
        ui.print(
            "    Run /setup to configure the provider."
        )

    # The confirm_callback uses agent_ref but it is safe because
    # the callback is invoked only after the agent has been assigned.
    session_state = {
        "asked": False,
    }

    agent_ref: dict[str, Agent] = {}

    def confirm_cb(
        prompt: str,
        level: PermissionLevel,
    ) -> bool:

        if (
            level in (
                PermissionLevel.WRITE,
                PermissionLevel.EXECUTE,
            )
            and not session_state["asked"]
        ):
            session_state["asked"] = True

            try:
                answer = ui.prompt(
                    "Approve write + execute for the rest "
                    "of this session? [y/n]: "
                ).strip().lower()

            except (KeyboardInterrupt, EOFError):
                answer = "n"

            if answer in ("y", "yes"):
                agent_ref["agent"].permissions.approve_for_session(
                    PermissionLevel.WRITE
                )

                agent_ref["agent"].permissions.approve_for_session(
                    PermissionLevel.EXECUTE
                )

                return True

        return ui.confirm(
            prompt,
            level.name,
        )

    def on_event(
        kind: str,
        **data,
    ):
        if kind == "tool_result":
            result = data["result"]

            ui.tool_event(
                data["tool"],
                result.ok,
                result.duration_s,
            )

        elif kind == "stage":
            pass

    agent = Agent(
        config,
        provider,
        SKILLS_DIR,
        confirm_callback=confirm_cb,
        on_event=on_event,
    )

    agent_ref["agent"] = agent

    return agent


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

def run_repl(workspace: str) -> None:
    """Launch the interactive NEO REPL."""

    ui = TerminalUI()

    config = Config.load(
        workspace=workspace
    )

    agent = _make_agent(
        config,
        ui,
    )

    # If provider is not configured, offer setup immediately.
    if agent.provider.is_available():
        ui.print("")
        ui.print(
            "NEO needs provider configuration."
        )

        answer = ui.prompt(
            "Run provider setup now? [Y/n]: "
        ).strip().lower()

        if answer in ("", "y", "yes"):
            _configure_provider(
                config,
                agent,
                ui,
            )

    # -----------------------------------------------------------------------
    # Startup UI
    # -----------------------------------------------------------------------

    ui.startup_banner()

    ui.banner(
        config,
        provider_id=agent.provider.id,
        model=agent.provider.model,
        memory_status=agent.memory.status(),
        skills_count=len(agent.skills.all()),
        tools_count=len(agent.tools.all()),
    )

    ui.print(
        "Type /help for commands, "
        "or describe an engineering task.\n"
    )

    # -----------------------------------------------------------------------
    # Neo REPL
    # -----------------------------------------------------------------------

    while True:
        try:
            line = ui.prompt(
                "<Neo> "
            ).strip()

        except (EOFError, KeyboardInterrupt):
            ui.print(
                "\nExiting NEO."
            )
            break

        if not line:
            continue

        # Commands
        if line.startswith("/"):
            if _handle_command(
                line,
                config,
                agent,
                ui,
            ) == "exit":
                break

            continue

        # -------------------------------------------------------------------
        # Engineering task
        # -------------------------------------------------------------------

        try:
            report = agent.run_task(line)
            ui.report(report)

        except (KeyboardInterrupt, EOFError):
            ui.print(
                "\n[!] Task cancelled.",
                style="yellow",
            )

        except Exception as exc:
            ui.print(
                f"[!] Task failed with an unexpected error: {exc}",
                style="red",
            )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _handle_command(
    line: str,
    config: Config,
    agent: Agent,
    ui: TerminalUI,
) -> str | None:

    parts = line.split(
        maxsplit=1
    )

    cmd = parts[0].lower()

    arg = (
        parts[1].strip()
        if len(parts) > 1
        else ""
    )

    if cmd == "/help":

        ui.print(
            HELP_TEXT
        )

    elif cmd == "/setup":

        _configure_provider(
            config,
            agent,
            ui,
        )

    elif cmd == "/status":

        ui.table(
            "NEO status",
            ["field", "value"],
            [
                [
                    "provider",
                    agent.provider.id,
                ],
                [
                    "model",
                    agent.provider.model,
                ],
                [
                    "workspace",
                    config.workspace,
                ],
                [
                    "tools",
                    str(len(agent.tools.all())),
                ],
                [
                    "skills",
                    str(len(agent.skills.all())),
                ],
                [
                    "memory",
                    str(agent.memory.status()),
                ],
            ],
        )

    elif cmd == "/provider":

        if not arg:
            ui.print(
                "Available providers: "
                + ", ".join(available_providers())
            )

        else:
            config.provider = arg

            config.model = PROVIDER_DEFAULT_MODELS.get(
                arg,
                "deepseek-chat",
            )

            new_provider = create_provider(
                config
            )

            reason = new_provider.is_available()

            if reason:
                ui.print(
                    f"[!] '{arg}' not ready: {reason}",
                    style="red",
                )

            else:
                agent.provider = new_provider

                ui.print(
                    f"Switched provider to '{arg}' "
                    f"(model: {config.model})."
                )

    elif cmd == "/model":

        if not arg:
            ui.print(
                f"Current model: {agent.provider.model}"
            )

        else:
            agent.provider.model = arg
            config.model = arg

            ui.print(
                f"Switched model to '{arg}'."
            )

    elif cmd == "/apikey":

        provider_name = agent.provider.id

        api_key = _prompt_api_key(
            provider_name,
            ui,
        )

        if api_key:
            try:
                _set_runtime_api_key(
                    config,
                    provider_name,
                    api_key,
                )

                # Recreate provider so the new key is actually used.
                new_provider = create_provider(
                    config
                )

                if hasattr(
                    new_provider,
                    "api_key",
                ):
                    new_provider.api_key = api_key

                reason = new_provider.is_available()

                if reason:
                    ui.print(
                        f"✗ Provider is not ready: {reason}",
                        style="red",
                    )

                else:
                    agent.provider = new_provider

                    ui.print(
                        "✓ API key accepted."
                    )

                    ui.print(
                        f"✓ Provider: {provider_name}"
                    )

                    ui.print(
                        f"✓ Model: {agent.provider.model}"
                    )

                    save = ui.prompt(
                        "Save key to configuration? [Y/n]: "
                    ).strip().lower()

                    if save in (
                        "",
                        "y",
                        "yes",
                    ):
                        if _save_config(config):
                            ui.print(
                                "✓ API key saved."
                            )
                        else:
                            ui.print(
                                "[!] Key works for this session "
                                "but could not be saved.",
                                style="yellow",
                            )

            except Exception as exc:
                ui.print(
                    f"✗ API key update failed: {exc}",
                    style="red",
                )

    elif cmd == "/memory":

        if arg:
            results = agent.memory.recall(
                arg
            )

            for scope, entries in results.items():
                for entry in entries:
                    ui.print(
                        f"[{scope}] {entry['content']}"
                    )

        else:
            ui.print(
                agent.memory.context_snapshot()
            )

    elif cmd == "/remember":

        if arg:
            agent.memory.remember(
                arg,
                scope="project",
            )

            ui.print(
                "Stored in project memory."
            )

        else:
            ui.print(
                "Usage: /remember <text>"
            )

    elif cmd == "/skills":

        rows = [
            [
                skill.id,
                skill.name,
                skill.description[:60],
            ]
            for skill in agent.skills.all()
        ]

        ui.table(
            "Skills",
            [
                "id",
                "name",
                "description",
            ],
            rows,
        )

    elif cmd == "/tools":

        rows = [
            [
                tool.name,
                tool.permission.name,
                tool.description[:60],
            ]
            for tool in agent.tools.all()
        ]

        ui.table(
            "Tools",
            [
                "name",
                "permission",
                "description",
            ],
            rows,
        )

    elif cmd == "/project":

        ui.print(
            agent.project_context.as_prompt_block()
        )

    elif cmd == "/history":

        for entry in agent.session.recent(20):
            ui.print(
                f"- {entry.get('event')}: "
                f"{str(entry)[:120]}"
            )

    elif cmd == "/permissions":

        ui.print(
            str(config.require_confirmation)
        )

    elif cmd == "/approve":

        try:
            level = PermissionLevel.from_str(
                arg
            )

            agent.permissions.approve_for_session(
                level
            )

            ui.print(
                f"Auto-approving {level.name} "
                "for the rest of this session."
            )

        except KeyError:
            ui.print(
                "Usage: /approve WRITE|EXECUTE|SYSTEM"
            )

    elif cmd == "/clear":

        agent.memory.clear_short_term()
        agent.messages = []

        ui.print(
            "Cleared short-term memory "
            "and conversation history."
        )

    elif cmd == "/reset":

        agent.messages = []

        agent.session = agent.session.__class__(
            config.log_dir,
            config.workspace,
        )

        ui.print(
            "Session reset. "
            "New session log started."
        )

    elif cmd == "/exit":

        return "exit"

    else:

        ui.print(
            f"Unknown command: {cmd}. Type /help."
        )

    return None


# ---------------------------------------------------------------------------
# Neo bridge
# ---------------------------------------------------------------------------

from neo_code.connector.api import run_from_stdin  # noqa: E402


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    """The `neo` console-script entry point."""

    parser = argparse.ArgumentParser(
        prog="neo",
        description=(
            "NEO — AI software engineering "
            "terminal agent."
        ),
    )

    parser.add_argument(
        "--workspace",
        default=".",
        help="Project root to operate in.",
    )

    parser.add_argument(
        "--task-json",
        metavar="-",
        help=(
            "JSON task mode: read one JSON task object "
            "from stdin, print one JSON report object "
            "to stdout, then exit."
        ),
    )

    parser.add_argument(
        "--task",
        help=(
            "Run a single task non-interactively "
            "and exit (human-readable output)."
        ),
    )

    args = parser.parse_args(
        argv
    )

    # -----------------------------------------------------------------------
    # JSON task mode
    # -----------------------------------------------------------------------

    if args.task_json is not None:
        run_from_stdin()
        return 0

    # -----------------------------------------------------------------------
    # Single task mode
    # -----------------------------------------------------------------------

    if args.task:
        ui = TerminalUI()

        config = Config.load(
            workspace=args.workspace
        )

        agent = _make_agent(
            config,
            ui,
        )

        report = agent.run_task(
            args.task
        )

        ui.report(
            report
        )

        return (
            0
            if report["status"] != "failed"
            else 1
        )

    # -----------------------------------------------------------------------
    # Interactive Neo REPL
    # -----------------------------------------------------------------------

    run_repl(
        args.workspace
    )

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(
        main()
    )