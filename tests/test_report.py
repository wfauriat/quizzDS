from contextlib import closing
from datetime import UTC, datetime

import pytest

from quizz import service
from quizz.db import connect, import_decks
from quizz.decks import load_decks
from quizz.report import build_report, load_attempts
from tests.helpers import make_question, write_deck

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path):
    decks_dir = tmp_path / "decks"
    decks_dir.mkdir()
    write_deck(
        decks_dir / "t.yaml",
        "test-deck",
        [
            make_question(),  # cs, L2, single, answer a
            make_question(
                id="ds-test-001",
                domain="ds",
                level=3,
                type="multi",
                choices=[{"id": "a", "text": "x"}, {"id": "b", "text": "y"}, {"id": "c", "text": "z"}],
                answer=["a", "c"],
            ),
            make_question(id="de-test-001", domain="de", topic="sql", level=4,
                          prompt="Which `event_ts` wins?\n\n```sql\nSELECT 1\n```"),
        ],
    )
    with closing(connect(tmp_path / "q.sqlite")) as c:
        import_decks(c, load_decks(decks_dir))
        yield c


def take(conn, mode, answers):
    """Run a finished session; answers are (question_id, selected, confidence)."""
    session_id = service.create_session(conn, "test-deck", mode)
    for question_id, selected, confidence in answers:
        service.record_answer(conn, session_id, question_id, selected, confidence, 2000)
    service.finish_session(conn, session_id)
    return session_id


@pytest.fixture
def history(conn):
    exam = take(conn, "exam", [("cs-test-001", ["a"], 3), ("ds-test-001", ["a"], 2), ("de-test-001", ["b"], 3)])
    learn = take(conn, "learn", [("de-test-001", ["a"], 2)])  # a repeat, after the answer was revealed
    return exam, learn


def test_attempts_are_numbered_per_question_with_partial_credit(conn, history):
    attempts = load_attempts(conn)
    assert [(a.question_id, a.attempt_no) for a in attempts] == [
        ("cs-test-001", 1),
        ("ds-test-001", 1),
        ("de-test-001", 1),
        ("de-test-001", 2),
    ]
    multi = attempts[1]
    assert not multi.is_correct and multi.credit == 0.5  # picked {a}, answer {a, c}


def test_report_scores_first_attempts_only(conn, history):
    report = build_report(conn, now=NOW)
    assert "_Generated 2026-10-09 12:00 UTC · filters: none_" in report
    assert "- Answers: 4 (3 first attempts, 1 repeats)" in report
    assert "First-attempt accuracy: **33%** (1/3) · partial credit 50% · median time 2 s" in report
    assert "| L4 | 1 | 0 | 0% | 0% | 2 s |" in report
    assert "| cs | · | 1/1 | · | · | · |" in report  # domain × level matrix


def test_report_flags_confident_mistakes_and_details_misses(conn, history):
    report = build_report(conn, now=NOW)
    assert "- Sure but wrong (possible misconceptions): `de-test-001` (L4)" in report
    assert "- ✗ picked **b**: 5" in report and "- ○ missed **a**: 4" in report
    assert "> Which event_ts wins? […]" in report
    assert "session 1 · partial credit 50%" in report  # the multi-select miss
    assert "- ○ missed **c**: z" in report


def test_report_tracks_retention_and_coverage(conn, history):
    report = build_report(conn, now=NOW)
    assert "| `de-test-001` | L4 | ✗ → ✓ |" in report
    assert "| test-deck | 3 | 3 | 0 |" in report


def test_report_filters(conn, history):
    _, learn = history
    only_learn = build_report(conn, session_ids=[learn], now=NOW)
    assert "- Answers: 1 (0 first attempts, 1 repeats)" in only_learn
    assert "## Breakdown" not in only_learn
    assert "No answers recorded" in build_report(conn, deck="other-deck", now=NOW)
    assert "No answers recorded" in build_report(conn, since="2999-01-01", now=NOW)


def test_report_on_an_empty_history(conn):
    report = build_report(conn, now=NOW)
    assert "No answers recorded" in report
    assert "| test-deck | 3 | 0 | 3 |" in report