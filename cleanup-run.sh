#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_COMPOSE="$ROOT_DIR/docker-compose.yml"
RUNTIME_COMPOSE="$ROOT_DIR/docker-compose.runtime.yml"
PROJECT_NAME="juno"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --help)
      echo "Usage: $0"
      echo ""
      echo "Clean up Docker resources created by run.sh"
      echo ""
      echo "This script performs a complete cleanup:"
      echo "  - Stop and remove all containers in the project"
      echo "  - Remove all project volumes (model caches, IPC sockets, etc.)"
      echo "  - Remove all juno-ai-labs images (all tags/versions)"
      echo "  - Remove orphaned containers"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Usage: $0 [--help]" >&2
      exit 1
      ;;
  esac
done

# Check if Docker daemon is running
if ! docker info >/dev/null 2>&1; then
  echo "Error: Docker daemon is not running" >&2
  exit 1
fi

if [[ ! -f "$BASE_COMPOSE" ]]; then
  echo "Base compose file not found: $BASE_COMPOSE" >&2
  exit 1
fi

if [[ ! -f "$RUNTIME_COMPOSE" ]]; then
  echo "Runtime compose file not found: $RUNTIME_COMPOSE" >&2
  exit 1
fi

echo "Cleaning up all juno project resources..."
echo "  - Stopping and removing containers"
echo "  - Removing volumes"
echo "  - Removing all juno-ai-labs images"
echo ""

# Stop all containers, remove volumes and orphaned containers
if ! docker compose -p "$PROJECT_NAME" -f "$BASE_COMPOSE" -f "$RUNTIME_COMPOSE" down --volumes --remove-orphans; then
  echo "Error: Failed to stop containers and remove volumes" >&2
  exit 1
fi

# Remove all juno-ai-labs images
echo "Removing juno-ai-labs images..."

# Get all juno-ai-labs images (all tags, including dangling ones)
IMAGES=$(docker images 'ghcr.io/juno-ai-labs/*' --format '{{.Repository}}:{{.Tag}}')

IMAGES_REMOVED=false
if [[ -n "$IMAGES" ]]; then
  IMAGE_COUNT=$(echo "$IMAGES" | grep -c . || echo 0)
  echo "Found $IMAGE_COUNT images to remove"
  if echo "$IMAGES" | xargs docker rmi --force; then
    IMAGES_REMOVED=true
  fi
else
  echo "No juno-ai-labs images found"
fi

# Clean up any dangling resources (system-wide, not just project-scoped)
# This is intentional to clean up build cache, unused networks, and dangling images
# that may have accumulated from development work
echo "Cleaning up dangling resources..."
docker system prune -f

echo ""
echo "Cleanup complete!"
echo ""
echo "✓ Containers stopped and removed"
echo "✓ Volumes removed"

if [[ "$IMAGES_REMOVED" == true ]]; then
  echo "✓ Images removed"
elif [[ -z "$IMAGES" ]]; then
  echo "✓ No images needed removal"
else
  echo "⚠ Image removal may have partially failed"
fi
