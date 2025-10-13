#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_COMPOSE="$ROOT_DIR/docker-compose.yml"
RUNTIME_COMPOSE="$ROOT_DIR/docker-compose.runtime.yml"
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-$(basename "$ROOT_DIR")}" 

if [[ ! -f "$BASE_COMPOSE" ]]; then
  echo "Base compose file not found: $BASE_COMPOSE" >&2
  exit 1
fi

if [[ ! -f "$RUNTIME_COMPOSE" ]]; then
  echo "Runtime compose file not found: $RUNTIME_COMPOSE" >&2
  exit 1
fi

COMBINED_FILE=$(mktemp)
trap 'rm -f "$COMBINED_FILE"' EXIT
"$ROOT_DIR/setup-jetson.py"

# Generate the combined compose configuration while preserving the compose project name.
docker compose -p "$PROJECT_NAME" -f "$BASE_COMPOSE" -f "$RUNTIME_COMPOSE" config > "$COMBINED_FILE"

# Define the runtime services that should be pulled and started.
# Only the stt-stream, llm, and tts services are managed by this script.
# Other services defined in docker-compose.runtime.yml (monitor, memory, cli, stt)
# are either managed elsewhere or not required for the runtime environment handled here.
runtime_services=(stt llm tts)

# Pull the latest versions of the runtime services we will start.
docker compose -p "$PROJECT_NAME" -f "$COMBINED_FILE" pull --ignore-pull-failures "${runtime_services[@]}"

# Run echo cancellation setup prior to starting runtime services.
"$ROOT_DIR/setup-echo.sh"

# Start the runtime services in the foreground so Ctrl-C tears them down,
# and clean up any orphaned containers for these services.
docker compose -p "$PROJECT_NAME" -f "$COMBINED_FILE" up --remove-orphans "${runtime_services[@]}"
