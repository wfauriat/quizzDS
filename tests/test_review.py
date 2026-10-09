"""Reviewing past sessions offline: the HTML page and the `sessions` / `review` commands."""

from contextlib import closing

import pytest
from typer.testing import CliRunner

from quizz import service
from quizz.__main__ import app
from quizz.db import connect, import_decks
from quizz.decks import load_decks
from quizz.render import render_session
from tests.helpers import make_question, write_deck

runner = CliRunner()


@pytest.fixture
def db_path(tmp_path):
    decks_dir = tmp_path / "decks"
    decks_dir.mkdir()
    write_deck(
        decks_dir / "t.yaml",
        "test-deck",
        [
            make_question(choices=[{"id": "a", "text": "4", "why": "Two and two."}, {"id": "b", "text": "<b>5</b>"}]),
            make_question(id="ds-test-001", domain="ds", level=3, explanation="Because **reasons**."),
            make_question(id="de-test-001", domain="de", level=4),
        ],
    )
    path = tmp_path / "q.sqlite"
    with closing(connect(path)) as conn:
        import_decks(conn, load_decks(decks_dir))
        # Exam: right, wrong (sure), skipped.
        sid = service.create_session(conn, "test-deck", "exam")
        service.record_answer(conn, sid, "cs-test-001", ["a"], 2, 1500)
        service.record_answer(conn, sid, "ds-test-001", ["b"], 3, 65000)
        service.finish_session(conn, sid)
        # An exam left unfinished: its answers must stay hidden.
        service.create_session(conn, "test-deck", "exam")
    return path


def test_session_page_shows_answers_like_the_ui_summary(db_path):
    with closing(connect(db_path)) as conn:
        html = render_session(service.summarize(conn, 1))
    assert "<title>test-deck — session 1</title>" in html
    assert '<div class="score-value">33%</div>' in html
    assert "<b>1</b><span>sure but wrong</span>" in html
    # Right answer, wrong answer (expanded) with the missed correct choice, skipped question.
    assert '<details class="q review-ok" id="cs-test-001">' in html
    assert '<details class="q review-ko" id="ds-test-001" open>' in html
    assert '<details class="q review-skipped" id="de-test-001">' in html
    assert "✗ your answer" in html and "correct answer" in html and "✓ your answer" in html
    assert "Unsure · 2s" in html and "Sure · 1m 05s" in html and ">skipped<" in html
    assert "Because <strong>reasons</strong>." in html
    assert '<span class="why">Two and two.</span>' in html
    assert "&lt;b&gt;5&lt;/b&gt;" in html  # choice text is escaped


def test_sessions_command_lists_newest_first(db_path):
    result = runner.invoke(app, ["sessions", "--db-path", str(db_path)])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0].split()[0] == "2" and lines[0].endswith("(unfinished)")
    assert lines[1].split()[0] == "1" and "1/3  correct  test-deck" in lines[1]


def test_review_command_defaults_to_the_latest_finished_session(db_path, tmp_path):
    out = tmp_path / "review.html"
    result = runner.invoke(app, ["review", "--db-path", str(db_path), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "test-deck — session 1" in out.read_text(encoding="utf-8")


@pytest.mark.parametrize("session_id, message", [("2", "finish the exam"), ("99", "not found")])
def test_review_command_refuses_unfinished_exams_and_unknown_sessions(db_path, session_id, message):
    result = runner.invoke(app, ["review", session_id, "--db-path", str(db_path)])
    assert result.exit_code == 1
    assert message in result.output
