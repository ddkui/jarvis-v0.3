# Jarvis

Jarvis is a personal "second brain": a local, markdown-based note vault with a
Jarvis-style AI assistant on top. Ask it about things you've written down, have
it jot new notes and reminders for you mid-conversation, and get a quick daily
digest of what's changed and what's due.

## Architecture

Notes live as plain markdown files with YAML frontmatter in a local vault
directory, and are indexed into a SQLite FTS5 table for fast keyword search;
retrieval assembles the top matching snippets into context for the assistant.
The assistant itself is a thin agentic loop over [litellm](https://docs.litellm.ai/),
which routes to whichever model provider you configure (Claude, Gemini, DeepSeek,
Groq-hosted open models, a local Ollama model, and more) behind one call shape,
with tool use wired up to tools for searching/adding notes and managing
reminders, plus calendar and email as stubbed extension points (they return no
tools until you configure credentials for them, at which point they're meant
to be filled in with a real integration). Reminders are stored separately in
their own SQLite table, independent of the note vault.

## Choosing a model

Set `JARVIS_MODEL` to a litellm `<provider>/<model>` string, and set that
provider's API key. A few starting points:

| Provider | `JARVIS_MODEL` example | API key env var |
|---|---|---|
| Claude (default, most capable) | `anthropic/claude-opus-5` | `ANTHROPIC_API_KEY` |
| Gemini Flash (cheap, fast) | `gemini/gemini-2.5-flash` | `GEMINI_API_KEY` |
| DeepSeek | `deepseek/deepseek-chat` | `DEEPSEEK_API_KEY` |
| Groq-hosted open models | `groq/llama-3.3-70b-versatile` | `GROQ_API_KEY` |
| Local via Ollama (free, runs on your machine) | `ollama/llama3.1` | none — run `ollama serve` |

Any [model litellm supports](https://docs.litellm.ai/docs/providers) works the
same way — just set `JARVIS_MODEL` and the matching key in `.env`.

## Usage

Install dependencies:

```bash
pip install -r requirements.txt
```

Copy the example environment file and set your API key:

```bash
cp .env.example .env
# then edit .env and set ANTHROPIC_API_KEY=sk-ant-...
```

### Chat with Jarvis

```bash
jarvis chat
```

Starts an interactive REPL. Responses stream in live as the model generates
them, tool calls show up as they happen (`→ using search_notes`), and the
final answer renders as formatted markdown — all via [rich](https://github.com/Textualize/rich).
Type `exit` or `quit`, or press Ctrl-D, to leave.

### Storing API keys securely

```bash
jarvis auth set ANTHROPIC_API_KEY
jarvis auth list
jarvis auth delete ANTHROPIC_API_KEY
```

`jarvis auth set` prompts for the value (hidden input) and stores it in your
OS's native keychain (macOS Keychain, Windows Credential Locker, Linux Secret
Service) via [keyring](https://github.com/jaraco/keyring), instead of sitting
in plaintext in `.env`. `load_config()` checks the keychain for any known key
that isn't already set by your shell or `.env`, so this is a drop-in upgrade —
nothing else changes. On a machine with no OS keychain available (headless
servers, some Linux setups, CI), it silently falls back to `.env`/environment
variables — `.env` remains fully supported.

### Notes

```bash
jarvis note add --title "Trip idea" --content "Look into Portugal in spring" --tags travel,ideas
jarvis note list
jarvis note search "portugal"
jarvis note show <note_id>
```

### Reminders

```bash
jarvis remind add "Renew passport" --due 2026-11-01T09:00:00
jarvis remind list --all
jarvis remind done <reminder_id>
```

### Daily digest

```bash
jarvis digest
```

Prints a quick, offline (no API call) summary of notes updated in the last 24
hours and reminders due today or overdue.

## Computer use (off by default — read this before enabling)

Jarvis can optionally see the screen and drive the mouse and keyboard on
whatever machine runs `jarvis chat` — take a screenshot, click, move, type,
press keys, scroll. This is real, unconfirmed control of your actual desktop:
whatever app has focus, whatever window is open, whatever a click actually
lands on. A misread screenshot or a slightly-off coordinate can hit the wrong
button — send something, delete something, submit a form — before you have a
chance to stop it. Do not enable this on a machine you can't afford to have
something go wrong on; a spare machine, VM, or throwaway account is safer
than your daily-driver desktop.

**It's off unless you turn it on.** Two things are required:

1. Install the optional dependencies: `pip install -e .[computer-use]` (or
   `pip install pyautogui pillow`).
2. Set `JARVIS_ENABLE_COMPUTER_USE=1` in `.env`.

You'll also want a model that can actually see images — Claude and Gemini
both work; check that whatever you set `JARVIS_MODEL` to supports vision.

**Safety mechanisms that are always on when it's enabled:**

- **Physical failsafe**: drag the mouse to any corner of the screen at any
  time to immediately abort. This stops the whole conversation turn, not
  just the one action — Jarvis won't retry.
- **Live action log**: every click, keystroke, and move is printed to the
  terminal as it happens (`[computer-use] click at (512, 300) ...`), so
  whoever is watching the terminal sees it in real time.
- The assistant is instructed to screenshot before acting and to pause and
  ask before anything hard to undo (sending, submitting, deleting, paying,
  posting) — this is a prompt-level habit, not a hard block, so don't rely
  on it alone.

This build doesn't gate individual actions on a confirmation prompt — once
you send a message, Jarvis acts on its own until it's done or hits the
failsafe. If you want a confirmation step before each action instead, that's
a reasonable follow-up change to `jarvis/agent/core.py`'s tool-execution
loop.
