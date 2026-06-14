# claude-preview

> **Cursor, but in your terminal — and the agent runs on your own Claude Code subscription.**

---

## 🎯 The pitch

**The problem.** Cursor and Copilot are great, but they're heavy GUI apps tied to their own billing. If you already pay for Claude (Pro / Max), you can't point those editors at it. And terminal AI chat just scrolls code off the screen — you copy-paste like it's 2022.

**The product.** `claude-preview` is a split-screen terminal IDE. **Pick a folder**, then chat with Claude on the left while the right pane shows a live file explorer, the **diff of every change the agent makes**, and command output. The agent reads, writes, edits, and runs code *directly in your folder* — you watch it happen and the files update on disk in real time.

**The engine.** It runs on the **Claude Agent SDK**, which uses your local **Claude Code login** — your Pro/Max subscription, no API key, no per-token bill. Each person runs it on their own machine with their own Claude session.

**Why it's different.**

| | Web chat + copy/paste | Cursor / Copilot | **claude-preview** |
|---|---|---|---|
| Edits real files for you | ❌ | ✅ | ✅ |
| Live diffs + command output | ❌ | ✅ | ✅ |
| Runs in the terminal / over SSH | ❌ | ❌ | ✅ |
| Uses your Claude **subscription** | ❌ | ❌ | ✅ |
| Zero per-token API bill | ❌ | ❌ | ✅ |
| Pick any folder to work in | ⚠️ | ✅ | ✅ (native picker) |

**The experience.** Launch → `Ctrl+O`, pick a project folder → "add a dark mode toggle" → watch Claude edit the files, see the red/green diffs, run the tests, all without leaving the terminal.

Built with [Textual](https://textual.textualize.io/) (reactive TUI), [Rich](https://rich.readthedocs.io/) (rendering), and the [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview).

---

## Two ways to run it

| | What it is |
|---|---|
| 🖥️ **Web IDE** (`start-web.bat`) | A **Cursor-style editor in your browser** — file tree, Monaco code editor with tabs, AI chat composer, inline diffs with **accept/reject**, and an integrated terminal. This is the main experience (and the base for the upcoming Electron app). |
| ⌨️ **Terminal app** (`start.bat`) | The same agent in a split-screen **TUI** — chat + live preview, no browser. Great over SSH. |

Both run the same engine: the Claude Agent SDK on your local Claude Code login.

## Quick start (one click)

Clone the repo, then:

- **Web IDE — Windows:** double-click **`start-web.bat`** (opens `http://127.0.0.1:8765`)
- **Terminal app — Windows:** double-click **`start.bat`**
- **macOS / Linux (terminal app):** `./start.sh`  ·  **(web)** `python webapp/server.py`

The launcher installs everything it needs (Python deps, and Claude Code if you
have Node.js), then asks for your **Claude auth token once** and saves it
locally — every run after that goes straight into the app. To get a token it can
generate one for you (`claude setup-token`, which opens a browser and signs you
in with your Claude subscription), or you can paste one you already have.

The token is stored at `%LOCALAPPDATA%\claude-preview\auth.token` (Windows) or
`~/.config/claude-preview/auth.token` (macOS/Linux) — outside the repo, so it is
never committed or shared.

### The Web IDE

Once it's open in your browser:

- **Open folder** (top bar) → pick the project you want to work in (native dialog).
- **Explorer** (left) → click any file to open it in the Monaco editor; edit and `Ctrl+S` to save.
- **Chat** (right) → ask Claude to build or change things. It edits the real files; you see live activity.
- **Review changes** (top of chat) → every edit appears with a **badge** (new/modified). Click a file to see the **side-by-side diff**, then **Accept** (keep) or **Reject** (revert). Accept-all / Reject-all too.
- **Terminal** (bottom) → run commands in the workspace; the agent's commands stream here as well.

Eventually this ships as a one-click **Electron** desktop app; the architecture (local FastAPI backend + browser UI) is already set up for it.

## Manual install

Prefer to do it by hand? Python 3.10+ and **Claude Code**:

```sh
# 1. Claude Code — the agent runtime + your login
npm install -g @anthropic-ai/claude-code
claude setup-token        # one-time; prints a token tied to your subscription

# 2. This app
pip install -r requirements.txt        # or: pip install -e .
```

Set the token for your shell (or just use `start.bat`/`start.sh`, which do this
for you):

```sh
# PowerShell
$env:CLAUDE_CODE_OAUTH_TOKEN = "sk-ant-oat..."
# bash/zsh
export CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat..."
```

(If you're already logged in via `claude /login`, the app reuses that session and
no token is needed at all.)

## Run

```sh
python claude_preview.py                 # starts in the current folder
python claude_preview.py C:\path\to\proj # start in a specific folder
# or, after pip install -e .:
claude-preview
```

Then press **Ctrl+O** (or the *Open folder* button) to choose the project you want to work in.

## Using it

- **Chat** on the left. Ask for features, fixes, refactors, explanations.
- The agent works in your folder — every read/edit/write/command shows as activity in the chat.
- **Explorer** tab: browse the real folder; click any file to preview it (syntax-highlighted).
- **Changes** tab: red/green diffs of everything the agent edited this session.
- **Output** tab: stdout/stderr of commands the agent ran.
- Changes land on disk immediately — review them, or `git diff` / undo as you normally would.

## Keyboard shortcuts

| Key | Action |
|---|---|
| `Ctrl+O` | Open a folder (native picker) |
| `Ctrl+R` | Reload the file tree + open previews |
| `Ctrl+G` | Stop / interrupt the agent |
| `Ctrl+L` | Clear the chat log |
| `Ctrl+Q` | Quit |
| `Tab` | Cycle focus between panes |

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `CLAUDE_PREVIEW_MODEL` | Claude Code's default | Override the model (e.g. `claude-opus-4-8`) |
| `CLAUDE_PREVIEW_PERMISSION` | `acceptEdits` | Agent permission mode: `acceptEdits`, `bypassPermissions`, `default`, or `plan` |

## A note on accounts

This uses **your own** Claude Code login. Anthropic doesn't allow a third-party app to sign other people in on *your* subscription — so this is open-sourced for everyone to run locally on **their own** Claude session. Clone it, log into Claude Code, and go.

## Safety

The agent can edit files and run commands in the folder you select. Point it at a project under version control (so you can review/revert), and read the Changes tab. Use `CLAUDE_PREVIEW_PERMISSION=plan` if you want it to propose changes without applying them.
