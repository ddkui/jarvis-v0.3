# Jarvis

Jarvis is a personal "second brain": a local, markdown-based note vault with a
Jarvis-style AI assistant on top. Ask it about things you've written down, have
it jot new notes and reminders for you mid-conversation, and get a quick daily
digest of what's changed and what's due.

## Architecture

Notes live as plain markdown files with YAML frontmatter in a local vault
directory, and are indexed into a SQLite FTS5 table for fast keyword search;
retrieval assembles the top matching snippets into context for the assistant.
The assistant itself is a thin agentic loop over the Claude API (`anthropic`
SDK) with tool use, wired up to tools for searching/adding notes and managing
reminders, plus calendar and email as stubbed extension points (they return no
tools until you configure credentials for them, at which point they're meant
to be filled in with a real integration). Reminders are stored separately in
their own SQLite table, independent of the note vault.

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

Starts an interactive REPL (`you> ` / `jarvis> `). Type `exit` or `quit`, or
press Ctrl-D, to leave.

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
