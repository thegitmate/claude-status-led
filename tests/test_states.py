#!/usr/bin/env python3
"""
State aggregation tests for claude-status-led.

Run against temporary directories, never live state, so they cannot drive
the real LED. An earlier round of ad hoc testing wrote to the live session
directory and made the light flicker on the desk of whoever was watching.

    /usr/bin/python3 tests/test_states.py
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "led_daemon", os.path.join(HERE, "..", "daemon", "claude_led_daemon.py"))
daemon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daemon)

LED = {b"0": "OFF", b"1": "SOLID", b"2": "BLINK"}
ALIVE = os.getpid()
DEAD = 999999
failures = []


def check(label, expected, got):
    if expected != got:
        failures.append(label)
    print("  %-56s %-6s %s" % (label, LED.get(got, got),
                               "" if expected == got else "FAIL (wanted %s)" % LED[expected]))


def aggregate(sessions):
    """sessions: list of (session_id, status, pid)."""
    root = tempfile.mkdtemp()
    try:
        for i, (sid, status, pid) in enumerate(sessions):
            json.dump({"pid": pid, "sessionId": sid, "status": status},
                      open(os.path.join(root, "%d.json" % (1000 + i)), "w"))
        daemon.CLAUDE_SESSIONS_DIR = root
        return daemon.desired_state(daemon.session_statuses())
    finally:
        shutil.rmtree(root, ignore_errors=True)


print("single session")
check("busy",    b"1", aggregate([("s1", "busy", ALIVE)]))
check("waiting", b"2", aggregate([("s1", "waiting", ALIVE)]))
check("idle",    b"0", aggregate([("s1", "idle", ALIVE)]))
check("shell (prompt awaiting you, incl. a cancelled submit)",
                 b"0", aggregate([("s1", "shell", ALIVE)]))
check("no sessions at all", b"0", aggregate([]))
check("an unknown future status is treated as not working",
                 b"0", aggregate([("s1", "something-new", ALIVE)]))

print("\nseveral sessions: whoever most wants you wins")
check("one working, one asking",
      b"2", aggregate([("s1", "busy", ALIVE), ("s2", "waiting", ALIVE)]))
check("one working, two at the prompt",
      b"1", aggregate([("s1", "busy", ALIVE), ("s2", "shell", ALIVE), ("s3", "idle", ALIVE)]))
check("all at the prompt or idle",
      b"0", aggregate([("s1", "shell", ALIVE), ("s2", "idle", ALIVE)]))
check("asking wins even when buried behind working sessions",
      b"2", aggregate([("s1", "busy", ALIVE), ("s2", "busy", ALIVE), ("s3", "waiting", ALIVE)]))

print("\ndead sessions stop counting")
check("a killed terminal still marked busy",
      b"0", aggregate([("s1", "busy", DEAD)]))
check("dead busy session alongside a live idle one",
      b"0", aggregate([("s1", "busy", DEAD), ("s2", "idle", ALIVE)]))
check("dead session ignored, live one still blinks",
      b"2", aggregate([("s1", "busy", DEAD), ("s2", "waiting", ALIVE)]))

print("\n%s" % ("ALL PASS" if not failures else "%d FAILED: %s" % (len(failures), failures)))
sys.exit(1 if failures else 0)
