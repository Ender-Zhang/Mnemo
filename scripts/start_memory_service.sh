#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage: bash scripts/start_memory_service.sh [options]

Starts the local Mnemo Memory HTTP API and WebUI.

Options:
  --state-dir DIR   Memory state directory. Default: MNEMO_MEMORY_STATE_DIR or .mnemo-memory
  --host HOST       HTTP bind host. Default: MNEMO_MEMORY_HOST or 127.0.0.1
  --port PORT       HTTP port. Default: MNEMO_MEMORY_PORT or 8765
  --env-file FILE   Shell-compatible env file. Default: MNEMO_MEMORY_ENV_FILE or .env
  --dry-run         Print the resolved command without starting the server.
  -h, --help        Show this help.

Model provider environment:
  MNEMO_MEMORY_BASE_URL=https://api.openai.com/v1
  MNEMO_MEMORY_MODEL=gpt-4.1-mini
  MNEMO_MEMORY_API_KEY=replace-me

The service itself is open on the configured host/port. Keep the default
127.0.0.1 bind unless you intentionally trust the network.
EOF
}

arg_state_dir=""
arg_host=""
arg_port=""
env_file="${MNEMO_MEMORY_ENV_FILE:-$ROOT_DIR/.env}"
dry_run=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --state-dir)
      arg_state_dir="${2:?missing value for --state-dir}"
      shift 2
      ;;
    --host)
      arg_host="${2:?missing value for --host}"
      shift 2
      ;;
    --port)
      arg_port="${2:?missing value for --port}"
      shift 2
      ;;
    --env-file)
      env_file="${2:?missing value for --env-file}"
      shift 2
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -f "$env_file" ]]; then
  set +u
  set -a
  # shellcheck disable=SC1090
  . "$env_file"
  set +a
  set -u
fi

state_dir="${arg_state_dir:-${MNEMO_MEMORY_STATE_DIR:-$ROOT_DIR/.mnemo-memory}}"
host="${arg_host:-${MNEMO_MEMORY_HOST:-127.0.0.1}}"
port="${arg_port:-${MNEMO_MEMORY_PORT:-8765}}"
config_file="${MNEMO_MEMORY_CONFIG:-$state_dir/config.json}"

export MNEMO_MEMORY_STATE_DIR="$state_dir"
export MNEMO_MEMORY_HOST="$host"
export MNEMO_MEMORY_PORT="$port"

if [[ -x "$ROOT_DIR/.venv/bin/mnemo-memory" ]]; then
  mnemo_cmd=("$ROOT_DIR/.venv/bin/mnemo-memory")
elif command -v mnemo-memory >/dev/null 2>&1; then
  mnemo_cmd=("mnemo-memory")
else
  python_bin="${PYTHON:-}"
  if [[ -z "$python_bin" && -x "$ROOT_DIR/.venv/bin/python" ]]; then
    python_bin="$ROOT_DIR/.venv/bin/python"
  fi
  python_bin="${python_bin:-python3}"
  mnemo_cmd=("$python_bin" -m mnemo_memory)
fi

cd "$ROOT_DIR"

echo "Mnemo Memory startup"
echo "  root: $ROOT_DIR"
echo "  state: $state_dir"
echo "  http: http://$host:$port/"

if [[ -f "$config_file" ]]; then
  echo "  provider config: $config_file"
elif [[ -n "${MNEMO_MEMORY_BASE_URL:-}" ]]; then
  echo "  provider: ${MNEMO_MEMORY_PROVIDER:-openai-compatible}"
  echo "  base url: $MNEMO_MEMORY_BASE_URL"
  echo "  model: ${MNEMO_MEMORY_MODEL:-memory-maintainer}"
  if [[ -n "${MNEMO_MEMORY_API_KEY:-}" || -n "${MNEMO_MEMORY_API_KEY_ENV:-}" ]]; then
    echo "  api key: configured"
  else
    echo "  api key: not configured"
  fi
else
  echo "  provider: not configured; set MNEMO_MEMORY_BASE_URL and MNEMO_MEMORY_MODEL for model Dream"
fi

if [[ "$dry_run" -eq 1 ]]; then
  printf 'Would run:'
  printf ' %q' "${mnemo_cmd[@]}" serve --state-dir "$state_dir" --host "$host" --port "$port"
  printf '\n'
  exit 0
fi

"${mnemo_cmd[@]}" init --state-dir "$state_dir" >/dev/null
exec "${mnemo_cmd[@]}" serve --state-dir "$state_dir" --host "$host" --port "$port"
