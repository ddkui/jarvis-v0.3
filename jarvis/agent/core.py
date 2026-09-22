from __future__ import annotations

import anthropic

from jarvis.agent.prompts import SYSTEM_PROMPT
from jarvis.models import Tool

_MAX_TOOL_ITERATIONS = 8


class JarvisAgent:
    """Wraps the Anthropic SDK with a manual agentic tool-use loop.

    Requires ANTHROPIC_API_KEY to be set in the environment. If it is not,
    anthropic.AuthenticationError propagates out of send() unhandled; the CLI
    layer is expected to catch it and print a friendly message pointing the
    user at .env.example.
    """

    def __init__(self, model: str, tools: list[Tool]) -> None:
        self.model = model
        self._client = anthropic.Anthropic()
        self._tool_schemas = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in tools
        ]
        self._handlers = {tool.name: tool.handler for tool in tools}
        self.messages: list = []

    def _execute(self, name: str, tool_input: dict) -> str:
        handler = self._handlers.get(name)
        if handler is None:
            raise ValueError(f"unknown tool: {name}")
        return handler(tool_input)

    def send(self, user_message: str) -> str:
        """Send a user message and run the tool-use loop to completion.

        Returns the concatenated text of the final assistant response. Raises
        anthropic.AuthenticationError if ANTHROPIC_API_KEY is missing/invalid,
        and any other anthropic API error that the SDK's own retries could not
        resolve; callers should catch and present these to the user.
        """
        self.messages.append({"role": "user", "content": user_message})

        for _ in range(_MAX_TOOL_ITERATIONS):
            response = self._client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=self._tool_schemas,
                messages=self.messages,
                thinking={"type": "adaptive"},
                output_config={"effort": "medium"},
            )

            if response.stop_reason != "tool_use":
                self.messages.append({"role": "assistant", "content": response.content})
                return "".join(
                    block.text for block in response.content if block.type == "text"
                )

            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
            self.messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in tool_use_blocks:
                try:
                    result_text = self._execute(block.name, block.input)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_text,
                        }
                    )
                except Exception as e:
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(e),
                            "is_error": True,
                        }
                    )

            self.messages.append({"role": "user", "content": tool_results})

        return (
            "I've gone through several tool calls without reaching an answer — "
            "something's likely looping. Try rephrasing, or ask me something narrower."
        )
