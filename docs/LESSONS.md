# Building a Claude Code status light: what goes wrong

Everything below was hit while building this project in a single afternoon. Each one looked like a hardware fault or a finished feature at the time. If you are building anything that reacts to Claude Code sessions, this is the document to read first.

## Start here, and skip most of the rest

**Claude Code publishes its own live session state.** `~/.claude/sessions/<pid>.json`:

```json
{"pid": 95237, "sessionId": "0d5c2d00-...", "status": "busy", "statusUpdatedAt": 1789914156334}
```

| status | meaning |
|---|---|
| `busy` | working |
| `waiting` | wants something from you |
| `idle` | session doing nothing |
| `shell` | back at the input prompt, awaiting your next message |

Four values, no hooks required, correct in every case that hooks miss. It also covers sessions that started before you installed anything.

Two traps:

- The file is named by **process id**, but the identity you want is the `sessionId` field inside it. Check the process is still alive.
- **`shell` does not mean a shell command is running.** During an actual Bash tool call the status is `busy`. `shell` means the prompt is waiting for you. Treat `shell` and `idle` as "not working" and it behaves.

Most of this project is hook and transcript archaeology done before finding that file. It works, but if you are starting now, start there.

## Claude Code fires no hooks for anything cancelled

This is the single biggest thing to understand. Hooks are reliable for things that **succeed** and silent for things that are **abandoned**.

| What you do | Hook fired |
|---|---|
| Send a prompt | `UserPromptSubmit` |
| A tool completes | `PostToolUse` |
| Claude finishes | `Stop` |
| **Dismiss a permission prompt with Esc** | **nothing** |
| **Interrupt Claude mid-answer** | **nothing** |
| **Submit a prompt then cancel it** | **nothing** |

That was verified, not assumed. Every plausible event was registered, including `MessageDisplay`, `UserPromptExpansion`, `TaskCompleted`, `PostToolBatch`, `PermissionDenied`, `ElicitationResult` and `StopFailure`, then a prompt was cancelled. Not one event was emitted.

**Consequence:** anything hook-driven gets stuck in whatever state it was last told about. A light that says "Claude needs you" at a prompt you dismissed two minutes ago is worse than no light, because you learn to ignore it.

### `SubagentStop` fires after `Stop`

Observed firing about two seconds **after** `Stop` at the end of an ordinary turn, with no subagent involved. Mapping it to a working state switches your indicator back on after it has correctly gone out. Do not treat it as activity.

## The transcript, and how to read it safely

Claude Code writes a live JSONL transcript per session at `~/.claude/projects/*/<session_id>.jsonl`. It records what hooks miss, but naive readings fail in three specific ways.

### A pending prompt is not a silent transcript

While you sit looking at a question, Claude Code keeps appending untimestamped housekeeping:

```
file-history-snapshot, last-prompt, ai-title, mode, permission-mode, atis-latch
```

Treating any file growth as "something happened" kills a blink roughly a minute into an unanswered prompt. Filter by entry `type` and only count `user`, `assistant` or `system`.

### Answering and dismissing look identical

Both append a `tool_result`. The transcript cannot tell them apart, so a transcript-only rule turns the light off the moment you answer, then leaves it off while Claude works. `PostToolUse` is the discriminator: only an answer completes the tool.

### Never substring-match interrupt text

An interrupt is a `user` entry whose content starts with `[Request interrupted by user`. Search the raw text and you will match assistant messages that merely **discuss** interrupts, which is exactly what happens when you use Claude to build this. Parse each entry and check `type` and the content prefix.

### Never treat silence as stopped

A single long tool call writes nothing for minutes while genuinely working. If you need a silence fallback, measure first. Across 35 real turns here, the gap between a prompt and Claude's first transcript entry was:

| median | 90th | max |
|---|---|---|
| 7s | 26s | 59s |

Anything under a minute switches the light off mid-reply.

## macOS specifics

### launchd cannot read `~/Documents`

A launchd agent runs without TCC privileges. Running a daemon from a repo cloned into `~/Documents`, `~/Desktop` or `~/Downloads` fails with `Operation not permitted`, reported only in the log. Copy the scripts somewhere unprotected, such as `~/.your-app/bin/`, and re-copy them whenever the code changes.

### `launchctl bootstrap` races `bootout`

Bootstrapping immediately after `bootout` fails with `Input/output error` because the label has not been released. Under `set -e` this aborts the installer, leaving hooks installed, no daemon running, and no error shown. Retry a few times and verify afterwards.

### Opening a serial port resets an Arduino

Opening the port pulls DTR and resets the board. Anything that opens the port per event will reset the board constantly. Hold it open in one long-lived process.

## Hardware

### A lit power LED proves nothing

Charge-only USB cables carry 5V but leave the data lines unconnected. The board powers up, boots, runs its last sketch and looks perfectly healthy while being completely invisible to your Mac. Three cables were tried here before one carried data.

If `ls /dev/cu.*` shows nothing, it is physical. It is not a driver problem: an unrecognised device still appears in `ioreg -p IOUSB -l`.

### Clone Nanos need the old bootloader

`arduino:avr:nano` fails with `not in sync: resp=0x00`. Use `arduino:avr:nano:cpu=atmega328old`.

## Testing

### Your tests will drive the real light

Test scripts here wrote to the live session directory, so every verification run made the LED flicker through several states on the desk of the person watching. It looks exactly like a bug. Either isolate test state or warn whoever is watching.

### A config file beats your defaults

A timeout raised from 60 to 300 in code never took effect, because an explicit `60` left behind by an earlier test was still sitting in the live config. It cut off live prompts at exactly one minute and looked identical to a logic bug. **An exact round number in a symptom points at a configured value, not a race.**

## Method

Three things found every bug here, and none of them was reading the code:

1. **Log every hook event to a file.** Unmapped events included. When the light does something unexpected, the answer is usually "an event you did not expect fired" or "nothing fired at all", and both are invisible otherwise.
2. **Read the transcript around the timestamp.** It shows what actually happened, as opposed to what you assume happens.
3. **Measure before choosing a threshold.** Every number in this project that was guessed turned out wrong, and every number derived from measurement held.

The person watching the light is a better bug detector than the person writing the code, because only they can see it. Take "it is still doing the wrong thing" seriously even when you are certain you just fixed it.
