#!/usr/bin/env bash
# Installs ozbargain_monitor.py as a launchd agent that:
#   - Runs once daily at 7:00 PM
#   - Uses caffeinate -s to prevent system sleep during each run
#   - Works even when the lid is closed (on AC power)
#
# Usage:  bash install_launchd.sh
# Remove: bash install_launchd.sh --uninstall

set -e

LABEL="com.ozbargain.monitor"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$(which python3)"
LOG="$SCRIPT_DIR/ozbargain_monitor.log"
ERR_LOG="$SCRIPT_DIR/ozbargain_monitor_err.log"

# ── Uninstall ──────────────────────────────────────────────────────────────────
if [ "${1:-}" = "--uninstall" ]; then
  launchctl unload "$PLIST" 2>/dev/null && echo "Stopped launchd agent" || true
  rm -f "$PLIST"
  echo "Uninstalled. Logs remain at $LOG"
  exit 0
fi

# ── Verify script exists ───────────────────────────────────────────────────────
if [ ! -f "$SCRIPT_DIR/ozbargain_monitor.py" ]; then
  echo "ERROR: ozbargain_monitor.py not found in $SCRIPT_DIR"
  exit 1
fi

# ── Write plist ────────────────────────────────────────────────────────────────
# AEST = UTC+10, so run times in local time (launchd uses local time):
#   6am, 12pm, 6pm, 11:59pm  (midnight overshoots into next day so use 23:59)
cat > "$PLIST" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>

  <!-- caffeinate -s prevents system sleep for the duration of the run.
       Works when on AC power even with lid closed.
       -i also prevents idle sleep. -->
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string>
    <string>-si</string>
    <string>${PYTHON}</string>
    <string>${SCRIPT_DIR}/ozbargain_monitor.py</string>
  </array>

  <key>WorkingDirectory</key>
  <string>${SCRIPT_DIR}</string>

  <!-- Run once daily at 7:00 PM -->
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>19</integer>
    <key>Minute</key><integer>0</integer>
  </dict>

  <!-- If the Mac was asleep at the scheduled time, run as soon as it wakes -->
  <key>RunAtLoad</key>
  <false/>

  <key>StandardOutPath</key>
  <string>${LOG}</string>
  <key>StandardErrorPath</key>
  <string>${ERR_LOG}</string>

  <!-- Restart automatically if it crashes -->
  <key>KeepAlive</key>
  <false/>

  <!-- Give it time to finish — 10 minutes max -->
  <key>TimeOut</key>
  <integer>600</integer>

  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>HOME</key>
    <string>${HOME}</string>
  </dict>
</dict>
</plist>
PLIST_EOF

# ── Unload old version if running ─────────────────────────────────────────────
launchctl unload "$PLIST" 2>/dev/null || true

# ── Load the new agent ────────────────────────────────────────────────────────
launchctl load "$PLIST"

echo ""
echo "✅ launchd agent installed: $LABEL"
echo ""
echo "Schedule: once daily at 7:00 PM"
echo "Logs:     $LOG"
echo "Errors:   $ERR_LOG"
echo ""
echo "Notes:"
echo "  • caffeinate -si keeps the Mac awake during each run"
echo "  • If the Mac was asleep at run time, it will run on next wake"
echo "  • For reliable lid-closed operation: plug into AC power"
echo "  • To keep awake overnight: run  sudo pmset -a sleep 0"
echo "    (restore with: sudo pmset -a sleep 10)"
echo ""
echo "Useful commands:"
echo "  Check status:   launchctl list | grep ozbargain"
echo "  Run now:        launchctl start $LABEL"
echo "  Uninstall:      bash install_launchd.sh --uninstall"
echo "  View logs:      tail -f $LOG"
