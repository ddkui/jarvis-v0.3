# Delphi

Delphi is a personal "second brain": a local, markdown-based note vault with a
Delphi-style AI assistant on top. Ask it about things you've written down, have
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

Set `DELPHI_MODEL` to a litellm `<provider>/<model>` string, and set that
provider's API key. A few starting points:

| Provider | `DELPHI_MODEL` example | API key env var |
|---|---|---|
| Claude (default, most capable) | `anthropic/claude-opus-5` | `ANTHROPIC_API_KEY` |
| Gemini Flash (cheap, fast) | `gemini/gemini-2.5-flash` | `GEMINI_API_KEY` |
| DeepSeek | `deepseek/deepseek-chat` | `DEEPSEEK_API_KEY` |
| Groq-hosted open models | `groq/llama-3.3-70b-versatile` | `GROQ_API_KEY` |
| Local via Ollama (free, runs on your machine) | `ollama/llama3.1` | none — run `ollama serve` |

Any [model litellm supports](https://docs.litellm.ai/docs/providers) works the
same way — just set `DELPHI_MODEL` and the matching key in `.env`.

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

### Chat with Delphi

```bash
delphi chat
```

Starts an interactive REPL. Responses stream in live as the model generates
them, tool calls show up as they happen (`→ using search_notes`), and the
final answer renders as formatted markdown — all via [rich](https://github.com/Textualize/rich).
Type `exit` or `quit`, or press Ctrl-D, to leave. Add `--speak` to also hear
responses aloud (see "Voice output" below — off by default, extra setup
required).

The conversation picks up where you left off across restarts (stored at
`<vault_dir>/.delphi/conversation.json`) — it's one ongoing conversation, not
a history of separate sessions. Run `delphi chat --new` to clear it and start
fresh instead.

### Memory

Separately from the note vault, Delphi keeps a short list of durable facts
about you — your name, preferences, ongoing context — that it remembers
silently across *every* conversation, not just the current one. It decides
on its own when something's worth remembering (via a `remember` tool) rather
than asking each time, the same way it already decides when to offer to save
a note; unlike notes, these facts don't need to be searched for — they're
folded straight into its instructions on every turn. See what it's
remembered, or make it forget something:

```bash
delphi memory list
delphi memory forget <fact_id>
```

Stored at `<vault_dir>/.delphi/memory_facts.json`, capped at 50 facts (oldest
dropped first) so it can't grow the prompt without bound.

### Storing API keys securely

```bash
delphi auth set ANTHROPIC_API_KEY
delphi auth list
delphi auth delete ANTHROPIC_API_KEY
```

`delphi auth set` prompts for the value (hidden input) and stores it in your
OS's native keychain (macOS Keychain, Windows Credential Locker, Linux Secret
Service) via [keyring](https://github.com/jaraco/keyring), instead of sitting
in plaintext in `.env`. `load_config()` checks the keychain for any known key
that isn't already set by your shell or `.env`, so this is a drop-in upgrade —
nothing else changes. On a machine with no OS keychain available (headless
servers, some Linux setups, CI), it silently falls back to `.env`/environment
variables — `.env` remains fully supported.

### Notes

```bash
delphi note add --title "Trip idea" --content "Look into Portugal in spring" --tags travel,ideas
delphi note list
delphi note search "portugal"
delphi note show <note_id>
delphi note delete <note_id>
```

### Reminders

```bash
delphi remind add "Renew passport" --due 2026-11-01T09:00:00
delphi remind list --all
delphi remind done <reminder_id>
```

### Daily digest

```bash
delphi digest
```

Prints a quick, offline (no API call) summary of notes updated in the last 24
hours and reminders due today or overdue.

## Computer use (off by default — read this before enabling)

Delphi can optionally see the screen and drive the mouse and keyboard on
whatever machine runs `delphi chat` — take a screenshot, click, move, type,
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
2. Set `DELPHI_ENABLE_COMPUTER_USE=1` in `.env`.

You'll also want a model that can actually see images — Claude and Gemini
both work; check that whatever you set `DELPHI_MODEL` to supports vision.

**Safety mechanisms that are always on when it's enabled:**

- **Physical failsafe**: drag the mouse to any corner of the screen at any
  time to immediately abort. This stops the whole conversation turn, not
  just the one action — Delphi won't retry.
- **Live action log**: every click, keystroke, and move is printed to the
  terminal as it happens (`[computer-use] click at (512, 300) ...`), so
  whoever is watching the terminal sees it in real time.
- The assistant is instructed to screenshot before acting and to pause and
  ask before anything hard to undo (sending, submitting, deleting, paying,
  posting) — this is a prompt-level habit, not a hard block, so don't rely
  on it alone.

This build doesn't gate individual actions on a confirmation prompt — once
you send a message, Delphi acts on its own until it's done or hits the
failsafe. If you want a confirmation step before each action instead, that's
a reasonable follow-up change to `delphi/agent/core.py`'s tool-execution
loop.

## Writing & running code (off by default)

Delphi can run Python and shell commands and read/write files, scoped to a
working directory — useful for scripts, data work, automation, and coding on
an existing project. This is real, unconfirmed code execution: a wrong shell
command can delete or overwrite real files. It's off unless you turn it on:

1. Set `DELPHI_ENABLE_CODE=1` in `.env`.
2. Optionally set `DELPHI_CODE_DIR=/path/to/a/project` to point it at a
   specific project; if unset, it's scoped to whatever directory you ran
   `delphi` from (so `cd your-project && delphi chat` is the normal way to
   use this for a coding session).

Tools: `run_python`, `run_shell`, `read_file`, `write_file`, `list_dir`. All
file/shell access is confined to the scoped directory — a path that resolves
outside it is rejected before anything touches disk — and every command run
is logged to the terminal as it happens, the same as computer-use. Commands
time out after 60s and their output is truncated if huge, so a runaway
command can't hang the conversation.

## Self-improvement (off by default)

Separately from the general code tools above, Delphi can read, edit, test,
and — only on your explicit approval — commit and restart itself into
changes to its own source code (this repository). It's off unless you turn
it on:

```bash
# DELPHI_ENABLE_SELF_UPDATE=1 in .env
```

Tools: `read_own_file`, `write_own_file`, `list_own_dir`,
`view_pending_changes`, `run_own_tests`, `discard_pending_changes`,
`apply_pending_changes` — all scoped to this repo specifically, independent
of `DELPHI_CODE_DIR`. The flow is a hard two-step gate, not a formality:

1. Delphi edits files (working tree only, nothing committed), then shows you
   `view_pending_changes` (the diff) and `run_own_tests` (pass/fail).
2. Only when you explicitly say to proceed does it call
   `apply_pending_changes` — which **independently re-runs the full test
   suite itself** and refuses to commit or restart on a single failing test,
   regardless of what the model believes about its own change. If it passes,
   it commits and restarts the running process into the new code.

The system prompt also instructs the model to never call
`apply_pending_changes` in the same turn it made the edits — there should
always be a real message from you between "here's the diff" and "apply it."
If you don't like a pending change, ask it to keep iterating, or say
"discard it" to call `discard_pending_changes` and reset to the last commit.

## Voice output (off by default)

`delphi chat --speak` also speaks each response aloud, using
[Chatterbox](https://github.com/resemble-ai/chatterbox) (Resemble AI, MIT
licensed) for synthesis. It's off unless you ask for it:

1. Install the optional dependency — this pulls in torch/torchaudio, a
   multi-GB download: `pip install -e .[voice]`.
2. Set `DELPHI_ENABLE_VOICE=1` in `.env`.
3. Run `delphi chat --speak`.

The model (~1-2GB) downloads from Hugging Face and is cached locally the
first time you use it; after that it runs offline. It's noticeably faster
with a GPU — on CPU-only machines, expect each response to take a few
seconds to synthesize before it plays. Playback shells out to whatever audio
player your OS already has (`afplay` on macOS, `paplay`/`aplay`/`ffplay` on
Linux, the built-in player on Windows) rather than pulling in another audio
dependency.

If the model isn't installed, hasn't been downloaded yet, or synthesis fails
for any reason, Delphi prints a one-line warning and falls back to text-only
for that response (or the whole session, if it fails at startup) rather than
crashing the chat.

Why Chatterbox and not something else: see the comparison in this project's
commit history / conversation — the short version is Chatterbox's MIT
license has no commercial-use restriction (unlike Coqui XTTS-v2's CPML), and
it's a credible size/quality tradeoff among fully open options. Piper is the
lighter-weight fallback if you'd rather avoid the torch dependency, at the
cost of sounding more synthetic — swap it in via a different `delphi/tts.py`
backend if that trade makes more sense for your machine.

**Known dependency gaps on a fresh install** — Chatterbox's own pinned
dependencies can lag behind what pip actually resolves for you, especially on
a recently-updated machine. Two seen in practice (both one-time fixes, not
Delphi bugs):

- `ModuleNotFoundError: No module named 'pkg_resources'` (or the model
  loading fails with a cryptic `'NoneType' object is not callable`) — a
  dependency (`perth`, Chatterbox's watermarker) still uses the old
  `pkg_resources` API, which very new `setuptools` versions have dropped.
  Fix: `pip install "setuptools<81"`.
- `TorchCodec is required for save_with_torchcodec` — recent `torchaudio`
  versions need the separate `torchcodec` package to write audio files.
  This is now in the `voice` extra's dependencies, so a fresh
  `pip install -e .[voice]` should pull it in automatically; if you hit this
  on an existing install, `pip install torchcodec` fixes it directly.

### Voice settings dashboard

```bash
delphi dashboard
```

Opens a small local web page (`http://127.0.0.1:8734`, bound to localhost
only — never exposed to the network) for adjusting how the voice sounds,
without editing files or restarting `delphi chat`:

- **Voice** — upload a short (few-second) reference audio clip and Chatterbox
  clones that voice; pick which one is active, or use the built-in default.
- **Intonation** — an expressiveness slider (Chatterbox's `exaggeration`
  parameter) and a pace-adherence slider (`cfg_weight`).
- **Speaking speed** — not a native Chatterbox parameter, so this is applied
  as a post-processing time-stretch via `librosa`.
- **Preview** — generates and plays a sample with your current (even
  unsaved) slider positions, so you can hear a change before committing to it.

Settings are stored at `<vault_dir>/.delphi/voice_settings.json` and read by
`delphi chat --speak` on every turn — no restart needed. Requires the same
`pip install -e .[voice]` as `--speak`; the dashboard itself also needs
`flask` (included in that extra). It works even before `DELPHI_ENABLE_VOICE=1`
is set, so you can configure everything ahead of time — the settings just
won't audibly do anything until voice output is enabled.

`delphi dashboard` also serves a web chat at `/chat` — a browser alternative
to `delphi chat` that stays open in a tab instead of a terminal, backed by
the same persisted conversation (reload the page, or restart the server, and
your history reloads with it — click "New conversation" to actually clear
it). It's one conversation with no multi-tab sessions, and it doesn't stream
token-by-token like the terminal chat does; you'll see a "Thinking..." state
while it generates.

## Running in the background

By default `delphi chat` and `delphi dashboard` are things you start
yourself, in a terminal, and stop with Ctrl-C. `delphi tray` runs the same
dashboard+chat web server as a background process with a system tray icon —
click it to open the dashboard or chat in your browser, no terminal window
needed once it's running:

```bash
pip install -e .[tray]
delphi tray
```

Needs a real desktop session (X11/Wayland on Linux, or macOS/Windows) — like
computer-use and voice, it can't run headless, and reports a clear error
rather than crashing if there's no display to attach to.

To make Delphi appear in your application launcher (the grid of installed
apps), so you can start it by clicking an icon instead of typing a command:

```bash
delphi install-launcher
```

Linux only — writes a standard `.desktop` file to
`~/.local/share/applications/delphi.desktop` plus a generated icon, pointing
at `delphi tray`. There's no equivalent here yet for macOS (a `.app` bundle)
or Windows (a Start Menu shortcut); those would need their own installers.

This doesn't auto-start Delphi on login — `delphi tray` still has to be
launched once, by hand or from the launcher entry above. Auto-start (a
systemd user service on Linux, a Login Item on macOS, Task Scheduler on
Windows) is a reasonable follow-up if you want Delphi always running in the
background without launching it yourself each time.

## Auto-update (on by default)

Delphi checks the git remote for new commits to itself and updates
automatically — `delphi tray` and `delphi dashboard` poll for it hourly in
the background (`DELPHI_AUTOUPDATE_INTERVAL`, seconds), and `delphi chat`
checks once at startup. When an update is found, it fast-forwards
(`git fetch` + `git merge --ff-only`) and restarts the running process into
the new code automatically, no prompt.

It's conservative about when it acts: it only ever fast-forwards, and only
when the working tree is clean. If there are uncommitted local changes (for
example a pending self-update you haven't applied yet) or local history has
diverged from the remote, it silently skips the check rather than risk
discarding or conflicting with anything — it is not a merge tool. Set
`DELPHI_ENABLE_AUTOUPDATE=0` in `.env` if you'd rather update by hand; you can
still trigger a one-off check anytime with:

```bash
delphi update
```

This runs the same fast-forward-only check immediately (regardless of the
`DELPHI_ENABLE_AUTOUPDATE` setting) and restarts if it finds one.
