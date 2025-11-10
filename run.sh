#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_COMPOSE="$ROOT_DIR/docker-compose.yml"
RUNTIME_COMPOSE="$ROOT_DIR/docker-compose.runtime.yml"
PROJECT_NAME="juno"

ensure_latest_commit() {
  if ! git -C "$ROOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    return
  fi

  if ! git -C "$ROOT_DIR" fetch --quiet origin main; then
    echo "Warning: Unable to contact origin to verify the latest commit." >&2
    echo "Skipping up-to-date check. Please check your network connection or manually run 'git fetch origin'." >&2
    return
  fi

  if ! latest_commit=$(git -C "$ROOT_DIR" rev-parse --verify origin/main 2>/dev/null); then
    echo "Unable to verify the latest commit from origin/main." >&2
    echo "Please ensure the remote 'origin' has a 'main' branch." >&2
    exit 1
  fi

  current_commit=$(git -C "$ROOT_DIR" rev-parse HEAD)

  if [[ "$current_commit" != "$latest_commit" ]]; then
    echo "Error: This checkout is not up to date with origin/main." >&2
    echo "Please update before running this script:" >&2
    echo "  git fetch origin" >&2
    echo "  git pull origin main" >&2
    exit 1
  fi
}

ensure_latest_commit

DEFAULT_SERVICES=(audio-manager stt-stream-rust llm memory tts message-broker monitor llm-qwen3-4b llm-gemma3-4b llm-embedding)
DEFAULT_RELEASE_TAG="latest"

# Parse command line arguments
RELEASE_TAG=""
CUSTOM_SERVICES=()
ENABLE_WEB_SERVER=false
while [[ $# -gt 0 ]]; do
  case $1 in
    --help)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --release TAG          Use specific release tag (default: $DEFAULT_RELEASE_TAG)"
      echo "  --services FOO BAR ... Specify which services to run (default: ${DEFAULT_SERVICES[*]})"
      echo "  --web-server           Include the browser web server service"
      echo "  --help                 Show this help message"
      echo ""
      echo "Examples:"
      echo "  $0"
      echo "  $0 --release 2025-10-20"
      echo "  $0 --services stt tts"
      echo "  $0 --release 2025-10-20 --services test-playback"
      echo "  $0 --web-server"
      exit 0
      ;;
    --release)
      if [[ -z "${2:-}" || "${2:-}" == --* ]]; then
        # Example: ./run.sh --release 2025-10-20
        echo "Error: --release requires a tag value" >&2
        echo "Usage: $0 [--release TAG] [--services SERVICE...]" >&2
        exit 1
      fi
      RELEASE_TAG="$2"
      shift 2
      ;;
    --services)
      shift
      while [[ $# -gt 0 && "$1" != --* ]]; do
        CUSTOM_SERVICES+=("$1")
        shift
      done
      if [[ ${#CUSTOM_SERVICES[@]} -eq 0 ]]; then
        # Example: ./run.sh --services stt llm tts message-broker
        # Example: ./run.sh --services test-playback
        echo "Error: --services requires at least one service name" >&2
        echo "Usage: $0 [--release TAG] [--services SERVICE...]" >&2
        exit 1
      fi
      ;;
    --web-server)
      ENABLE_WEB_SERVER=true
      shift
      ;;
    *)
      # Example: ./run.sh --services stt llm tts message-broker --release 2025-10-20
      echo "Unknown option: $1" >&2
      echo "Usage: $0 [--release TAG] [--services SERVICE...]" >&2
      exit 1
      ;;
  esac
done

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

# If a release tag is specified, update image tags in the combined config
if [[ -n "$RELEASE_TAG" ]]; then
  # Replace image references to use the specified release tag
  # Handles both implicit (no tag) and explicit tags like :latest
  sed -i.bak -E "s|image: ghcr.io/juno-ai-labs/juno-([^:[:space:]]+)(:[^[:space:]]+)?|image: ghcr.io/juno-ai-labs/juno-\1:${RELEASE_TAG}|g" "$COMBINED_FILE"
  rm -f "${COMBINED_FILE}.bak"
else
  RELEASE_TAG="$DEFAULT_RELEASE_TAG"
fi

echo "Using image tag: $RELEASE_TAG"

# Define the runtime services that should be pulled and started.
# Only the audio-manager, stt-stream, llm, and tts services are managed by this script.
# Other services defined in docker-compose.runtime.yml (monitor, memory, cli, stt)
# are either managed elsewhere or not required for the runtime environment handled here.
if [[ ${#CUSTOM_SERVICES[@]} -gt 0 ]]; then
  runtime_services=("${CUSTOM_SERVICES[@]}")
else
  runtime_services=("${DEFAULT_SERVICES[@]}")
fi

if [[ "$ENABLE_WEB_SERVER" == true ]]; then
  local_found=false
  for svc in "${runtime_services[@]}"; do
    if [[ "$svc" == "web-server" ]]; then
      local_found=true
      break
    fi
  done
  if [[ "$local_found" == false ]]; then
    runtime_services+=("web-server")
  fi
fi

echo "Starting services: ${runtime_services[*]}"

# Pull the latest versions of the runtime services we will start.
docker compose -p "$PROJECT_NAME" -f "$COMBINED_FILE" pull --ignore-pull-failures "${runtime_services[@]}"

# Run echo cancellation setup prior to starting runtime services.
"$ROOT_DIR/setup-echo.sh"

# Start the runtime services in the foreground so Ctrl-C tears them down,
# and clean up any orphaned containers for these services.
docker compose -p "$PROJECT_NAME" -f "$COMBINED_FILE" up --remove-orphans --always-recreate-deps --attach-dependencies --menu --renew-anon-volumes --timestamps "${runtime_services[@]}"
