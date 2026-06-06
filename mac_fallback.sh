#!/usr/bin/env bash
# Mac fallback runner for OzBargain Monitor.
#
# This script is intended to be called by launchd after the GitHub Actions
# schedule should have run. It only runs the local monitor when GitHub Actions
# has not started or completed a run for the current Sydney slot.

set -euo pipefail

REPO="eswar67/OZB-Deals-Tracker"
WORKFLOW_ID="288527704"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$SCRIPT_DIR/ozbargain_monitor.log"
PYTHON="$(command -v python3)"

sydney_date="$(TZ=Australia/Sydney date +%Y-%m-%d)"
sydney_ymd="$(TZ=Australia/Sydney date +%Y%m%d)"
sydney_hour="$(TZ=Australia/Sydney date +%H)"
sydney_minute="$(TZ=Australia/Sydney date +%M)"
sydney_minutes=$((10#$sydney_hour * 60 + 10#$sydney_minute))

if (( sydney_minutes >= 14 * 60 && sydney_minutes < 19 * 60 + 15 )); then
  slot="afternoon"
  slot_start_local="$sydney_date 14:00:00 Australia/Sydney"
elif (( sydney_minutes >= 19 * 60 + 15 )); then
  slot="evening"
  slot_start_local="$sydney_date 19:15:00 Australia/Sydney"
else
  echo "$(date) Mac fallback: outside monitored slots; exiting." >> "$LOG"
  exit 0
fi

slot_start_utc="$("$PYTHON" - "$slot_start_local" <<'PY'
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

text = sys.argv[1].replace(" Australia/Sydney", "")
dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo("Australia/Sydney"))
print(dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ"))
PY
)"

echo "$(date) Mac fallback: checking GitHub Actions for $sydney_ymd-$slot since $slot_start_utc" >> "$LOG"

runs_json="$(curl -fsS "https://api.github.com/repos/$REPO/actions/workflows/$WORKFLOW_ID/runs?per_page=20&branch=main" || true)"

if "$PYTHON" - "$slot_start_utc" "$runs_json" <<'PY'
import json
import sys
from datetime import datetime, timezone

slot_start = datetime.strptime(sys.argv[1], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
try:
    payload = json.loads(sys.argv[2])
except Exception:
    sys.exit(1)

for run in payload.get("workflow_runs", []):
    event = run.get("event")
    status = run.get("status")
    conclusion = run.get("conclusion")
    created_raw = run.get("created_at")
    if event not in {"schedule", "workflow_dispatch"} or not created_raw:
        continue
    created = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
    if created < slot_start:
        continue
    if status in {"queued", "in_progress"} or conclusion == "success":
        sys.exit(0)
sys.exit(1)
PY
then
  echo "$(date) Mac fallback: GitHub Actions has run or is running; skipping local run." >> "$LOG"
  exit 0
fi

echo "$(date) Mac fallback: no GitHub Actions run found; running local monitor." >> "$LOG"
cd "$SCRIPT_DIR"
"$PYTHON" ozbargain_monitor.py >> "$LOG" 2>&1
