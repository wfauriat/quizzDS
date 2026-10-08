"""SQLite persistence: connection, schema migrations and deck import."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from quizz.decks import ROOT
from quizz.models import Deck, Question

DB_PATH = ROOT / "data" / "quizz.sqlite"
SCHEMA_VERSION = 1
_SCHEMA_SQL = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    """Open the database, creating the schema if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # FastAPI may run a request's dependency and handler in different threads; each
    # connection is still used by a single request at a time.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == SCHEMA_VERSION:
        return
    if version == 0:
        conn.executescript(f"BEGIN;\n{_SCHEMA_SQL}\nCOMMIT;")
        return
    raise RuntimeError(f"database schema v{version} is not supported (this code expects v{SCHEMA_VERSION})")


def question_hash(q: Question) -> str:
    """Identify a question revision: sha256 (16 hex chars) of its canonical JSON."""
    canonical = json.dumps(q.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def import_decks(conn: sqlite3.Connection, decks: list[tuple[Path, Deck]]) -> Counter[str]:
    """Upsert decks and their questions into the content tables. Idempotent.

    Returns how many questions were "new", "changed" or "unchanged".
    """
    now = utcnow()
    counts: Counter[str] = Counter()
    with conn:
        for path, deck in decks:
            conn.execute(
                """
                INSERT INTO deck (id, title, description, author, source_path, imported_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (id) DO UPDATE SET
                    title = excluded.title, description = excluded.description, author = excluded.author,
                    source_path = excluded.source_path, imported_at = excluded.imported_at
                """,
                (deck.id, deck.title, deck.description, deck.author, _display_path(path), now),
            )
            conn.execute("DELETE FROM deck_question WHERE deck_id = ?", (deck.id,))
            for position, q in enumerate(deck.questions):
                counts[_upsert_question(conn, q, now)] += 1
                conn.execute(
                    "INSERT INTO deck_question (deck_id, question_id, position) VALUES (?, ?, ?)",
                    (deck.id, q.id, position),
                )
    return counts


def _upsert_question(conn: sqlite3.Connection, q: Question, now: str) -> str:
    h = question_hash(q)
    conn.execute(
        "INSERT OR IGNORE INTO question_revision (hash, question_id, body_json, first_seen) VALUES (?, ?, ?, ?)",
        (h, q.id, q.model_dump_json(), now),
    )
    row = conn.execute("SELECT current_hash FROM question WHERE id = ?", (q.id,)).fetchone()
    if row is not None and row["current_hash"] == h:
        return "unchanged"
    conn.execute(
        """
        INSERT INTO question (id, domain, topic, tags_json, level, kind, type, current_hash, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            domain = excluded.domain, topic = excluded.topic, tags_json = excluded.tags_json,
            level = excluded.level, kind = excluded.kind, type = excluded.type,
            current_hash = excluded.current_hash, updated_at = excluded.updated_at
        """,
        (q.id, q.domain, q.topic, json.dumps(q.tags), q.level, q.kind, q.type, h, now),
    )
    return "new" if row is None else "changed"


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)
