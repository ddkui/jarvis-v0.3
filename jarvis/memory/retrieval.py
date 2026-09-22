from jarvis.memory.store import MemoryStore
from jarvis.vault import Vault


def retrieve_context(store: MemoryStore, vault: Vault, query: str, limit: int = 5) -> str:
    results = store.search(query, limit=limit)
    if not results:
        return ""
    blocks = []
    for i, result in enumerate(results, start=1):
        blocks.append(f"[{i}] {result.title} (note_id: {result.note_id})\n{result.snippet}")
    return "\n\n".join(blocks)
