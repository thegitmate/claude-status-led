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

A "waiting" record is cleared as soon as the session's transcript grows,
which is how a dismissed prompt is detected: Claude Code fires no hook for
it, but it does write one. blink_timeout_seconds remains as a backstop.
See blink_is_stale.

A session record may also hold the state "idle", meaning the session is
open but nothing wants your attention. It is deliberately not special
cased below: anything that is neither "waiting" nor "busy" contributes
nothing, so an idle session keeps being tracked for liveness while
leaving the LED dark.

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
BLINK_TIMEOUT_DEFAULT = 300 # backstop only; transcript watching does the real work
BLINK_GRACE_SECONDS = 3     # settle time before we trust the transcript baseline

TRANSCRIPT_ROOT = os.path.join(HOME, ".claude", "projects")

# sid -> transcript path, and sid -> (record ts, transcript size at grace point)
_transcript_paths = {}
_blink_baselines = {}


def transcript_for(session_id):
    """
    Locate a session's live JSONL transcript. Claude Code names it after the
    session id, so the session file name is enough to find it. Cached,
    because this globs the project tree.
    """
    cached = _transcript_paths.get(session_id)
    if cached and os.path.exists(cached):
        return cached
    if cached is False:
        return None
    matches = glob.glob(os.path.join(TRANSCRIPT_ROOT, "**", session_id + ".jsonl"),
                        recursive=True)
    path = matches[0] if matches else None
    _transcript_paths[session_id] = path if path else False
    return path


# Transcript entry types that represent an actual conversational turn.
# Everything else Claude Code writes is housekeeping.
CONVERSATION_TYPES = ("user", "assistant", "system")

# Housekeeping Claude Code appends while a prompt is sitting unanswered:
# file-history-snapshot, last-prompt, ai-title, mode, permission-mode,
# atis-latch. These must NOT be read as "the prompt went away".

MAX_TAIL_BYTES = 2 * 1024 * 1024


INTERRUPT_PREFIX = "[Request interrupted by user"

# sid -> (record ts, byte offset) for busy records
_busy_baselines = {}


def read_tail(path, offset):
    """Return everything appended past `offset`, or None."""
    try:
        if os.path.getsize(path) <= offset:
            return None
        with open(path, "rb") as fh:
            fh.seek(offset)
            return fh.read(MAX_TAIL_BYTES)
    except OSError:
        return None


def entry_is_interrupt(entry):
    """
    True for the line Claude Code writes when a turn is interrupted:
    a user entry whose content starts with "[Request interrupted by user".

    Note this parses properly rather than searching the raw text. That
    string appears in ordinary assistant messages whenever the interrupt
    behaviour is being discussed, and a substring match would treat Claude
    talking about interrupts as an interrupt.
    """
    if entry.get("type") != "user":
        return False
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content.startswith(INTERRUPT_PREFIX)
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and \
                    str(block.get("text", "")).startswith(INTERRUPT_PREFIX):
                return True
    return False


def busy_is_stale(session_id, rec_ts, now):
    """
    Decide whether a session that looks busy has actually been stopped.

    Interrupting a turn (Esc while Claude is working) fires no hook at all,
    so the session record stays "busy" and the LED stays lit until the next
    prompt, sometimes for a long time. The transcript does record it.

    Deliberately not done by watching for the transcript going quiet: a
    single long tool call writes nothing for minutes while genuinely
    working, so silence is not evidence of having stopped.
    """
    path = transcript_for(session_id)
    if not path:
        return False

    baseline = _busy_baselines.get(session_id)
    if baseline is None or baseline[0] != rec_ts:
        try:
            _busy_baselines[session_id] = (rec_ts, os.path.getsize(path))
        except OSError:
            pass
        return False

    tail = read_tail(path, baseline[1])
    if not tail:
        return False

    for line in tail.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line.decode("utf-8", "replace"))
        except Exception:
            continue
        if entry_is_interrupt(entry):
            return True
    return False


def blink_is_stale(session_id, rec_ts, now):
    """
    Decide whether a blinking prompt has already been answered or dismissed.

    Claude Code fires no hook when you press Esc, so there is no event to
    listen for. The transcript does record it, as a tool_result plus an
    interrupt line within a second or two.

    The subtlety: a pending prompt is NOT a silent transcript. Claude Code
    keeps appending housekeeping lines (last-prompt, ai-title, mode,
    permission-mode, atis-latch, file-history-snapshot) the whole time you
    are looking at the question. An earlier version of this treated any
    growth as resolution, which killed the blink roughly a minute into an
    unanswered prompt.

    So we read what was actually appended and only count a real
    conversational entry.
    """
    path = transcript_for(session_id)
    if not path:
        return False                      # no transcript, fall back to timeout

    age = now - rec_ts
    if age < BLINK_GRACE_SECONDS:
        return False                      # too early to trust a baseline

    baseline = _blink_baselines.get(session_id)
    if baseline is None or baseline[0] != rec_ts:
        try:
            _blink_baselines[session_id] = (rec_ts, os.path.getsize(path))
        except OSError:
            pass
        return False

    tail = read_tail(path, baseline[1])
    if not tail:
        return False

    for line in tail.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line.decode("utf-8", "replace"))
        except Exception:
            continue                      # partial write, try again next poll
        if entry.get("type") in CONVERSATION_TYPES:
            return True
    return False
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

        # Bound how long a blink can last.
        #
        # Claude Code fires NO hook when you dismiss a prompt with Esc, and an
        # interrupted turn does not fire Stop either (verified by logging every
        # event to events.log and pressing Esc). So there is no event that can
        # tell us a question went away. Without a timeout the LED blinks at a
        # prompt that is no longer on screen until you happen to send your next
        # message, which is worse than not blinking at all: a light that lies
        # is a light you learn to ignore.
        #
        # After the timeout the blink decays and the LED goes off. Set
        # "blink_timeout_seconds": 0 to blink indefinitely instead.
        session_id = name[:-5]

        if state == "waiting":
            rec_ts = rec.get("ts", 0)
            if blink_is_stale(session_id, rec_ts, now):
                state = "idle"
            elif transcript_for(session_id) is None:
                # Backstop, and ONLY for sessions whose transcript we cannot
                # find. Where a transcript exists it is authoritative: a
                # question that is genuinely still on screen should keep
                # blinking however long you take, and a timeout here would
                # silently cut it off mid-prompt.
                timeout = cfg.get("blink_timeout_seconds", BLINK_TIMEOUT_DEFAULT)
                if timeout and (now - rec_ts) > timeout:
                    state = "idle"

        if state == "waiting":
            any_waiting = True
        elif state == "busy":
            if busy_is_stale(session_id, rec.get("ts", 0), now):
                state = "idle"
            else:
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
