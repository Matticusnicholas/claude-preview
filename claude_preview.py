#!/usr/bin/env python3
"""claude-preview — an interactive Claude coding session with a live preview pane.

Left pane:  chat with Claude (history, input, slash commands).
Right pane: live tabs for every code block Claude generates, a file tree,
            markdown preview, and script output.

Run:  python -m claude_preview   (or: python claude_preview.py, or: claude-preview)
Requires: ANTHROPIC_API_KEY in the environment.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Protocol

from rich.markdown import Markdown as RichMarkdown
from rich.syntax import Syntax
from rich.text import Text

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Footer,
    Header,
    Input,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
    Tree,
)

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

DEFAULT_MODEL = os.environ.get("CLAUDE_PREVIEW_MODEL", "claude-opus-4-8")
MAX_TOKENS = int(os.environ.get("CLAUDE_PREVIEW_MAX_TOKENS", "32000"))

SYSTEM_PROMPT = """\
You are a coding assistant inside `claude-preview`, a terminal app with a live
preview pane that renders every code block you produce.

When you write a file, ALWAYS open the fenced block with the language AND a
filename, e.g.:

```python app.py
print("hello")
```

Use one fenced block per file and keep filenames stable across revisions so
the preview pane updates the same tab. Prefer complete files over fragments
when the user asks you to build or modify something.
"""

EXT_FOR_LANG = {
    "python": "py", "py": "py", "javascript": "js", "js": "js",
    "typescript": "ts", "ts": "ts", "tsx": "tsx", "jsx": "jsx",
    "html": "html", "css": "css", "json": "json", "yaml": "yaml",
    "yml": "yml", "toml": "toml", "bash": "sh", "sh": "sh", "shell": "sh",
    "sql": "sql", "rust": "rs", "go": "go", "java": "java", "c": "c",
    "cpp": "cpp", "markdown": "md", "md": "md", "text": "txt",
}

CODE_BLOCK_RE = re.compile(
    r"```([A-Za-z0-9_+-]*)[ \t]*([^\s`]*)[ \t]*\n(.*?)(?:```|\Z)",
    re.DOTALL,
)

HELP_TEXT = """\
[bold]Commands[/bold]
  /apply <file>     write a generated file to disk
  /apply all        write every generated file to disk
  /run <file>       run a generated/applied Python or shell file, output → Output tab
  /preview <file>   focus a file's tab in the preview pane
  /load <path>      read a file from disk into the conversation
  /files            list generated files
  /clear            clear conversation history (keeps generated files)
  /model [name]     show or switch the model
  /help             show this help

[bold]Keys[/bold]
  Ctrl+R  refresh preview    Tab  cycle focus    Ctrl+L  clear chat log    Ctrl+Q  quit
"""


# --------------------------------------------------------------------------- #
# Pluggable LLM provider layer
# --------------------------------------------------------------------------- #

class LLMProvider(Protocol):
    """Anything that can stream a chat completion. Swap in your own backend."""

    model: str

    def stream_chat(
        self, system: str, messages: list[dict]
    ) -> AsyncIterator[str]: ...


class AnthropicProvider:
    """Default provider — official Anthropic SDK, streaming, adaptive thinking."""

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        import anthropic

        self.model = model
        self._client = anthropic.AsyncAnthropic()

    async def stream_chat(self, system: str, messages: list[dict]) -> AsyncIterator[str]:
        async with self._client.messages.stream(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=system,
            thinking={"type": "adaptive"},
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text


# --------------------------------------------------------------------------- #
# Generated-file model
# --------------------------------------------------------------------------- #

@dataclass
class GeneratedFile:
    name: str
    language: str
    content: str
    applied: bool = False


@dataclass
class Workspace:
    """All code blocks extracted from the conversation, keyed by filename."""

    files: dict[str, GeneratedFile] = field(default_factory=dict)
    _anon_count: int = 0

    def update_from_text(self, text: str) -> list[str]:
        """Re-extract code blocks from an assistant message. Returns touched names."""
        touched: list[str] = []
        anon_index = 0
        for match in CODE_BLOCK_RE.finditer(text):
            lang = (match.group(1) or "text").lower()
            name = match.group(2) or ""
            content = match.group(3)
            if not name:
                anon_index += 1
                ext = EXT_FOR_LANG.get(lang, "txt")
                name = f"snippet_{anon_index}.{ext}"
            existing = self.files.get(name)
            if existing is not None:
                existing.content = content
                existing.language = lang
            else:
                self.files[name] = GeneratedFile(name=name, language=lang, content=content)
            touched.append(name)
        return touched


def slug(name: str) -> str:
    """Textual widget IDs allow letters, digits, underscore, hyphen."""
    return "tab-" + re.sub(r"[^A-Za-z0-9_-]", "-", name)


# --------------------------------------------------------------------------- #
# Widgets
# --------------------------------------------------------------------------- #

class ChatLog(RichLog):
    """Conversation history with rich rendering."""

    def add_user(self, text: str) -> None:
        self.write(Text(f"\nYou", style="bold cyan"))
        self.write(Text(text))

    def add_system(self, text: str) -> None:
        self.write(Text(f"\n{text}", style="dim"))

    def add_error(self, text: str) -> None:
        self.write(Text(f"\n✗ {text}", style="bold red"))

    def add_assistant_markdown(self, text: str) -> None:
        self.write(Text("\nClaude", style="bold magenta"))
        self.write(RichMarkdown(text))


class StatusBar(Static):
    def set_status(self, text: str, busy: bool = False) -> None:
        icon = "⠿ " if busy else "● "
        style = "yellow" if busy else "green"
        self.update(Text.assemble((icon, style), (text, "dim")))


# --------------------------------------------------------------------------- #
# The app
# --------------------------------------------------------------------------- #

class ClaudePreviewApp(App):
    """Split-screen Claude chat with live code preview."""

    TITLE = "claude-preview"
    SUB_TITLE = DEFAULT_MODEL

    CSS = """
    #main {
        height: 1fr;
    }
    #left {
        width: 65%;
        border: round $primary;
        border-title-align: left;
    }
    #right {
        width: 35%;
        border: round $secondary;
        border-title-align: left;
    }
    #chat-log {
        height: 1fr;
        padding: 0 1;
    }
    #chat-input {
        dock: bottom;
        margin: 0 1 1 1;
    }
    #status {
        dock: bottom;
        height: 1;
        padding: 0 2;
        background: $surface;
    }
    #file-tree {
        height: 1fr;
    }
    .preview-code {
        padding: 0 1;
    }
    TabbedContent {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("ctrl+r", "refresh_preview", "Refresh preview"),
        Binding("ctrl+l", "clear_log", "Clear log"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.workspace = Workspace()
        self.history: list[dict] = []
        self.provider: LLMProvider | None = None
        self.provider_error: str | None = None
        try:
            self.provider = AnthropicProvider()
        except Exception as exc:  # missing key / missing package
            self.provider_error = str(exc)

    # ----------------------------------------------------------------- UI -- #

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main"):
            with Vertical(id="left") as left:
                left.border_title = "Chat"
                yield ChatLog(id="chat-log", wrap=True, markup=False)
                yield Input(
                    placeholder="Message Claude…  (/help for commands)",
                    id="chat-input",
                )
            with Vertical(id="right") as right:
                right.border_title = "Preview"
                with TabbedContent(id="preview-tabs"):
                    with TabPane("Files", id="tab-files"):
                        yield Tree("workspace", id="file-tree")
                    with TabPane("Output", id="tab-output"):
                        yield RichLog(id="output-log", wrap=True)
        yield StatusBar(id="status")
        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one(ChatLog)
        log.add_system("Welcome to claude-preview — Copilot-style chat with a live preview pane.")
        log.add_system("Code blocks Claude writes appear as tabs on the right. Type /help for commands.")
        if self.provider is None:
            log.add_error(
                "Not logged in. Quit (Ctrl+Q) and relaunch to open the Claude browser login,\n"
                "or run `ant auth login` / set ANTHROPIC_API_KEY, then restart.\n"
                f"  detail: {self.provider_error}"
            )
            self.status("Not logged in — chat disabled")
        else:
            self.status(f"Ready — {self.provider.model}")
        self.query_one("#chat-input", Input).focus()
        self.refresh_file_tree()

    def status(self, text: str, busy: bool = False) -> None:
        self.query_one(StatusBar).set_status(text, busy)

    # ------------------------------------------------------------- actions -- #

    def action_refresh_preview(self) -> None:
        self.refresh_all_previews()
        self.status("Preview refreshed")

    def action_clear_log(self) -> None:
        self.query_one(ChatLog).clear()
        self.status("Chat log cleared")

    # --------------------------------------------------------------- input -- #

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text.startswith("/"):
            await self.handle_command(text)
        else:
            self.send_message(text)

    # ------------------------------------------------------------ commands -- #

    async def handle_command(self, raw: str) -> None:
        log = self.query_one(ChatLog)
        parts = raw.split(maxsplit=1)
        cmd, arg = parts[0].lower(), (parts[1].strip() if len(parts) > 1 else "")

        if cmd == "/help":
            log.write(Text.from_markup("\n" + HELP_TEXT))
        elif cmd == "/files":
            if not self.workspace.files:
                log.add_system("No generated files yet.")
            else:
                for f in self.workspace.files.values():
                    mark = "✔ on disk" if f.applied else "in memory"
                    log.add_system(f"  {f.name}  ({f.language}, {len(f.content)} chars, {mark})")
        elif cmd == "/apply":
            self.cmd_apply(arg)
        elif cmd == "/run":
            self.cmd_run(arg)
        elif cmd == "/preview":
            self.cmd_preview(arg)
        elif cmd == "/load":
            self.cmd_load(arg)
        elif cmd == "/clear":
            self.history.clear()
            log.add_system("Conversation history cleared (generated files kept).")
        elif cmd == "/model":
            if self.provider is None:
                log.add_error("No provider available.")
            elif arg:
                self.provider.model = arg
                self.sub_title = arg
                log.add_system(f"Model switched to {arg}")
            else:
                log.add_system(f"Current model: {self.provider.model}")
        else:
            log.add_error(f"Unknown command: {cmd}  (try /help)")

    def cmd_apply(self, arg: str) -> None:
        log = self.query_one(ChatLog)
        if not arg:
            log.add_error("Usage: /apply <filename>  or  /apply all")
            return
        targets = (
            list(self.workspace.files.values())
            if arg == "all"
            else [self.workspace.files[arg]] if arg in self.workspace.files else None
        )
        if not targets:
            log.add_error(f"No generated file named '{arg}'. Try /files.")
            return
        for f in targets:
            try:
                path = Path(f.name)
                if path.parent != Path("."):
                    path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f.content, encoding="utf-8")
                f.applied = True
                log.add_system(f"✔ wrote {path.resolve()}")
            except OSError as exc:
                log.add_error(f"Failed to write {f.name}: {exc}")
        self.refresh_file_tree()

    def cmd_run(self, arg: str) -> None:
        log = self.query_one(ChatLog)
        if not arg:
            log.add_error("Usage: /run <filename>")
            return
        f = self.workspace.files.get(arg)
        if f is None and not Path(arg).exists():
            log.add_error(f"No file named '{arg}'.")
            return
        # Make sure it exists on disk, then run it.
        if f is not None and not f.applied:
            self.cmd_apply(arg)
        self.run_script(arg)

    def cmd_preview(self, arg: str) -> None:
        log = self.query_one(ChatLog)
        if arg not in self.workspace.files:
            log.add_error(f"No generated file named '{arg}'. Try /files.")
            return
        tabs = self.query_one("#preview-tabs", TabbedContent)
        tabs.active = slug(arg)

    def cmd_load(self, arg: str) -> None:
        log = self.query_one(ChatLog)
        if not arg:
            log.add_error("Usage: /load <path>")
            return
        path = Path(arg)
        if not path.is_file():
            log.add_error(f"File not found: {arg}")
            return
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            log.add_error(f"Could not read {arg}: {exc}")
            return
        lang = EXT_FOR_LANG.get(path.suffix.lstrip("."), "text")
        self.history.append(
            {
                "role": "user",
                "content": f"Here is the current content of `{path.name}`:\n\n```{lang} {path.name}\n{content}\n```",
            }
        )
        gf = self.workspace.files.setdefault(
            path.name, GeneratedFile(path.name, lang, content, applied=True)
        )
        gf.content, gf.language = content, lang
        self.update_preview_tab(path.name)
        self.refresh_file_tree()
        log.add_system(f"Loaded {path.name} into the conversation ({len(content)} chars).")

    # ------------------------------------------------------------- preview -- #

    def update_preview_tab(self, name: str) -> None:
        f = self.workspace.files[name]
        tabs = self.query_one("#preview-tabs", TabbedContent)
        pane_id = slug(name)

        if f.language in ("markdown", "md"):
            renderable = RichMarkdown(f.content)
        else:
            renderable = Syntax(
                f.content,
                f.language or "text",
                line_numbers=True,
                word_wrap=True,
                indent_guides=True,
                theme="ansi_dark",
            )

        try:
            pane = tabs.get_pane(pane_id)
            pane.query_one(Static).update(renderable)
        except Exception:
            body = VerticalScroll(Static(renderable, classes="preview-code"))
            tabs.add_pane(TabPane(name, body, id=pane_id))

    def refresh_all_previews(self) -> None:
        for name in self.workspace.files:
            self.update_preview_tab(name)
        self.refresh_file_tree()

    def refresh_file_tree(self) -> None:
        tree = self.query_one("#file-tree", Tree)
        tree.clear()
        tree.root.expand()
        for f in self.workspace.files.values():
            label = f"{'✔ ' if f.applied else ''}{f.name}  [dim]({f.language})[/dim]"
            tree.root.add_leaf(label, data=f.name)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        name = event.node.data
        if name in self.workspace.files:
            self.cmd_preview(name)

    # ----------------------------------------------------------- streaming -- #

    def send_message(self, text: str) -> None:
        log = self.query_one(ChatLog)
        if self.provider is None:
            log.add_error("Chat disabled — set ANTHROPIC_API_KEY and restart.")
            return
        log.add_user(text)
        self.history.append({"role": "user", "content": text})
        self.stream_response()

    @work(exclusive=True)
    async def stream_response(self) -> None:
        log = self.query_one(ChatLog)
        assert self.provider is not None
        self.status("Claude is thinking…", busy=True)
        accumulated = ""
        chunk_count = 0
        try:
            async for chunk in self.provider.stream_chat(SYSTEM_PROMPT, self.history):
                accumulated += chunk
                chunk_count += 1
                # Hot-reload the preview as code streams in (throttled).
                if chunk_count % 8 == 0:
                    self.apply_extracted(accumulated)
                    self.status(f"Streaming… {len(accumulated)} chars", busy=True)
        except Exception as exc:
            self.status("Error")
            log.add_error(f"API error: {exc}")
            # Drop the failed user turn so history stays valid for a retry.
            if self.history and self.history[-1]["role"] == "user":
                self.history.pop()
            return

        self.history.append({"role": "assistant", "content": accumulated})
        log.add_assistant_markdown(accumulated)
        touched = self.apply_extracted(accumulated)
        if touched:
            log.add_system(
                f"Preview updated: {', '.join(touched)} — use /apply <file> to save."
            )
        self.status(f"Ready — {self.provider.model}")

    def apply_extracted(self, text: str) -> list[str]:
        touched = self.workspace.update_from_text(text)
        for name in touched:
            self.update_preview_tab(name)
        if touched:
            self.refresh_file_tree()
        return touched

    # ---------------------------------------------------------------- run -- #

    @work(exclusive=False, thread=True)
    def run_script(self, name: str) -> None:
        path = Path(name)
        if path.suffix == ".py":
            cmd = [sys.executable, str(path)]
        elif path.suffix in (".sh",):
            cmd = ["bash", str(path)]
        else:
            self.call_from_thread(
                self.query_one(ChatLog).add_error,
                f"Don't know how to run {name} (only .py and .sh).",
            )
            return
        self.call_from_thread(self.status, f"Running {name}…", True)
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60
            )
            out = proc.stdout or ""
            err = proc.stderr or ""
            code = proc.returncode
        except subprocess.TimeoutExpired:
            out, err, code = "", "Timed out after 60s", -1
        except OSError as exc:
            out, err, code = "", str(exc), -1

        def show() -> None:
            output_log = self.query_one("#output-log", RichLog)
            output_log.write(Text(f"\n$ {' '.join(cmd)}", style="bold"))
            if out:
                output_log.write(Text(out))
            if err:
                output_log.write(Text(err, style="red"))
            output_log.write(Text(f"[exit {code}]", style="dim"))
            self.query_one("#preview-tabs", TabbedContent).active = "tab-output"
            self.status(f"{name} exited with code {code}")

        self.call_from_thread(show)


# --------------------------------------------------------------------------- #
# Login bootstrap — browser OAuth via the `ant` CLI, saved profile thereafter
# --------------------------------------------------------------------------- #

def _anthropic_config_dirs() -> list[Path]:
    override = os.environ.get("ANTHROPIC_CONFIG_DIR")
    if override:
        return [Path(override)]
    dirs = []
    if os.environ.get("APPDATA"):  # Windows
        dirs.append(Path(os.environ["APPDATA"]) / "Anthropic")
    dirs.append(Path.home() / ".config" / "anthropic")  # Linux/macOS
    return dirs


def has_credentials() -> bool:
    """True if the SDK will find something: env key/token or a saved login profile."""
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    for cfg in _anthropic_config_dirs():
        creds = cfg / "credentials"
        if creds.is_dir() and any(creds.glob("*.json")):
            return True
    return False


def ensure_login() -> None:
    """First launch: open the Claude browser login and save the profile.

    The saved profile is picked up automatically by the anthropic SDK on every
    future launch, so this only happens once.
    """
    if has_credentials():
        return
    ant = shutil.which("ant")
    if ant:
        print("No Claude credentials found — opening the Claude login in your browser…")
        print("(complete the login there; your session will be saved for next time)\n")
        try:
            result = subprocess.run([ant, "auth", "login"])
            if result.returncode == 0 and has_credentials():
                print("\n✔ Logged in. Starting claude-preview…")
                return
        except OSError as exc:
            print(f"Could not run ant auth login: {exc}", file=sys.stderr)
        print(
            "\nLogin didn't complete — the app will start with chat disabled.\n"
            "Run `ant auth login` manually, then restart.",
            file=sys.stderr,
        )
    else:
        print(
            "No Claude credentials found, and the `ant` CLI (which provides the\n"
            "browser login) isn't installed. Two ways to log in:\n"
            "  1. Install the Anthropic CLI from\n"
            "       https://github.com/anthropics/anthropic-cli/releases\n"
            "     then just relaunch — the login window opens automatically.\n"
            "  2. Or set an API key:  set ANTHROPIC_API_KEY=sk-ant-...\n"
            "\nStarting with chat disabled for now.",
            file=sys.stderr,
        )


def main() -> None:
    ensure_login()
    ClaudePreviewApp().run()


if __name__ == "__main__":
    main()
