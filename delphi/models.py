from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class Note:
    id: str
    title: str
    content: str
    tags: list[str]
    created_at: str
    updated_at: str
    path: str


@dataclass
class SearchResult:
    note_id: str
    title: str
    snippet: str
    score: float


@dataclass
class Reminder:
    id: str
    text: str
    due_at: str
    done: bool = False


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], str]


class AgentAbort(Exception):
    """Raise from a Tool.handler to stop the agent loop immediately, rather than
    letting the failure come back as a retriable tool error the model might act on
    again (e.g. a physical computer-use failsafe trip)."""
