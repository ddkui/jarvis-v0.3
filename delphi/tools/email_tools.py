"""Gmail tools - search, read, label and archive the user's inbox.

Gated by DELPHI_ENABLE_EMAIL, mirroring delphi/tools/code_tools.py: build_tools()
just checks the flag and returns [] if unset, without touching the network -
real OAuth/API failures surface lazily, per call, via gmail_auth.get_client().
See delphi/gmail_auth.py and README.md "Email (Gmail)" for setup.

Deliberately narrow: label + archive only (archiving just removes the INBOX
label - reversible, nothing is deleted). No trash/delete or send tool is
implemented here, by design - out of scope for this build.
"""

from __future__ import annotations

import base64
import html as html_lib
import re

from delphi import gmail_auth
from delphi.models import Tool

_DEFAULT_MAX_RESULTS = 10


def _require(input: dict, key: str) -> object:
    if key not in input or input[key] in (None, ""):
        raise ValueError(f"missing required field: {key}")
    return input[key]


def _decode_part_data(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)  # urlsafe_b64decode needs proper padding
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _strip_html(markup: str) -> str:
    # A crude regex strip rather than a new HTML-parsing dependency - fine
    # for turning an email body into readable plain text, not a general
    # HTML-to-text tool.
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", markup)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _extract_body(payload: dict) -> str:
    """Walk the MIME part tree depth-first and return the first text/plain
    part found, falling back to a stripped text/html part."""
    plain, rendered_html = None, None

    def _walk(part: dict) -> None:
        nonlocal plain, rendered_html
        mime_type = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data and mime_type == "text/plain" and plain is None:
            plain = _decode_part_data(data)
        elif data and mime_type == "text/html" and rendered_html is None:
            rendered_html = _decode_part_data(data)
        for sub_part in part.get("parts") or []:
            _walk(sub_part)

    _walk(payload)
    if plain:
        return plain
    if rendered_html:
        return _strip_html(rendered_html)
    return "(no readable body)"


def _headers_of(message: dict) -> dict:
    return {h["name"]: h["value"] for h in message.get("payload", {}).get("headers", [])}


def _fetch_message_summaries(service, query: str, max_results: int) -> list[dict]:
    result = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    summaries = []
    for ref in result.get("messages", []):
        message = (
            service.users()
            .messages()
            .get(userId="me", id=ref["id"], format="metadata", metadataHeaders=["From", "Subject", "Date"])
            .execute()
        )
        headers = _headers_of(message)
        summaries.append(
            {
                "id": ref["id"],
                "from": headers.get("From", "(unknown sender)"),
                "subject": headers.get("Subject", "(no subject)"),
                "date": headers.get("Date", ""),
                "snippet": message.get("snippet", ""),
            }
        )
    return summaries


def _format_summaries(summaries: list[dict]) -> str:
    if not summaries:
        return "No matching emails."
    return "\n".join(
        f"{s['id']} | {s['from']} | {s['subject']} | {s['date']} | {s['snippet']}" for s in summaries
    )


def _get_or_create_label_id(service, label: str) -> str:
    existing = service.users().labels().list(userId="me").execute().get("labels", [])
    for candidate in existing:
        if candidate["name"].lower() == label.lower():
            return candidate["id"]
    created = service.users().labels().create(userId="me", body={"name": label}).execute()
    return created["id"]


def summarize_inbox(max_results: int = 20) -> str | None:
    """A fast, local-formatting (no LLM call) inbox summary for the daily
    digest: unread count plus the most recent messages. Returns None if email
    isn't enabled or not yet authorized, so callers can skip it silently the
    same way the rest of the digest degrades around missing optional
    features; returns a one-line failure note (rather than raising) if the
    Gmail API call itself fails, so a transient hiccup never breaks the
    digest."""
    if not gmail_auth.is_enabled():
        return None
    try:
        service = gmail_auth.get_client()
    except gmail_auth.GmailUnavailable:
        return None

    try:
        unread = service.users().messages().list(userId="me", q="in:inbox is:unread", maxResults=1).execute()
        unread_count = unread.get("resultSizeEstimate", 0)
        recent = _fetch_message_summaries(service, "in:inbox", max_results)
    except Exception as e:
        return f"couldn't fetch email: {e}"

    if not recent:
        return f"Inbox: {unread_count} unread, no messages in inbox."

    lines = [f"Inbox: {unread_count} unread. Most recent {len(recent)}:"]
    for summary in recent:
        lines.append(f"  - {summary['from']} - {summary['subject']} - {summary['snippet']}")
    return "\n".join(lines)


def build_tools() -> list[Tool]:
    if not gmail_auth.is_enabled():
        return []

    def search_email(input: dict) -> str:
        query = _require(input, "query")
        max_results = int(input.get("max_results", _DEFAULT_MAX_RESULTS))
        try:
            service = gmail_auth.get_client()
            summaries = _fetch_message_summaries(service, query, max_results)
        except gmail_auth.GmailUnavailable as e:
            return f"Gmail isn't available: {e}"
        except Exception as e:
            return f"Failed to search email: {e}"
        return _format_summaries(summaries)

    def list_recent_emails(input: dict) -> str:
        max_results = int(input.get("max_results", _DEFAULT_MAX_RESULTS))
        try:
            service = gmail_auth.get_client()
            summaries = _fetch_message_summaries(service, "in:inbox", max_results)
        except gmail_auth.GmailUnavailable as e:
            return f"Gmail isn't available: {e}"
        except Exception as e:
            return f"Failed to list recent emails: {e}"
        return _format_summaries(summaries)

    def get_email(input: dict) -> str:
        message_id = _require(input, "message_id")
        try:
            service = gmail_auth.get_client()
            message = service.users().messages().get(userId="me", id=message_id, format="full").execute()
        except gmail_auth.GmailUnavailable as e:
            return f"Gmail isn't available: {e}"
        except Exception as e:
            return f"Failed to fetch email {message_id}: {e}"
        headers = _headers_of(message)
        body = _extract_body(message.get("payload", {}))
        return (
            f"From: {headers.get('From', '')}\n"
            f"To: {headers.get('To', '')}\n"
            f"Subject: {headers.get('Subject', '')}\n"
            f"Date: {headers.get('Date', '')}\n\n"
            f"{body}"
        )

    def label_email(input: dict) -> str:
        message_id = _require(input, "message_id")
        label = _require(input, "label")
        try:
            service = gmail_auth.get_client()
            label_id = _get_or_create_label_id(service, label)
            service.users().messages().modify(userId="me", id=message_id, body={"addLabelIds": [label_id]}).execute()
        except gmail_auth.GmailUnavailable as e:
            return f"Gmail isn't available: {e}"
        except Exception as e:
            return f"Failed to label email {message_id}: {e}"
        return f"Labeled {message_id} with '{label}'."

    def archive_email(input: dict) -> str:
        message_id = _require(input, "message_id")
        try:
            service = gmail_auth.get_client()
            service.users().messages().modify(userId="me", id=message_id, body={"removeLabelIds": ["INBOX"]}).execute()
        except gmail_auth.GmailUnavailable as e:
            return f"Gmail isn't available: {e}"
        except Exception as e:
            return f"Failed to archive email {message_id}: {e}"
        return f"Archived {message_id} (removed from inbox - not deleted)."

    def mark_read(input: dict) -> str:
        message_id = _require(input, "message_id")
        try:
            service = gmail_auth.get_client()
            service.users().messages().modify(userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}).execute()
        except gmail_auth.GmailUnavailable as e:
            return f"Gmail isn't available: {e}"
        except Exception as e:
            return f"Failed to mark email {message_id} as read: {e}"
        return f"Marked {message_id} as read."

    def mark_unread(input: dict) -> str:
        message_id = _require(input, "message_id")
        try:
            service = gmail_auth.get_client()
            service.users().messages().modify(userId="me", id=message_id, body={"addLabelIds": ["UNREAD"]}).execute()
        except gmail_auth.GmailUnavailable as e:
            return f"Gmail isn't available: {e}"
        except Exception as e:
            return f"Failed to mark email {message_id} as unread: {e}"
        return f"Marked {message_id} as unread."

    return [
        Tool(
            name="search_email",
            description=(
                "Search the user's Gmail inbox using Gmail search syntax "
                "(e.g. 'is:unread', 'from:someone@example.com', 'newer_than:1d'). "
                "Returns a compact list: id, from, subject, date, snippet."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Gmail search query"},
                    "max_results": {"type": "integer", "description": "Max results to return (default 10)"},
                },
                "required": ["query"],
            },
            handler=search_email,
        ),
        Tool(
            name="list_recent_emails",
            description="List the most recent emails in the inbox (id, from, subject, date, snippet).",
            input_schema={
                "type": "object",
                "properties": {
                    "max_results": {"type": "integer", "description": "Max results to return (default 10)"},
                },
                "required": [],
            },
            handler=list_recent_emails,
        ),
        Tool(
            name="get_email",
            description="Fetch the full content (headers + body) of a single email by id.",
            input_schema={
                "type": "object",
                "properties": {"message_id": {"type": "string", "description": "Gmail message id"}},
                "required": ["message_id"],
            },
            handler=get_email,
        ),
        Tool(
            name="label_email",
            description="Apply a Gmail label to an email, creating the label first if it doesn't exist yet.",
            input_schema={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string", "description": "Gmail message id"},
                    "label": {"type": "string", "description": "Label name to apply"},
                },
                "required": ["message_id", "label"],
            },
            handler=label_email,
        ),
        Tool(
            name="archive_email",
            description=(
                "Archive an email (remove it from the inbox). This only removes the INBOX label - "
                "it is reversible and does not delete the email."
            ),
            input_schema={
                "type": "object",
                "properties": {"message_id": {"type": "string", "description": "Gmail message id"}},
                "required": ["message_id"],
            },
            handler=archive_email,
        ),
        Tool(
            name="mark_read",
            description="Mark an email as read.",
            input_schema={
                "type": "object",
                "properties": {"message_id": {"type": "string", "description": "Gmail message id"}},
                "required": ["message_id"],
            },
            handler=mark_read,
        ),
        Tool(
            name="mark_unread",
            description="Mark an email as unread.",
            input_schema={
                "type": "object",
                "properties": {"message_id": {"type": "string", "description": "Gmail message id"}},
                "required": ["message_id"],
            },
            handler=mark_unread,
        ),
    ]
