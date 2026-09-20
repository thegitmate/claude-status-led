# claude-status-led

An LED on your desk that shows what Claude Code is doing, so you can stop watching the terminal.

| LED | Meaning |
|---|---|
| **Off** | Nothing wants you: no session, or your turn to type |
| **Solid** | Claude is working |
| **Blink** | Claude is blocked on you: a permission prompt or a question |

Works across several sessions at once. If any session needs you it blinks, even if that terminal is buried behind other windows.

macOS and an Arduino Nano. No Arduino IDE, no pip, no venv.

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

**Daemon: "Operation not permitted"** launchd cannot read `~/Documents`. `install.sh` copies scripts to `~/.claude-status-led/bin/`, so **re-run `install.sh` after changing code**.

**LED blinks at a prompt you dismissed** Clears in about 5 seconds. If not, the session transcript could not be found.

**LED dark but the log says `state -> 1`** Wiring. The daemon reports what it sent, it cannot see the light.

**LED stays on after you stop Claude mid-answer** Interrupting fires no hook, so the daemon watches the transcript for the interrupt entry instead. Clears within a couple of seconds.

**LED stays on if you stop Claude before it replies** Cleared using Claude Code's own session status at `~/.claude/sessions/<pid>.json`, which reports `idle` even though no hook fires and nothing is written to the transcript.

**LED stays on if you stop Claude before it replies (fallback)** Nothing is written in that case, not even an interrupt marker, so it clears after `busy_silence_seconds` (60) instead. It cannot be made faster without switching the light off during slow replies, which take up to 59 seconds to produce their first output.

**LED stuck on with no session running** The firmware drops to off after 10s of silence, so this should be impossible. If it happens, reflash.

When anything is odd, read `~/.claude-status-led/events.log`. It shows exactly which events arrived.

## How it works

```
Claude Code ──hooks──► session files ──► daemon ──serial──► Arduino
```

One JSON file per session, aggregated by a launchd daemon that holds the serial port and sends one byte: `0` off, `1` on, `2` blink, `p` heartbeat. Blinking runs on the board, so its rhythm never depends on the Mac.

Several decisions here are non-obvious and were arrived at by being wrong first. See **[docs/DESIGN.md](docs/DESIGN.md)**.

## Uninstall

```bash
./uninstall.sh
```

Removes the agent and the hooks, backing up `settings.json` first. `~/.claude-status-led` is left in place.

## Credits

Transcript watching borrowed from [Claw Light](https://clawlight.dev/).

## Licence

MIT
