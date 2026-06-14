#!/usr/bin/env bash
# claude-preview launcher (macOS/Linux): set up if needed, save token once, run.
# Usage:  ./start.sh [optional/start/folder]
set -e
cd "$(dirname "$0")"

# --- Python ---
command -v python3 >/dev/null 2>&1 || { echo "[claude-preview] Python 3.10+ required: https://www.python.org/downloads/"; exit 1; }

# --- Python dependencies ---
if ! python3 -c "import textual, rich, claude_agent_sdk" >/dev/null 2>&1; then
    echo "[claude-preview] Installing Python dependencies..."
    python3 -m pip install --disable-pip-version-check -r requirements.txt
fi

# --- Claude Code CLI ---
if ! command -v claude >/dev/null 2>&1; then
    if command -v npm >/dev/null 2>&1; then
        echo "[claude-preview] Installing Claude Code..."
        npm install -g @anthropic-ai/claude-code
    else
        echo "[claude-preview] Claude Code required and npm not found. Install Node.js: https://nodejs.org"
        exit 1
    fi
fi

# --- Auth token (saved locally, asked only once) ---
TOKFILE="${HOME}/.config/claude-preview/auth.token"
mkdir -p "$(dirname "$TOKFILE")"
[ -s "$TOKFILE" ] && export CLAUDE_CODE_OAUTH_TOKEN="$(cat "$TOKFILE")"

if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
    echo
    echo "First-time setup - one-time Claude login (uses your subscription)."
    echo "Token will be saved to: $TOKFILE"
    echo
    read -r -p "Do you already have a Claude auth token? [y/N] " have
    case "$have" in
        y|Y) ;;
        *) echo "Generating one - sign in in the browser, then copy the token it prints."; claude setup-token ;;
    esac
    read -r -p "Paste your Claude auth token here: " CLAUDE_CODE_OAUTH_TOKEN
    [ -n "$CLAUDE_CODE_OAUTH_TOKEN" ] || { echo "[claude-preview] No token entered - exiting."; exit 1; }
    printf '%s' "$CLAUDE_CODE_OAUTH_TOKEN" > "$TOKFILE"
    chmod 600 "$TOKFILE"
    export CLAUDE_CODE_OAUTH_TOKEN
    echo "[claude-preview] Token saved - you won't be asked again."
fi

python3 claude_preview.py "$@"
