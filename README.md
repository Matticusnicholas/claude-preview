# claude-preview

> **Copilot's side panel, but it lives in your terminal — and the AI is Claude.**

---

## 🎯 The pitch

**The problem.** AI chat in the terminal is a wall of scrolling text. Claude writes you a beautiful file… and it disappears off the top of your screen while you keep talking. You copy-paste code blocks out of chat logs like it's 2022.

**The product.** `claude-preview` splits your terminal: a live Claude conversation on the left, and a **hot-reloading preview pane** on the right that renders every file Claude writes — syntax-highlighted, tabbed, updated *while the response is still streaming*. When you like what you see: `/apply` writes it to disk, `/run` executes it and pipes the output into its own tab. You never leave the keyboard, you never leave the terminal.

**Why it wins.**

| | Plain CLI chat | Web chat + copy/paste | **claude-preview** |
|---|---|---|---|
| See code while chatting | ❌ scrolls away | ⚠️ alt-tab | ✅ always visible |
| Live updates mid-stream | ❌ | ❌ | ✅ hot-reload |
| One keystroke to save / run | ❌ | ❌ | ✅ `/apply`, `/run` |
| Works over SSH | ✅ | ❌ | ✅ |
| Zero-friction login | ⚠️ paste a key | — | ✅ one-time browser auth |

**The experience.** Open it → a Claude login pops in your browser (once, ever) → ask for code → watch the right pane fill in token by token → apply, run, iterate. That's the whole learning curve.

**Built on a modern stack.** [Textual](https://textual.textualize.io/) for the reactive TUI, [Rich](https://rich.readthedocs.io/) for rendering, the official [`anthropic`](https://github.com/anthropics/anthropic-sdk-python) SDK with streaming + adaptive thinking — and a pluggable provider layer, so OpenAI/Grok/local models are one small class away.

---

```
┌ Chat ──────────────────────────────┐┌ Preview ──────────────────┐
│ You                                ││ Files │ Output │ app.py   │
│ build me a flask hello world       ││  1 from flask import Flask│
│                                    ││  2                        │
│ Claude                             ││  3 app = Flask(__name__)  │
│ Here's a minimal Flask app…        ││  4                        │
│                                    ││  5 @app.route("/")        │
│ Preview updated: app.py            ││  6 def index():           │
│ > /apply app.py_                   ││  7     return "hello"    │
└────────────────────────────────────┘└───────────────────────────┘
 ● Ready — claude-opus-4-8
 Ctrl+R Refresh  Ctrl+L Clear log  Ctrl+Q Quit
```

## Install

Python 3.10+.

```sh
pip install -r requirements.txt
# or, to get the `claude-preview` command on your PATH:
pip install -e .
```

## Logging in

On first launch the app looks for Claude credentials. If none are found, it opens
the **Claude login in your browser** (via Anthropic's `ant` CLI) and saves your
session — you only do this once; later launches reuse it automatically.

The browser login needs the small `ant` CLI installed once:
download it from <https://github.com/anthropics/anthropic-cli/releases>
(or `brew install anthropics/tap/ant` on macOS).

Prefer a key instead? Skip `ant` and set one:

```sh
# PowerShell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
# bash/zsh
export ANTHROPIC_API_KEY="sk-ant-..."
```

## Run

```sh
python claude_preview.py
# or
python -m claude_preview
# or (after pip install -e .)
claude-preview
```

## How it works

Type a message and Claude streams its reply into the chat pane. Any fenced code block it produces (` ```python app.py `) is extracted **while it streams** and rendered as a syntax-highlighted tab in the preview pane — one tab per filename, updated in place when Claude revises a file. Markdown blocks render as formatted markdown. The **Files** tab lists everything generated (click a file to jump to its tab), and **Output** shows the stdout/stderr of scripts you run.

Nothing touches disk until you `/apply` it.

## Commands

| Command | Effect |
|---|---|
| `/apply <file>` | Write a generated file to disk (`/apply all` for everything) |
| `/run <file>` | Run a `.py` or `.sh` file (applies it first if needed); output goes to the Output tab |
| `/preview <file>` | Focus that file's preview tab |
| `/load <path>` | Read a file from disk into the conversation and the preview pane |
| `/files` | List generated files and their on-disk status |
| `/clear` | Clear conversation history (keeps generated files) |
| `/model [name]` | Show or switch the model |
| `/help` | Show help |

## Keyboard shortcuts

| Key | Action |
|---|---|
| `Tab` / `Shift+Tab` | Cycle focus between panes |
| `Ctrl+R` | Refresh the preview pane |
| `Ctrl+L` | Clear the chat log |
| `Ctrl+Q` | Quit |

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required for chat |
| `CLAUDE_PREVIEW_MODEL` | `claude-opus-4-8` | Model ID (switchable at runtime with `/model`) |
| `CLAUDE_PREVIEW_MAX_TOKENS` | `32000` | Max output tokens per response |

## Swapping providers

The Anthropic client is isolated behind a tiny `LLMProvider` protocol in `claude_preview.py` — anything with a `model` attribute and an async `stream_chat(system, messages)` generator works. Implement one for OpenAI/Grok/Ollama and pass it to `ClaudePreviewApp`.
