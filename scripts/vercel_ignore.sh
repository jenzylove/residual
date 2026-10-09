#!/bin/sh
# Vercel runs this before each deploy: exit 0 skips the deploy, exit 1 builds it.
# A watcher heartbeat (only its logs changed) deploys at most once an hour, so a runner pushing
# every 10 minutes stays inside the deploy limits. Anything else always deploys.
git diff --quiet HEAD^ HEAD -- . ':(exclude)data/live_log.jsonl' ':(exclude)data/watcher.log' ':(exclude)web/live.json' || exit 1
[ "$(date -u +%M)" -lt 10 ] && exit 1
exit 0
