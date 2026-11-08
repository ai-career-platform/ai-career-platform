#!/usr/bin/env bash
# One-night wrapper, installed only after normal PR/CI/deployment gates.
set -eu
umask 077
cd /home/kant/ai-career-staging-poc
output=outputs/t154-night-20261108
mkdir -p "$output"
if [ -f "$output/HALT" ]; then
  echo '{"event":"NIGHT_WRAPPER","status":"IDLE","reason":"HALT_REQUIRES_REVIEW","external_http_requests":0}'
  exit 0
fi
snapshot=$(mktemp -d "$output/snapshot-XXXXXXXX")
token=$(python3 -c "import secrets; print(secrets.token_hex(8))")
launched=0
finish() {
  status=$?
  trap - EXIT
  if [ "$launched" -eq 1 ]; then
    container=$(docker compose --project-name ai-career-staging-poc ps -q backend) || status=1
    if [ -n "${container:-}" ]; then
      # Cancel by known identity and wait for final DB/log cleanup before archive.
      docker exec "$container" python -c '
import pathlib,sys,time
p=pathlib.Path("/tmp/t154-night-20261108/invocations");p.mkdir(parents=True,exist_ok=True)
token=sys.argv[1];(p/(token+".cancel")).touch();done=p/(token+".done.json")
for _ in range(100):
 if done.is_file():break
 time.sleep(.1)
sys.exit(0 if done.is_file() else 1)
' "$token" >/dev/null 2>&1 || status=1
      docker cp "$container:/tmp/t154-night-20261108/." "$snapshot/state" >/dev/null 2>&1 || status=1
    else
      status=1
    fi
  fi
  if [ "$status" -ne 0 ]; then
    : > "$output/HALT"
    echo '{"event":"NIGHT_WRAPPER","status":"UNRESOLVED","reason":"CALLER_OR_ARCHIVE_FAILED","external_http_requests":0}'
  fi
  exit "$status"
}
trap finish EXIT
trap ': > "$output/HALT"; exit 143' TERM
trap ': > "$output/HALT"; exit 130' INT
launched=1
docker compose --project-name ai-career-staging-poc exec -T backend \
  python -m crawler.jobs.fixture_night_caller once \
  --night-date 2026-11-08 \
  --invocation-id "$token" \
  --input /app/crawler/fixtures/night_synthetic_input.json \
  --raw-root /tmp/t154-night-20261108/raw \
  --log-file /tmp/t154-night-20261108/caller.jsonl \
  > "$snapshot/caller.stdout.jsonl" 2>/dev/null
cat "$snapshot/caller.stdout.jsonl"
