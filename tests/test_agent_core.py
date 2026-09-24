import json
from types import SimpleNamespace

import litellm
import pytest

from delphi.agent.core import DelphiAgent
from delphi.models import AgentAbort, Tool


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
        "delphi.agent.core.litellm.completion",
        lambda **kwargs: _text_stream("Hello there."),
    )

    agent = DelphiAgent(model="anthropic/claude-opus-5", tools=[])
    assert agent.send("hi") == "Hello there."
    assert agent.messages[-1] == {"role": "assistant", "content": "Hello there."}


def test_send_streams_text_via_on_delta(monkeypatch):
    monkeypatch.setattr(
        "delphi.agent.core.litellm.completion",
        lambda **kwargs: _text_stream("Hello there.", split_into=3),
    )

    received = []
    agent = DelphiAgent(model="anthropic/claude-opus-5", tools=[])
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
        "delphi.agent.core.litellm.completion",
        lambda **kwargs: next(calls),
    )

    echo_tool = Tool(
        name="echo",
        description="Echoes text back reversed.",
        input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
        handler=lambda args: "pong" if args["text"] == "ping" else "unexpected",
    )
    agent = DelphiAgent(model="gemini/gemini-2.5-flash", tools=[echo_tool])

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
        "delphi.agent.core.litellm.completion",
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
    agent = DelphiAgent(model="deepseek/deepseek-chat", tools=[boom_tool])

    result = agent.send("trigger it")

    assert result == "Sorted it out."
    tool_result = next(m for m in agent.messages if m.get("role") == "tool")
    assert "kaboom" in tool_result["content"]


def test_send_stops_after_max_iterations(monkeypatch):
    monkeypatch.setattr(
        "delphi.agent.core.litellm.completion",
        lambda **kwargs: _tool_call_stream("call_x", "loopy", {}),
    )

    loopy_tool = Tool(
        name="loopy",
        description="Never resolves.",
        input_schema={"type": "object", "properties": {}},
        handler=lambda args: "still going",
    )
    agent = DelphiAgent(model="groq/llama-3.3-70b-versatile", tools=[loopy_tool])

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
        "delphi.agent.core.litellm.completion",
        lambda **kwargs: next(calls),
    )

    screenshot_tool = Tool(
        name="screenshot",
        description="Takes a screenshot.",
        input_schema={"type": "object", "properties": {}},
        handler=lambda args: "data:image/png;base64,ZmFrZQ==",
    )
    agent = DelphiAgent(model="anthropic/claude-opus-5", tools=[screenshot_tool])

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


def test_agent_abort_mid_batch_leaves_valid_message_history(monkeypatch):
    two_calls_stream = iter(
        [
            _chunk(tool_call=_tool_call_delta(0, call_id="call_safe", name="safe")),
            _chunk(tool_call=_tool_call_delta(0, arguments="{}")),
            _chunk(tool_call=_tool_call_delta(1, call_id="call_abort", name="click")),
            _chunk(tool_call=_tool_call_delta(1, arguments="{}")),
        ]
    )
    monkeypatch.setattr("delphi.agent.core.litellm.completion", lambda **kwargs: two_calls_stream)

    safe_tool = Tool(
        name="safe",
        description="Runs fine.",
        input_schema={"type": "object", "properties": {}},
        handler=lambda args: "safe ok",
    )
    click_tool = Tool(
        name="click",
        description="Clicks.",
        input_schema={"type": "object", "properties": {}},
        handler=lambda args: (_ for _ in ()).throw(AgentAbort("failsafe tripped")),
    )
    agent = DelphiAgent(model="anthropic/claude-opus-5", tools=[safe_tool, click_tool])

    with pytest.raises(AgentAbort):
        agent.send("do both things")

    tool_call_ids_declared = {
        tc["id"] for m in agent.messages if m.get("role") == "assistant" for tc in m.get("tool_calls", [])
    }
    tool_result_ids = {m["tool_call_id"] for m in agent.messages if m.get("role") == "tool"}
    assert tool_call_ids_declared == {"call_safe", "call_abort"}
    assert tool_result_ids == tool_call_ids_declared

    results_by_id = {m["tool_call_id"]: m["content"] for m in agent.messages if m.get("role") == "tool"}
    assert results_by_id["call_safe"] == "safe ok"
    assert "Aborted" in results_by_id["call_abort"]


def test_agent_abort_propagates_immediately(monkeypatch):
    monkeypatch.setattr(
        "delphi.agent.core.litellm.completion",
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
    agent = DelphiAgent(model="anthropic/claude-opus-5", tools=[click_tool])

    with pytest.raises(AgentAbort, match="failsafe tripped"):
        agent.send("click something")


def test_falls_back_to_next_model_on_rate_limit(monkeypatch):
    models_seen = []

    def fake_completion(**kwargs):
        models_seen.append(kwargs["model"])
        if kwargs["model"] == "gemini/gemini-2.5-flash":
            raise litellm.exceptions.RateLimitError(
                "quota exceeded", llm_provider="gemini", model="gemini-2.5-flash"
            )
        return _text_stream("Answered by the backup model.")

    monkeypatch.setattr("delphi.agent.core.litellm.completion", fake_completion)

    agent = DelphiAgent(
        model="gemini/gemini-2.5-flash",
        tools=[],
        fallback_models=["nvidia_nim/meta/llama3-70b-instruct"],
    )
    result = agent.send("hi")

    assert result == "Answered by the backup model."
    assert models_seen == ["gemini/gemini-2.5-flash", "nvidia_nim/meta/llama3-70b-instruct"]


def test_raises_last_error_when_every_fallback_also_fails(monkeypatch):
    def fake_completion(**kwargs):
        raise litellm.exceptions.RateLimitError(
            f"quota exceeded on {kwargs['model']}", llm_provider="x", model=kwargs["model"]
        )

    monkeypatch.setattr("delphi.agent.core.litellm.completion", fake_completion)

    agent = DelphiAgent(
        model="gemini/gemini-2.5-flash",
        tools=[],
        fallback_models=["nvidia_nim/meta/llama3-70b-instruct"],
    )
    with pytest.raises(litellm.exceptions.RateLimitError, match="nvidia_nim/meta/llama3-70b-instruct"):
        agent.send("hi")


def test_non_retryable_error_skips_fallbacks_entirely(monkeypatch):
    models_seen = []

    def fake_completion(**kwargs):
        models_seen.append(kwargs["model"])
        raise litellm.exceptions.AuthenticationError("bad key", llm_provider="gemini", model="x")

    monkeypatch.setattr("delphi.agent.core.litellm.completion", fake_completion)

    agent = DelphiAgent(
        model="gemini/gemini-2.5-flash",
        tools=[],
        fallback_models=["nvidia_nim/meta/llama3-70b-instruct"],
    )
    with pytest.raises(litellm.exceptions.AuthenticationError):
        agent.send("hi")

    assert models_seen == ["gemini/gemini-2.5-flash"]


def test_no_fallback_models_configured_behaves_as_before(monkeypatch):
    monkeypatch.setattr(
        "delphi.agent.core.litellm.completion",
        lambda **kwargs: _text_stream("Hello there."),
    )

    agent = DelphiAgent(model="anthropic/claude-opus-5", tools=[])
    assert agent.send("hi") == "Hello there."


def test_completion_call_gets_a_timeout_by_default(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured["timeout"] = kwargs.get("timeout")
        return _text_stream("hi")

    monkeypatch.setattr("delphi.agent.core.litellm.completion", fake_completion)

    agent = DelphiAgent(model="anthropic/claude-opus-5", tools=[])
    agent.send("hi")

    assert captured["timeout"] == 60.0


def test_completion_call_uses_configured_timeout(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured["timeout"] = kwargs.get("timeout")
        return _text_stream("hi")

    monkeypatch.setattr("delphi.agent.core.litellm.completion", fake_completion)

    agent = DelphiAgent(model="anthropic/claude-opus-5", tools=[], request_timeout_seconds=15)
    agent.send("hi")

    assert captured["timeout"] == 15


def test_ollama_model_gets_num_ctx_by_default(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured["num_ctx"] = kwargs.get("num_ctx")
        return _text_stream("hi")

    monkeypatch.setattr("delphi.agent.core.litellm.completion", fake_completion)

    agent = DelphiAgent(model="ollama/llama3.1", tools=[])
    agent.send("hi")

    assert captured["num_ctx"] == 8192


def test_ollama_num_ctx_is_configurable(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured["num_ctx"] = kwargs.get("num_ctx")
        return _text_stream("hi")

    monkeypatch.setattr("delphi.agent.core.litellm.completion", fake_completion)

    agent = DelphiAgent(model="ollama/llama3.1", tools=[], ollama_num_ctx=16384)
    agent.send("hi")

    assert captured["num_ctx"] == 16384


def test_ollama_num_ctx_can_be_disabled(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured["num_ctx_present"] = "num_ctx" in kwargs
        return _text_stream("hi")

    monkeypatch.setattr("delphi.agent.core.litellm.completion", fake_completion)

    agent = DelphiAgent(model="ollama/llama3.1", tools=[], ollama_num_ctx=None)
    agent.send("hi")

    assert captured["num_ctx_present"] is False


def test_non_ollama_models_never_get_num_ctx(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured["num_ctx_present"] = "num_ctx" in kwargs
        return _text_stream("hi")

    monkeypatch.setattr("delphi.agent.core.litellm.completion", fake_completion)

    agent = DelphiAgent(model="anthropic/claude-opus-5", tools=[])
    agent.send("hi")

    assert captured["num_ctx_present"] is False


def test_a_stalled_fallback_model_times_out_and_tries_the_next_one(monkeypatch):
    # This is the bug this test guards against: a fallback model that stalls
    # (no bytes at all, ever) rather than erroring cleanly used to hang the
    # whole turn forever, since litellm.completion() had no timeout at all.
    models_seen = []

    def fake_completion(**kwargs):
        models_seen.append(kwargs["model"])
        if kwargs["model"] == "gemini/gemini-2.5-flash":
            raise litellm.exceptions.RateLimitError(
                "quota exceeded", llm_provider="gemini", model="gemini-2.5-flash"
            )
        if kwargs["model"] == "nvidia_nim/moonshotai/kimi-k3":
            raise litellm.exceptions.Timeout(
                "timed out", llm_provider="nvidia_nim", model="moonshotai/kimi-k3"
            )
        return _text_stream("Answered by the second fallback.")

    monkeypatch.setattr("delphi.agent.core.litellm.completion", fake_completion)

    agent = DelphiAgent(
        model="gemini/gemini-2.5-flash",
        tools=[],
        fallback_models=["nvidia_nim/moonshotai/kimi-k3", "nvidia_nim/deepseek-ai/deepseek-v4-flash"],
    )
    result = agent.send("hi")

    assert result == "Answered by the second fallback."
    assert models_seen == [
        "gemini/gemini-2.5-flash",
        "nvidia_nim/moonshotai/kimi-k3",
        "nvidia_nim/deepseek-ai/deepseek-v4-flash",
    ]


def test_unknown_tool_call_surfaces_as_error(monkeypatch):
    calls = iter(
        [
            _tool_call_stream("call_1", "does_not_exist", {}),
            _text_stream("ok"),
        ]
    )
    monkeypatch.setattr(
        "delphi.agent.core.litellm.completion",
        lambda **kwargs: next(calls),
    )

    agent = DelphiAgent(model="anthropic/claude-opus-5", tools=[])
    agent.send("call a missing tool")

    tool_result = next(m for m in agent.messages if m.get("role") == "tool")
    assert "unknown tool" in tool_result["content"]
