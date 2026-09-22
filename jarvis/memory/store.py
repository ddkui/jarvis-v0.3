import sqlite3
from pathlib import Path

from jarvis.models import Note, SearchResult


def _sanitize_fts_query(query: str) -> str:
    # Raw user text can contain FTS5 syntax (", *, AND/OR/NEAR, column:filters) that
    # would raise sqlite3.OperationalError. Quoting each token as a phrase and
    # joining with OR treats the query as plain keywords instead of FTS5 syntax.
    tokens = query.split()
    quoted = []
    for token in tokens:
        escaped = token.replace('"', '""')
        quoted.append(f'"{escaped}"')
    return " OR ".join(quoted)


class MemoryStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5("
            "note_id UNINDEXED, title, content, tags)"
        )
        self._conn.commit()

    def index_note(self, note: Note) -> None:
        self._conn.execute("DELETE FROM notes_fts WHERE note_id = ?", (note.id,))
        self._conn.execute(
            "INSERT INTO notes_fts (note_id, title, content, tags) VALUES (?, ?, ?, ?)",
            (note.id, note.title, note.content, " ".join(note.tags)),
        )
        self._conn.commit()

    def remove_note(self, note_id: str) -> None:
        self._conn.execute("DELETE FROM notes_fts WHERE note_id = ?", (note_id,))
        self._conn.commit()

    def search(self, query: str, limit: int = 8) -> list[SearchResult]:
        fts_query = _sanitize_fts_query(query)
        if not fts_query:
            return []
        cursor = self._conn.execute(
            "SELECT note_id, title, "
            "snippet(notes_fts, 2, '**', '**', '...', 10) AS snip, "
            "bm25(notes_fts) AS rank "
            "FROM notes_fts WHERE notes_fts MATCH ? ORDER BY rank LIMIT ?",
            (fts_query, limit),
        )
        results = []
        for note_id, title, snip, rank in cursor.fetchall():
            results.append(
                SearchResult(note_id=note_id, title=title, snippet=snip, score=rank)
            )
        return results
