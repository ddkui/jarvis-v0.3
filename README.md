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
reminders, a real Gmail integration (see "Email (Gmail)" below), and calendar
as a stubbed extension point (it returns no tools until you configure
credentials for it, at which point it's meant to be filled in with a real
integration the same way email was). Reminders are stored separately in
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
| NVIDIA-hosted models ([build.nvidia.com](https://build.nvidia.com/models), free tier) | `nvidia_nim/meta/llama3-70b-instruct` | `NVIDIA_NIM_API_KEY` |
| Local via Ollama (free, runs on your machine) | `ollama/llama3.1` | none — run `ollama serve` |

Any [model litellm supports](https://docs.litellm.ai/docs/providers) works the
same way — just set `DELPHI_MODEL` and the matching key in `.env`. For NVIDIA,
get a key by signing in at [build.nvidia.com](https://build.nvidia.com/models),
opening any model's page, and generating an API key there (it starts with
`nvapi-`); the same key works for every model in their catalog, so the exact
`DELPHI_MODEL` you pick (any `<namespace>/<model>` path from that catalog,
e.g. `nvidia_nim/nvidia/llama-3.1-nemotron-70b-instruct`) is just a matter of
picking one from the site.

### Falling back to a second model on rate limits/outages

Set `DELPHI_FALLBACK_MODELS` to a comma-separated list of additional
`<provider>/<model>` strings (same format and key requirements as
`DELPHI_MODEL` above). If the primary model hits a rate limit or a transient
outage mid-conversation, Delphi automatically retries the same turn against
the next model in the list instead of failing the turn — useful for pairing a
provider with a tight free-tier quota (Gemini's free tier caps at 20
requests/day) with a backup:

```
DELPHI_MODEL=gemini/gemini-2.5-flash
DELPHI_FALLBACK_MODELS=nvidia_nim/meta/llama3-70b-instruct
```

This only triggers for availability problems (rate limits, timeouts, 5xx
errors) — a bad API key or an invalid model name fails immediately rather
than cycling through the whole list, since that kind of error would just
repeat identically on every entry. Each provider's own key still needs to be
set for its model to work as a fallback.

Every request (whether or not fallbacks are configured) has a timeout —
`DELPHI_REQUEST_TIMEOUT` seconds (default `60`) of the connection going fully
silent, not a cap on how long a response can take overall, so a normal reply
that's just slow to fully arrive isn't cut off as long as *something* keeps
coming in. Without this, a model that stalls instead of returning a clean
error — seen in practice with a fallback model choking on something in the
conversation history — hung the whole turn forever with no way to recover;
now it raises a timeout instead, which (for a fallback attempt) moves on to
the next model the same way a rate limit does.

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

**Known gotcha: typing into a window that isn't focused yet.** Opening an
application (e.g. via the Start menu) isn't instant — if Delphi types
immediately after launching something, the keystrokes can land on whatever
still had focus a moment earlier (often the terminal `delphi chat` itself is
running in) instead of the new window. The `computer_type` tool's
description tells the model to screenshot and confirm focus first, but this
is prompt-level guidance, not a hard guarantee — if you see typed text show
up in the wrong place, that's what happened; just ask it to try again.

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

## Email (Gmail)

Delphi can read, search, label, and archive mail in your Gmail inbox — it
**cannot delete anything or send mail on your behalf**. "Organize" here means
label + archive only: archiving an email just removes Gmail's `INBOX` label
(the same thing the archive button in Gmail does), which is reversible and
never destructive — nothing is ever moved to Trash. It's off unless you set
it up:

1. In [Google Cloud Console](https://console.cloud.google.com/), create a
   project (or use an existing one), enable the **Gmail API** for it, then
   create an OAuth client under "Credentials" with application type
   **Desktop app**. Download its `credentials.json`.
2. Install the optional dependency: `pip install -e .[gmail]`.
3. In `.env`, set `GOOGLE_GMAIL_CREDENTIALS=/path/to/credentials.json` and
   `DELPHI_ENABLE_EMAIL=1`.
4. Run the one-time interactive consent flow:
   ```bash
   delphi auth gmail
   ```
   This opens a browser to sign in and grant access, then stores the
   resulting token in your OS keychain (not a file) — the same secure
   storage `delphi auth set` uses for API keys. You only need to do this
   once; Delphi refreshes the token silently after that.

Tools: `search_email`, `list_recent_emails`, `get_email`, `label_email`
(creates the label first if it doesn't exist yet), `archive_email`,
`mark_read`, `mark_unread`. There is deliberately no `trash_email`,
`delete_email`, or `send_email` tool in this build.

## Daily summary (off by default)

Delphi can automatically put together a digest — notes updated recently,
reminders due, and (if email is set up, see above) an inbox summary — twice a
day without you asking for it, the same content `delphi digest` prints
on-demand. It's off unless you turn it on, and only runs as part of
`delphi tray` (like wake-word listening below — it doesn't run under
`delphi chat` or `delphi dashboard`):

```bash
# DELPHI_ENABLE_DAILY_SUMMARY=1 in .env
```

- `DELPHI_DAILY_SUMMARY_TIMES` (default `08:00,20:00`) — comma-separated
  24h local times to run at.
- `DELPHI_ENABLE_DAILY_SUMMARY_SPEAK` — a **separate** opt-in from just
  enabling the summary: set this to also have Delphi speak a short version
  of each summary aloud (requires `DELPHI_ENABLE_VOICE=1` too — see "Voice
  output" below). Unprompted spoken output is more intrusive than a written
  note, so it stays off unless you ask for it specifically.

Every run is saved as a new note in your vault regardless of whether
speaking is on, so you always have a written record even if you weren't
around to hear it.

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

**Speeding it up with a GPU** — `delphi/tts.py` already auto-detects and uses
CUDA if it's available (`torch.cuda.is_available()`), so no code change is
needed. The default `pip install -e .[voice]` pulls in a CPU-only `torch`
build though, which is the bottleneck: full synthesis on CPU can take a
minute or more per response, versus a few seconds on an NVIDIA GPU. To switch
an existing install over:

1. Check your driver's max supported CUDA version: `nvidia-smi` (top-right of
   the header).
2. Get the matching install command from
   [pytorch.org/get-started/locally](https://pytorch.org/get-started/locally/)
   (choose Pip, your OS, and a CUDA version at or below what `nvidia-smi`
   reported), then install `torch`/`torchaudio` from that CUDA index instead
   of the default PyPI one, e.g.:
   ```
   pip uninstall -y torch torchaudio torchvision
   pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126
   pip install --force-reinstall torchcodec
   ```
   (the `torchcodec` reinstall avoids an ABI mismatch against the new `torch`
   build.)
3. Verify: `python -c "import torch; print(torch.cuda.is_available())"`
   should print `True`.

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

**Windows: a silent (no console window) desktop shortcut** — `delphi tray`
launched normally still opens a console window, since `delphi.exe` (the
pip-installed launcher) is tied to `python.exe`. To get a double-clickable
icon with no visible window at all (only the tray icon), launch via
`pythonw.exe` instead, wrapped in a `.vbs` file so it also runs fully
detached from the shell that starts it:

```powershell
@"
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c cd /d ""<repo-path>"" && "".venv\Scripts\pythonw.exe"" -m delphi.cli tray > ""<repo-path>\delphi-tray.log"" 2>&1", 0, False
"@ | Set-Content -Path "<repo-path>\start-delphi.vbs" -Encoding ASCII
```

(replace both `<repo-path>` with your actual install path). Point a Desktop
shortcut's target at that `.vbs` file instead of a `.bat`/`delphi tray`
directly — double-clicking it then launches with no window at all, and
anything that would normally print to the console goes to
`delphi-tray.log` instead (useful for troubleshooting, since you won't see
console output otherwise).

## Wake-word voice input (off by default)

`delphi tray` can also listen for you to say its name and respond hands-free,
Siri/Alexa-style — say "Delphi" followed by a command (or just "Delphi" on
its own, then say the command after it acknowledges):

1. Install the optional dependency: `pip install -e .[listen]`.
2. Set `DELPHI_ENABLE_WAKE_WORD=1` in `.env`.
3. Launch (or relaunch) `delphi tray`.

Commands go through the exact same agent and persisted conversation as
`delphi chat` and the dashboard, and replies are spoken back if
`DELPHI_ENABLE_VOICE=1` is also set (otherwise they're just applied silently
— check the dashboard or `delphi chat` to see the reply text).

**Why there's no dedicated wake-word model**: engines like openWakeWord or
Picovoice Porcupine only ship pretrained models for a fixed set of words
(`alexa`, `hey jarvis`, etc.) — training a custom one for an arbitrary word
like "Delphi" needs an external one-time step (synthetic training data
generation, typically via a Colab notebook). To avoid that setup burden,
Delphi instead uses a different, zero-training approach: a lightweight
voice-activity detector (`webrtcvad`) segments your microphone stream into
utterances, each one is transcribed locally with Whisper (`faster-whisper`,
which can use a GPU if one's usable — see the `DELPHI_WHISPER_DEVICE` note
below), and the transcript is checked for the wake word. This uses more
CPU/GPU per utterance than a
dedicated wake-word model would (every utterance gets transcribed, not just
ones that start with "Delphi"), but works immediately with the literal word
"Delphi" and needs no extra setup or external training step.

**Privacy**: this only runs when you explicitly enable it. Nothing is sent
over the network until the wake word is actually heard and a command
follows — transcription happens fully locally. Utterances that don't contain
the wake word (and aren't a follow-up to a bare "Delphi") are discarded, not
logged or transmitted.

Tunable via `.env`:

- `DELPHI_WAKE_WORD` (default `delphi`) — the trigger word/phrase to listen
  for, case-insensitive.
- `DELPHI_WHISPER_MODEL` (default `small.en`) — any
  [faster-whisper model name](https://github.com/SYSTRAN/faster-whisper);
  smaller (`tiny.en`, `base.en`) is faster and lighter but less accurate,
  larger (`medium.en`) is the reverse. Matters most on CPU — on a GPU, even
  `small.en` transcribes each command in well under a second.
- `DELPHI_WHISPER_DEVICE` (default `auto`) — set to `cpu` to force CPU
  transcription. `auto` tries to use a GPU if `faster-whisper`'s own runtime
  (`ctranslate2`) can see one usable, which is a **separate** check from
  Chatterbox/torch's GPU detection for voice output — a CUDA-enabled `torch`
  install (see "Speeding it up with a GPU" above) does *not* automatically
  make this work, since `ctranslate2` needs its own CUDA/cuBLAS runtime DLLs
  visible on the system rather than the private copies `torch` bundles for
  itself. If you see `Library cublas64_12.dll is not found or cannot be
  loaded` (or similar), either set `DELPHI_WHISPER_DEVICE=cpu` — CPU
  transcription of a short spoken command is fast enough that this usually
  isn't noticeable, unlike TTS generation — or install the matching
  [NVIDIA CUDA/cuBLAS runtime](https://github.com/SYSTRAN/faster-whisper#gpu)
  system-wide to get GPU transcription too.

Only `delphi tray` runs the listener — `delphi chat` and `delphi dashboard`
don't, since they're meant to be run in a foreground terminal you're already
looking at.

## Auto-update (on by default)

Delphi checks the git remote for new commits to itself and updates
automatically — `delphi tray` and `delphi dashboard` poll for it hourly in
the background (`DELPHI_AUTOUPDATE_INTERVAL`, seconds), and `delphi chat`
checks once at startup. When an update is found, it fast-forwards
(`git fetch` + `git merge --ff-only`). `tray`/`dashboard` then restart the
running process into the new code automatically, no prompt - `delphi chat`
deliberately does not: it pulls, tells you to relaunch, and exits, rather
than restarting itself right before opening an interactive input loop. An
`os.execv` restart doesn't hand the console off cleanly to a process that
then reads stdin interactively on Windows, so restarting in place there can
leave your next keystrokes landing on the shell instead of Delphi.

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
