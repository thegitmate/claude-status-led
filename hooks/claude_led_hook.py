#!/usr/bin/env python3
"""
claude-status-led - Claude Code hook.

Claude Code runs this on session events. It does one cheap thing:
write this session's state to ~/.claude-status-led/sessions/<id>.json.
The daemon reads those files and drives the LED.

Event -> state mapping:

    SessionStart      busy     a session opened
    UserPromptSubmit  busy     you sent a prompt, Claude is working
    Notification      waiting  Claude wants permission or input
    Stop              waiting  Claude finished, your turn
    SessionEnd        (file removed)

Set "stop_state": "busy" in ~/.claude-status-led/config.json if you would
rather the LED stay solid when Claude finishes and only blink on
permission prompts.

This must never break a Claude session, so every path is wrapped and the
exit code is always 0. Standard library only.
"""

import json
import os
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
STATE_DIR = os.path.join(HOME, ".claude-status-led")
SESSION_DIR = os.path.join(STATE_DIR, "sessions")
CONFIG_PATH = os.path.join(STATE_DIR, "config.json")

EVENT_STATE = {
    "SessionStart": "busy",
    "UserPromptSubmit": "busy",
    "PreToolUse": "busy",
    "PostToolUse": "busy",
    "Notification": "waiting",
    "Stop": "waiting",
}


def load_config():
    try:
        with open(CONFIG_PATH) as fh:
            return json.load(fh)
    except Exception:
        return {}


def find_claude_pid():
    """
    Walk up the parent chain to find the Claude Code process that owns this
    hook. The daemon uses this pid to tell a live session from a dead one,
    because a session killed with ctrl-C never fires SessionEnd.
    """
    pid = os.getppid()
    for _ in range(6):
        if pid <= 1:
            return None
        try:
            out = subprocess.check_output(
                ["ps", "-o", "ppid=,comm=", "-p", str(pid)],
                stderr=subprocess.DEVNULL,
            ).decode("utf-8", "replace").strip()
        except Exception:
            return None
        parts = out.split(None, 1)
        if len(parts) < 2:
            return None
        parent, comm = parts[0], parts[1]
        # Match the executable NAME, never the full command line. The shell
        # that runs this hook has "claude-status-led" in its command string
        # and would match a substring test, and that shell exits the moment
        # the hook returns, so the daemon would treat the session as dead.
        if os.path.basename(comm.strip()).lower() == "claude":
            return pid
        try:
            pid = int(parent)
        except ValueError:
            return None
    return None


def main():
    # Event name comes from argv (how we configure it) or the hook payload.
    event = sys.argv[1] if len(sys.argv) > 1 else None

    payload = {}
    try:
        raw = sys.stdin.read()
        if raw.strip():
            payload = json.loads(raw)
    except Exception:
        payload = {}

    if not event:
        event = payload.get("hook_event_name", "")

    session_id = payload.get("session_id") or ("pid-%d" % os.getppid())
    # Keep the filename tame whatever the id looks like.
    safe_id = "".join(c for c in str(session_id) if c.isalnum() or c in "-_")[:80]
    if not safe_id:
        safe_id = "unknown"

    path = os.path.join(SESSION_DIR, safe_id + ".json")

    if event == "SessionEnd":
        try:
            os.remove(path)
        except OSError:
            pass
        return

    state = EVENT_STATE.get(event)
    if state is None:
        return

    if event == "Stop":
        state = load_config().get("stop_state", "waiting")

    record = {
        "state": state,
        "event": event,
        "ts": time.time(),
        "pid": find_claude_pid(),
    }

    try:
        os.makedirs(SESSION_DIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(record, fh)
        os.replace(tmp, path)     # atomic, the daemon never sees a half file
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
