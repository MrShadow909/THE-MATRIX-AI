"""Professional terminal UI. Uses `rich` if available; falls back to
plain print() so the CLI still runs in a minimal environment.
"""

from __future__ import annotations

from typing import Any

try:
    from rich.align import Align
    from rich.console import Console
    from rich.prompt import Confirm
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False


# ---------------------------------------------------------------------------
# NEO / NEO visual identity
# ---------------------------------------------------------------------------

neo_code_ASCII = r"""



█████████████████████████████████████████████████████████████████████████████████████████████████


████████╗██╗  ██╗███████╗    ███╗   ███╗ █████╗ ████████╗██████╗ ██╗██╗  ██╗    █████╗ ██╗
╚══██╔══╝██║  ██║██╔════╝    ████╗ ████║██╔══██╗╚══██╔══╝██╔══██╗██║╚██╗██╔╝   ██╔══██╗██║
   ██║   ███████║█████╗      ██╔████╔██║███████║   ██║   ██████╔╝██║ ╚███╔╝    ███████║██║
   ██║   ██╔══██║██╔══╝      ██║╚██╔╝██║██╔══██║   ██║   ██╔══██╗██║ ██╔██╗    ██╔══██║██║
   ██║   ██║  ██║███████╗    ██║ ╚═╝ ██║██║  ██║   ██║   ██║  ██║██║██╔╝ ██╗   ██║  ██║██║
   ╚═╝   ╚═╝  ╚═╝╚══════╝    ╚═╝     ╚═╝╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝╚═╝╚═╝  ╚═╝   ╚═╝  ╚═╝


████████████████████████████████████████████████████████████████████████████████████████████████


""".strip("\n")

neo_code_TAGLINE = "AI SOFTWARE ENGINEERING TERMINAL"


class TerminalUI:
    """Rich-based presentation layer for the REPL.

    Uses Rich when available and falls back to plain print/input so the
    CLI remains functional in minimal environments.

    This class contains presentation logic only. It does not own or modify
    agent state, providers, tools, memory, permissions, or mission logic.
    """

    # -----------------------------------------------------------------------
    # Visual theme
    # -----------------------------------------------------------------------

    MATRIX_GREEN = "green"
    MATRIX_GREEN_DIM = "green3"
    MATRIX_GREEN_DARK = "dark_green"

    NEO_BORDER = "green"
    NEO_TITLE = "bold bright_green"
    NEO_TEXT = "green"

    # User input is intentionally blue so it is immediately distinguishable
    # from Neo's green output.
    USER_BORDER = "blue"
    USER_TITLE = "bold bright_blue"
    USER_PROMPT = "bold bright_blue"

    SYSTEM_BORDER = "cyan"
    SYSTEM_TITLE = "bold cyan"

    ERROR_BORDER = "red"

    # Visual-only terminal prompt label.
    # This does NOT change the prompt argument/default below.
    MATRIX_PROMPT_LABEL = "[ THE MATRIX ]"

    def __init__(self):
        self.console = Console() if _HAS_RICH else None

    # -----------------------------------------------------------------------
    # Generic output
    # -----------------------------------------------------------------------

    def print(self, text: str, style: str | None = None) -> None:
        if self.console:
            self.console.print(text, style=style)
        else:
            print(text)

    # -----------------------------------------------------------------------
    # Startup
    # -----------------------------------------------------------------------

    def startup_banner(self) -> None:
        """Large Matrix-style NEO banner shown once at startup.

        Cosmetic only. Does not touch config, providers, tools,
        permissions, memory, skills, or agent state.
        """
        if self.console:
            art = Text(
                neo_code_ASCII,
                style="bold bright_green",
            )

            tagline = Text(
                neo_code_TAGLINE,
                style="bold green3",
            )

            separator = Text(
                "─" * len(neo_code_TAGLINE),
                style="dim green",
            )

            self.console.print(Align.center(art))
            self.console.print(Align.center(tagline))
            self.console.print(Align.center(separator))
            self.console.print()

        else:
            print(neo_code_ASCII)
            print(neo_code_TAGLINE.center(64))
            print("-" * 64)

    # -----------------------------------------------------------------------
    # Main information banner
    # -----------------------------------------------------------------------

    def banner(
        self,
        config,
        provider_id: str,
        model: str,
        memory_status: dict[str, int],
        skills_count: int,
        tools_count: int,
    ) -> None:
        lines = [
            "[bold bright_green]Neo[/bold bright_green]"
            if self.console
            else "Neo",
            "AI SOFTWARE ENGINEERING TERMINAL",
            "",
            f"Provider : {provider_id}",
            f"Model    : {model}",
            f"Workspace: {config.workspace}",
            (
                f"Memory   : short-term={memory_status['short_term']} "
                f"project={memory_status['project']} "
                f"long-term={memory_status['long_term']}"
            ),
            f"Skills   : {skills_count} loaded",
            f"Tools    : {tools_count} registered",
        ]

        body = "\n".join(lines)

        if self.console:
            self.console.print(
                Align.center(
                    Panel(
                        body,
                        title="[bold bright_green] NEO [/bold bright_green]",
                        border_style=self.NEO_BORDER,
                        style="green",
                        expand=False,
                        padding=(1, 2),
                    )
                )
            )

        else:
            print("=" * 50)
            print(body)
            print("=" * 50)

    # -----------------------------------------------------------------------
    # Status
    # -----------------------------------------------------------------------

    def status_line(self, text: str) -> None:
        if self.console:
            self.console.print(
                Text(text, style="dim green3")
            )
        else:
            print(text)

    # -----------------------------------------------------------------------
    # Tool events
    # -----------------------------------------------------------------------

    def tool_event(
        self,
        tool: str,
        ok: bool,
        duration_s: float,
    ) -> None:
        mark = "✓" if ok else "✗"
        color = "bright_green" if ok else "red"

        if self.console:
            self.console.print(
                f"  [{color}]{mark}[/{color}] "
                f"[green3]{tool}[/green3] "
                f"[dim]({duration_s:.2f}s)[/dim]"
            )
        else:
            print(
                f"  [{mark}] {tool} ({duration_s:.2f}s)"
            )

    # -----------------------------------------------------------------------
    # Mission stages
    # -----------------------------------------------------------------------

    def stage(self, stage_name: str) -> None:
        if self.console:
            self.console.print(
                f"[bold bright_green]→ {stage_name.upper()}[/bold bright_green]"
            )
        else:
            print(f"-> {stage_name.upper()}")

    # -----------------------------------------------------------------------
    # Agent / Neo report
    # -----------------------------------------------------------------------

    def report(self, report: dict[str, Any]) -> None:
        """Render Neo's response.

        Neo's output remains visually distinct from user input:
        - completed -> bright Matrix green
        - completed_with_errors -> yellow
        - failed -> red
        """

        status = report.get("status", "unknown")

        color = {
            "completed": "bright_green",
            "completed_with_errors": "yellow",
            "failed": "red",
        }.get(status, "white")

        if self.console:
            summary = report.get("summary", "")

            self.console.print(
                Align.center(
                    Panel(
                        summary,
                        title=(
                            f"[bold {color}]"
                            f" NEO • {status.upper()} "
                            f"[/bold {color}]"
                        ),
                        border_style=color,
                        style="green",
                        expand=False,
                        padding=(1, 2),
                    )
                )
            )

            if report.get("files_changed"):
                self.console.print(
                    Panel(
                        ", ".join(report["files_changed"]),
                        title="[bold green]Files changed[/bold green]",
                        border_style="green",
                        style="green",
                        expand=False,
                    )
                )

            if report.get("errors"):
                self.console.print(
                    Panel(
                        "\n".join(
                            f"• {e}"
                            for e in report["errors"]
                        ),
                        title="[bold red]Errors[/bold red]",
                        border_style=self.ERROR_BORDER,
                        expand=False,
                    )
                )

        else:
            print(f"--- {status} ---")
            print(report.get("summary", ""))

            if report.get("files_changed"):
                print(
                    "Files changed:",
                    ", ".join(report["files_changed"]),
                )

            if report.get("errors"):
                print("Errors:")
                for e in report["errors"]:
                    print(" -", e)

    # -----------------------------------------------------------------------
    # Confirmation
    # -----------------------------------------------------------------------

    def confirm(
        self,
        prompt: str,
        level_name: str,
    ) -> bool:
        message = f"[{level_name}] {prompt}"

        if self.console:
            return Confirm.ask(
                f"[bold yellow]CONFIRM[/bold yellow] {message}",
                default=False,
            )

        answer = input(
            f"CONFIRM ({level_name}) {prompt} [y/N]: "
        ).strip().lower()

        return answer in ("y", "yes")

    # -----------------------------------------------------------------------
    # Tables
    # -----------------------------------------------------------------------

    def table(
        self,
        title: str,
        columns: list[str],
        rows: list[list[str]],
    ) -> None:
        if self.console:
            t = Table(
                title=title,
                title_style="bold bright_green",
                border_style="green",
                header_style="bold green3",
            )

            for c in columns:
                t.add_column(c)

            for r in rows:
                t.add_row(*r)

            self.console.print(t)

        else:
            print(title)
            print(" | ".join(columns))

            for r in rows:
                print(" | ".join(r))

    # -----------------------------------------------------------------------
    # REPL prompt
    # -----------------------------------------------------------------------

    def prompt(
        self,
        text: str = "<The Matrix> ",
    ) -> str:
        """Read user input.

        IMPORTANT:
        The original prompt/default argument is preserved exactly.
        Only the visual Rich presentation is changed.

        Backend/REPL behavior is unchanged.
        """

        if self.console:
            return self.console.input(
                f"[bold bright_blue]{self.MATRIX_PROMPT_LABEL}[/bold bright_blue] "
            )

        # Fallback keeps the original input behavior.
        return input(text)