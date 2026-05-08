#!/usr/bin/env bash
# Mnemo one-click installer for macOS/Linux.
#
# Acknowledgement: the installer structure intentionally adapts safe patterns
# from NousResearch Hermes Agent's scripts/install.sh, especially clearing
# inherited Python environment variables, using an isolated venv, and linking a
# stable CLI command. This script is Mnemo-specific and does not copy Hermes'
# platform setup flow.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/Chriskuei/Mnemo/main/scripts/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/Chriskuei/Mnemo/main/scripts/install.sh | bash -s -- --skip-setup

set -euo pipefail

REPO_URL="${MNEMO_REPO_URL:-https://github.com/Chriskuei/Mnemo.git}"
BRANCH="${MNEMO_BRANCH:-main}"
STATE_DIR="${MNEMO_STATE_DIR:-$HOME/.mnemo}"
INSTALL_DIR="${MNEMO_INSTALL_DIR:-$STATE_DIR/mnemo}"
BIN_DIR="${MNEMO_BIN_DIR:-$HOME/.local/bin}"
RUN_SETUP=true
INSTALL_DIR_EXPLICIT=false

if [ -n "${PYTHONPATH:-}" ]; then
  echo "Ignoring inherited PYTHONPATH during install"
  unset PYTHONPATH
fi
if [ -n "${PYTHONHOME:-}" ]; then
  echo "Ignoring inherited PYTHONHOME during install"
  unset PYTHONHOME
fi

usage() {
  cat <<'EOF'
Mnemo Installer

Usage:
  install.sh [OPTIONS]

Options:
  --repo URL       Git repository URL (default: https://github.com/Chriskuei/Mnemo.git)
  --branch NAME    Git branch to install (default: main)
  --dir PATH       Install checkout directory (default: ~/.mnemo/mnemo)
  --state-dir PATH Runtime state directory (default: ~/.mnemo)
  --bin-dir PATH   Command link directory (default: ~/.local/bin)
  --skip-setup     Skip post-install setup hints
  -h, --help       Show this help

After installing:
  mnemo --version
  mnemo web --state-dir ~/.mnemo
  mnemo channels feishu serve --state-dir ~/.mnemo --host 0.0.0.0 --port 8771
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo)
      REPO_URL="$2"
      shift 2
      ;;
    --branch)
      BRANCH="$2"
      shift 2
      ;;
    --dir)
      INSTALL_DIR="$2"
      INSTALL_DIR_EXPLICIT=true
      shift 2
      ;;
    --state-dir)
      STATE_DIR="$2"
      shift 2
      ;;
    --bin-dir)
      BIN_DIR="$2"
      shift 2
      ;;
    --skip-setup)
      RUN_SETUP=false
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [ "$INSTALL_DIR_EXPLICIT" = false ] && [ -z "${MNEMO_INSTALL_DIR:-}" ]; then
  INSTALL_DIR="$STATE_DIR/mnemo"
fi

log() {
  printf '→ %s\n' "$1"
}

ok() {
  printf '✓ %s\n' "$1"
}

find_python() {
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
      then
        command -v "$candidate"
        return 0
      fi
    fi
  done
  echo "Python 3.11+ is required" >&2
  return 1
}

PYTHON_BIN="$(find_python)"

mkdir -p "$STATE_DIR"
if [ -d "$INSTALL_DIR/.git" ]; then
  log "Updating existing checkout at $INSTALL_DIR"
  git -C "$INSTALL_DIR" fetch --depth 1 origin "$BRANCH"
  git -C "$INSTALL_DIR" checkout -B "$BRANCH" "origin/$BRANCH"
else
  log "Cloning Mnemo into $INSTALL_DIR"
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

log "Creating virtual environment"
"$PYTHON_BIN" -m venv "$INSTALL_DIR/venv"

log "Installing Mnemo"
"$INSTALL_DIR/venv/bin/python" -m pip install --upgrade pip setuptools wheel >/dev/null
"$INSTALL_DIR/venv/bin/python" -m pip install -e "$INSTALL_DIR"

mkdir -p "$BIN_DIR"
ln -sf "$INSTALL_DIR/venv/bin/mnemo" "$BIN_DIR/mnemo"
ok "mnemo linked at $BIN_DIR/mnemo"

if ! command -v mnemo >/dev/null 2>&1; then
  case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
      echo "Add this to your shell profile if mnemo is not found:"
      echo "  export PATH=\"$BIN_DIR:\$PATH\""
      ;;
  esac
fi

"$INSTALL_DIR/venv/bin/mnemo" --version

if [ "$RUN_SETUP" = true ]; then
  cat <<EOF

Next:
  1. Start the web UI:
     $BIN_DIR/mnemo web --state-dir "$STATE_DIR"

  2. Connect Feishu/Lark via webhook:
     export FEISHU_APP_ID=cli_xxx
     export FEISHU_APP_SECRET=...
     export FEISHU_VERIFICATION_TOKEN=...
     $BIN_DIR/mnemo channels feishu serve --state-dir "$STATE_DIR" --host 0.0.0.0 --port 8771

  Feishu webhook path:
     /feishu/webhook
EOF
fi

ok "Mnemo install complete"
