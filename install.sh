#!/usr/bin/env bash
# Install the Mac side: Claude Code hooks + a launchd agent for the daemon.
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
STATE_DIR="$HOME/.claude-status-led"
SETTINGS="$HOME/.claude/settings.json"
LABEL="com.claude-status-led.daemon"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PY=/usr/bin/python3

mkdir -p "$STATE_DIR/sessions" "$STATE_DIR/bin" "$HOME/Library/LaunchAgents" "$HOME/.claude"

# Copy the scripts out of the repo and into ~/.claude-status-led/bin.
# This is NOT cosmetic. A launchd agent runs without TCC privileges, so it
# cannot read ~/Documents, ~/Desktop or ~/Downloads: you get
# "Operation not permitted" and the daemon never starts. The home
# directory root is not TCC-protected, so the daemon can be read there.
# Re-run this script after you change the code, to copy it across again.
cp "$REPO/daemon/claude_led_daemon.py" "$STATE_DIR/bin/claude_led_daemon.py"
cp "$REPO/hooks/claude_led_hook.py" "$STATE_DIR/bin/claude_led_hook.py"
chmod +x "$STATE_DIR/bin/claude_led_daemon.py" "$STATE_DIR/bin/claude_led_hook.py"
echo "Copied scripts to $STATE_DIR/bin"

if [ ! -f "$STATE_DIR/config.json" ]; then
  cp "$REPO/config.example.json" "$STATE_DIR/config.json"
  echo "Wrote default config to $STATE_DIR/config.json"
fi

echo "Adding hooks to $SETTINGS ..."
"$PY" - "$SETTINGS" "$STATE_DIR" <<'PYEOF'
import json, os, shutil, sys, time

settings_path, state_dir = sys.argv[1], sys.argv[2]
hook = os.path.join(state_dir, "bin", "claude_led_hook.py")

data = {}
if os.path.exists(settings_path):
    shutil.copy(settings_path, settings_path + ".backup-%d" % int(time.time()))
    try:
        with open(settings_path) as fh:
            data = json.load(fh)
    except Exception:
        print("Existing settings.json is not valid JSON; aborting.", file=sys.stderr)
        raise SystemExit(1)

hooks = data.setdefault("hooks", {})
for event in ["SessionStart", "UserPromptSubmit", "Notification", "Stop", "SessionEnd"]:
    command = "/usr/bin/python3 %s %s" % (hook, event)
    entries = hooks.setdefault(event, [])
    # Drop any previous install of ours, then add a fresh entry.
    for entry in list(entries):
        for h in list(entry.get("hooks", [])):
            if "claude_led_hook.py" in h.get("command", ""):
                entry["hooks"].remove(h)
        if not entry.get("hooks"):
            entries.remove(entry)
    entries.append({"hooks": [{"type": "command", "command": command, "timeout": 5}]})

with open(settings_path, "w") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
print("Hooks installed.")
PYEOF

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

# launchd does not always release the label immediately after bootout.
# Bootstrapping too soon fails with "Input/output error" and, under set -e,
# aborts this script leaving nothing running. So retry a few times.
bootstrapped=0
for _ in 1 2 3 4 5; do
  if launchctl bootstrap "gui/$UID" "$PLIST" 2>/dev/null; then
    bootstrapped=1
    break
  fi
  sleep 1
done

if [ "$bootstrapped" -ne 1 ] || ! launchctl list | grep -q "$LABEL"; then
  echo >&2
  echo "Warning: the daemon did not start. Start it by hand with:" >&2
  echo "  launchctl bootstrap gui/\$UID $PLIST" >&2
  echo "then check:  launchctl list | grep $LABEL   (middle column 0 = healthy)" >&2
fi

echo
echo "Installed."
echo "  Daemon log:  $STATE_DIR/daemon.log"
echo "  Config:      $STATE_DIR/config.json"
echo
echo "Open a NEW Claude Code session for the hooks to take effect."
