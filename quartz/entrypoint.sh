#!/bin/sh
# Container entrypoint: build once, then run the trigger + static server.

echo "[quartz] initial build at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
./rebuild.sh

echo "[quartz] starting trigger server on :${TRIGGER_PORT}"
exec node ./server.mjs
