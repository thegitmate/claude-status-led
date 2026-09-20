#!/usr/bin/env bash
# Remove the launchd agent and take our hooks back out of settings.json.
set -euo pipefail

LABEL="com.claude-status-led.daemon"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SETTINGS="$HOME/.claude/settings.json"

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
rm -f "$PLIST"

if [ -f "$SETTINGS" ]; then
  /usr/bin/python3 - "$SETTINGS" <<'PYEOF'
import json, shutil, sys, time
p = sys.argv[1]
shutil.copy(p, p + ".backup-%d" % int(time.time()))
data = json.load(open(p))
hooks = data.get("hooks", {})
for event, entries in list(hooks.items()):
    for entry in list(entries):
        for h in list(entry.get("hooks", [])):
            if "claude_led_hook.py" in h.get("command", ""):
                entry["hooks"].remove(h)
        if not entry.get("hooks"):
            entries.remove(entry)
    if not entries:
        del hooks[event]
if not hooks:
    data.pop("hooks", None)
json.dump(data, open(p, "w"), indent=2)
open(p, "a").write("\n")
print("Hooks removed.")
PYEOF
fi

echo "Uninstalled. Session state in ~/.claude-status-led was left in place."
