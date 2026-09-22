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
Type `exit` or `quit`, or press Ctrl-D, to leave. Add `--speak` to also hear
responses aloud (see "Voice output" below — off by default, extra setup
required).

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
jarvis note delete <note_id>
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

## Voice output (off by default)

`jarvis chat --speak` also speaks each response aloud, using
[Chatterbox](https://github.com/resemble-ai/chatterbox) (Resemble AI, MIT
licensed) for synthesis. It's off unless you ask for it:

1. Install the optional dependency — this pulls in torch/torchaudio, a
   multi-GB download: `pip install -e .[voice]`.
2. Set `JARVIS_ENABLE_VOICE=1` in `.env`.
3. Run `jarvis chat --speak`.

The model (~1-2GB) downloads from Hugging Face and is cached locally the
first time you use it; after that it runs offline. It's noticeably faster
with a GPU — on CPU-only machines, expect each response to take a few
seconds to synthesize before it plays. Playback shells out to whatever audio
player your OS already has (`afplay` on macOS, `paplay`/`aplay`/`ffplay` on
Linux, the built-in player on Windows) rather than pulling in another audio
dependency.

If the model isn't installed, hasn't been downloaded yet, or synthesis fails
for any reason, Jarvis prints a one-line warning and falls back to text-only
for that response (or the whole session, if it fails at startup) rather than
crashing the chat.

Why Chatterbox and not something else: see the comparison in this project's
commit history / conversation — the short version is Chatterbox's MIT
license has no commercial-use restriction (unlike Coqui XTTS-v2's CPML), and
it's a credible size/quality tradeoff among fully open options. Piper is the
lighter-weight fallback if you'd rather avoid the torch dependency, at the
cost of sounding more synthetic — swap it in via a different `jarvis/tts.py`
backend if that trade makes more sense for your machine.

### Voice settings dashboard

```bash
jarvis dashboard
```

Opens a small local web page (`http://127.0.0.1:8734`, bound to localhost
only — never exposed to the network) for adjusting how the voice sounds,
without editing files or restarting `jarvis chat`:

- **Voice** — upload a short (few-second) reference audio clip and Chatterbox
  clones that voice; pick which one is active, or use the built-in default.
- **Intonation** — an expressiveness slider (Chatterbox's `exaggeration`
  parameter) and a pace-adherence slider (`cfg_weight`).
- **Speaking speed** — not a native Chatterbox parameter, so this is applied
  as a post-processing time-stretch via `librosa`.
- **Preview** — generates and plays a sample with your current (even
  unsaved) slider positions, so you can hear a change before committing to it.

Settings are stored at `<vault_dir>/.jarvis/voice_settings.json` and read by
`jarvis chat --speak` on every turn — no restart needed. Requires the same
`pip install -e .[voice]` as `--speak`; the dashboard itself also needs
`flask` (included in that extra). It works even before `JARVIS_ENABLE_VOICE=1`
is set, so you can configure everything ahead of time — the settings just
won't audibly do anything until voice output is enabled.

`jarvis dashboard` also serves a web chat at `/chat` — a browser alternative
to `jarvis chat` that stays open in a tab instead of a terminal. It holds one
conversation (no multi-tab sessions, no history across reloads — click "New
conversation" to reset it) and doesn't stream token-by-token like the
terminal chat does; you'll see a "Thinking..." state while it generates.

## Running in the background

By default `jarvis chat` and `jarvis dashboard` are things you start
yourself, in a terminal, and stop with Ctrl-C. `jarvis tray` runs the same
dashboard+chat web server as a background process with a system tray icon —
click it to open the dashboard or chat in your browser, no terminal window
needed once it's running:

```bash
pip install -e .[tray]
jarvis tray
```

Needs a real desktop session (X11/Wayland on Linux, or macOS/Windows) — like
computer-use and voice, it can't run headless, and reports a clear error
rather than crashing if there's no display to attach to.

To make Jarvis appear in your application launcher (the grid of installed
apps), so you can start it by clicking an icon instead of typing a command:

```bash
jarvis install-launcher
```

Linux only — writes a standard `.desktop` file to
`~/.local/share/applications/jarvis.desktop` plus a generated icon, pointing
at `jarvis tray`. There's no equivalent here yet for macOS (a `.app` bundle)
or Windows (a Start Menu shortcut); those would need their own installers.

This doesn't auto-start Jarvis on login — `jarvis tray` still has to be
launched once, by hand or from the launcher entry above. Auto-start (a
systemd user service on Linux, a Login Item on macOS, Task Scheduler on
Windows) is a reasonable follow-up if you want Jarvis always running in the
background without launching it yourself each time.
