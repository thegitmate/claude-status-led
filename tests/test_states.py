#!/usr/bin/env python3
"""
State aggregation tests for claude-status-led.

These run entirely against temporary directories. They do NOT touch the
live session state and so never drive the real LED, which earlier ad hoc
testing did: every verification run made the light flicker through several
states on the desk of whoever was watching.

    /usr/bin/python3 tests/test_states.py
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.join(HERE, "..", "daemon", "claude_led_daemon.py")

spec = importlib.util.spec_from_file_location("led_daemon", DAEMON)
daemon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daemon)

LED = {b"0": "OFF", b"1": "SOLID", b"2": "BLINK"}
ALIVE = os.getpid()
DEAD = None          # filled in below

failures = []


def check(label, expected, got):
    ok = expected == got
    if not ok:
        failures.append(label)
    print("  %-58s %-6s %s" % (label, LED.get(got, got),
                               "" if ok else "FAIL (wanted %s)" % LED[expected]))


def build(claude_sessions, hook_records, transcripts=None):
    """Point the daemon at throwaway directories and aggregate once."""
    root = tempfile.mkdtemp()
    cc = os.path.join(root, "cc")
    hooks = os.path.join(root, "hooks")
    proj = os.path.join(root, "projects")
    for d in (cc, hooks, proj):
        os.makedirs(d)

    for i, (sid, status) in enumerate(claude_sessions.items()):
        json.dump({"pid": ALIVE, "sessionId": sid, "status": status},
                  open(os.path.join(cc, "%d.json" % (1000 + i)), "w"))

    for sid, rec in hook_records.items():
        rec = dict(rec)
        rec.setdefault("ts", time.time())
        rec.setdefault("pid", ALIVE)
        rec.setdefault("event", "test")
        json.dump(rec, open(os.path.join(hooks, sid + ".json"), "w"))

    for sid, lines in (transcripts or {}).items():
        with open(os.path.join(proj, sid + ".jsonl"), "w") as fh:
            for line in lines:
                fh.write(json.dumps(line) + "\n")

    daemon.CLAUDE_SESSIONS_DIR = cc
    daemon.SESSION_DIR = hooks
    daemon.TRANSCRIPT_ROOT = proj
    daemon._transcript_paths.clear()
    daemon._blink_baselines.clear()
    daemon._busy_baselines.clear()

    try:
        return daemon.desired_state({})
    finally:
        shutil.rmtree(root, ignore_errors=True)


print("Claude Code's status is primary")
check("claude busy, hook record says idle",
      b"1", build({"s1": "busy"}, {"s1": {"state": "idle"}}))
check("claude waiting, no hook record at all",
      b"2", build({"s1": "waiting"}, {}))
check("claude shell while hooks think it is busy (cancelled prompt)",
      b"0", build({"s1": "shell"}, {"s1": {"state": "busy"}}))
check("claude idle while hooks think it is waiting",
      b"0", build({"s1": "idle"}, {"s1": {"state": "waiting"}}))

print("\nFallback to hooks when Claude Code does not report the session")
check("hooks busy", b"1", build({}, {"s1": {"state": "busy"}}))
check("hooks waiting", b"2", build({}, {"s1": {"state": "waiting"}}))
check("hooks idle", b"0", build({}, {"s1": {"state": "idle"}}))
check("no sessions at all", b"0", build({}, {}))

print("\nAggregation across several sessions")
check("one working, one asking: asking wins",
      b"2", build({"s1": "busy", "s2": "waiting"}, {}))
check("one working, two idle",
      b"1", build({"s1": "busy", "s2": "idle", "s3": "idle"}, {}))
check("all idle or at the prompt",
      b"0", build({"s1": "idle", "s2": "shell"}, {}))
check("claude idle but another session's hooks say waiting",
      b"2", build({"s1": "idle"}, {"s1": {"state": "busy"}, "s2": {"state": "waiting"}}))

print("\nDead sessions are dropped")
DEAD = 999999
check("hook record whose process has gone",
      b"0", build({}, {"s1": {"state": "busy", "pid": DEAD}}))

print("\n%s" % ("ALL PASS" if not failures else "%d FAILED: %s" % (len(failures), failures)))
sys.exit(1 if failures else 0)
