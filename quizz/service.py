"""Application logic on top of the database: deck catalog, quiz sessions, grading, summaries.

Grading happens here, server-side: a question's answer is only revealed after it is answered
(learn mode) or after the session is finished (exam mode).
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from quizz.db import utcnow
from quizz.models import Question

Mode = Literal["learn", "exam"]


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class Invalid(Exception):
    pass


class SessionStats(BaseModel):
    session_id: int
    mode: Mode
    started_at: str
    finished_at: str | None
    n_questions: int
    n_answered: int
    n_correct: int


class DeckInfo(BaseModel):
    id: str
    title: str
    description: str
    author: str
    n_questions: int
    domains: dict[str, int]
    levels: dict[str, int]
    last_finished: SessionStats | None


class Bucket(BaseModel):
    key: str
    n: int
    answered: int
    correct: int


class ReviewItem(BaseModel):
    question: Question
    selected: list[str] | None
    is_correct: bool | None
    confidence: int | None
    time_ms: int | None


class Summary(SessionStats):
    deck_id: str
    by_domain: list[Bucket]
    by_level: list[Bucket]
    items: list[ReviewItem]


@dataclass
class Graded:
    question: Question
    is_correct: bool
    mode: Mode


_STATS_SQL = """
SELECT s.id AS session_id, s.mode, s.started_at, s.finished_at,
       (SELECT count(*) FROM session_question WHERE session_id = s.id) AS n_questions,
       (SELECT count(*) FROM attempt WHERE session_id = s.id) AS n_answered,
       (SELECT coalesce(sum(is_correct), 0) FROM attempt WHERE session_id = s.id) AS n_correct
FROM quiz_session s
"""


def list_decks(conn: sqlite3.Connection) -> list[DeckInfo]:
    decks = []
    for d in conn.execute("SELECT id, title, description, author FROM deck ORDER BY id"):
        meta = conn.execute(
            "SELECT q.domain, q.level FROM deck_question dq JOIN question q ON q.id = dq.question_id "
            "WHERE dq.deck_id = ?",
            (d["id"],),
        ).fetchall()
        last = conn.execute(
            _STATS_SQL + "WHERE s.deck_id = ? AND s.finished_at IS NOT NULL ORDER BY s.id DESC LIMIT 1",
            (d["id"],),
        ).fetchone()
        decks.append(
            DeckInfo(
                **d,
                n_questions=len(meta),
                domains=dict(sorted(Counter(r["domain"] for r in meta).items())),
                levels=dict(sorted(Counter(str(r["level"]) for r in meta).items())),
                last_finished=SessionStats(**last) if last else None,
            )
        )
    return decks


def create_session(conn: sqlite3.Connection, deck_id: str, mode: Mode) -> int:
    """Start a session serving the deck's current questions, in deck order."""
    rows = conn.execute(
        "SELECT dq.question_id, q.current_hash FROM deck_question dq JOIN question q ON q.id = dq.question_id "
        "WHERE dq.deck_id = ? ORDER BY dq.position",
        (deck_id,),
    ).fetchall()
    if not rows:
        raise NotFound(f"deck {deck_id!r} not found")
    with conn:
        session_id = conn.execute(
            "INSERT INTO quiz_session (deck_id, mode, started_at) VALUES (?, ?, ?)", (deck_id, mode, utcnow())
        ).lastrowid
        conn.executemany(
            "INSERT INTO session_question (session_id, position, question_id, question_hash) VALUES (?, ?, ?, ?)",
            [(session_id, i, r["question_id"], r["current_hash"]) for i, r in enumerate(rows)],
        )
    return session_id


def get_session(conn: sqlite3.Connection, session_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM quiz_session WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        raise NotFound(f"session {session_id} not found")
    return row


def session_questions(conn: sqlite3.Connection, session_id: int) -> list[Question]:
    """The questions served in a session, as they were when it started."""
    rows = conn.execute(
        "SELECT r.body_json FROM session_question sq JOIN question_revision r ON r.hash = sq.question_hash "
        "WHERE sq.session_id = ? ORDER BY sq.position",
        (session_id,),
    ).fetchall()
    return [Question.model_validate_json(r["body_json"]) for r in rows]


def record_answer(
    conn: sqlite3.Connection,
    session_id: int,
    question_id: str,
    selected: list[str],
    confidence: int,
    time_ms: int,
) -> Graded:
    """Grade an answer against the served revision of the question and store it."""
    session = get_session(conn, session_id)
    if session["finished_at"]:
        raise Conflict(f"session {session_id} is already finished")
    row = conn.execute(
        "SELECT r.body_json FROM session_question sq JOIN question_revision r ON r.hash = sq.question_hash "
        "WHERE sq.session_id = ? AND sq.question_id = ?",
        (session_id, question_id),
    ).fetchone()
    if row is None:
        raise NotFound(f"question {question_id!r} is not part of session {session_id}")
    if conn.execute(
        "SELECT 1 FROM attempt WHERE session_id = ? AND question_id = ?", (session_id, question_id)
    ).fetchone():
        raise Conflict(f"question {question_id!r} was already answered in session {session_id}")

    q = Question.model_validate_json(row["body_json"])
    chosen = sorted(set(selected))
    if not chosen:
        raise Invalid("select at least one choice")
    if unknown := set(chosen) - {c.id for c in q.choices}:
        raise Invalid(f"unknown choice ids: {sorted(unknown)}")
    if q.type == "single" and len(chosen) != 1:
        raise Invalid(f"question {question_id!r} takes exactly one choice")

    is_correct = chosen == sorted(q.answer)
    with conn:
        conn.execute(
            "INSERT INTO attempt (session_id, question_id, selected_json, is_correct, confidence, time_ms, answered_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, question_id, json.dumps(chosen), int(is_correct), confidence, time_ms, utcnow()),
        )
    return Graded(question=q, is_correct=is_correct, mode=session["mode"])


def finish_session(conn: sqlite3.Connection, session_id: int) -> None:
    """Mark the session finished (idempotent: the first finish time is kept)."""
    get_session(conn, session_id)
    with conn:
        conn.execute(
            "UPDATE quiz_session SET finished_at = ? WHERE id = ? AND finished_at IS NULL", (utcnow(), session_id)
        )


def summarize(conn: sqlite3.Connection, session_id: int) -> Summary:
    """Score, breakdowns and per-question review (with answers) of a session."""
    session = get_session(conn, session_id)
    if session["mode"] == "exam" and not session["finished_at"]:
        raise Conflict("finish the exam before viewing its results")
    stats = conn.execute(_STATS_SQL + "WHERE s.id = ?", (session_id,)).fetchone()
    attempts = {a["question_id"]: a for a in conn.execute("SELECT * FROM attempt WHERE session_id = ?", (session_id,))}

    items = []
    by_domain: dict[str, Counter[str]] = {}
    by_level: dict[str, Counter[str]] = {}
    for q in session_questions(conn, session_id):
        a = attempts.get(q.id)
        for bucket in (by_domain.setdefault(q.domain, Counter()), by_level.setdefault(str(q.level), Counter())):
            bucket["n"] += 1
            bucket["answered"] += a is not None
            bucket["correct"] += bool(a and a["is_correct"])
        items.append(
            ReviewItem(
                question=q,
                selected=json.loads(a["selected_json"]) if a else None,
                is_correct=bool(a["is_correct"]) if a else None,
                confidence=a["confidence"] if a else None,
                time_ms=a["time_ms"] if a else None,
            )
        )
    return Summary(
        **stats,
        deck_id=session["deck_id"],
        by_domain=_buckets(by_domain),
        by_level=_buckets(by_level),
        items=items,
    )


def _buckets(groups: dict[str, Counter[str]]) -> list[Bucket]:
    return [Bucket(key=k, n=c["n"], answered=c["answered"], correct=c["correct"]) for k, c in sorted(groups.items())]
