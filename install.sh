#!/usr/bin/env bash
# Install the Mac side: a launchd agent running the daemon.
# No Claude Code hooks are needed; the daemon reads Claude Code's own
# session state directly. Any hooks from an older version are removed.
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
STATE_DIR="$HOME/.claude-status-led"
SETTINGS="$HOME/.claude/settings.json"
LABEL="com.claude-status-led.daemon"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$STATE_DIR/bin" "$HOME/Library/LaunchAgents"

# Copy the daemon out of the repo. This is NOT cosmetic: a launchd agent
# runs without TCC privileges and cannot read ~/Documents, ~/Desktop or
# ~/Downloads, so running it from a repo cloned there fails with
# "Operation not permitted". Re-run this script after changing the code.
cp "$REPO/daemon/claude_led_daemon.py" "$STATE_DIR/bin/claude_led_daemon.py"
chmod +x "$STATE_DIR/bin/claude_led_daemon.py"
echo "Copied daemon to $STATE_DIR/bin"

if [ ! -f "$STATE_DIR/config.json" ]; then
  cp "$REPO/config.example.json" "$STATE_DIR/config.json"
  echo "Wrote default config to $STATE_DIR/config.json"
fi

# Older versions installed hooks. Take them back out.
if [ -f "$SETTINGS" ]; then
  /usr/bin/python3 - "$SETTINGS" <<'PYEOF'
import json, shutil, sys, time
path = sys.argv[1]
try:
    data = json.load(open(path))
except Exception:
    raise SystemExit(0)
hooks = data.get("hooks", {})
removed = 0
for event, entries in list(hooks.items()):
    for entry in list(entries):
        for h in list(entry.get("hooks", [])):
            if "claude_led_hook.py" in h.get("command", ""):
                entry["hooks"].remove(h); removed += 1
        if not entry.get("hooks"):
            entries.remove(entry)
    if not entries:
        del hooks[event]
if removed:
    shutil.copy(path, path + ".backup-%d" % int(time.time()))
    if not hooks:
        data.pop("hooks", None)
    json.dump(data, open(path, "w"), indent=2); open(path, "a").write("\n")
    print("Removed %d hook(s) from a previous version." % removed)
PYEOF
fi
rm -f "$STATE_DIR/bin/claude_led_hook.py" "$STATE_DIR/events.log"
rm -rf "$STATE_DIR/sessions"

echo "Installing launchd agent ..."
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>$STATE_DIR/bin/claude_led_daemon.py</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>$STATE_DIR/daemon.log</string>
    <key>StandardErrorPath</key><string>$STATE_DIR/daemon.log</string>
</dict>
</plist>
PLISTEOF

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true

# launchd does not always release the label immediately after bootout, and
# bootstrapping too soon fails with "Input/output error", which under set -e
# aborts this script leaving nothing running. Retry.
bootstrapped=0
for _ in 1 2 3 4 5; do
  if launchctl bootstrap "gui/$UID" "$PLIST" 2>/dev/null; then bootstrapped=1; break; fi
  sleep 1
done

# launchd registers the job asynchronously, so give it a moment before
# checking, otherwise this reports a failure for an agent that did start.
sleep 2

if [ "$bootstrapped" -ne 1 ] || ! launchctl list | grep -q "$LABEL"; then
  echo >&2
  echo "Warning: the daemon did not start. Start it by hand with:" >&2
  echo "  launchctl bootstrap gui/\$UID $PLIST" >&2
fi

echo
echo "Installed. No Claude Code restart needed."
echo "  Log:    $STATE_DIR/daemon.log"
echo "  Config: $STATE_DIR/config.json"
