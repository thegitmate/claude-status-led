#!/usr/bin/env python3
"""
claude-status-led - Mac-side daemon.

Owns the serial port and pushes one byte of state to the Arduino:

    '0' off    - no Claude Code session open
    '1' on     - a session is open and working
    '2' blink  - a session is waiting on you
    'p' ping   - heartbeat so the board's watchdog stays fed

Why a daemon rather than talking to the board straight from the hooks:
opening the serial port pulls DTR and RESETS the Nano, costing a
bootloader stall every time. This process opens the port once and
holds it for as long as it lives.

Session state is read from ~/.claude-status-led/sessions/*.json, one
file per Claude Code session, written by the hook script. Several
sessions can be open at once, so the states are aggregated:
any session waiting wins, otherwise any session working wins,
otherwise the LED is off.

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
SESSION_DIR = os.path.join(STATE_DIR, "sessions")
CONFIG_PATH = os.path.join(STATE_DIR, "config.json")

POLL_SECONDS = 0.2          # how often we re-read session state
PING_SECONDS = 2.0          # heartbeat interval, must be < firmware watchdog
REOPEN_SECONDS = 2.0        # retry cadence when the board is missing
STALE_SECONDS_DEFAULT = 12 * 3600

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
    except OSError:
        return False
    except Exception:
        return False


def desired_state(cfg):
    """Aggregate every session file into a single state byte."""
    stale_after = cfg.get("stale_seconds", STALE_SECONDS_DEFAULT)
    now = time.time()
    any_busy = False
    any_waiting = False

    try:
        entries = os.listdir(SESSION_DIR)
    except OSError:
        return b"0"

    for name in entries:
        if not name.endswith(".json"):
            continue
        path = os.path.join(SESSION_DIR, name)
        try:
            with open(path) as fh:
                rec = json.load(fh)
        except Exception:
            continue

        # Drop records whose owning Claude process has gone away. This is
        # the reliable check: a session killed with ctrl-C or a closed
        # terminal never fires SessionEnd, so its file would linger.
        pid = rec.get("pid")
        if isinstance(pid, int) and not pid_alive(pid):
            try:
                os.remove(path)
            except OSError:
                pass
            continue

        # Fallback for records with no usable pid.
        ts = rec.get("ts", 0)
        if pid is None and (now - ts) > stale_after:
            try:
                os.remove(path)
            except OSError:
                pass
            continue

        state = rec.get("state")
        if state == "waiting":
            any_waiting = True
        elif state == "busy":
            any_busy = True

    if any_waiting:
        return b"2"
    if any_busy:
        return b"1"
    return b"0"


def shutdown(signum, frame):
    global _running
    _running = False


def main():
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    os.makedirs(SESSION_DIR, exist_ok=True)
    cfg = load_config()

    fd = None
    port_path = None
    last_sent = None
    last_ping = 0.0
    last_open_attempt = 0.0
    cfg_checked = 0.0

    log("daemon starting; sessions dir %s" % SESSION_DIR)

    while _running:
        now = time.time()

        # Pick up config edits without a restart.
        if now - cfg_checked > 5:
            cfg = load_config()
            cfg_checked = now

        if fd is None and now - last_open_attempt >= REOPEN_SECONDS:
            last_open_attempt = now
            port_path = find_port(cfg)
            if port_path:
                try:
                    fd = open_port(port_path)
                    # Opening resets the board; give the bootloader time
                    # to hand over to the sketch before we send anything.
                    time.sleep(3)
                    last_sent = None      # force a resend of current state
                    log("opened %s" % port_path)
                except Exception as exc:
                    log("could not open %s: %s" % (port_path, exc))
                    fd = None

        if fd is not None:
            want = desired_state(cfg)
            try:
                if want != last_sent:
                    os.write(fd, want)
                    last_sent = want
                    last_ping = now
                    log("state -> %s" % want.decode())
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
