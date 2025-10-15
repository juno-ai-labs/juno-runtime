#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_COMPOSE="$ROOT_DIR/docker-compose.yml"
RUNTIME_COMPOSE="$ROOT_DIR/docker-compose.runtime.yml"
PROJECT_NAME="juno"

# Parse command line arguments
RELEASE_TAG=""
while [[ $# -gt 0 ]]; do
  case $1 in
    # Supports the--release TAG style
    --release)
      if [[ -z "${2:-}" || "${2:-}" == --* ]]; then
        echo "Error: --release requires a tag value" >&2
        echo "Usage: $0 [--release TAG]" >&2
        exit 1
      fi
      RELEASE_TAG="$2"
      shift 2
      ;;
    # Supports the--release=TAG style
    --release=*)
      RELEASE_TAG="${1#*=}"
      if [[ -z "$RELEASE_TAG" ]]; then
        echo "Error: --release requires a tag value" >&2
        echo "Usage: $0 [--release TAG]" >&2
        exit 1
      fi
      shift
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Usage: $0 [--release TAG]" >&2
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

# Generate the combined compose configuration while preserving the compose project name.
docker compose -p "$PROJECT_NAME" -f "$BASE_COMPOSE" -f "$RUNTIME_COMPOSE" config > "$COMBINED_FILE"

# If a release tag is specified, update image tags in the combined config
if [[ -n "$RELEASE_TAG" ]]; then
  echo "Using release tag: $RELEASE_TAG"
  # Replace image references to use the specified release tag
  # Handles both implicit (no tag) and explicit tags like :latest
  sed -i.bak -E "s|image: ghcr.io/juno-ai-labs/juno-([^:[:space:]]+)(:[^[:space:]]+)?|image: ghcr.io/juno-ai-labs/juno-\1:${RELEASE_TAG}|g" "$COMBINED_FILE"
  rm -f "${COMBINED_FILE}.bak"
else
  echo "Using default (latest) image tags"
fi

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
docker compose -p "$PROJECT_NAME" -f "$COMBINED_FILE" up --remove-orphans --always-recreate-dep --attach-dependencies --menu --renew-anon-volumes --timestamps "${runtime_services[@]}"
