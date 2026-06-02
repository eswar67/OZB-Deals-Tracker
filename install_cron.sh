#!/usr/bin/env bash
# DEPRECATED — use install_launchd.sh instead (macOS launchd is preferred over cron).
#
# Installs a cron job to run ozbargain_monitor.py once daily at 7:00 PM AEST.
#
# AEST is UTC+10, so 7pm AEST = 09:00 UTC.
# AEDT (DST) is UTC+11, so 7pm AEDT = 08:00 UTC.
# This cron entry uses AEST (UTC+10) — adjust to 08:00 UTC during daylight saving.
#
# Usage:  bash install_cron.sh
# Remove: crontab -e  → delete the OzBargain line

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$(which python3)"
SCRIPT="$SCRIPT_DIR/ozbargain_monitor.py"
LOG="$SCRIPT_DIR/ozbargain_monitor.log"

if [ ! -f "$SCRIPT" ]; then
  echo "ERROR: $SCRIPT not found. Run this from the project directory."
  exit 1
fi

# 7pm AEST = 09:00 UTC
CRON_LINE="0 9 * * * $PYTHON $SCRIPT >> $LOG 2>&1  # OzBargain 7pm AEST"

# Get existing crontab (suppress error if none)
EXISTING="$(crontab -l 2>/dev/null || true)"

# Remove any old OzBargain entries
CLEANED="$(echo "$EXISTING" | grep -v '# OzBargain' || true)"

# Append new entry
echo -e "$CLEANED\n$CRON_LINE" | crontab -

echo ""
echo "Cron job installed. Current OzBargain entry:"
crontab -l | grep OzBargain
echo ""
echo "Schedule: once daily at 7:00 PM AEST (09:00 UTC)"
echo "Logs will be written to: $LOG"
echo "To remove, run:  crontab -e  and delete the OzBargain line."
echo ""
echo "NOTE: On macOS, prefer install_launchd.sh — it handles sleep/wake correctly."
