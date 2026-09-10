#!/bin/sh
# Start FinAlly. Idempotent: safe to run repeatedly.
#   ./scripts/start_mac.sh [--build] [--no-open]
set -eu

IMAGE=finally:latest
NAME=finally
VOLUME=finally-data
PORT=8000
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

BUILD=0; OPEN=1
for arg in "$@"; do
  case "$arg" in
    --build) BUILD=1 ;;
    --no-open) OPEN=0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

command -v docker >/dev/null 2>&1 || { echo "ERROR: docker not found on PATH" >&2; exit 1; }

if [ ! -f .env ]; then
  echo "WARNING: .env not found - creating it from .env.example."
  echo "         AI chat runs in mock mode until you add OPENROUTER_API_KEY."
  cp .env.example .env
fi

if [ "$BUILD" -eq 1 ] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building $IMAGE ..."
  docker build -t "$IMAGE" .
fi

# Remove any previous container (running or exited); the volume is untouched.
if docker container inspect "$NAME" >/dev/null 2>&1; then
  echo "Removing existing container '$NAME' ..."
  docker rm -f "$NAME" >/dev/null
fi

docker volume create "$VOLUME" >/dev/null

echo "Starting $NAME ..."
docker run -d --name "$NAME" \
  -p "${PORT}:8000" \
  -v "${VOLUME}:/app/db" \
  --env-file .env \
  --restart unless-stopped \
  "$IMAGE" >/dev/null

URL="http://localhost:${PORT}"
printf "Waiting for %s/api/health " "$URL"
i=0
while [ "$i" -lt 60 ]; do
  if curl -fsS "${URL}/api/health" >/dev/null 2>&1; then
    echo
    echo "FinAlly is up:  $URL"
    [ "$OPEN" -eq 1 ] && command -v open >/dev/null 2>&1 && open "$URL" || true
    exit 0
  fi
  # A crashed container will never become healthy - fail fast with its logs.
  if [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" != "true" ]; then
    echo; echo "ERROR: container exited. Logs:" >&2
    docker logs "$NAME" >&2 || true
    exit 1
  fi
  printf .
  i=$((i + 1))
  sleep 1
done

echo; echo "ERROR: timed out waiting for health. Logs:" >&2
docker logs --tail 50 "$NAME" >&2 || true
exit 1
