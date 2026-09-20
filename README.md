# claude-status-led

An LED on your desk that tells you what Claude Code is doing, without you having to look at the terminal.

| LED | Meaning |
|---|---|
| **Off** | Nothing wants you: no session open, or simply your turn to type |
| **Solid on** | Claude is working |
| **Blinking** | Claude is blocked on you: a permission prompt, or a question it needs answered |

Blinking deliberately does **not** mean "Claude finished its turn". If it did, the light would blink for most of the day and you would learn to ignore it. It blinks only when Claude genuinely cannot continue without you, which keeps it worth looking up for.

It works with several sessions at once. If any session needs you, the light blinks. Otherwise, if any session is working, it stays solid. Otherwise it is off.

Built for macOS and an Arduino Nano. No Arduino IDE needed, no Python packages, no pip, no venv. Everything uses `arduino-cli` and the Python that ships with macOS.

## What you need

- An Arduino Nano (a cheap clone is fine, this is written for one)
- An LED, any colour
- A 220Ω or 330Ω resistor
- A USB **data** cable that fits your Nano. Read that word again, it is the single most common thing that goes wrong. See Troubleshooting.
- A Mac with Homebrew

## One-prompt install

Never touched an Arduino? Don't follow the steps below. Paste this into Claude Code instead, from any folder:

```
Install github.com/thegitmate/claude-status-led on my Mac. Read the README,
do everything you can yourself, and stop to ask me whenever you need hands
on the wiring or eyes on the LED.
```

That is the whole thing. Claude will clone the repo, install `arduino-cli` if it is missing, flash the board, run `install.sh` and confirm the daemon is healthy. It can list your serial ports and read the daemon log, so it can diagnose most of what goes wrong by itself.

The two things it cannot do are hold a wire and see your LED, which is why the prompt tells it to ask you. When it asks what the light did, answer honestly, including "nothing happened": that is useful information, not a failure.

Everything below is the same install done by hand.

## Wiring

```
Nano D9  ──►  [220Ω resistor]  ──►  LED long leg (anode)
                                    LED short leg (cathode)  ──►  Nano GND
```

Three things worth knowing:

- **Polarity matters.** The long leg goes towards the resistor and D9, the short leg to GND. The short-leg side also has a flat notch on the plastic rim. An LED in backwards does nothing at all, and does no harm, so if it stays dark just turn it round.
- **Do not skip the resistor.** An LED straight across a 5V pin draws enough current to damage the LED and the pin.
- **D9, not D13.** Pin 13 already has the Nano's own onboard LED wired in parallel, which makes an external LED dimmer and flashes it on every reset and upload.

## Install

### 1. Install arduino-cli

```bash
brew install arduino-cli
arduino-cli config init
arduino-cli core update-index
arduino-cli core install arduino:avr
```

### 2. Flash the board

Plug in the Nano, then:

```bash
git clone https://github.com/thegitmate/claude-status-led.git
cd claude-status-led
./flash.sh
```

`flash.sh` finds the serial port itself, and if the normal upload fails it automatically retries with the old-bootloader board type that most clone Nanos need. That second attempt is the usual outcome, not an error.

### 3. Install the Mac side

```bash
./install.sh
```

That does three things:

1. Copies the daemon and hook scripts to `~/.claude-status-led/bin/`
2. Adds five hooks to `~/.claude/settings.json`, backing the file up first
3. Installs and starts a launchd agent that runs the daemon

Then **open a new Claude Code session**. Existing sessions do not pick up new hooks.

### Check it worked

```bash
launchctl list | grep claude-status-led   # middle column should be 0
tail -f ~/.claude-status-led/daemon.log   # watch state changes live
```

The log prints a line each time the state changes: `state -> 1` is solid, `2` is blinking, `0` is off.

## Configuration

`~/.claude-status-led/config.json`:

```json
{
  "port": null,
  "stop_state": "waiting",
  "stale_seconds": 43200
}
```

- **`port`** pins a specific serial device. `null` means find it automatically.
- **`stop_state`** controls what happens when Claude finishes its turn. `"idle"` (the default) turns the LED off, because a finished turn is not a request for anything. `"waiting"` blinks every time Claude stops. `"busy"` keeps it solid for the whole session.
- **`blink_timeout_seconds`** is a backstop, default 300. A blink normally clears within about five seconds through transcript watching (below); this only catches the case where the transcript cannot be found. Set to `0` to disable the backstop.
- **`idle_notification_state`** handles the nudge Claude Code fires after roughly 60 seconds of idle input. `"idle"` (the default) ignores it, so stepping away from your desk does not start the light blinking. `"waiting"` blinks for it too.
- **`stale_seconds`** is a safety net for session records whose process could not be identified.
- **`event_log`** writes every hook event to `~/.claude-status-led/events.log`. Leave it on: when the LED does something you did not expect, that file tells you exactly which events arrived, rather than leaving you to guess. It is capped and trims itself.

Changes are picked up within about five seconds, no restart needed.

## Troubleshooting

### The board doesn't appear at all

```bash
ls /dev/cu.*
```

If there is no `usbserial` or `wchusbserial` entry, the Mac cannot see the board.

**It is almost always the cable.** Charge-only USB cables carry power but leave the data lines unconnected. The board's power LED lights up, it boots, it runs its last sketch, and it looks perfectly healthy while being completely invisible to your Mac. A lit power LED is not evidence that the cable works. This project took three cables before one carried data.

Check in this order:

1. Try a different cable, ideally one you have seen move files.
2. Plug directly into the Mac, not through a hub, dock or adapter chain.
3. Check the board's power LED. If it is dark, no power is reaching it at all.

This is not a driver problem. macOS has supported the CH340 chip natively for years, and an unrecognised device would still show up in `ioreg -p IOUSB -l`. If nothing appears there, the problem is physical.

### Upload fails with "not in sync" or "programmer is not responding"

Your board has the old bootloader, which is normal for clones. `flash.sh` handles this automatically. By hand:

```bash
arduino-cli upload -p /dev/cu.usbserial-XXXXX \
  --fqbn arduino:avr:nano:cpu=atmega328old firmware/StatusLed
```

### Daemon won't start: "Operation not permitted"

A launchd agent runs without TCC privileges, so it cannot read files in `~/Documents`, `~/Desktop` or `~/Downloads`. This is why `install.sh` copies the scripts to `~/.claude-status-led/bin/` rather than running them from wherever you cloned the repo.

If you change the code, **re-run `install.sh`** to copy the new version across. Editing the repo alone changes nothing.

### LED stays dark but the daemon log looks right

The daemon only reports what it sent down the wire, it cannot see the light. If the log shows `state -> 1` and nothing lights up, it is the wiring: LED in backwards, wrong pin, or a loose GND.

### LED keeps blinking after I dismissed a prompt

It should clear about five seconds after you press Esc. If it does not, check that the session's transcript can be found:

```bash
ls ~/.claude/projects/*/$(ls -t ~/.claude-status-led/sessions | head -1 | sed 's/.json//').jsonl
```

**Why this needs explaining:** Claude Code fires no hook when you dismiss a prompt with Esc, and an interrupted turn fires no `Stop` either. You can verify this in `~/.claude-status-led/events.log`: press Esc and nothing at all is written between the `Notification` and your next message. Every purely hook-driven status light has this blind spot.

The transcript does record it, though. Claude Code writes a live JSONL transcript per session, and a dismissal appends a tool result and an interrupt line within a second or two, while a genuinely pending prompt writes nothing at all because the session is blocked. So the daemon lets the transcript settle for three seconds, notes its size, and treats any later growth as proof the prompt is gone.

Credit for the idea goes to [Claw Light](https://clawlight.dev/), which watches session files rather than relying on hooks.

### LED stuck on

It should not be possible. The firmware has a watchdog: if nothing is heard for 10 seconds it drops the LED to off by itself, so a crashed daemon or a sleeping Mac cannot leave the light lying to you. If it really is stuck, the board is running old firmware, so re-flash.

## How it works

Three pieces:

```
Claude Code ──hooks──► session files ──► daemon ──serial──► Arduino
```

**Hooks** (`hooks/claude_led_hook.py`) fire on Claude Code session events and write one small JSON file per session into `~/.claude-status-led/sessions/`. They never block and always exit 0, so they cannot break your session.

| Hook event | State written |
|---|---|
| `UserPromptSubmit`, `PostToolUse` | `busy` |
| `Notification` (permission or question) | `waiting` |
| `Notification` (60s idle nudge) | `idle` |
| `SessionStart`, `Stop` | `idle` |
| `SessionEnd` | file removed |

States are `busy` (solid), `waiting` (blink) and `idle` (off). `idle` is not special cased in the daemon: anything that is neither `busy` nor `waiting` contributes nothing, so an idle session stays tracked for liveness while leaving the LED dark.

**The daemon** (`daemon/claude_led_daemon.py`) polls those files five times a second, aggregates them and sends a single byte to the board.

**The firmware** (`firmware/StatusLed/StatusLed.ino`) reads that byte: `0` off, `1` on, `2` blink, `p` heartbeat.

Two design decisions worth explaining:

- **Why a daemon rather than hooks writing to the serial port?** Opening a serial port pulls DTR, which resets the Nano. Doing that on every hook would mean a board reset and a bootloader stall several times per prompt. The daemon opens the port once and holds it.
- **Why does the blinking happen on the Arduino?** So the rhythm never depends on the Mac. The daemon sends "blink" once, and the board handles it from there.

A blinking session is cleared by watching its transcript grow, not by an event, because no dismissal event exists. See the troubleshooting section for why.

Answering a question and dismissing one both grow the transcript identically, so the transcript cannot tell them apart. `PostToolUse` does: only an answer completes the tool. That is why it is registered despite firing on every tool call, and why the hook reuses a cached pid rather than walking the process tree each time (21ms instead of about 70ms).

**Several sessions at once** are aggregated, so the light reflects whichever session most wants you, not whichever terminal you are looking at. If any session is blocked on you it blinks, even if that session is buried behind other windows. Otherwise, if any session is working it stays solid. Only when nothing is working and nothing is waiting does it go off.

Dead sessions are detected by process id. The hook walks up its parent chain to find the owning `claude` process and records its pid; the daemon drops any record whose process has gone. This matters because a session killed with ctrl-C or a closed terminal never fires `SessionEnd`.

Note the pid lookup matches the process *name*, not its command line. A substring match would match the shell running the hook, since that shell's command line contains "claude-status-led", and that shell exits immediately, so every session would look dead the moment it started.

## Uninstall

```bash
./uninstall.sh
```

Stops the agent and removes the hooks from `settings.json`, backing it up first. Your session state directory is left alone, delete `~/.claude-status-led` by hand if you want it gone. The firmware stays on the board until you flash something else over it.

## Licence

MIT
