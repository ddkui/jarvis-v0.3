import json
from types import SimpleNamespace

import pytest

from jarvis.agent.core import JarvisAgent
from jarvis.models import AgentAbort, Tool


def _response(content=None, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _tool_call(call_id, name, arguments):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


def test_send_returns_text_when_no_tool_calls(monkeypatch):
    monkeypatch.setattr(
        "jarvis.agent.core.litellm.completion",
        lambda **kwargs: _response(content="Hello there."),
    )

    agent = JarvisAgent(model="anthropic/claude-opus-5", tools=[])
    assert agent.send("hi") == "Hello there."
    assert agent.messages[-1] == {"role": "assistant", "content": "Hello there."}


def test_send_executes_tool_then_returns_final_text(monkeypatch):
    calls = iter(
        [
            _response(tool_calls=[_tool_call("call_1", "echo", {"text": "ping"})]),
            _response(content="Done: pong"),
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

    result = agent.send("say ping")

    assert result == "Done: pong"
    tool_result_messages = [m for m in agent.messages if m.get("role") == "tool"]
    assert tool_result_messages == [
        {"role": "tool", "tool_call_id": "call_1", "content": "pong"}
    ]


def test_send_records_error_as_tool_result_without_raising(monkeypatch):
    calls = iter(
        [
            _response(tool_calls=[_tool_call("call_1", "boom", {})]),
            _response(content="Sorted it out."),
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
        lambda **kwargs: _response(tool_calls=[_tool_call("call_x", "loopy", {})]),
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
            _response(tool_calls=[_tool_call("call_1", "screenshot", {})]),
            _response(content="I can see the desktop now."),
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
        lambda **kwargs: _response(tool_calls=[_tool_call("call_1", "click", {})]),
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
            _response(tool_calls=[_tool_call("call_1", "does_not_exist", {})]),
            _response(content="ok"),
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
