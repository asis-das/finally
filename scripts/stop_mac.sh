#!/bin/sh
# Stop FinAlly. Idempotent. The finally-data volume is deliberately preserved.
set -eu
NAME=finally
if docker container inspect "$NAME" >/dev/null 2>&1; then
  docker rm -f "$NAME" >/dev/null
  echo "Stopped and removed container '$NAME'. Data volume 'finally-data' kept."
else
  echo "Container '$NAME' is not present. Nothing to do."
fi
