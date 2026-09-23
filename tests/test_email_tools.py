import base64

from delphi import gmail_auth
from delphi.tools import email_tools


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


class _Execute:
    def __init__(self, result):
        self._result = result

    def execute(self):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _FakeMessagesResource:
    def __init__(self, service):
        self._service = service
        self.calls = []

    def list(self, userId, q=None, maxResults=None):
        self.calls.append(("list", {"q": q, "maxResults": maxResults}))
        ids = self._service.message_ids_for_query.get(q, self._service.default_message_ids)
        if maxResults is not None:
            ids = ids[:maxResults]
        return _Execute({"messages": [{"id": i} for i in ids], "resultSizeEstimate": len(ids)})

    def get(self, userId, id, format=None, metadataHeaders=None):
        self.calls.append(("get", {"id": id, "format": format}))
        return _Execute(self._service.messages_by_id[id])

    def modify(self, userId, id, body):
        self.calls.append(("modify", {"id": id, "body": body}))
        return _Execute({})


class _FakeLabelsResource:
    def __init__(self, service):
        self._service = service
        self.calls = []

    def list(self, userId):
        return _Execute({"labels": self._service.label_dicts})

    def create(self, userId, body):
        self.calls.append(("create", body))
        new_label = {"id": f"Label_{len(self._service.label_dicts) + 1}", "name": body["name"]}
        self._service.label_dicts.append(new_label)
        return _Execute(new_label)


class FakeGmailService:
    def __init__(self, messages_by_id, message_ids_for_query=None, labels=None):
        self.messages_by_id = messages_by_id
        self.message_ids_for_query = message_ids_for_query or {}
        self.default_message_ids = list(messages_by_id.keys())
        self.label_dicts = labels if labels is not None else []
        self._messages = _FakeMessagesResource(self)
        self._labels = _FakeLabelsResource(self)

    def users(self):
        return self

    def messages(self):
        return self._messages

    def labels(self):
        return self._labels


def _plain_message(message_id: str, sender: str, subject: str, snippet: str, body: str) -> dict:
    return {
        "id": message_id,
        "snippet": snippet,
        "payload": {
            "headers": [
                {"name": "From", "value": sender},
                {"name": "To", "value": "me@example.com"},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": "Mon, 1 Jan 2024 00:00:00 +0000"},
            ],
            "mimeType": "text/plain",
            "body": {"data": _b64(body)},
        },
    }


def _tools_by_name(tools):
    return {t.name: t for t in tools}


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DELPHI_ENABLE_EMAIL", raising=False)
    assert email_tools.build_tools() == []


def test_enabled_exposes_expected_tools_and_nothing_destructive(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_EMAIL", "1")
    tools = _tools_by_name(email_tools.build_tools())

    assert set(tools) == {
        "search_email",
        "list_recent_emails",
        "get_email",
        "label_email",
        "archive_email",
        "mark_read",
        "mark_unread",
    }
    assert "trash_email" not in tools
    assert "delete_email" not in tools
    assert "send_email" not in tools


def test_search_email_returns_compact_summaries(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_EMAIL", "1")
    service = FakeGmailService(
        {"m1": _plain_message("m1", "alice@example.com", "Hi", "hello there", "Hello there")},
        message_ids_for_query={"is:unread": ["m1"]},
    )
    monkeypatch.setattr(email_tools.gmail_auth, "get_client", lambda: service)

    tools = _tools_by_name(email_tools.build_tools())
    result = tools["search_email"].handler({"query": "is:unread"})

    assert "m1" in result
    assert "alice@example.com" in result
    assert "Hi" in result
    assert "hello there" in result


def test_search_email_missing_query_raises(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_EMAIL", "1")
    tools = _tools_by_name(email_tools.build_tools())

    import pytest

    with pytest.raises(ValueError, match="query"):
        tools["search_email"].handler({})


def test_list_recent_emails_uses_inbox_query(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_EMAIL", "1")
    service = FakeGmailService(
        {"m1": _plain_message("m1", "bob@example.com", "Inbox item", "snippet text", "body")},
        message_ids_for_query={"in:inbox": ["m1"]},
    )
    monkeypatch.setattr(email_tools.gmail_auth, "get_client", lambda: service)

    tools = _tools_by_name(email_tools.build_tools())
    result = tools["list_recent_emails"].handler({})

    assert "bob@example.com" in result
    assert service._messages.calls[0] == ("list", {"q": "in:inbox", "maxResults": 10})


def test_get_email_returns_plain_text_body(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_EMAIL", "1")
    message = _plain_message("m1", "alice@example.com", "Hi", "snippet", "Full plain body")
    service = FakeGmailService({"m1": message})
    monkeypatch.setattr(email_tools.gmail_auth, "get_client", lambda: service)

    tools = _tools_by_name(email_tools.build_tools())
    result = tools["get_email"].handler({"message_id": "m1"})

    assert "From: alice@example.com" in result
    assert "Subject: Hi" in result
    assert "Full plain body" in result


def test_get_email_falls_back_to_stripped_html_when_no_plain_part(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_EMAIL", "1")
    message = {
        "id": "m1",
        "snippet": "snippet",
        "payload": {
            "headers": [{"name": "From", "value": "a@example.com"}, {"name": "Subject", "value": "S"}],
            "mimeType": "text/html",
            "body": {"data": _b64("<p>Hello <b>world</b></p>")},
        },
    }
    service = FakeGmailService({"m1": message})
    monkeypatch.setattr(email_tools.gmail_auth, "get_client", lambda: service)

    tools = _tools_by_name(email_tools.build_tools())
    result = tools["get_email"].handler({"message_id": "m1"})

    assert "Hello world" in result
    assert "<p>" not in result
    assert "<b>" not in result


def test_get_email_prefers_plain_part_in_multipart_message(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_EMAIL", "1")
    message = {
        "id": "m1",
        "snippet": "snippet",
        "payload": {
            "headers": [{"name": "From", "value": "a@example.com"}],
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/plain", "body": {"data": _b64("Plain version")}},
                {"mimeType": "text/html", "body": {"data": _b64("<p>HTML version</p>")}},
            ],
        },
    }
    service = FakeGmailService({"m1": message})
    monkeypatch.setattr(email_tools.gmail_auth, "get_client", lambda: service)

    tools = _tools_by_name(email_tools.build_tools())
    result = tools["get_email"].handler({"message_id": "m1"})

    assert "Plain version" in result
    assert "HTML version" not in result


def test_get_email_wraps_gmail_unavailable(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_EMAIL", "1")

    def _raise():
        raise gmail_auth.GmailUnavailable("no token")

    monkeypatch.setattr(email_tools.gmail_auth, "get_client", _raise)
    tools = _tools_by_name(email_tools.build_tools())

    result = tools["get_email"].handler({"message_id": "m1"})

    assert "Gmail isn't available" in result
    assert "no token" in result


def test_label_email_applies_existing_label_case_insensitively(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_EMAIL", "1")
    service = FakeGmailService(
        {"m1": _plain_message("m1", "a@example.com", "S", "snip", "body")},
        labels=[{"id": "Label_9", "name": "Work"}],
    )
    monkeypatch.setattr(email_tools.gmail_auth, "get_client", lambda: service)
    tools = _tools_by_name(email_tools.build_tools())

    result = tools["label_email"].handler({"message_id": "m1", "label": "work"})

    assert "Labeled m1" in result
    assert service._labels.calls == []  # no create call - matched the existing label
    assert service._messages.calls[-1] == ("modify", {"id": "m1", "body": {"addLabelIds": ["Label_9"]}})


def test_label_email_creates_label_when_missing(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_EMAIL", "1")
    service = FakeGmailService({"m1": _plain_message("m1", "a@example.com", "S", "snip", "body")})
    monkeypatch.setattr(email_tools.gmail_auth, "get_client", lambda: service)
    tools = _tools_by_name(email_tools.build_tools())

    result = tools["label_email"].handler({"message_id": "m1", "label": "Todo"})

    assert "Labeled m1" in result
    assert service._labels.calls == [("create", {"name": "Todo"})]
    assert service.label_dicts == [{"id": "Label_1", "name": "Todo"}]
    assert service._messages.calls[-1] == ("modify", {"id": "m1", "body": {"addLabelIds": ["Label_1"]}})


def test_archive_email_removes_inbox_label(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_EMAIL", "1")
    service = FakeGmailService({"m1": _plain_message("m1", "a@example.com", "S", "snip", "body")})
    monkeypatch.setattr(email_tools.gmail_auth, "get_client", lambda: service)
    tools = _tools_by_name(email_tools.build_tools())

    result = tools["archive_email"].handler({"message_id": "m1"})

    assert "Archived m1" in result
    assert service._messages.calls[-1] == ("modify", {"id": "m1", "body": {"removeLabelIds": ["INBOX"]}})


def test_mark_read_and_unread(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_EMAIL", "1")
    service = FakeGmailService({"m1": _plain_message("m1", "a@example.com", "S", "snip", "body")})
    monkeypatch.setattr(email_tools.gmail_auth, "get_client", lambda: service)
    tools = _tools_by_name(email_tools.build_tools())

    tools["mark_read"].handler({"message_id": "m1"})
    assert service._messages.calls[-1] == ("modify", {"id": "m1", "body": {"removeLabelIds": ["UNREAD"]}})

    tools["mark_unread"].handler({"message_id": "m1"})
    assert service._messages.calls[-1] == ("modify", {"id": "m1", "body": {"addLabelIds": ["UNREAD"]}})


def test_summarize_inbox_returns_none_when_disabled(monkeypatch):
    monkeypatch.delenv("DELPHI_ENABLE_EMAIL", raising=False)
    assert email_tools.summarize_inbox() is None


def test_summarize_inbox_returns_none_when_not_authorized(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_EMAIL", "1")

    def _raise():
        raise gmail_auth.GmailUnavailable("no token")

    monkeypatch.setattr(email_tools.gmail_auth, "get_client", _raise)

    assert email_tools.summarize_inbox() is None


def test_summarize_inbox_returns_structured_summary(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_EMAIL", "1")
    service = FakeGmailService(
        {"m1": _plain_message("m1", "alice@example.com", "Hi", "hello", "body")},
        message_ids_for_query={"in:inbox is:unread": ["m1"], "in:inbox": ["m1"]},
    )
    monkeypatch.setattr(email_tools.gmail_auth, "get_client", lambda: service)

    result = email_tools.summarize_inbox(max_results=5)

    assert result is not None
    assert "1 unread" in result
    assert "alice@example.com" in result


def test_summarize_inbox_handles_api_failure_gracefully(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_EMAIL", "1")

    class _BrokenService:
        def users(self):
            return self

        def messages(self):
            return self

        def list(self, **kwargs):
            return _Execute(RuntimeError("Gmail API is down"))

    monkeypatch.setattr(email_tools.gmail_auth, "get_client", lambda: _BrokenService())

    result = email_tools.summarize_inbox()

    assert result is not None
    assert "couldn't fetch email" in result
