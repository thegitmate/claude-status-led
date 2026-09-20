# Supporting other coding agents

This project reads Claude Code's session state. The same light could show Codex, OpenCode or Grok Build. These are notes on what each one exposes, gathered from their documentation rather than from working code: **nothing here has been implemented or verified on a real machine yet.**

## What a provider has to supply

The daemon needs one thing:

```python
def statuses() -> dict:        # {session_id: "busy" | "waiting" | "idle"}
```

Everything else (aggregating sessions, driving the LED, the serial protocol) is already agent-agnostic. Adding a tool means writing that one function.

Two questions decide how hard it is for any given agent:

1. **Does it publish live state to a file?** Cheapest by far. Poll it, no integration, works for sessions started before you installed anything.
2. **Does it emit events?** Workable, but you must be running before the event fires, and you have to track state yourself.

Claude Code answers yes to the first, at `~/.claude/sessions/<pid>.json`, which is why this project ended up so small.

## Claude Code (implemented)

`~/.claude/sessions/<pid>.json` carries `status`: `busy`, `waiting`, `idle` or `shell`. No hooks, no integration, correct for sessions that predate installation. See [LESSONS.md](LESSONS.md).

## Codex CLI

Two plausible routes, both documented.

**Session rollout files.** Codex writes a JSONL per thread under `~/.codex/sessions/YYYY/MM/DD/`, named `rollout-<timestamp>-<thread-id>.jsonl`. The first record is a `session_meta` carrying the thread id and working directory. Entries include `task_started`, `task_complete` and `turn_aborted`, which look like exactly the transitions a status light needs.

Promising, with a caveat this project learned the hard way: derive state from **explicit entry types**, never from the file merely growing, and never from it going quiet. Both assumptions failed for Claude Code.

**The `notify` hook.** Codex can run a program on `agent-turn-complete`, receiving thread id, turn id, working directory and the last assistant message. It must be set in the user-level `~/.codex/config.toml`, since project-local config cannot override it.

That gives you turn-complete but, on its own, no turn-start and nothing for abandoned turns. Codex also has a fuller lifecycle hooks system configured via `hooks.json` or a `[hooks]` table, with a trust prompt before non-managed hooks run.

**Likely shape:** rollout files as the source of truth, hooks only if the files turn out to lag.

- [Codex advanced configuration](https://developers.openai.com/codex/config-advanced)
- [Session and rollout files discussion](https://github.com/openai/codex/discussions/3827)

## OpenCode

Different architecture: a client/server split where the TUI is just one client. The server exposes an HTTP API plus Server-Sent Events, with `/api/event` for all server events and `/api/session/:sessionID/event` for a single session. Sessions are persistent and report an idle status.

This is the nicest of the three to integrate, because you subscribe rather than poll and get session status changes pushed to you. The trade is that a subscriber must be running when events fire, so a daemon restart needs a state resync, and you need the server's address.

- [OpenCode API documentation](https://opencode.ai/v2/docs/api)

## Grok Build

xAI's terminal coding agent, in the same category as Claude Code and Codex CLI. Reached v1.0 in August 2026, Apache 2.0 licensed, and runs subagents in isolated git worktrees.

**Its on-disk state format has not been checked.** Being open source, the answer is in the repository rather than a guess, and that is where to start. The worktree-based subagents raise a design question the others do not: if eight subagents run at once, is that one light or eight?

- [Introducing Grok Build](https://x.ai/news/grok-build-cli)

## Suggested structure

```
providers/
  claude_code.py    statuses() from ~/.claude/sessions/*.json
  codex.py          statuses() from ~/.codex/sessions/**/rollout-*.jsonl
  opencode.py       statuses() from the SSE event stream
  grok_build.py     statuses() from whatever it turns out to publish
```

The daemon imports whichever are enabled, merges the dictionaries and aggregates as it does now. Prefix session ids by provider so two agents cannot collide.

## The real design problem is not technical

One LED cannot say **which** agent wants you, and that matters once two are running. A blinking light you have to go and investigate is only slightly better than no light.

Options, roughly in order of effort:

- **Ignore it.** Blink means someone wants you. Fine if you rarely run two at once.
- **Colour per agent.** An RGB LED or a WS2812: green blink for Claude, blue blink for Codex. Colour says who, behaviour says what. Cheap and readable across a room.
- **One LED per agent.** Honest and obvious, but now it is a panel, not a light.
- **A small screen.** Says who, what and for how long, at the cost of needing to be read rather than glanced at.

Colour per agent is the sweet spot: it preserves the glanceable quality that makes the single LED worth having.

## If you add one

Two things worth doing, both learned from building the Claude Code provider:

- **Log every raw state you receive**, including ones you do not understand. Every bug in this project was found that way, and none by reading code.
- **Measure before choosing any timeout.** Every guessed threshold here turned out wrong; every measured one held.
