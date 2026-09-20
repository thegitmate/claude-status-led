# Design notes

Why this is built the way it is. Every decision below replaced something simpler that did not work.

## Why a daemon, not hooks talking to the board

Opening a serial port pulls DTR, which **resets the Nano**. Hooks fire many times per turn, so a hook that opened the port would reset the board and stall in the bootloader constantly. The daemon opens the port once and holds it.

## Why blinking runs on the Arduino

The daemon sends "blink" once and the firmware does the rest, so the rhythm never depends on the Mac being responsive. The firmware also drops the LED to off after 10 seconds of silence, so a crashed daemon or a sleeping Mac cannot leave a light on saying something that is no longer true.

## Why scripts are copied to `~/.claude-status-led/bin/`

A launchd agent runs without TCC privileges and **cannot read `~/Documents`, `~/Desktop` or `~/Downloads`**. Running the daemon from a repo cloned into Documents fails with `Operation not permitted`, and launchd reports it only in the log.

Consequence: editing the repo changes nothing until you re-run `install.sh`.

## Why session liveness matches the process NAME

The hook records the owning `claude` process id so the daemon can drop sessions killed with ctrl-C, which never fire `SessionEnd`.

It matches `ps -o comm=` (the executable name), **not the command line**. A substring match on the command line matches the shell running the hook, because that shell's command contains `claude-status-led`. That shell exits the instant the hook returns, so every session would look dead immediately and the LED would never stay on.

## Why the daemon watches session transcripts

**Claude Code fires no hook when you dismiss a prompt with Esc**, and an interrupted turn does not fire `Stop` either. You can verify this yourself: press Esc on a prompt and nothing at all is written to `events.log` between the `Notification` and your next message.

A purely hook-driven status light therefore blinks at a question that is no longer on screen, until you happen to send another message. Measured at over four minutes in testing.

The transcript does record it. Claude Code writes a live JSONL file per session at `~/.claude/projects/*/<session_id>.jsonl`, and the asymmetry is the signal:

- A **dismissed** prompt appends a tool result and an interrupt line within a second or two, both `type: "user"`.
- A **pending** prompt appends only housekeeping.

That second point cost a bug. A pending prompt is not a silent transcript: Claude Code keeps appending untimestamped lines the whole time you are looking at the question.

```
file-history-snapshot, last-prompt, ai-title, mode, permission-mode, atis-latch
```

The first version treated any growth as resolution, so one of those would kill the blink around a minute into an unanswered prompt, long before the user replied.

So the daemon settles for 3 seconds, records a byte offset, and on growth reads only what was appended, clearing the blink only if an entry of type `user`, `assistant` or `system` appears. Latency is about 5 seconds.

This approach is borrowed from [Claw Light](https://clawlight.dev/), which watches session files rather than relying on hooks. [Agent Light](https://github.com/eternityspring/agent-light) is hook-driven and has the same blind spot.

## Why `PostToolUse` is registered despite firing constantly

Answering a question and dismissing one **grow the transcript identically**, so the rule above cannot tell them apart. It cleared the blink to off in both cases, which meant the LED went dark the moment you answered and stayed dark while Claude worked.

Only an answer completes the tool, so only an answer fires `PostToolUse`. That is the discriminator.

Because it now runs on every tool call, the hook reuses the pid already in the session record when that process is still alive, instead of walking the process tree with `ps` each time. 70ms down to 21ms.

## State model

| State | LED | Set by |
|---|---|---|
| `busy` | Solid | `UserPromptSubmit`, `PostToolUse` |
| `waiting` | Blink | `Notification`, `PermissionRequest` |
| `idle` | Off | `SessionStart`, `Stop`, dismissal detected via transcript |

`idle` is deliberately not special cased in the daemon. Anything that is neither `busy` nor `waiting` contributes nothing, so an idle session stays tracked for liveness while leaving the LED dark.

`Notification` is classified by its message, because Claude Code fires it both for real requests and as a plain "waiting for your input" nudge after about 60 seconds idle. Without the split, stepping away from your desk starts the light blinking on its own.

## Multiple sessions

Aggregated, so the light reflects whichever session most wants you rather than whichever window you are looking at:

1. Any session `waiting` wins, and it blinks.
2. Otherwise any session `busy`, and it is solid.
3. Otherwise off.

Verified across 8 scenarios including a question in an unfocused session, a terminal killed mid-question, and the backstop timeout.
