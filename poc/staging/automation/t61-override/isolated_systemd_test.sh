#!/bin/bash
# Isolated systemd recovery test (user manager; production units, timer, lock, project and DB untouched).
set -u
export XDG_RUNTIME_DIR=/run/user/$(id -u)
T=/home/kant/t61-systemd-test
U=$HOME/.config/systemd/user
SVC=t61systest-dispatch.service
rm -rf "$T"; mkdir -m 700 -p "$T/probe" "$T/out" "$U"
IMG=$(python3 -c 'import json;print(json.load(open("/home/kant/ai-career-staging-poc/.deploy-state/success.json"))["images"]["backend"])')
echo "== $(TZ=Asia/Seoul date '+%F %T KST') image=${IMG##*@}"

# Isolated compose project: same backend image, no network, container env flags ON (like a live .env).
cat > "$T/compose.yaml" <<YML
name: t61systest
services:
  backend:
    image: $IMG
    network_mode: none
    entrypoint: ["sleep", "1800"]
    environment:
      CRAWLER_NIGHT_ENABLED: "\${CRAWLER_NIGHT_ENABLED:-0}"
      CRAWLER_LIVE_SCHEDULE_APPROVED: "\${CRAWLER_LIVE_SCHEDULE_APPROVED:-0}"
      CRAWLER_NIGHT_POLICY_FILE: /probe/approval.json
      PYTHONPATH: /app
    volumes:
      - ./probe:/probe:ro
      - ./out:/out
YML
printf 'CRAWLER_NIGHT_ENABLED=1\nCRAWLER_LIVE_SCHEDULE_APPROVED=1\n' > "$T/.env"

# Probe: real dispatcher.night_step env check, then the real live_gate + approval loader.
# run_night_step is replaced only so nothing touches a DB; no HTTP is possible (network none).
cat > "$T/probe/probe.py" <<'PY'
import json, os, sys
from datetime import datetime, timezone
import crawler.jobs.night_crawl as nc
from crawler.jobs import dispatcher
now = datetime.fromisoformat(os.environ.get('PROBE_NOW') or datetime.now(timezone.utc).isoformat())
def fake_run(connection, *, environ, **kw):
    gate, _ = nc.live_gate(environ=environ, keyword='AX', now=now)
    return {'night': 'WOULD_RUN_LIVE_JOB' if gate == 'ALLOWED' else 'BLOCKED', 'reason': gate}
nc.run_night_step = fake_run
class Store:
    connection = None
    def lock(self, key): return True
    def unlock(self, key): pass
res = dispatcher.night_step(Store())
line = json.dumps({'case': os.environ.get('PROBE_CASE'), 'env_night': os.environ.get('CRAWLER_NIGHT_ENABLED'),
                   'env_live': os.environ.get('CRAWLER_LIVE_SCHEDULE_APPROVED'), 'now': now.isoformat(), 'result': res})
open('/out/results.jsonl', 'a').write(line + '\n'); print(line)
PY

approval() {  # $1 = review_due_utc; ISOLATED TEST fixture, never an operational record
python3 - "$1" > "$T/probe/approval.json" <<'PY'
import json, sys
from urllib.parse import quote
kw = ['AX', '데이터 분석', '빅데이터', 'AI 엔지니어', '머신러닝', '딥러닝']
print(json.dumps({'source_code': 'jobkorea', 'approval_status': 'APPROVED', 'enabled': True,
  'approved_by': 'ISOLATED-SYSTEMD-TEST-ONLY', 'evidence_ref': 'isolated test fixture; network none; not operational',
  'valid_from_utc': '2026-11-15T00:00:00Z', 'review_due_utc': sys.argv[1], 'collection_method': 'WEB',
  'allowed_urls': ['https://www.jobkorea.co.kr/Search/?stext=' + quote(k) + '&tabType=recruit' for k in kw],
  'allowed_purposes': ['night_keyword_collection'], 'max_requests': 7, 'retention_days': 1,
  'stop_on_block': True, 'max_discovered_details': 5}))
PY
}
DC="docker compose --project-name t61systest --project-directory $T --env-file $T/.env -f $T/compose.yaml"
$DC up -d </dev/null 2>&1 | tail -1

# Unit = production unit with only names/paths changed (same flock --nonblock + compose exec shape).
ORIG="/usr/bin/flock --nonblock $T/.dispatch.lock /usr/bin/docker compose --project-name t61systest --project-directory $T --env-file $T/.env -f $T/compose.yaml exec -T backend python /probe/probe.py"
cat > "$U/$SVC" <<UNIT
[Unit]
Description=T61 isolated systemd recovery test (copy of ai-career-crawler-dispatch shape)
[Service]
Type=oneshot
WorkingDirectory=$T
ExecStart=$ORIG
TimeoutStartSec=180
UNIT
D="$U/$SVC.d"; mkdir -p "$D"
# 90: exactly the transformation the 2026-11-13 root script applied to the production unit.
OFF=$(echo "$ORIG" | sed 's# exec -T backend python# exec -T -e CRAWLER_NIGHT_ENABLED=0 -e CRAWLER_LIVE_SCHEDULE_APPROVED=0 backend python#')
put90() { printf '[Service]\nExecStart=\nExecStart=%s\n' "$OFF" > "$D/90-live-auto-off.conf"; }
put95() { printf '[Service]\n# T61 one-night override %s: restores the original ExecStart; removed by a timer\nExecStart=\nExecStart=%s\n' "$1" "$ORIG" > "$D/95-t61-night.conf"; }
reload() { systemctl --user daemon-reload; }
execline() { systemctl --user show $SVC -p ExecStart --value | grep -o 'exec -T[^;]*backend' | head -1; }
dropins() { systemctl --user show $SVC -p DropInPaths --value | tr ' ' '\n' | xargs -n1 basename 2>/dev/null | tr '\n' ' '; }
run() {  # $1 case, $2 PROBE_NOW ('' = real now)
  # pass case/now into the exec via the compose env file is not possible; use a per-case wrapper env:
  sed -i "s#^CRAWLER_NIGHT_ENABLED=.*#CRAWLER_NIGHT_ENABLED=${ENV_NIGHT:-1}#; s#^CRAWLER_LIVE_SCHEDULE_APPROVED=.*#CRAWLER_LIVE_SCHEDULE_APPROVED=${ENV_LIVE:-1}#" "$T/.env"
  echo "{\"case\":\"$1\",\"now\":\"$2\"}" > "$T/out/next.json"
  systemctl --user start $SVC; rc=$?
  r=$(tail -1 "$T/out/results.jsonl" 2>/dev/null)
  echo "CASE $1 | dropins=[$(dropins)] | exec='$(execline)' | rc=$rc | $r"
}
# probe reads case/now from /out/next.json
python3 - "$T/probe/probe.py" <<'PY'
import sys; p=sys.argv[1]; s=open(p).read()
s=s.replace("now = datetime.fromisoformat(os.environ.get('PROBE_NOW') or datetime.now(timezone.utc).isoformat())",
 "nxt = json.load(open('/out/next.json'))\nos.environ['PROBE_CASE'] = nxt['case']\nnow = datetime.fromisoformat(nxt['now'] or datetime.now(timezone.utc).isoformat())")
open(p,'w').write(s)
PY
FUT=2026-11-16T23:00:00Z
reload
echo "== A. no approval file (flags ON)"; rm -f "$T/probe/approval.json"; run A_NO_APPROVAL ""
echo "== A2. default OFF: container env flags 0"; approval $FUT; $DC up -d --force-recreate </dev/null >/dev/null 2>&1
ENV_NIGHT=0 ENV_LIVE=0; sed -i 's/=1$/=0/' "$T/.env"; $DC up -d --force-recreate </dev/null >/dev/null 2>&1; run A2_FLAGS_OFF ""
sed -i 's/=0$/=1/' "$T/.env"; unset ENV_NIGHT ENV_LIVE; $DC up -d --force-recreate </dev/null >/dev/null 2>&1
echo "== B. valid approval, flags ON, no drop-in"; run B_VALID ""
echo "== C. after expiry (08:00 KST boundary + 1s)"; approval 2026-11-15T23:00:00Z; run C_EXPIRED "2026-11-15T23:00:01+00:00"
approval $FUT
echo "== D. 90-live-auto-off applied"; put90; reload; run D_KILL_SWITCH ""
echo "== E. 95 override on top of 90"; put95 "test"; reload; run E_OVERRIDE ""
echo "== E2. 95 does not bypass expiry"; run E2_OVERRIDE_EXPIRED "2026-11-16T23:00:01+00:00"
echo "== E3. 95 does not bypass flags OFF"; sed -i 's/=1$/=0/' "$T/.env"; $DC up -d --force-recreate </dev/null >/dev/null 2>&1; ENV_NIGHT=0 ENV_LIVE=0 run E3_OVERRIDE_FLAGS_OFF ""
sed -i 's/=0$/=1/' "$T/.env"; $DC up -d --force-recreate </dev/null >/dev/null 2>&1
echo "== F. transient timer removes 95 (auto-off)"
systemd-run --user --unit t61systest-expire --on-active=15s /bin/sh -c "rm -f '$D/95-t61-night.conf' && systemctl --user daemon-reload" 2>&1 | tail -1
systemctl --user list-timers --no-pager | grep t61systest | cut -c1-120
for i in $(seq 1 20); do [ -e "$D/95-t61-night.conf" ] || break; sleep 2; done
echo "95 present after timer: $([ -e "$D/95-t61-night.conf" ] && echo yes || echo no)"; run F_AFTER_TIMER ""
echo "== G1. concurrent start while the dispatch lock is held"
put95 "g"; reload
( flock "$T/.dispatch.lock" sleep 8 ) & sleep 1
n0=$(wc -l < "$T/out/results.jsonl"); echo '{"case":"G1_LOCKED","now":""}' > "$T/out/next.json"
systemctl --user start $SVC; echo "rc=$? (non-zero = flock --nonblock refused) probe_ran=$(( $(wc -l < "$T/out/results.jsonl") - n0 ))"
wait
echo "== G2. daemon-reload / restart while 95 present keeps one ExecStart"
systemctl --user daemon-reload; systemctl --user show $SVC -p ExecStart --value | grep -c 'argv\[\]'; run G2_AFTER_RELOAD ""
echo "== G3. rollback: remove 95 manually"; rm -f "$D/95-t61-night.conf"; reload; run G3_ROLLBACK ""
echo "== H1. host time zone and calendar specs (08:01 KST = 23:01 UTC previous day)"
echo "timezone=$(timedatectl show -p Timezone --value 2>/dev/null) now_utc=$(date -u +%FT%TZ)"
systemd-analyze calendar '2026-11-16 23:01:00 UTC' 2>&1 | grep -E 'Normalized|Next elapse|UTC' | head -3
systemd-analyze calendar '2026-11-17 08:01:00 Asia/Seoul' 2>&1 | grep -E 'Normalized|Next elapse|UTC' | head -3
echo "== H2. real --on-calendar (UTC spec) removal with AccuracySec=1s fires on time and restores the kill switch"
# Finding (first run, 2026-11-16 08:31 KST): without AccuracySec the transient timer fired ~30-60 s late
# (systemd default AccuracySec=1min). The production procedure therefore pins AccuracySec=1s.
put95 "h2"; reload
SPEC="$(date -u -d '+30 seconds' '+%Y-%m-%d %H:%M:%S') UTC"
systemd-run --user --unit t61systest-cal --on-calendar="$SPEC" --timer-property=AccuracySec=1s /bin/sh -c "rm -f '$D/95-t61-night.conf' && systemctl --user daemon-reload" 2>&1 | tail -1
systemctl --user list-timers --no-pager | grep t61systest-cal | cut -c1-90
run H2_BEFORE_FIRE ""
for i in $(seq 1 60); do [ -e "$D/95-t61-night.conf" ] || break; sleep 1; done
echo "spec='$SPEC' removed_seen_at=$(date -u +%T) 95_present=$([ -e "$D/95-t61-night.conf" ] && echo yes || echo no)"
sleep 2; run H2_AFTER_FIRE ""
echo "== I. removal command fails: 95 stays, but approval expiry and flags-off still block"
put95 "i"; reload
systemd-run --user --unit t61systest-fail --on-active=2s --timer-property=AccuracySec=1s /bin/false 2>&1 | tail -1; sleep 5
echo "95_present=$([ -e "$D/95-t61-night.conf" ] && echo yes || echo no) removal_result=$(systemctl --user show t61systest-fail.service -p Result --value)"
run I_EXPIRED_WITH_STUCK_OVERRIDE "2026-11-16T23:00:01+00:00"
sed -i 's/=1$/=0/' "$T/.env"; $DC up -d --force-recreate </dev/null >/dev/null 2>&1; ENV_NIGHT=0 ENV_LIVE=0 run I_FLAGS_OFF_WITH_STUCK_OVERRIDE ""
echo "== J. backend recreate fails after .env flags set to 1: the running container keeps flags 0"
printf 'services:\n  backend:\n    image: t61systest-missing:none\n' > "$T/broken.yaml"
sed -i 's/=0$/=1/' "$T/.env"
docker compose --project-name t61systest --project-directory "$T" --env-file "$T/.env" -f "$T/compose.yaml" -f "$T/broken.yaml" up -d --no-build --pull never backend </dev/null >/dev/null 2>&1; echo "recreate_rc=$?"
echo "container_state=$(docker inspect -f '{{.State.Status}}' t61systest-backend-1 2>&1 | head -1)"
ENV_NIGHT=1 ENV_LIVE=1 run J_AFTER_FAILED_RECREATE ""
rm -f "$D/95-t61-night.conf"; reload
echo "== cleanup"
$DC down </dev/null 2>&1 | tail -1
rm -rf "$U/$SVC" "$D"; systemctl --user daemon-reload; systemctl --user reset-failed 2>/dev/null
cp "$T/out/results.jsonl" /home/kant/t61-systemd-results.jsonl 2>/dev/null; rm -rf "$T"
echo "leftover units: $(systemctl --user list-unit-files --no-pager | grep -c t61systest) containers: $(docker ps -a --filter label=com.docker.compose.project=t61systest -q | wc -l)"
echo "production untouched: $(systemctl show ai-career-crawler-dispatch.service -p DropInPaths --value | xargs -n1 basename) active=$(systemctl is-active ai-career-crawler-dispatch.timer)"
echo "== end $(TZ=Asia/Seoul date '+%F %T KST')"
