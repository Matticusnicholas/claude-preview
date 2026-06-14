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

## Install

Python 3.10+ and **Claude Code** (which provides the engine + login):

```sh
# 1. Claude Code — the agent runtime and your login
npm install -g @anthropic-ai/claude-code
claude            # then run /login once to sign in with your Claude subscription

# 2. This app
pip install -r requirements.txt
# or, for the `claude-preview` command on your PATH:
pip install -e .
```

That's the whole setup — your Claude Code login is reused automatically, so there's no API key to manage.

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
