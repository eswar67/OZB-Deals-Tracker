#!/usr/bin/env bash
# Manual Mac fallback for ozbargain_monitor.py.
#
# GitHub Actions is the primary scheduler. This launchd fallback checks GitHub
# before running locally and only runs when GitHub has not started/completed the
# current slot.
#
# Usage:  bash install_launchd.sh --install
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

if [ "${1:-}" != "--install" ]; then
  echo ""
  echo "Mac launchd fallback is not installed by default."
  echo ""
  echo "GitHub Actions is the primary scheduler for:"
  echo "  • 2:00 PM Australia/Sydney"
  echo "  • 7:15 PM Australia/Sydney"
  echo ""
  echo "Install the Mac fallback safety net with:"
  echo "  bash install_launchd.sh --install"
  echo ""
  echo "To remove the fallback:"
  echo "  bash install_launchd.sh --uninstall"
  echo ""
  exit 0
fi

# ── Verify script exists ───────────────────────────────────────────────────────
if [ ! -f "$SCRIPT_DIR/ozbargain_monitor.py" ]; then
  echo "ERROR: ozbargain_monitor.py not found in $SCRIPT_DIR"
  exit 1
fi

if [ ! -f "$SCRIPT_DIR/mac_fallback.sh" ]; then
  echo "ERROR: mac_fallback.sh not found in $SCRIPT_DIR"
  exit 1
fi

chmod +x "$SCRIPT_DIR/mac_fallback.sh"

# ── Write plist ────────────────────────────────────────────────────────────────
# launchd uses local time. These fallback checks run after GitHub should have
# started each slot: 2:45 PM and 8:00 PM Australia/Sydney.
cat > "$PLIST" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>

  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${SCRIPT_DIR}/mac_fallback.sh</string>
  </array>

  <key>WorkingDirectory</key>
  <string>${SCRIPT_DIR}</string>

  <!-- Manual fallback checks: 2:45 PM and 8:00 PM local time -->
  <key>StartCalendarInterval</key>
  <array>
    <dict>
      <key>Hour</key><integer>14</integer>
      <key>Minute</key><integer>45</integer>
    </dict>
    <dict>
      <key>Hour</key><integer>20</integer>
      <key>Minute</key><integer>0</integer>
    </dict>
  </array>

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
echo "✅ Mac fallback launchd agent installed: $LABEL"
echo ""
echo "Schedule: fallback checks at 2:45 PM and 8:00 PM Australia/Sydney"
echo "Logs:     $LOG"
echo "Errors:   $ERR_LOG"
echo ""
echo "Notes:"
echo "  • This checks GitHub Actions first and only runs locally if GitHub failed"
echo "  • If the Mac is asleep at a scheduled time, the fallback may be missed"
echo "  • Remove this fallback once GitHub Actions is healthy again"
echo ""
echo "Useful commands:"
echo "  Check status:   launchctl list | grep ozbargain"
echo "  Run now:        launchctl start $LABEL"
echo "  Uninstall:      bash install_launchd.sh --uninstall"
echo "  View logs:      tail -f $LOG"
