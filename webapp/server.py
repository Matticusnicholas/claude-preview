#!/usr/bin/env python3
"""claude-preview web — a local, Cursor-style IDE in your browser.

FastAPI backend that drives the Claude Agent SDK (your Claude Code login) and
serves a Monaco-based editor UI. The agent edits files on disk; the frontend
shows live diffs with accept/reject, an integrated terminal, and a chat composer.

Run:  python webapp/server.py [optional/start/folder]
Then open http://127.0.0.1:8765
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    PermissionResultAllow,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

BASE = Path(__file__).parent
STATIC = BASE / "static"
HOST = os.environ.get("CLAUDE_PREVIEW_HOST", "127.0.0.1")
PORT = int(os.environ.get("CLAUDE_PREVIEW_PORT", "8765"))
MODEL = os.environ.get("CLAUDE_PREVIEW_MODEL")
PERMISSION_MODE = os.environ.get("CLAUDE_PREVIEW_PERMISSION", "acceptEdits")

ALLOWED_TOOLS = ["Read", "Write", "Edit", "MultiEdit", "Bash", "Glob", "Grep"]
EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".idea", ".vscode"}
TEXT_LIMIT = 2_000_000  # don't try to preview files larger than ~2MB

CURSOR_SYSTEM_PROMPT = """\
You are the AI coding assistant inside claude-preview, a local IDE modeled on
Cursor. You operate directly on the user's open project through tools (read,
write, edit, run shell commands). Behave like Cursor's Composer/Agent:

OUTPUT STYLE
- Be concise and skimmable. The user sees your file changes as diffs and your
  commands' output in the UI, so do NOT paste whole files or long code blocks
  into the chat. A short sentence of intent before acting, and a brief summary
  after, is the right amount.
- Use tight, plain language. Reference code as `path:line` so the user can jump
  to it. Explain only non-obvious decisions.

HOW YOU WORK
- Make changes by editing the actual files with the edit tools — never by
  pasting the new code in chat for the user to copy. The user reviews each
  change as a diff and accepts or rejects it in the UI.
- Prefer minimal, targeted edits. Don't rewrite a whole file when a small edit
  will do. Match the existing code style, naming, and structure.
- When a task needs commands (install deps, run tests, build), run them with the
  Bash tool and report the result briefly.
- Read before you edit: open the relevant files/symbols so your change fits the
  real code, not an assumption.
- For multi-step work, just proceed through the steps; don't stop to ask
  permission for routine edits — the user can reject anything. Ask only when the
  request is genuinely ambiguous or an action is destructive/irreversible.

Keep momentum: understand, edit, verify, summarize.
"""

LANG_BY_EXT = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript", ".ts": "typescript",
    ".tsx": "typescript", ".json": "json", ".html": "html", ".css": "css",
    ".scss": "scss", ".md": "markdown", ".markdown": "markdown", ".yaml": "yaml",
    ".yml": "yaml", ".toml": "toml", ".sh": "shell", ".bash": "shell", ".rs": "rust",
    ".go": "go", ".java": "java", ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp",
    ".cs": "csharp", ".php": "php", ".rb": "ruby", ".sql": "sql", ".xml": "xml",
    ".vue": "vue", ".svelte": "html", ".txt": "plaintext", ".bat": "bat",
}


def lang_for(path: Path) -> str:
    return LANG_BY_EXT.get(path.suffix.lower(), "plaintext")


# --------------------------------------------------------------------------- #
# Session: one persistent agent + the pending-change snapshots
# --------------------------------------------------------------------------- #

class Session:
    def __init__(self, workspace: str) -> None:
        self.workspace = Path(workspace).resolve()
        self.client: ClaudeSDKClient | None = None
        self.snapshots: dict[str, str | None] = {}  # abspath -> original text (None = new file)
        self.lock = asyncio.Lock()

    def options(self) -> ClaudeAgentOptions:
        async def allow_all(*_a, **_k):
            return PermissionResultAllow()

        async def pre_edit(input_data, _tool_use_id, _ctx):
            ti = (input_data or {}).get("tool_input", {}) or {}
            fp = ti.get("file_path") or ti.get("notebook_path")
            if fp:
                p = Path(fp).resolve()
                key = str(p)
                if key not in self.snapshots:
                    try:
                        self.snapshots[key] = (
                            p.read_text(encoding="utf-8", errors="replace") if p.exists() else None
                        )
                    except Exception:
                        self.snapshots[key] = None
            return {}

        kwargs = dict(
            allowed_tools=ALLOWED_TOOLS,
            permission_mode=PERMISSION_MODE,
            cwd=str(self.workspace),
            system_prompt=CURSOR_SYSTEM_PROMPT,
            can_use_tool=allow_all,
            hooks={
                "PreToolUse": [
                    HookMatcher(matcher="Write|Edit|MultiEdit|NotebookEdit", hooks=[pre_edit])
                ]
            },
        )
        if MODEL:
            kwargs["model"] = MODEL
        return ClaudeAgentOptions(**kwargs)

    async def ensure_client(self) -> None:
        if self.client is None:
            self.client = ClaudeSDKClient(options=self.options())
            await self.client.connect()

    async def reset(self, workspace: str) -> None:
        if self.client is not None:
            try:
                await self.client.disconnect()
            except Exception:
                pass
        self.client = None
        self.snapshots = {}
        self.workspace = Path(workspace).resolve()

    def pending(self) -> list[dict]:
        items = []
        for key, original in self.snapshots.items():
            p = Path(key)
            current = None
            if p.exists():
                try:
                    current = p.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    current = None
            if current != original:
                items.append({
                    "path": key,
                    "rel": self.rel(key),
                    "status": "new" if original is None else ("deleted" if current is None else "modified"),
                })
        return items

    def rel(self, p: str) -> str:
        try:
            return str(Path(p).resolve().relative_to(self.workspace)).replace("\\", "/")
        except (ValueError, OSError):
            return p


SESSION = Session(sys.argv[1] if len(sys.argv) > 1 else os.getcwd())

app = FastAPI(title="claude-preview")


# --------------------------------------------------------------------------- #
# Static + index
# --------------------------------------------------------------------------- #

@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


# --------------------------------------------------------------------------- #
# Workspace / file REST API
# --------------------------------------------------------------------------- #

@app.get("/api/state")
async def state():
    return {"workspace": str(SESSION.workspace), "name": SESSION.workspace.name}


@app.get("/api/tree")
async def tree(path: str | None = None):
    base = Path(path).resolve() if path else SESSION.workspace
    if not base.is_dir():
        return JSONResponse({"error": "not a directory"}, status_code=400)
    dirs, files = [], []
    try:
        for entry in sorted(base.iterdir(), key=lambda e: e.name.lower()):
            if entry.name in IGNORE_DIRS or entry.name.startswith(".") and entry.is_dir():
                if entry.name in IGNORE_DIRS:
                    continue
            if entry.is_dir():
                if entry.name in IGNORE_DIRS:
                    continue
                dirs.append({"name": entry.name, "path": str(entry), "type": "dir"})
            else:
                files.append({"name": entry.name, "path": str(entry), "type": "file"})
    except PermissionError:
        return JSONResponse({"error": "permission denied"}, status_code=403)
    return {"path": str(base), "children": dirs + files}


@app.get("/api/file")
async def read_file(path: str):
    p = Path(path).resolve()
    if not p.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    if p.stat().st_size > TEXT_LIMIT:
        return JSONResponse({"error": "file too large to open"}, status_code=413)
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
    return {"path": str(p), "rel": SESSION.rel(str(p)), "language": lang_for(p), "content": content}


@app.post("/api/save")
async def save_file(payload: dict):
    p = Path(payload["path"]).resolve()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(payload.get("content", ""), encoding="utf-8")
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
    return {"ok": True}


@app.post("/api/open")
async def open_folder(payload: dict):
    path = payload.get("path")
    if not path or not Path(path).is_dir():
        return JSONResponse({"error": "not a directory"}, status_code=400)
    await SESSION.reset(path)
    return {"workspace": str(SESSION.workspace), "name": SESSION.workspace.name}


@app.post("/api/pick-folder")
async def pick_folder():
    """Native folder dialog (server runs locally, so this opens on the user's machine)."""
    def _pick() -> str | None:
        try:
            import tkinter as tk
            from tkinter import filedialog
        except Exception:
            return None
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(title="Open folder in claude-preview",
                                         initialdir=str(SESSION.workspace))
        root.destroy()
        return chosen or None

    chosen = await asyncio.to_thread(_pick)
    if not chosen:
        return {"cancelled": True}
    await SESSION.reset(chosen)
    return {"workspace": str(SESSION.workspace), "name": SESSION.workspace.name}


# --------------------------------------------------------------------------- #
# Pending changes: diff / accept / reject
# --------------------------------------------------------------------------- #

@app.get("/api/changes")
async def changes():
    return {"items": SESSION.pending()}


@app.get("/api/diff")
async def diff(path: str):
    key = str(Path(path).resolve())
    original = SESSION.snapshots.get(key)
    p = Path(key)
    current = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
    return {
        "path": key,
        "rel": SESSION.rel(key),
        "language": lang_for(p),
        "original": original or "",
        "current": current,
    }


@app.post("/api/accept")
async def accept(payload: dict):
    key = str(Path(payload["path"]).resolve())
    SESSION.snapshots.pop(key, None)  # finalize: keep current on disk
    return {"ok": True, "items": SESSION.pending()}


@app.post("/api/reject")
async def reject(payload: dict):
    key = str(Path(payload["path"]).resolve())
    original = SESSION.snapshots.pop(key, "__missing__")
    p = Path(key)
    try:
        if original is None:
            if p.exists():
                p.unlink()  # was a new file -> remove
        elif original != "__missing__":
            p.write_text(original, encoding="utf-8")  # restore original
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
    return {"ok": True, "items": SESSION.pending()}


@app.post("/api/accept-all")
async def accept_all():
    SESSION.snapshots.clear()
    return {"ok": True, "items": []}


@app.post("/api/reject-all")
async def reject_all():
    for key, original in list(SESSION.snapshots.items()):
        p = Path(key)
        try:
            if original is None:
                if p.exists():
                    p.unlink()
            else:
                p.write_text(original, encoding="utf-8")
        except Exception:
            pass
    SESSION.snapshots.clear()
    return {"ok": True, "items": []}


# --------------------------------------------------------------------------- #
# Agent chat over WebSocket
# --------------------------------------------------------------------------- #

@app.websocket("/ws/agent")
async def ws_agent(ws: WebSocket):
    await ws.accept()
    try:
        await SESSION.ensure_client()
    except Exception as exc:
        await ws.send_json({"type": "error", "message":
            f"Couldn't start the agent. Make sure Claude Code is installed and logged in "
            f"(claude setup-token). Detail: {exc}"})
        return

    try:
        while True:
            data = await ws.receive_json()
            kind = data.get("type")
            if kind == "chat":
                await run_turn(ws, data.get("text", ""))
            elif kind == "interrupt":
                try:
                    await SESSION.client.interrupt()  # type: ignore[union-attr]
                    await ws.send_json({"type": "info", "message": "Interrupted."})
                except Exception as exc:
                    await ws.send_json({"type": "error", "message": f"interrupt failed: {exc}"})
    except WebSocketDisconnect:
        pass


async def run_turn(ws: WebSocket, prompt: str) -> None:
    if not prompt.strip():
        return
    async with SESSION.lock:
        client = SESSION.client
        assert client is not None
        bash_calls: dict[str, str] = {}
        await ws.send_json({"type": "turn_start"})
        try:
            await client.query(prompt)
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            if block.text.strip():
                                await ws.send_json({"type": "assistant", "text": block.text})
                        elif isinstance(block, ThinkingBlock):
                            await ws.send_json({"type": "thinking"})
                        elif isinstance(block, ToolUseBlock):
                            await emit_tool_use(ws, block, bash_calls)
                elif isinstance(msg, UserMessage):
                    await emit_tool_results(ws, msg, bash_calls)
                elif isinstance(msg, ResultMessage):
                    await ws.send_json({"type": "result",
                                        "cost": getattr(msg, "total_cost_usd", None)})
        except Exception as exc:
            await ws.send_json({"type": "error", "message": f"agent error: {exc}"})
            return
        await ws.send_json({"type": "changes", "items": SESSION.pending()})
        await ws.send_json({"type": "turn_end"})


async def emit_tool_use(ws: WebSocket, block: ToolUseBlock, bash_calls: dict) -> None:
    name = block.name
    inp = block.input or {}
    if name == "Bash":
        cmd = str(inp.get("command", ""))
        bash_calls[block.id] = cmd
        await ws.send_json({"type": "tool", "tool": "Bash", "summary": cmd})
    elif name in EDIT_TOOLS:
        fp = str(inp.get("file_path", inp.get("notebook_path", "")))
        await ws.send_json({"type": "edit", "path": fp, "rel": SESSION.rel(fp),
                            "op": "write" if name == "Write" else "edit"})
    elif name in ("Read", "Glob", "Grep"):
        target = inp.get("file_path") or inp.get("pattern") or inp.get("path") or ""
        await ws.send_json({"type": "tool", "tool": name, "summary": str(target)})
    else:
        await ws.send_json({"type": "tool", "tool": name, "summary": ""})


async def emit_tool_results(ws: WebSocket, msg: UserMessage, bash_calls: dict) -> None:
    content = msg.content
    if not isinstance(content, list):
        return
    for block in content:
        if isinstance(block, ToolResultBlock) and block.tool_use_id in bash_calls:
            await ws.send_json({
                "type": "terminal",
                "command": bash_calls[block.tool_use_id],
                "output": _result_text(block.content),
            })


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


# --------------------------------------------------------------------------- #
# Integrated terminal over WebSocket (line-based command runner)
# --------------------------------------------------------------------------- #

@app.websocket("/ws/term")
async def ws_term(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            data = await ws.receive_json()
            cmd = data.get("cmd", "")
            if not cmd.strip():
                continue
            await ws.send_json({"type": "started", "cmd": cmd})
            try:
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    cwd=str(SESSION.workspace),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                assert proc.stdout is not None
                async for raw in proc.stdout:
                    await ws.send_json({"type": "out", "data": raw.decode("utf-8", "replace")})
                code = await proc.wait()
                await ws.send_json({"type": "exit", "code": code})
            except Exception as exc:
                await ws.send_json({"type": "out", "data": f"[error: {exc}]\n"})
                await ws.send_json({"type": "exit", "code": -1})
    except WebSocketDisconnect:
        pass


def main() -> None:
    print(f"\n  claude-preview web — open  http://{HOST}:{PORT}\n")
    print(f"  workspace: {SESSION.workspace}\n")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
