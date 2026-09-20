#!/usr/bin/env bash
# Remove the launchd agent, and any hooks left by an older version.
set -euo pipefail

LABEL="com.claude-status-led.daemon"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SETTINGS="$HOME/.claude/settings.json"

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
rm -f "$PLIST"

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
    print("Removed %d hook(s)." % removed)
PYEOF
fi

echo "Uninstalled. ~/.claude-status-led was left in place; delete it to remove config and logs."
