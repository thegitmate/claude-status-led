# claude-status-led

An LED on your desk that shows what Claude Code is doing, so you can stop watching the terminal.

| LED | Meaning |
|---|---|
| **Off** | Nothing wants you: no session, or your turn to type |
| **Solid** | Claude is working |
| **Blink** | Claude is blocked on you: a permission prompt or a question |

Works across several sessions at once. If any session needs you it blinks, even if that terminal is buried behind other windows.

macOS and an Arduino Nano. No Arduino IDE, no pip, no venv, and no Claude Code hooks: it reads Claude Code's own session state, so it adds nothing to your sessions.

## Install with one prompt

```
Install github.com/thegitmate/claude-status-led on my Mac. Follow its README and
run the steps for me rather than listing them. Ask me when you need the wiring
checked or need to know what the LED is doing.
```

## Hardware

- Arduino Nano (a cheap clone is fine)
- LED, any colour
- 220Ω or 330Ω resistor
- A USB **data** cable. Charge-only cables light the board's power LED while staying invisible to your Mac, and are the most common cause of "it doesn't work".

```
Nano D9  ──►  [220Ω]  ──►  LED long leg
                           LED short leg  ──►  Nano GND
```

Long leg towards the resistor. Backwards does nothing and harms nothing. Use D9, not D13: pin 13 shares the onboard LED, which dims yours and flashes on every reset.

## Manual install

```bash
brew install arduino-cli
arduino-cli config init && arduino-cli core update-index && arduino-cli core install arduino:avr

git clone https://github.com/thegitmate/claude-status-led.git
cd claude-status-led
./flash.sh      # finds the port, retries with the old-bootloader board type
./install.sh    # hooks + launchd agent
```

Then open a new Claude Code session. Existing sessions do not pick up new hooks.

Verify:

```bash
launchctl list | grep claude-status-led   # middle column 0 = healthy
tail -f ~/.claude-status-led/daemon.log    # state -> 0 off, 1 solid, 2 blink
```

## Tests

```bash
/usr/bin/python3 tests/test_states.py
```

Thirteen state-aggregation cases, run against temporary directories. They never touch live session state, so they do not drive your LED.

## Configuration

`~/.claude-status-led/config.json`:

| Key | Default | Meaning |
|---|---|---|
| `port` | `null` | Pin a serial device, or autodetect |
| `stop_state` | `idle` | What happens when Claude finishes a turn. `waiting` blinks instead |
| `idle_notification_state` | `idle` | Whether the 60s idle nudge blinks |
| `blink_timeout_seconds` | `300` | Backstop for sessions with no findable transcript. Ignored when one exists |
| `busy_silence_seconds` | `60` | Turn the LED off when a busy session writes nothing at all for this long. Catches stopping Claude before it replies |
| `stale_seconds` | `43200` | Fallback expiry for unidentifiable sessions |
| `event_log` | `true` | Log every hook event to `events.log`. Leave on |

Picked up within 5 seconds, no restart.

## Troubleshooting

**Board does not appear in `ls /dev/cu.*`** Try another cable, then plug straight into the Mac with no hub. Not a driver problem: an unrecognised device would still show in `ioreg -p IOUSB -l`.

**Upload fails, "not in sync"** Clone board with the old bootloader. `flash.sh` retries automatically.

**Daemon: "Operation not permitted"** launchd cannot read `~/Documents`. `install.sh` copies the daemon to `~/.claude-status-led/bin/`, so **re-run `install.sh` after changing code**.

**LED dark but the log says `state -> 1`** Wiring. The daemon reports what it sent, it cannot see the light.

**LED stuck on** The firmware drops to off after 10s of silence, so this should be impossible. If it happens, reflash.

**LED never comes on** Check `~/.claude/sessions/` exists and holds a `.json` per running session. Everything depends on it:

```bash
cat ~/.claude/sessions/*.json | /usr/bin/python3 -c "import json,sys
for l in sys.stdin.read().replace('}{','}\n{').splitlines(): print(json.loads(l)['status'])"
```

`~/.claude-status-led/daemon.log` names the session behind every state change.

## How it works

```
~/.claude/sessions/<pid>.json  ──►  daemon  ──serial──►  Arduino
```

Claude Code writes a live record per session carrying a `status` of `busy`, `waiting`, `idle` or `shell`. A launchd daemon reads them twice a second, aggregates, and sends one byte: `0` off, `1` on, `2` blink, `p` heartbeat. Blinking runs on the board, so its rhythm never depends on the Mac.

**No hooks.** An earlier version used them and needed transcript parsing, timeouts and a silence fallback to cover the cases where Claude Code fires nothing, at a cost of a process spawn on every tool call. Reading Claude Code's own state removed all of it.

Further reading:

- **[docs/LESSONS.md](docs/LESSONS.md)** what goes wrong building one of these, and how each was found. The useful document if you are building something similar.
- **[docs/DESIGN.md](docs/DESIGN.md)** why it is built this way.
- **[docs/OTHER-AGENTS.md](docs/OTHER-AGENTS.md)** notes on extending it to Codex CLI, OpenCode and Grok Build.

## Uninstall

```bash
./uninstall.sh
```

Removes the agent and the hooks, backing up `settings.json` first. `~/.claude-status-led` is left in place.

## Credits

Transcript watching borrowed from [Claw Light](https://clawlight.dev/).

## Licence

MIT
