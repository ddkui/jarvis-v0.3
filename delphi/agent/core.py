from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from typing import Callable

import litellm

from delphi.agent.prompts import SYSTEM_PROMPT
from delphi.models import AgentAbort, Tool

_MAX_TOOL_ITERATIONS = 8
_IMAGE_DATA_URL_PREFIX = "data:image/"
# No timeout on the completion call meant a provider that stalls instead of
# erroring cleanly (no bytes at all, ever) just hung forever - especially
# visible with a fallback model choking on something in the conversation
# history (e.g. a large embedded screenshot) without returning a clean 4xx.
# litellm's `timeout` is a read timeout: as long as *something* keeps
# streaming in, however long the response takes, it's fine; it only fires
# once the connection goes fully silent for this many seconds - which then
# raises litellm.exceptions.Timeout, already in _RETRYABLE_ERRORS, so a
# stalled fallback model correctly moves on to the next one instead of
# hanging the whole turn.
_DEFAULT_REQUEST_TIMEOUT_SECONDS = 60
# Ollama defaults every model to a 2048/4096-token context window regardless
# of what the underlying model actually supports, unless told otherwise per
# request - and Delphi's system prompt plus its full tool schema list alone
# can easily be 10k+ tokens (more tools enabled, e.g. computer-use/code, make
# this worse), so a fresh conversation can blow straight past the Ollama
# default before the user has said anything. Only applies to "ollama/..."
# models - other providers manage their own (much larger) context windows.
_DEFAULT_OLLAMA_NUM_CTX = 8192

# Transient/availability failures worth retrying with a fallback model rather
# than surfacing immediately - e.g. a provider's rate limit or an outage.
# ServiceUnavailableError also covers MidStreamFallbackError (litellm raises
# that as a subclass) - a stream that dies partway through hits this path.
# NotFoundError is here too - "this exact model string doesn't exist/isn't
# available" (a typo, or a model that's been retired - hit live as a 410 Gone
# for a model whose end-of-life date had passed) is inherently per-entry in
# the fallback list, not something that would recur identically on a
# *different* model the way a bad API key or a malformed request would.
_RETRYABLE_ERRORS = (
    litellm.exceptions.RateLimitError,
    litellm.exceptions.APIConnectionError,
    litellm.exceptions.ServiceUnavailableError,
    litellm.exceptions.Timeout,
    litellm.exceptions.InternalServerError,
    litellm.exceptions.BadGatewayError,
    litellm.exceptions.NotFoundError,
)
# Deliberately excludes AuthenticationError/BadRequestError and friends:
# those usually mean a request that's broken regardless of which model
# receives it (missing/invalid key for that provider, malformed payload), so
# burning through the whole fallback list on them just delays the same error
# rather than recovering from it.

# Statuses meaning "this specific model/endpoint is gone or doesn't exist"
# rather than "the request itself is malformed" - worth treating the same as
# NotFoundError above even when litellm couldn't map the response to that
# specific exception type and fell back to its generic APIError instead (as
# happened for a 410 Gone from a retired model).
_RETRYABLE_GENERIC_API_ERROR_STATUS_CODES = {404, 410}


def _is_retryable(e: Exception) -> bool:
    if isinstance(e, _RETRYABLE_ERRORS):
        return True
    if isinstance(e, litellm.exceptions.APIError):
        return getattr(e, "status_code", None) in _RETRYABLE_GENERIC_API_ERROR_STATUS_CODES
    return False


class DelphiAgent:
    """Wraps litellm's unified completion API with a manual agentic tool-use loop.

    The model string picks the provider via litellm's "<provider>/<model>" convention,
    e.g. "anthropic/claude-opus-5", "gemini/gemini-2.5-flash", "deepseek/deepseek-chat",
    "groq/llama-3.3-70b-versatile", "ollama/llama3.1". litellm reads that provider's API
    key from the environment (ANTHROPIC_API_KEY, GEMINI_API_KEY, DEEPSEEK_API_KEY,
    GROQ_API_KEY; Ollama needs no key, just a local server) and normalizes tool-calling
    and errors across all of them to the OpenAI-compatible shape used below.

    If the configured provider's credentials are missing/invalid,
    litellm.exceptions.AuthenticationError propagates out of send() unhandled; the CLI
    layer is expected to catch it and print a friendly message.

    fallback_models, if given, are tried in order whenever `model` (or the
    previous fallback) hits a transient/availability error - a provider's
    rate limit being the main case in practice. See _RETRYABLE_ERRORS.
    """

    def __init__(
        self,
        model: str,
        tools: list[Tool],
        max_tool_iterations: int = _MAX_TOOL_ITERATIONS,
        system_prompt: str = SYSTEM_PROMPT,
        fallback_models: list[str] | None = None,
        request_timeout_seconds: float = _DEFAULT_REQUEST_TIMEOUT_SECONDS,
        ollama_num_ctx: int | None = _DEFAULT_OLLAMA_NUM_CTX,
    ) -> None:
        self.model = model
        self.fallback_models = fallback_models or []
        self.system_prompt = system_prompt
        self._max_tool_iterations = max_tool_iterations
        self._request_timeout_seconds = request_timeout_seconds
        self._ollama_num_ctx = ollama_num_ctx
        self._tool_schemas = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in tools
        ]
        self._handlers = {tool.name: tool.handler for tool in tools}
        self.messages: list[dict] = []

    def _execute(self, name: str, arguments: dict) -> str:
        handler = self._handlers.get(name)
        if handler is None:
            raise ValueError(f"unknown tool: {name}")
        return handler(arguments)

    def _stream_completion(self, on_delta: Callable[[str], None] | None):
        """Run one streamed completion call, trying self.model first and then
        each of self.fallback_models in order if a transient/availability
        error hits, or the model turns out to be unavailable/nonexistent (see
        _is_retryable) - e.g. the primary provider's rate limit, or a
        fallback entry that's been retired. A failure that isn't retryable
        (bad API key, a malformed request) propagates immediately without
        wasting time cycling through fallbacks, since it would fail
        identically on every one of them.

        Any text already streamed via on_delta before a retryable failure
        stays on screen - the retry starts a fresh response after it rather
        than trying to splice output together, which keeps this simple at the
        cost of a visible seam on the rare turn that actually needs to fall
        back mid-stream."""
        models_to_try = [self.model, *self.fallback_models]
        last_error: Exception | None = None
        for attempt, model in enumerate(models_to_try):
            try:
                return self._stream_completion_with_model(model, on_delta)
            except Exception as e:
                if not _is_retryable(e):
                    raise
                last_error = e
                if attempt + 1 < len(models_to_try):
                    print(
                        f"[agent] {model} failed ({e}); falling back to {models_to_try[attempt + 1]}",
                        file=sys.stderr,
                    )
        assert last_error is not None  # models_to_try is never empty (self.model is always first)
        raise last_error

    def _stream_completion_with_model(self, model: str, on_delta: Callable[[str], None] | None):
        """Run one streamed completion call against a specific model and
        return an object shaped like a non-streaming response's `.message`
        (`.content`, `.tool_calls`), by accumulating chunks as they arrive.
        Tool-call argument fragments are concatenated by their stream
        `index`, matching how providers split large tool calls across many
        chunks."""
        extra_params = {}
        if self._ollama_num_ctx is not None and model.startswith("ollama/"):
            extra_params["num_ctx"] = self._ollama_num_ctx

        stream = litellm.completion(
            model=model,
            messages=[{"role": "system", "content": self.system_prompt}] + self.messages,
            tools=self._tool_schemas or None,
            stream=True,
            timeout=self._request_timeout_seconds,
            **extra_params,
        )

        content_parts: list[str] = []
        tool_call_slots: dict[int, dict] = {}

        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                content_parts.append(delta.content)
                if on_delta is not None:
                    on_delta(delta.content)
            for tc in delta.tool_calls or []:
                slot = tool_call_slots.setdefault(tc.index, {"id": None, "name": None, "arguments": ""})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function and tc.function.name:
                    slot["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    slot["arguments"] += tc.function.arguments

        tool_calls = [
            SimpleNamespace(
                id=slot["id"],
                function=SimpleNamespace(name=slot["name"], arguments=slot["arguments"]),
            )
            for _, slot in sorted(tool_call_slots.items())
        ]
        return SimpleNamespace(content="".join(content_parts) or None, tool_calls=tool_calls or None)

    def send(
        self,
        user_message: str,
        on_delta: Callable[[str], None] | None = None,
        on_tool_call: Callable[[str], None] | None = None,
    ) -> str:
        """Send a user message and run the tool-use loop to completion.

        Streams the model's text as it arrives; pass on_delta to receive each text
        fragment as it's generated (e.g. to print it live), and on_tool_call to be
        notified of each tool name just before it runs. Both are optional — omit
        them and send() just returns the final text once everything's done.

        Returns the assistant's final response text. Raises
        litellm.exceptions.AuthenticationError if the active provider's API key is
        missing/invalid, and any other litellm API error its own retries could not
        resolve; callers should catch and present these to the user. Also raises
        delphi.models.AgentAbort if a tool handler requests an immediate stop (e.g. a
        computer-use failsafe trip) — this propagates out unconditionally rather than
        becoming a tool error the model could act on again.
        """
        self.messages.append({"role": "user", "content": user_message})

        for _ in range(self._max_tool_iterations):
            message = self._stream_completion(on_delta)
            tool_calls = message.tool_calls or []

            assistant_message: dict = {"role": "assistant", "content": message.content or ""}
            if tool_calls:
                assistant_message["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                    for call in tool_calls
                ]
            self.messages.append(assistant_message)

            if not tool_calls:
                return message.content or ""

            image_urls = []
            for i, call in enumerate(tool_calls):
                if on_tool_call is not None:
                    on_tool_call(call.function.name)
                try:
                    arguments = json.loads(call.function.arguments or "{}")
                    result_text = self._execute(call.function.name, arguments)
                except AgentAbort as abort:
                    # Every tool_call in this turn needs a matching tool result before
                    # any future turn, even the ones we're not going to run - otherwise
                    # a caller that catches AgentAbort and resumes send() on this same
                    # agent would send a malformed history (unmatched tool_calls) to
                    # the provider.
                    self.messages.append(
                        {"role": "tool", "tool_call_id": call.id, "content": f"Aborted: {abort}"}
                    )
                    for remaining in tool_calls[i + 1 :]:
                        self.messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": remaining.id,
                                "content": "Not executed: agent aborted.",
                            }
                        )
                    raise
                except Exception as e:
                    result_text = f"Error: {e}"

                if isinstance(result_text, str) and result_text.startswith(_IMAGE_DATA_URL_PREFIX):
                    image_urls.append(result_text)
                    result_text = "Image captured; see the image in the next message."

                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": result_text,
                    }
                )

            if image_urls:
                self.messages.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": url}}
                            for url in image_urls
                        ],
                    }
                )

        return (
            "I've gone through several tool calls without reaching an answer — "
            "something's likely looping. Try rephrasing, or ask me something narrower."
        )
