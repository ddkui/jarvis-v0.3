from __future__ import annotations

import argparse
import sys

import litellm

from jarvis.config import load_config
from jarvis.memory.store import MemoryStore
from jarvis.scheduler.jobs import ReminderStore, daily_digest
from jarvis.tools import calendar_tools, email_tools, notes_tools, reminder_tools
from jarvis.vault import Vault


def _summarize(e: Exception) -> str:
    # litellm embeds a full traceback in some exceptions' message text; show only
    # the first line so CLI error output stays readable.
    return str(e).splitlines()[0]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jarvis", description="Your personal second brain.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("chat", help="Start an interactive chat session with Jarvis.")

    note_parser = subparsers.add_parser("note", help="Manage notes.")
    note_sub = note_parser.add_subparsers(dest="note_command", required=True)

    note_add = note_sub.add_parser("add", help="Add a new note.")
    note_add.add_argument("--title", required=True)
    note_add.add_argument("--content", required=True)
    note_add.add_argument("--tags", default=None, help="Comma-separated tags.")

    note_sub.add_parser("list", help="List all notes.")

    note_search = note_sub.add_parser("search", help="Search notes.")
    note_search.add_argument("query")

    note_show = note_sub.add_parser("show", help="Show a single note.")
    note_show.add_argument("note_id")

    remind_parser = subparsers.add_parser("remind", help="Manage reminders.")
    remind_sub = remind_parser.add_subparsers(dest="remind_command", required=True)

    remind_add = remind_sub.add_parser("add", help="Add a new reminder.")
    remind_add.add_argument("text")
    remind_add.add_argument("--due", required=True, dest="due_at", help="ISO8601 due date/time.")

    remind_list = remind_sub.add_parser("list", help="List reminders.")
    remind_list.add_argument("--all", action="store_true", help="Include completed reminders.")

    remind_done = remind_sub.add_parser("done", help="Mark a reminder as done.")
    remind_done.add_argument("reminder_id")

    subparsers.add_parser("digest", help="Print the daily digest.")

    return parser


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [tag.strip() for tag in raw.split(",") if tag.strip()]


def _build_agent_stack(config):
    vault = Vault(config.vault_dir)
    store = MemoryStore(config.db_path)
    reminders = ReminderStore(config.reminders_db_path)

    tools = []
    tools.extend(notes_tools.build_tools(vault, store))
    tools.extend(reminder_tools.build_tools(reminders))
    tools.extend(calendar_tools.build_tools())
    tools.extend(email_tools.build_tools())

    return vault, store, reminders, tools


def cmd_chat(args: argparse.Namespace) -> int:
    from jarvis.agent.core import JarvisAgent

    config = load_config()
    _vault, _store, _reminders, tools = _build_agent_stack(config)

    try:
        agent = JarvisAgent(model=config.model, tools=tools)
        print("Jarvis is ready. Type 'exit' or 'quit' to leave.")
        while True:
            try:
                user_input = input("you> ")
            except EOFError:
                print()
                break
            if user_input.strip().lower() in ("exit", "quit"):
                break
            if not user_input.strip():
                continue
            response = agent.send(user_input)
            print(f"jarvis> {response}")
    except (litellm.exceptions.AuthenticationError, litellm.exceptions.APIConnectionError) as e:
        print(
            f"Jarvis couldn't authenticate with the API for model '{config.model}': "
            f"{_summarize(e)}\n"
            "If you haven't set an API key for this provider yet, copy .env.example to "
            ".env and set it (e.g. ANTHROPIC_API_KEY, GEMINI_API_KEY, DEEPSEEK_API_KEY, "
            "GROQ_API_KEY) — otherwise this may be a network issue reaching the provider."
        )
        return 1
    except (litellm.exceptions.NotFoundError, litellm.exceptions.BadRequestError) as e:
        print(
            f"Jarvis couldn't reach model '{config.model}': {_summarize(e)}\n"
            "Check JARVIS_MODEL uses a valid litellm provider prefix, e.g. "
            "anthropic/claude-opus-5, gemini/gemini-2.5-flash, deepseek/deepseek-chat, "
            "groq/llama-3.3-70b-versatile, ollama/llama3.1."
        )
        return 1

    return 0


def cmd_note_add(args: argparse.Namespace) -> int:
    config = load_config()
    vault = Vault(config.vault_dir)
    store = MemoryStore(config.db_path)
    note = vault.create_note(args.title, args.content, tags=_parse_tags(args.tags))
    store.index_note(note)
    print(f"Created note {note.id}: {note.title}")
    return 0


def cmd_note_list(args: argparse.Namespace) -> int:
    config = load_config()
    vault = Vault(config.vault_dir)
    notes = vault.list_notes()
    if not notes:
        print("No notes yet.")
        return 0
    for note in notes:
        print(f"{note.id}  {note.title}")
    return 0


def cmd_note_search(args: argparse.Namespace) -> int:
    config = load_config()
    store = MemoryStore(config.db_path)
    results = store.search(args.query)
    if not results:
        print("No matches.")
        return 0
    for result in results:
        print(f"{result.note_id}  {result.title}  {result.snippet}")
    return 0


def cmd_note_show(args: argparse.Namespace) -> int:
    config = load_config()
    vault = Vault(config.vault_dir)
    note = vault.get_note(args.note_id)
    if note is None:
        print(f"No note found with id {args.note_id}")
        return 1
    print(f"# {note.title}\n")
    print(note.content)
    return 0


def cmd_remind_add(args: argparse.Namespace) -> int:
    config = load_config()
    reminders = ReminderStore(config.reminders_db_path)
    reminder = reminders.add(args.text, args.due_at)
    print(f"Added reminder {reminder.id}: {reminder.text} (due {reminder.due_at})")
    return 0


def cmd_remind_list(args: argparse.Namespace) -> int:
    config = load_config()
    reminders = ReminderStore(config.reminders_db_path)
    items = reminders.list(include_done=args.all)
    if not items:
        print("No reminders.")
        return 0
    for reminder in items:
        status = "done" if reminder.done else "pending"
        print(f"{reminder.id}  [{status}]  {reminder.text}  (due {reminder.due_at})")
    return 0


def cmd_remind_done(args: argparse.Namespace) -> int:
    config = load_config()
    reminders = ReminderStore(config.reminders_db_path)
    ok = reminders.complete(args.reminder_id)
    if ok:
        print(f"Marked {args.reminder_id} as done.")
        return 0
    print(f"No reminder found with id {args.reminder_id}")
    return 1


def cmd_digest(args: argparse.Namespace) -> int:
    config = load_config()
    vault = Vault(config.vault_dir)
    reminders = ReminderStore(config.reminders_db_path)
    print(daily_digest(vault, reminders))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "chat":
        return cmd_chat(args)
    if args.command == "note":
        if args.note_command == "add":
            return cmd_note_add(args)
        if args.note_command == "list":
            return cmd_note_list(args)
        if args.note_command == "search":
            return cmd_note_search(args)
        if args.note_command == "show":
            return cmd_note_show(args)
    if args.command == "remind":
        if args.remind_command == "add":
            return cmd_remind_add(args)
        if args.remind_command == "list":
            return cmd_remind_list(args)
        if args.remind_command == "done":
            return cmd_remind_done(args)
    if args.command == "digest":
        return cmd_digest(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
