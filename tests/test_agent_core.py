import json
from types import SimpleNamespace

import pytest

from jarvis.agent.core import JarvisAgent
from jarvis.models import AgentAbort, Tool


def _chunk(content=None, tool_call=None):
    delta = SimpleNamespace(content=content, tool_calls=[tool_call] if tool_call else None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def _tool_call_delta(index, call_id=None, name=None, arguments=None):
    return SimpleNamespace(index=index, id=call_id, function=SimpleNamespace(name=name, arguments=arguments))


def _text_stream(text, split_into=2):
    # Split into multiple fragments to exercise chunk accumulation, not just single-chunk delivery.
    if len(text) < split_into:
        split_into = 1
    size = max(1, len(text) // split_into)
    parts = [text[i : i + size] for i in range(0, len(text), size)] or [""]
    return iter([_chunk(content=part) for part in parts])


def _tool_call_stream(call_id, name, arguments):
    # A real stream fragments id/name/arguments across separate chunks; simulate that split.
    args_json = json.dumps(arguments)
    return iter(
        [
            _chunk(tool_call=_tool_call_delta(0, call_id=call_id, name=name)),
            _chunk(tool_call=_tool_call_delta(0, arguments=args_json)),
        ]
    )


def test_send_returns_text_when_no_tool_calls(monkeypatch):
    monkeypatch.setattr(
        "jarvis.agent.core.litellm.completion",
        lambda **kwargs: _text_stream("Hello there."),
    )

    agent = JarvisAgent(model="anthropic/claude-opus-5", tools=[])
    assert agent.send("hi") == "Hello there."
    assert agent.messages[-1] == {"role": "assistant", "content": "Hello there."}


def test_send_streams_text_via_on_delta(monkeypatch):
    monkeypatch.setattr(
        "jarvis.agent.core.litellm.completion",
        lambda **kwargs: _text_stream("Hello there.", split_into=3),
    )

    received = []
    agent = JarvisAgent(model="anthropic/claude-opus-5", tools=[])
    result = agent.send("hi", on_delta=received.append)

    assert "".join(received) == "Hello there."
    assert result == "Hello there."


def test_send_executes_tool_then_returns_final_text(monkeypatch):
    calls = iter(
        [
            _tool_call_stream("call_1", "echo", {"text": "ping"}),
            _text_stream("Done: pong"),
        ]
    )
    monkeypatch.setattr(
        "jarvis.agent.core.litellm.completion",
        lambda **kwargs: next(calls),
    )

    echo_tool = Tool(
        name="echo",
        description="Echoes text back reversed.",
        input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
        handler=lambda args: "pong" if args["text"] == "ping" else "unexpected",
    )
    agent = JarvisAgent(model="gemini/gemini-2.5-flash", tools=[echo_tool])

    tool_calls_seen = []
    result = agent.send("say ping", on_tool_call=tool_calls_seen.append)

    assert result == "Done: pong"
    assert tool_calls_seen == ["echo"]
    tool_result_messages = [m for m in agent.messages if m.get("role") == "tool"]
    assert tool_result_messages == [
        {"role": "tool", "tool_call_id": "call_1", "content": "pong"}
    ]


def test_send_records_error_as_tool_result_without_raising(monkeypatch):
    calls = iter(
        [
            _tool_call_stream("call_1", "boom", {}),
            _text_stream("Sorted it out."),
        ]
    )
    monkeypatch.setattr(
        "jarvis.agent.core.litellm.completion",
        lambda **kwargs: next(calls),
    )

    def _raise(_args):
        raise ValueError("kaboom")

    boom_tool = Tool(
        name="boom",
        description="Always fails.",
        input_schema={"type": "object", "properties": {}},
        handler=_raise,
    )
    agent = JarvisAgent(model="deepseek/deepseek-chat", tools=[boom_tool])

    result = agent.send("trigger it")

    assert result == "Sorted it out."
    tool_result = next(m for m in agent.messages if m.get("role") == "tool")
    assert "kaboom" in tool_result["content"]


def test_send_stops_after_max_iterations(monkeypatch):
    monkeypatch.setattr(
        "jarvis.agent.core.litellm.completion",
        lambda **kwargs: _tool_call_stream("call_x", "loopy", {}),
    )

    loopy_tool = Tool(
        name="loopy",
        description="Never resolves.",
        input_schema={"type": "object", "properties": {}},
        handler=lambda args: "still going",
    )
    agent = JarvisAgent(model="groq/llama-3.3-70b-versatile", tools=[loopy_tool])

    result = agent.send("loop forever")

    assert "gone through several tool calls" in result


def test_image_result_becomes_followup_image_message(monkeypatch):
    calls = iter(
        [
            _tool_call_stream("call_1", "screenshot", {}),
            _text_stream("I can see the desktop now."),
        ]
    )
    monkeypatch.setattr(
        "jarvis.agent.core.litellm.completion",
        lambda **kwargs: next(calls),
    )

    screenshot_tool = Tool(
        name="screenshot",
        description="Takes a screenshot.",
        input_schema={"type": "object", "properties": {}},
        handler=lambda args: "data:image/png;base64,ZmFrZQ==",
    )
    agent = JarvisAgent(model="anthropic/claude-opus-5", tools=[screenshot_tool])

    result = agent.send("look at the screen")

    assert result == "I can see the desktop now."
    tool_result = next(m for m in agent.messages if m.get("role") == "tool")
    assert tool_result["content"] == "Image captured; see the image in the next message."

    image_message = next(
        m
        for m in agent.messages
        if m.get("role") == "user" and isinstance(m.get("content"), list)
    )
    assert image_message["content"] == [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,ZmFrZQ=="}}
    ]


def test_agent_abort_propagates_immediately(monkeypatch):
    monkeypatch.setattr(
        "jarvis.agent.core.litellm.completion",
        lambda **kwargs: _tool_call_stream("call_1", "click", {}),
    )

    def _abort(_args):
        raise AgentAbort("failsafe tripped")

    click_tool = Tool(
        name="click",
        description="Clicks.",
        input_schema={"type": "object", "properties": {}},
        handler=_abort,
    )
    agent = JarvisAgent(model="anthropic/claude-opus-5", tools=[click_tool])

    with pytest.raises(AgentAbort, match="failsafe tripped"):
        agent.send("click something")


def test_unknown_tool_call_surfaces_as_error(monkeypatch):
    calls = iter(
        [
            _tool_call_stream("call_1", "does_not_exist", {}),
            _text_stream("ok"),
        ]
    )
    monkeypatch.setattr(
        "jarvis.agent.core.litellm.completion",
        lambda **kwargs: next(calls),
    )

    agent = JarvisAgent(model="anthropic/claude-opus-5", tools=[])
    agent.send("call a missing tool")

    tool_result = next(m for m in agent.messages if m.get("role") == "tool")
    assert "unknown tool" in tool_result["content"]
