from __future__ import annotations

import argparse
import sys

import litellm
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.markup import escape
from rich.spinner import Spinner
from rich.table import Table

from jarvis import secrets, tts
from jarvis.config import load_config
from jarvis.memory.store import MemoryStore
from jarvis.models import AgentAbort
from jarvis.scheduler.jobs import ReminderStore, daily_digest
from jarvis.tools import calendar_tools, computer_tools, email_tools, notes_tools, reminder_tools
from jarvis.vault import Vault

_COMPUTER_USE_MAX_TOOL_ITERATIONS = 25

console = Console()


def _summarize(e: Exception) -> str:
    # litellm embeds a full traceback in some exceptions' message text; show only
    # the first line so CLI error output stays readable.
    return str(e).splitlines()[0]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jarvis", description="Your personal second brain.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    chat_parser = subparsers.add_parser("chat", help="Start an interactive chat session with Jarvis.")
    chat_parser.add_argument(
        "--speak", action="store_true", help="Also speak each response aloud (see README 'Voice output')."
    )

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

    note_delete = note_sub.add_parser("delete", help="Delete a note.")
    note_delete.add_argument("note_id")

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

    auth_parser = subparsers.add_parser("auth", help="Manage provider API keys in the OS keychain.")
    auth_sub = auth_parser.add_subparsers(dest="auth_command", required=True)

    auth_set = auth_sub.add_parser("set", help="Store a provider API key in the OS keychain.")
    auth_set.add_argument("name", help="Env var name, e.g. ANTHROPIC_API_KEY.")

    auth_sub.add_parser("list", help="Show which known keys have a stored value.")

    auth_delete = auth_sub.add_parser("delete", help="Remove a stored key from the OS keychain.")
    auth_delete.add_argument("name")

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
    tools.extend(computer_tools.build_tools())

    return vault, store, reminders, tools


def cmd_chat(args: argparse.Namespace) -> int:
    from jarvis.agent.core import _MAX_TOOL_ITERATIONS, JarvisAgent

    config = load_config()
    _vault, _store, _reminders, tools = _build_agent_stack(config)

    computer_use_active = any(tool.name.startswith("computer_") for tool in tools)
    max_tool_iterations = _COMPUTER_USE_MAX_TOOL_ITERATIONS if computer_use_active else _MAX_TOOL_ITERATIONS

    speak_enabled = False
    if args.speak:
        try:
            with console.status("[dim]Loading voice model...[/dim]"):
                tts.ensure_ready()
            speak_enabled = True
        except tts.VoiceUnavailable as e:
            console.print(f"[yellow]Voice unavailable:[/yellow] {escape(str(e))} Continuing in text-only mode.")

    try:
        agent = JarvisAgent(model=config.model, tools=tools, max_tool_iterations=max_tool_iterations)
        console.print("[bold cyan]Jarvis[/bold cyan] is ready. Type 'exit' or 'quit' to leave.")
        if computer_use_active:
            console.print(
                "[yellow]Computer-use tools are active[/yellow]: Jarvis can see the screen "
                "and control the mouse/keyboard on this machine. Drag the mouse to any "
                "screen corner at any time to hard-stop it."
            )
        while True:
            try:
                user_input = console.input("[bold green]you>[/bold green] ")
            except EOFError:
                console.print()
                break
            if user_input.strip().lower() in ("exit", "quit"):
                break
            if not user_input.strip():
                continue
            _run_turn(agent, user_input, speak=speak_enabled)
    except AgentAbort as e:
        console.print(f"\n[bold red]Stopped:[/bold red] {e}")
        return 1
    except (litellm.exceptions.AuthenticationError, litellm.exceptions.APIConnectionError) as e:
        console.print(
            f"[bold red]Jarvis couldn't authenticate[/bold red] with the API for model "
            f"'{escape(config.model)}': {escape(_summarize(e))}\n"
            "If you haven't set an API key for this provider yet, run "
            f"[cyan]jarvis auth set {_key_env_var_hint(config.model)}[/cyan] or copy "
            ".env.example to .env — otherwise this may be a network issue reaching the provider."
        )
        return 1
    except (litellm.exceptions.NotFoundError, litellm.exceptions.BadRequestError) as e:
        console.print(
            f"[bold red]Jarvis couldn't reach model[/bold red] '{escape(config.model)}': "
            f"{escape(_summarize(e))}\n"
            "Check JARVIS_MODEL uses a valid litellm provider prefix, e.g. "
            "anthropic/claude-opus-5, gemini/gemini-2.5-flash, deepseek/deepseek-chat, "
            "groq/llama-3.3-70b-versatile, ollama/llama3.1."
        )
        return 1

    return 0


def _key_env_var_hint(model: str) -> str:
    provider = model.split("/", 1)[0] if "/" in model else "anthropic"
    return {
        "anthropic": "ANTHROPIC_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "groq": "GROQ_API_KEY",
    }.get(provider, "ANTHROPIC_API_KEY")


def _run_turn(agent, user_input: str, speak: bool = False) -> str:
    """Send one message, streaming the response live into the terminal via rich."""
    state = {"live": None, "buffer": []}

    def start_live():
        state["live"] = Live(
            Spinner("dots", text="Jarvis is thinking..."),
            console=console,
            refresh_per_second=12,
            transient=True,
        )
        state["live"].start()

    def on_delta(text: str) -> None:
        state["buffer"].append(text)
        state["live"].update(Markdown("".join(state["buffer"])))

    def on_tool_call(name: str) -> None:
        state["live"].stop()
        console.print(f"[dim]→ using {escape(name)}[/dim]")
        start_live()

    start_live()
    try:
        response = agent.send(user_input, on_delta=on_delta, on_tool_call=on_tool_call)
    finally:
        state["live"].stop()

    console.print("[bold cyan]jarvis>[/bold cyan]")
    console.print(Markdown(response) if response else "[dim](no response)[/dim]")

    if speak and response:
        try:
            with console.status("[dim]Generating voice...[/dim]"):
                tts.speak(response)
        except tts.VoiceUnavailable as e:
            console.print(f"[dim](voice failed: {escape(str(e))})[/dim]")

    return response


def cmd_auth_set(args: argparse.Namespace) -> int:
    value = console.input(f"Enter value for [bold]{escape(args.name)}[/bold] (hidden): ", password=True)
    if not value:
        console.print("No value entered; nothing stored.")
        return 1
    try:
        secrets.set_secret(args.name, value)
    except Exception as e:
        console.print(
            f"[bold red]Couldn't store {escape(args.name)} in the OS keychain:[/bold red] {escape(str(e))}"
        )
        return 1
    console.print(f"Stored {escape(args.name)} in the OS keychain.")
    return 0


def cmd_auth_list(args: argparse.Namespace) -> int:
    table = Table(show_header=True, header_style="bold")
    table.add_column("Key")
    table.add_column("Stored in keychain")
    for name in secrets.KNOWN_KEYS:
        stored = "yes" if secrets.get_secret(name) else "no"
        table.add_row(name, stored)
    console.print(table)
    return 0


def cmd_auth_delete(args: argparse.Namespace) -> int:
    if secrets.delete_secret(args.name):
        console.print(f"Removed {escape(args.name)} from the OS keychain.")
        return 0
    console.print(f"No stored value for {escape(args.name)}.")
    return 1


def cmd_note_add(args: argparse.Namespace) -> int:
    config = load_config()
    vault = Vault(config.vault_dir)
    store = MemoryStore(config.db_path)
    note = vault.create_note(args.title, args.content, tags=_parse_tags(args.tags))
    store.index_note(note)
    console.print(f"Created note {note.id}: {escape(note.title)}")
    return 0


def cmd_note_list(args: argparse.Namespace) -> int:
    config = load_config()
    vault = Vault(config.vault_dir)
    notes = vault.list_notes()
    if not notes:
        console.print("No notes yet.")
        return 0
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("Title")
    table.add_column("Updated")
    for note in notes:
        table.add_row(note.id, escape(note.title), note.updated_at)
    console.print(table)
    return 0


def cmd_note_search(args: argparse.Namespace) -> int:
    config = load_config()
    store = MemoryStore(config.db_path)
    results = store.search(args.query)
    if not results:
        console.print("No matches.")
        return 0
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("Title")
    table.add_column("Snippet")
    for result in results:
        table.add_row(result.note_id, escape(result.title), escape(result.snippet))
    console.print(table)
    return 0


def cmd_note_show(args: argparse.Namespace) -> int:
    config = load_config()
    vault = Vault(config.vault_dir)
    note = vault.get_note(args.note_id)
    if note is None:
        console.print(f"No note found with id {escape(args.note_id)}")
        return 1
    console.print(f"[bold]{escape(note.title)}[/bold]\n")
    console.print(Markdown(note.content))
    return 0


def cmd_note_delete(args: argparse.Namespace) -> int:
    config = load_config()
    vault = Vault(config.vault_dir)
    store = MemoryStore(config.db_path)
    if not vault.delete_note(args.note_id):
        console.print(f"No note found with id {escape(args.note_id)}")
        return 1
    store.remove_note(args.note_id)
    console.print(f"Deleted note {escape(args.note_id)}")
    return 0


def cmd_remind_add(args: argparse.Namespace) -> int:
    config = load_config()
    reminders = ReminderStore(config.reminders_db_path)
    try:
        reminder = reminders.add(args.text, args.due_at)
    except ValueError as e:
        console.print(f"[bold red]{escape(str(e))}[/bold red]")
        return 1
    console.print(
        f"Added reminder {reminder.id}: {escape(reminder.text)} (due {escape(reminder.due_at)})"
    )
    return 0


def cmd_remind_list(args: argparse.Namespace) -> int:
    config = load_config()
    reminders = ReminderStore(config.reminders_db_path)
    items = reminders.list(include_done=args.all)
    if not items:
        console.print("No reminders.")
        return 0
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("Status")
    table.add_column("Text")
    table.add_column("Due")
    for reminder in items:
        status = "[green]done[/green]" if reminder.done else "[yellow]pending[/yellow]"
        table.add_row(reminder.id, status, escape(reminder.text), escape(reminder.due_at))
    console.print(table)
    return 0


def cmd_remind_done(args: argparse.Namespace) -> int:
    config = load_config()
    reminders = ReminderStore(config.reminders_db_path)
    ok = reminders.complete(args.reminder_id)
    if ok:
        console.print(f"Marked {escape(args.reminder_id)} as done.")
        return 0
    console.print(f"No reminder found with id {escape(args.reminder_id)}")
    return 1


def cmd_digest(args: argparse.Namespace) -> int:
    config = load_config()
    vault = Vault(config.vault_dir)
    reminders = ReminderStore(config.reminders_db_path)
    console.print(escape(daily_digest(vault, reminders)))
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
        if args.note_command == "delete":
            return cmd_note_delete(args)
    if args.command == "remind":
        if args.remind_command == "add":
            return cmd_remind_add(args)
        if args.remind_command == "list":
            return cmd_remind_list(args)
        if args.remind_command == "done":
            return cmd_remind_done(args)
    if args.command == "digest":
        return cmd_digest(args)
    if args.command == "auth":
        if args.auth_command == "set":
            return cmd_auth_set(args)
        if args.auth_command == "list":
            return cmd_auth_list(args)
        if args.auth_command == "delete":
            return cmd_auth_delete(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
