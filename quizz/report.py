"""Learning report: a markdown digest of the answer history, for the user and for Claude's analysis.

Accuracy figures use *first attempts* only: once a question has been answered, its answer has been
revealed (right away in learn mode, in the summary in exam mode), so later attempts on the same
question measure retention instead. Those are reported separately.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from statistics import median

from quizz.models import DOMAIN_LABELS, Question

DOMAINS = list(DOMAIN_LABELS)
LEVELS = [1, 2, 3, 4, 5]
CONFIDENCE = {1: "guess", 2: "unsure", 3: "sure"}


@dataclass
class Attempt:
    attempt_id: int
    session_id: int
    deck_id: str
    mode: str
    answered_at: str
    question_id: str
    domain: str
    topic: str
    level: int
    kind: str
    type: str
    selected: list[str]
    is_correct: bool
    confidence: int | None
    time_ms: int | None
    attempt_no: int  # 1 = the first time this question was ever answered
    question: Question  # the revision that was served

    @property
    def credit(self) -> float:
        """1 or 0 for single-answer questions; for multi, Jaccard similarity of picked vs correct choices."""
        if self.type == "single":
            return float(self.is_correct)
        picked, answer = set(self.selected), set(self.question.answer)
        return len(picked & answer) / len(picked | answer)


_ATTEMPTS_SQL = """
SELECT v.*, r.body_json,
       ROW_NUMBER() OVER (PARTITION BY v.question_id ORDER BY v.answered_at, v.attempt_id) AS attempt_no
FROM v_attempt v
JOIN question_revision r ON r.hash = v.question_hash
ORDER BY v.answered_at, v.attempt_id
"""


def load_attempts(conn: sqlite3.Connection) -> list[Attempt]:
    """Every recorded answer, oldest first, numbered per question over the whole history."""
    return [
        Attempt(
            attempt_id=r["attempt_id"],
            session_id=r["session_id"],
            deck_id=r["deck_id"],
            mode=r["mode"],
            answered_at=r["answered_at"],
            question_id=r["question_id"],
            domain=r["domain"],
            topic=r["topic"],
            level=r["level"],
            kind=r["kind"],
            type=r["type"],
            selected=json.loads(r["selected_json"]),
            is_correct=bool(r["is_correct"]),
            confidence=r["confidence"],
            time_ms=r["time_ms"],
            attempt_no=r["attempt_no"],
            question=Question.model_validate_json(r["body_json"]),
        )
        for r in conn.execute(_ATTEMPTS_SQL)
    ]


@dataclass
class Group:
    key: Hashable
    n: int = 0
    correct: int = 0
    credit: float = 0.0
    times: list[int] = field(default_factory=list)

    def add(self, a: Attempt) -> None:
        self.n += 1
        self.correct += a.is_correct
        self.credit += a.credit
        if a.time_ms is not None:
            self.times.append(a.time_ms)

    @property
    def accuracy(self) -> float:
        return self.correct / self.n

    @property
    def median_s(self) -> float | None:
        return median(self.times) / 1000 if self.times else None


def group(attempts: list[Attempt], key: Callable[[Attempt], Hashable], order: list | None = None) -> list[Group]:
    groups: dict[Hashable, Group] = {}
    for a in attempts:
        k = key(a)
        groups.setdefault(k, Group(k)).add(a)
    rank = {k: i for i, k in enumerate(order or [])}
    return sorted(groups.values(), key=lambda g: (rank.get(g.key, len(rank)), str(g.key)))


def build_report(
    conn: sqlite3.Connection,
    *,
    deck: str | None = None,
    since: str | None = None,
    session_ids: list[int] | None = None,
    now: datetime | None = None,
) -> str:
    """Markdown report over the answers matching the filters (all of them by default)."""
    history = load_attempts(conn)
    selected = [
        a
        for a in history
        if (deck is None or a.deck_id == deck)
        and (since is None or a.answered_at >= since)
        and (not session_ids or a.session_id in session_ids)
    ]
    first = [a for a in selected if a.attempt_no == 1]
    filters = ", ".join(
        f"{name} = {value}" for name, value in (("deck", deck), ("since", since), ("sessions", session_ids)) if value
    )
    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M UTC")
    parts = [f"# quizzDS learning report\n\n_Generated {stamp} · filters: {filters or 'none'}_"]
    if not selected:
        parts.append("No answers recorded for these filters yet.")
    else:
        parts += [
            _overview(selected, first),
            _sessions(conn, sorted({a.session_id for a in selected})),
        ]
        if first:
            parts += [
                _breakdowns(first),
                _matrix(first),
                _calibration(first),
                _topics(first),
                _misses(first),
            ]
        parts.append(_repeats(selected, history))
    parts.append(_coverage(conn, history))
    return "\n\n".join(p for p in parts if p) + "\n"


# ---------------------------------------------------------------- formatting helpers


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def _secs(x: float | None) -> str:
    return "–" if x is None else f"{x:.0f} s"


def _table(headers: list[str], rows: list[list[object]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def _group_table(title: str, groups: list[Group], label: Callable[[Hashable], str] = str) -> str:
    headers = [title.removeprefix("By ").capitalize(), "n", "correct", "accuracy", "partial credit", "median time"]
    rows = [
        [label(g.key), g.n, g.correct, _pct(g.accuracy), _pct(g.credit / g.n), _secs(g.median_s)] for g in groups
    ]
    return f"### {title}\n\n" + _table(headers, rows)


def _excerpt(markdown: str, limit: int = 160) -> str:
    text = re.sub(r"```.*?```", " […] ", markdown, flags=re.S)
    text = re.sub(r"[*`]", "", " ".join(text.split()))
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# ---------------------------------------------------------------- sections


def _overview(selected: list[Attempt], first: list[Attempt]) -> str:
    g = Group("all")
    for a in first:
        g.add(a)
    lines = [
        "## Overview",
        "",
        f"- Period: {selected[0].answered_at[:10]} → {selected[-1].answered_at[:10]}",
        f"- Answers: {len(selected)} ({len(first)} first attempts, {len(selected) - len(first)} repeats)",
    ]
    if first:
        lines.append(
            f"- First-attempt accuracy: **{_pct(g.accuracy)}** ({g.correct}/{g.n}) · partial credit "
            f"{_pct(g.credit / g.n)} · median time {_secs(g.median_s)}"
        )
    return "\n".join(lines)


def _sessions(conn: sqlite3.Connection, ids: list[int]) -> str:
    rows = []
    for s in conn.execute(
        """
        SELECT s.*, (SELECT count(*) FROM session_question WHERE session_id = s.id) AS n_questions,
               (SELECT count(*) FROM attempt WHERE session_id = s.id) AS n_answered,
               (SELECT coalesce(sum(is_correct), 0) FROM attempt WHERE session_id = s.id) AS n_correct
        FROM quiz_session s ORDER BY s.id
        """
    ):
        if s["id"] not in ids:
            continue
        duration = "unfinished"
        if s["finished_at"]:
            elapsed = datetime.fromisoformat(s["finished_at"]) - datetime.fromisoformat(s["started_at"])
            duration = f"{int(elapsed.total_seconds()) // 60} min"
        answered = f"{s['n_answered']}/{s['n_questions']}"
        score = f"{s['n_correct']}/{s['n_questions']}"
        rows.append([s["id"], s["started_at"][:10], s["deck_id"], s["mode"], answered, score, duration])
    return "## Sessions\n\n" + _table(["#", "date", "deck", "mode", "answered", "score", "duration"], rows)


def _breakdowns(first: list[Attempt]) -> str:
    return "\n\n".join(
        [
            "## Breakdown (first attempts)",
            _group_table("By domain", group(first, lambda a: a.domain, DOMAINS)),
            _group_table("By level", group(first, lambda a: a.level, LEVELS), lambda k: f"L{k}"),
            _group_table("By kind", group(first, lambda a: a.kind)),
            _group_table("By type", group(first, lambda a: a.type)),
        ]
    )


def _matrix(first: list[Attempt]) -> str:
    cells = {g.key: g for g in group(first, lambda a: (a.domain, a.level))}
    rows = [
        [d] + [f"{cells[d, lv].correct}/{cells[d, lv].n}" if (d, lv) in cells else "·" for lv in LEVELS]
        for d in DOMAINS
    ]
    return "### Domain × level (correct/answered)\n\n" + _table(["domain"] + [f"L{lv}" for lv in LEVELS], rows)


def _calibration(first: list[Attempt]) -> str:
    groups = group(first, lambda a: a.confidence or 0, [3, 2, 1, 0])
    rows = [[CONFIDENCE.get(g.key, "—"), g.n, g.correct, _pct(g.accuracy), _secs(g.median_s)] for g in groups]
    sure_wrong = [a for a in first if a.confidence == 3 and not a.is_correct]
    guessed_right = [a for a in first if a.confidence == 1 and a.is_correct]

    def ids(attempts: list[Attempt]) -> str:
        return ", ".join(f"`{a.question_id}` (L{a.level})" for a in attempts) or "none"

    return "\n".join(
        [
            "## Confidence calibration (first attempts)",
            "",
            _table(["confidence", "n", "correct", "accuracy", "median time"], rows),
            "",
            f"- Sure but wrong (possible misconceptions): {ids(sure_wrong)}",
            f"- Guessed right (lucky, not yet known): {ids(guessed_right)}",
        ]
    )


def _topics(first: list[Attempt]) -> str:
    groups = group(first, lambda a: (a.domain, a.topic))
    groups.sort(key=lambda g: (DOMAINS.index(g.key[0]) if g.key[0] in DOMAINS else 99, g.key[1]))
    rows = [[g.key[0], g.key[1], g.n, g.correct, _pct(g.credit / g.n)] for g in groups]
    return "## Topics (first attempts)\n\n" + _table(["domain", "topic", "n", "correct", "partial credit"], rows)


def _misses(first: list[Attempt]) -> str:
    misses = [a for a in first if not a.is_correct]
    if not misses:
        return "## Misses (first attempts)\n\nNone."
    blocks = ["## Misses (first attempts)", "Legend: ✓ picked and correct · ✗ picked but wrong · ○ correct but missed."]
    for a in misses:
        q = a.question
        lines = [
            f"### `{a.question_id}` — {a.domain} / {a.topic} · L{a.level} · {a.kind} · {a.type}",
            f"{CONFIDENCE.get(a.confidence or 0, 'no confidence')} · {_secs((a.time_ms or 0) / 1000)} · "
            f"session {a.session_id}" + (f" · partial credit {_pct(a.credit)}" if a.type == "multi" else ""),
            "",
            f"> {_excerpt(q.prompt)}",
            "",
        ]
        for c in q.choices:
            picked, right = c.id in a.selected, c.id in q.answer
            if picked or right:
                mark = "✓ picked" if picked and right else "✗ picked" if picked else "○ missed"
                lines.append(f"- {mark} **{c.id}**: {c.text}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _repeats(selected: list[Attempt], history: list[Attempt]) -> str:
    repeated = sorted({a.question_id for a in selected if a.attempt_no > 1})
    if not repeated:
        return ""
    rows = []
    for qid in repeated:
        tries = [a for a in history if a.question_id == qid]
        rows.append([f"`{qid}`", f"L{tries[0].level}", " → ".join("✓" if a.is_correct else "✗" for a in tries)])
    return "## Repeats (retention)\n\n" + _table(["question", "level", "results over time"], rows)


def _coverage(conn: sqlite3.Connection, history: list[Attempt]) -> str:
    answered = {a.question_id for a in history}
    pool = conn.execute(
        "SELECT dq.deck_id, q.id, q.domain, q.level FROM deck_question dq JOIN question q ON q.id = dq.question_id"
    ).fetchall()
    per_deck: dict[str, list[int]] = {}
    unanswered: dict[tuple[str, int], int] = {}
    for r in pool:
        counts = per_deck.setdefault(r["deck_id"], [0, 0])
        counts[0] += 1
        if r["id"] in answered:
            counts[1] += 1
        else:
            unanswered[r["domain"], r["level"]] = unanswered.get((r["domain"], r["level"]), 0) + 1
    deck_rows = [[d, n, done, n - done] for d, (n, done) in sorted(per_deck.items())]
    matrix_rows = [[d] + [unanswered.get((d, lv), "·") for lv in LEVELS] for d in DOMAINS]
    return "\n\n".join(
        [
            "## Coverage",
            _table(["deck", "questions", "answered", "not yet answered"], deck_rows),
            "### Unanswered questions available (domain × level)",
            _table(["domain"] + [f"L{lv}" for lv in LEVELS], matrix_rows),
        ]
    )
