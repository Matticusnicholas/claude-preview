#!/usr/bin/env python3
"""claude-preview — a Cursor-style coding agent in your terminal.

Pick a folder, then chat with Claude. The agent reads, writes, edits, and runs
code directly in that folder — and the right-hand preview pane shows a live
file explorer, the diffs of every change, and command output.

Engine:  the Claude Agent SDK, which runs on your local Claude Code login
         (Pro/Max subscription — no API key needed). Each user runs it on
         their own machine with their own Claude Code session.

Run:  python claude_preview.py   (or: python -m claude_preview, or: claude-preview)
"""

from __future__ import annotations

import os
from pathlib import Path

from rich.markdown import Markdown as RichMarkdown
from rich.syntax import Syntax
from rich.text import Text

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    DirectoryTree,
    Footer,
    Header,
    Input,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
)

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

MODEL = os.environ.get("CLAUDE_PREVIEW_MODEL")  # None -> Claude Code's default
PERMISSION_MODE = os.environ.get("CLAUDE_PREVIEW_PERMISSION", "acceptEdits")
ALLOWED_TOOLS = ["Read", "Write", "Edit", "MultiEdit", "Bash", "Glob", "Grep"]
EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

SYSTEM_PROMPT = """\
You are the coding agent inside `claude-preview`, a terminal IDE. You work
directly in the user's chosen project folder: read, write, edit, and run code
as needed to fulfil requests. Be concise in chat — the user can see your file
changes and command output in a side panel, so don't paste whole files back.
After making changes, give a short summary of what you did.
"""

MARKDOWN_EXTS = {".md", ".markdown"}


def renderable_for_path(path: Path):
    """Syntax-highlighted (or markdown) view of a file on disk."""
    try:
        if path.suffix.lower() in MARKDOWN_EXTS:
            return RichMarkdown(path.read_text(encoding="utf-8", errors="replace"))
        return Syntax.from_path(
            str(path),
            line_numbers=True,
            word_wrap=True,
            indent_guides=True,
            theme="ansi_dark",
        )
    except Exception as exc:  # binary, too large, permissions, gone
        return Text(f"(cannot preview {path.name}: {exc})", style="red")


def tab_id(path: Path) -> str:
    import re

    return "file-" + re.sub(r"[^A-Za-z0-9_-]", "-", str(path))


def diff_text(file_path: str, old: str, new: str) -> Text:
    """Render an Edit as a small red/green diff."""
    import difflib

    t = Text()
    t.append(f"\n✱ {file_path}\n", style="bold yellow")
    for line in difflib.unified_diff(
        old.splitlines(), new.splitlines(), lineterm="", n=1
    ):
        if line.startswith("+") and not line.startswith("+++"):
            t.append(line + "\n", style="green")
        elif line.startswith("-") and not line.startswith("---"):
            t.append(line + "\n", style="red")
        elif line.startswith("@@"):
            t.append(line + "\n", style="cyan")
    return t


# --------------------------------------------------------------------------- #
# Widgets
# --------------------------------------------------------------------------- #

class ChatLog(RichLog):
    def add_user(self, text: str) -> None:
        self.write(Text("\nYou", style="bold cyan"))
        self.write(Text(text))

    def add_system(self, text: str) -> None:
        self.write(Text(f"\n{text}", style="dim"))

    def add_error(self, text: str) -> None:
        self.write(Text(f"\n✗ {text}", style="bold red"))

    def add_activity(self, text: str, style: str = "dim") -> None:
        self.write(Text(text, style=style))

    def add_assistant_header(self) -> None:
        self.write(Text("\nClaude", style="bold magenta"))

    def add_assistant_markdown(self, text: str) -> None:
        self.write(RichMarkdown(text))


class StatusBar(Static):
    def set_status(self, text: str, busy: bool = False) -> None:
        icon = "⠿ " if busy else "● "
        style = "yellow" if busy else "green"
        self.update(Text.assemble((icon, style), (text, "dim")))


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #

class ClaudePreviewApp(App):
    """Cursor-style Claude coding agent with a live workspace preview."""

    TITLE = "claude-preview"

    CSS = """
    #workspace-bar {
        dock: top;
        height: 1;
        padding: 0 1;
        background: $boost;
    }
    #main { height: 1fr; }
    #left {
        width: 62%;
        border: round $primary;
        border-title-align: left;
    }
    #right {
        width: 38%;
        border: round $secondary;
        border-title-align: left;
    }
    #chat-log { height: 1fr; padding: 0 1; }
    #chat-input { dock: bottom; margin: 0 1 1 1; }
    #status { dock: bottom; height: 1; padding: 0 2; background: $surface; }
    #open-folder { dock: top; width: 100%; margin: 0 1; }
    DirectoryTree { height: 1fr; }
    TabbedContent { height: 1fr; }
    .preview-body { padding: 0 1; }
    """

    BINDINGS = [
        Binding("ctrl+o", "open_folder", "Open folder"),
        Binding("ctrl+r", "reload_tree", "Reload tree"),
        Binding("ctrl+g", "stop_agent", "Stop agent"),
        Binding("ctrl+l", "clear_log", "Clear log"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, workspace: str | None = None) -> None:
        super().__init__()
        self.workspace = Path(workspace or os.getcwd()).resolve()
        self.client: ClaudeSDKClient | None = None
        self.connected = False
        self.connect_error: str | None = None
        self.open_tabs: dict[str, Path] = {}
        self._bash_calls: dict[str, str] = {}

    # ----------------------------------------------------------------- UI -- #

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(id="workspace-bar")
        with Horizontal(id="main"):
            with Vertical(id="left") as left:
                left.border_title = "Chat"
                yield ChatLog(id="chat-log", wrap=True, markup=False)
                yield Input(
                    placeholder="Ask Claude to build or change something…  (Ctrl+O to pick a folder)",
                    id="chat-input",
                )
            with Vertical(id="right") as right:
                right.border_title = "Workspace"
                with TabbedContent(id="preview-tabs"):
                    with TabPane("Explorer", id="tab-explorer"):
                        yield Button("📂  Open folder…", id="open-folder", variant="primary")
                        yield DirectoryTree(str(self.workspace), id="file-tree")
                    with TabPane("Changes", id="tab-changes"):
                        yield RichLog(id="changes-log", wrap=True, markup=False)
                    with TabPane("Output", id="tab-output"):
                        yield RichLog(id="output-log", wrap=True, markup=False)
        yield StatusBar(id="status")
        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one(ChatLog)
        log.add_system("claude-preview — a Claude coding agent that works in a folder you choose.")
        log.add_system("Engine: Claude Agent SDK on your local Claude Code login (no API key).")
        log.add_system("Press Ctrl+O (or the Open folder button) to pick a project, then just chat.")
        self.update_workspace_bar()
        self.query_one("#chat-input", Input).focus()
        self.connect_agent()

    def update_workspace_bar(self) -> None:
        self.query_one("#workspace-bar", Static).update(
            Text.assemble(("📂 ", "yellow"), (str(self.workspace), "bold"))
        )

    def status(self, text: str, busy: bool = False) -> None:
        self.query_one(StatusBar).set_status(text, busy)

    # ------------------------------------------------------- agent connect -- #

    def _build_options(self) -> ClaudeAgentOptions:
        async def allow_all(*_args, **_kwargs):  # never stall on a permission prompt
            return PermissionResultAllow()

        kwargs = dict(
            allowed_tools=ALLOWED_TOOLS,
            permission_mode=PERMISSION_MODE,
            cwd=str(self.workspace),
            system_prompt=SYSTEM_PROMPT,
            can_use_tool=allow_all,
        )
        if MODEL:
            kwargs["model"] = MODEL
        return ClaudeAgentOptions(**kwargs)

    @work(exclusive=True, group="connect")
    async def connect_agent(self) -> None:
        log = self.query_one(ChatLog)
        self.status("Connecting to Claude Code…", busy=True)
        # Tear down a previous session (e.g. on folder switch).
        if self.client is not None:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None
            self.connected = False
        try:
            self.client = ClaudeSDKClient(options=self._build_options())
            await self.client.connect()
            self.connected = True
            self.connect_error = None
            self.status(f"Ready — working in {self.workspace.name}")
        except Exception as exc:
            self.connected = False
            self.connect_error = str(exc)
            log.add_error(
                "Couldn't start the Claude agent. Make sure Claude Code is installed and "
                "logged in:\n"
                "  npm install -g @anthropic-ai/claude-code   (then run:  claude  and /login)\n"
                f"  detail: {exc}"
            )
            self.status("Not connected — log into Claude Code")

    # ------------------------------------------------------------- actions -- #

    def action_reload_tree(self) -> None:
        self.query_one(DirectoryTree).reload()
        self.refresh_open_tabs()
        self.status("Workspace reloaded")

    def action_clear_log(self) -> None:
        self.query_one(ChatLog).clear()

    def action_stop_agent(self) -> None:
        if self.client and self.connected:
            self.interrupt_agent()

    @work(group="interrupt")
    async def interrupt_agent(self) -> None:
        try:
            await self.client.interrupt()  # type: ignore[union-attr]
            self.query_one(ChatLog).add_system("⏹ Interrupted.")
            self.status(f"Ready — working in {self.workspace.name}")
        except Exception as exc:
            self.query_one(ChatLog).add_error(f"Couldn't interrupt: {exc}")

    def action_open_folder(self) -> None:
        self.pick_folder()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "open-folder":
            self.pick_folder()

    # ------------------------------------------------------- folder picker -- #

    @work(thread=True, group="picker")
    def pick_folder(self) -> None:
        try:
            import tkinter as tk
            from tkinter import filedialog
        except Exception as exc:
            self.call_from_thread(
                self.query_one(ChatLog).add_error,
                f"Folder dialog unavailable ({exc}). Set the folder by launching: "
                f"claude-preview <path>",
            )
            return
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(
            title="Select a folder for claude-preview to work in",
            initialdir=str(self.workspace),
        )
        root.destroy()
        if chosen:
            self.call_from_thread(self.set_workspace, chosen)

    def set_workspace(self, path: str) -> None:
        self.workspace = Path(path).resolve()
        self.update_workspace_bar()
        tree = self.query_one(DirectoryTree)
        tree.path = str(self.workspace)
        tree.reload()
        # Close stale file tabs.
        tabs = self.query_one("#preview-tabs", TabbedContent)
        for pane_id in list(self.open_tabs):
            try:
                tabs.remove_pane(pane_id)
            except Exception:
                pass
        self.open_tabs.clear()
        self.query_one("#changes-log", RichLog).clear()
        self.query_one(ChatLog).add_system(f"Switched workspace to {self.workspace}")
        self.connect_agent()  # restart agent rooted at the new folder

    # ------------------------------------------------------ file previews -- #

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        self.open_file_tab(Path(event.path))

    def open_file_tab(self, path: Path) -> None:
        tabs = self.query_one("#preview-tabs", TabbedContent)
        pid = tab_id(path)
        renderable = renderable_for_path(path)
        if pid in self.open_tabs:
            tabs.get_pane(pid).query_one(Static).update(renderable)
        else:
            body = VerticalScroll(Static(renderable, classes="preview-body"))
            tabs.add_pane(TabPane(path.name, body, id=pid))
            self.open_tabs[pid] = path
        tabs.active = pid

    def refresh_open_tabs(self) -> None:
        tabs = self.query_one("#preview-tabs", TabbedContent)
        for pid, path in list(self.open_tabs.items()):
            if path.exists():
                try:
                    tabs.get_pane(pid).query_one(Static).update(renderable_for_path(path))
                except Exception:
                    pass

    # --------------------------------------------------------------- chat -- #

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if not self.connected:
            self.query_one(ChatLog).add_error(
                "Not connected to Claude Code yet — see the message above."
            )
            return
        self.query_one(ChatLog).add_user(text)
        self.run_turn(text)

    @work(exclusive=True, group="turn")
    async def run_turn(self, prompt: str) -> None:
        log = self.query_one(ChatLog)
        assert self.client is not None
        self.status("Claude is working…", busy=True)
        self._bash_calls.clear()
        header_shown = False
        edited: set[str] = set()
        cost = None
        try:
            await self.client.query(prompt)
            async for msg in self.client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            if block.text.strip():
                                if not header_shown:
                                    log.add_assistant_header()
                                    header_shown = True
                                log.add_assistant_markdown(block.text)
                        elif isinstance(block, ThinkingBlock):
                            log.add_activity("  …thinking", "dim italic")
                        elif isinstance(block, ToolUseBlock):
                            self.handle_tool_use(block, edited)
                elif isinstance(msg, UserMessage):
                    self.handle_tool_results(msg)
                elif isinstance(msg, ResultMessage):
                    cost = getattr(msg, "total_cost_usd", None)
                elif isinstance(msg, SystemMessage):
                    pass
        except Exception as exc:
            log.add_error(f"Agent error: {exc}")
            self.status("Error")
            return

        # Reflect changes on disk in the preview.
        if edited:
            self.query_one(DirectoryTree).reload()
            self.refresh_open_tabs()
            log.add_activity(f"  ✓ touched {len(edited)} file(s)", "green")
        ready = f"Ready — {self.workspace.name}"
        if cost:
            ready += f"  (${cost:.4f} this session)"
        self.status(ready)

    def handle_tool_use(self, block: ToolUseBlock, edited: set[str]) -> None:
        log = self.query_one(ChatLog)
        name = block.name
        inp = block.input or {}
        if name == "Bash":
            cmd = str(inp.get("command", ""))
            self._bash_calls[block.id] = cmd
            log.add_activity(f"  ▶ {cmd.splitlines()[0][:80] if cmd else 'bash'}", "blue")
        elif name in EDIT_TOOLS:
            fp = str(inp.get("file_path", inp.get("notebook_path", "?")))
            edited.add(fp)
            verb = "📝 Write" if name == "Write" else "✏️  Edit"
            log.add_activity(f"  {verb} {self._rel(fp)}", "yellow")
            self.record_change(name, inp)
        elif name in ("Read", "Glob", "Grep"):
            target = inp.get("file_path") or inp.get("pattern") or inp.get("path") or ""
            log.add_activity(f"  👁 {name} {self._rel(str(target))}", "dim")
        else:
            log.add_activity(f"  • {name}", "dim")

    def handle_tool_results(self, msg: UserMessage) -> None:
        content = msg.content
        if not isinstance(content, list):
            return
        out = self.query_one("#output-log", RichLog)
        for block in content:
            if isinstance(block, ToolResultBlock) and block.tool_use_id in self._bash_calls:
                cmd = self._bash_calls[block.tool_use_id]
                out.write(Text(f"\n$ {cmd}", style="bold"))
                out.write(Text(self._result_text(block.content)))

    def record_change(self, name: str, inp: dict) -> None:
        changes = self.query_one("#changes-log", RichLog)
        fp = str(inp.get("file_path", inp.get("notebook_path", "?")))
        if name == "Write":
            changes.write(Text(f"\n📝 wrote {self._rel(fp)}", style="bold green"))
        elif name == "Edit":
            changes.write(diff_text(self._rel(fp), str(inp.get("old_string", "")),
                                    str(inp.get("new_string", ""))))
        elif name == "MultiEdit":
            for e in inp.get("edits", []):
                changes.write(diff_text(self._rel(fp), str(e.get("old_string", "")),
                                        str(e.get("new_string", ""))))
        else:
            changes.write(Text(f"\n✏️  edited {self._rel(fp)}", style="bold yellow"))

    # -------------------------------------------------------------- utils -- #

    def _rel(self, p: str) -> str:
        try:
            return str(Path(p).resolve().relative_to(self.workspace))
        except (ValueError, OSError):
            return p

    @staticmethod
    def _result_text(content) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text", item)))
                else:
                    parts.append(getattr(item, "text", str(item)))
            return "\n".join(parts)
        return str(content)

    async def on_unmount(self) -> None:
        if self.client is not None:
            try:
                await self.client.disconnect()
            except Exception:
                pass


def main() -> None:
    import sys

    workspace = sys.argv[1] if len(sys.argv) > 1 else None
    ClaudePreviewApp(workspace=workspace).run()


if __name__ == "__main__":
    main()
