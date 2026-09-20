#!/usr/bin/env python3
"""
claude-status-led - Mac-side daemon.

Reads Claude Code's own session state and pushes one byte to the Arduino:

    '0' off    - nothing wants you
    '1' on     - Claude is working
    '2' blink  - Claude is blocked on you
    'p' ping   - heartbeat so the board's watchdog stays fed

State comes from ~/.claude/sessions/<pid>.json, which Claude Code writes
and keeps current by itself:

    {"pid": 95237, "sessionId": "...", "status": "busy", ...}

    busy     working                              -> solid
    waiting  wants something from you             -> blink
    idle     session doing nothing                -> off
    shell    back at the prompt, awaiting input   -> off

"shell" is not what it sounds like: during an actual Bash tool call the
status is "busy". It means the prompt is waiting for you, and it is the
only signal for a prompt that was submitted and then cancelled.

This replaced a hook-based implementation. Hooks are silent for anything
abandoned (dismissed prompts, interrupted turns, cancelled submissions),
which needed transcript parsing, timeouts and a silence fallback to work
around, and cost a process spawn on every single tool call. None of that
is needed here. See docs/LESSONS.md.

Several sessions are aggregated: any session waiting wins and blinks,
otherwise any session working is solid, otherwise off.

Standard library only. No pip, no venv.
"""

import glob
import json
import os
import signal
import sys
import termios
import time

HOME = os.path.expanduser("~")
STATE_DIR = os.path.join(HOME, ".claude-status-led")
CONFIG_PATH = os.path.join(STATE_DIR, "config.json")
CLAUDE_SESSIONS_DIR = os.path.join(HOME, ".claude", "sessions")

POLL_SECONDS = 0.5          # twice a second; a human cannot see faster
PING_SECONDS = 2.0          # heartbeat, must stay under the firmware watchdog
REOPEN_SECONDS = 2.0        # retry cadence when the board is missing

WORKING = ("busy",)
BLOCKED = ("waiting",)
# Anything else, including "idle" and "shell", means nothing wants you.

PORT_GLOBS = [
    "/dev/cu.usbserial*",     # CH340 clones
    "/dev/cu.wchusbserial*",  # CH340 under some driver versions
    "/dev/cu.usbmodem*",      # genuine boards with native USB
]

_running = True


def log(msg):
    sys.stderr.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    sys.stderr.flush()


def load_config():
    try:
        with open(CONFIG_PATH) as fh:
            return json.load(fh)
    except Exception:
        return {}


def find_port(cfg):
    """Return a serial device path, or None. Config can pin one explicitly."""
    pinned = cfg.get("port")
    if pinned:
        return pinned if os.path.exists(pinned) else None
    for pattern in PORT_GLOBS:
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[0]
    return None


def open_port(path):
    """Open and configure the port at 9600 8N1 raw. Returns an fd."""
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY)
    iflag, oflag, cflag, lflag, _ispeed, _ospeed, cc = termios.tcgetattr(fd)
    iflag &= ~(termios.IGNBRK | termios.BRKINT | termios.PARMRK |
               termios.ISTRIP | termios.INLCR | termios.IGNCR |
               termios.ICRNL | termios.IXON)
    oflag &= ~termios.OPOST
    lflag &= ~(termios.ECHO | termios.ECHONL | termios.ICANON |
               termios.ISIG | termios.IEXTEN)
    cflag &= ~(termios.CSIZE | termios.PARENB)
    cflag |= termios.CS8 | termios.CREAD | termios.CLOCAL
    termios.tcsetattr(fd, termios.TCSANOW,
                      [iflag, oflag, cflag, lflag,
                       termios.B9600, termios.B9600, cc])
    return fd


def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def session_statuses():
    """
    Return {session_id: status} from Claude Code's own records.

    The files are named by process id, but the identity that matters is the
    sessionId inside. Records whose process has gone are skipped, so a
    crashed terminal stops counting without needing any cleanup.
    """
    statuses = {}
    try:
        names = os.listdir(CLAUDE_SESSIONS_DIR)
    except OSError:
        return statuses

    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(CLAUDE_SESSIONS_DIR, name)) as fh:
                record = json.load(fh)
        except Exception:
            continue          # mid-write, try again next poll
        session_id = record.get("sessionId")
        pid = record.get("pid")
        if not session_id or not isinstance(pid, int) or not pid_alive(pid):
            continue
        statuses[session_id] = record.get("status")
    return statuses


def desired_state(statuses):
    """Aggregate every session into a single state byte."""
    values = statuses.values()
    if any(s in BLOCKED for s in values):
        return b"2"
    if any(s in WORKING for s in values):
        return b"1"
    return b"0"


def describe(statuses):
    if not statuses:
        return "no sessions"
    return ", ".join("%s=%s" % (k[:8], v) for k, v in sorted(statuses.items()))


def shutdown(signum, frame):
    global _running
    _running = False


def main():
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    cfg = load_config()
    if not os.path.isdir(CLAUDE_SESSIONS_DIR):
        log("warning: %s does not exist; the LED will stay off" % CLAUDE_SESSIONS_DIR)

    fd = None
    last_sent = None
    last_ping = 0.0
    last_open_attempt = 0.0
    cfg_checked = 0.0

    log("daemon starting; reading %s" % CLAUDE_SESSIONS_DIR)

    while _running:
        now = time.time()

        if now - cfg_checked > 5:
            cfg = load_config()
            cfg_checked = now

        if fd is None and now - last_open_attempt >= REOPEN_SECONDS:
            last_open_attempt = now
            port_path = find_port(cfg)
            if port_path:
                try:
                    fd = open_port(port_path)
                    # Opening resets the board; let the bootloader hand over.
                    time.sleep(3)
                    last_sent = None
                    log("opened %s" % port_path)
                except Exception as exc:
                    log("could not open %s: %s" % (port_path, exc))
                    fd = None

        if fd is not None:
            statuses = session_statuses()
            want = desired_state(statuses)
            try:
                if want != last_sent:
                    os.write(fd, want)
                    last_sent = want
                    last_ping = now
                    log("state -> %s (%s)" % (want.decode(), describe(statuses)))
                elif now - last_ping >= PING_SECONDS:
                    os.write(fd, b"p")
                    last_ping = now
            except OSError as exc:
                log("write failed (%s); board unplugged?" % exc)
                try:
                    os.close(fd)
                except OSError:
                    pass
                fd = None
                last_sent = None

        time.sleep(POLL_SECONDS)

    if fd is not None:
        try:
            os.write(fd, b"0")
            time.sleep(0.1)
            os.close(fd)
        except OSError:
            pass
    log("daemon stopped")


if __name__ == "__main__":
    main()
