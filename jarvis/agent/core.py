from __future__ import annotations

import json

import litellm

from jarvis.agent.prompts import SYSTEM_PROMPT
from jarvis.models import AgentAbort, Tool

_MAX_TOOL_ITERATIONS = 8
_IMAGE_DATA_URL_PREFIX = "data:image/"


class JarvisAgent:
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
    """

    def __init__(
        self, model: str, tools: list[Tool], max_tool_iterations: int = _MAX_TOOL_ITERATIONS
    ) -> None:
        self.model = model
        self._max_tool_iterations = max_tool_iterations
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

    def send(self, user_message: str) -> str:
        """Send a user message and run the tool-use loop to completion.

        Returns the assistant's final response text. Raises
        litellm.exceptions.AuthenticationError if the active provider's API key is
        missing/invalid, and any other litellm API error its own retries could not
        resolve; callers should catch and present these to the user. Also raises
        jarvis.models.AgentAbort if a tool handler requests an immediate stop (e.g. a
        computer-use failsafe trip) — this propagates out unconditionally rather than
        becoming a tool error the model could act on again.
        """
        self.messages.append({"role": "user", "content": user_message})

        for _ in range(self._max_tool_iterations):
            response = litellm.completion(
                model=self.model,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}] + self.messages,
                tools=self._tool_schemas or None,
            )

            message = response.choices[0].message
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
            for call in tool_calls:
                try:
                    arguments = json.loads(call.function.arguments or "{}")
                    result_text = self._execute(call.function.name, arguments)
                except AgentAbort:
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
