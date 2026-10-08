from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from quizz.api import create_app
from quizz.db import connect, import_decks
from quizz.decks import load_decks
from tests.helpers import make_question, write_deck

MULTI = make_question(
    id="ds-test-001",
    domain="ds",
    level=4,
    type="multi",
    choices=[{"id": "a", "text": "x", "why": "wa"}, {"id": "b", "text": "y", "why": "wb"}, {"id": "c", "text": "z"}],
    answer=["a", "c"],
)


def write_test_deck(decks_dir, single=None):
    write_deck(decks_dir / "t.yaml", "test-deck", [single or make_question(), MULTI])


@pytest.fixture
def client(tmp_path):
    decks_dir = tmp_path / "decks"
    decks_dir.mkdir()
    write_test_deck(decks_dir)
    app = create_app(db_path=tmp_path / "q.sqlite", decks_dir=decks_dir, web_dist=tmp_path / "no-web")
    with TestClient(app) as c:
        yield c


def start(client, mode="learn"):
    r = client.post("/api/sessions", json={"deck_id": "test-deck", "mode": mode})
    assert r.status_code == 201, r.text
    return r.json()


def answer(client, session_id, question_id, selected, confidence=3, time_ms=1234):
    payload = {"question_id": question_id, "selected": selected, "confidence": confidence, "time_ms": time_ms}
    return client.post(f"/api/sessions/{session_id}/answers", json=payload)


def test_list_decks(client):
    [deck] = client.get("/api/decks").json()
    assert deck["id"] == "test-deck"
    assert deck["n_questions"] == 2
    assert deck["domains"] == {"cs": 1, "ds": 1}
    assert deck["levels"] == {"2": 1, "4": 1}
    assert deck["last_finished"] is None


def test_served_questions_hide_answers(client):
    session = start(client)
    assert session["mode"] == "learn"
    assert [q["id"] for q in session["questions"]] == ["cs-test-001", "ds-test-001"]
    for q in session["questions"]:
        assert set(q) == {"id", "domain", "topic", "tags", "level", "kind", "type", "prompt", "choices"}
        assert all(set(c) == {"id", "text"} for c in q["choices"])


def test_learn_mode_gives_feedback_after_each_answer(client):
    sid = start(client)["session_id"]
    r = answer(client, sid, "cs-test-001", ["a"])
    assert r.status_code == 200
    assert r.json() == {"recorded": True, "is_correct": True, "answer": ["a"], "explanation": "Arithmetic.", "why": {}}

    r = answer(client, sid, "ds-test-001", ["c", "a"])  # order doesn't matter
    assert r.json()["is_correct"] is True
    assert r.json()["why"] == {"a": "wa", "b": "wb"}


def test_multi_requires_the_exact_set(client):
    sid = start(client)["session_id"]
    assert answer(client, sid, "ds-test-001", ["a"]).json()["is_correct"] is False


def test_exam_mode_reveals_nothing_until_finished(client):
    sid = start(client, mode="exam")["session_id"]
    assert answer(client, sid, "cs-test-001", ["b"]).json() == {"recorded": True}
    assert client.get(f"/api/sessions/{sid}/summary").status_code == 409

    summary = client.post(f"/api/sessions/{sid}/finish").json()
    assert summary["finished_at"] is not None
    assert (summary["n_questions"], summary["n_answered"], summary["n_correct"]) == (2, 1, 0)
    first = summary["items"][0]
    assert first["selected"] == ["b"] and first["is_correct"] is False
    assert first["question"]["answer"] == ["a"]
    assert client.get(f"/api/sessions/{sid}/summary").status_code == 200


def test_summary_breakdowns_and_analysis_view(client):
    sid = start(client)["session_id"]
    answer(client, sid, "cs-test-001", ["a"], confidence=2, time_ms=4200)
    summary = client.post(f"/api/sessions/{sid}/finish").json()

    assert summary["by_domain"] == [
        {"key": "cs", "n": 1, "answered": 1, "correct": 1},
        {"key": "ds", "n": 1, "answered": 0, "correct": 0},
    ]
    assert [b["key"] for b in summary["by_level"]] == ["2", "4"]
    assert summary["items"][1]["selected"] is None  # skipped

    finish_again = client.post(f"/api/sessions/{sid}/finish").json()
    assert finish_again["finished_at"] == summary["finished_at"]  # first finish time is kept

    with closing(connect(client.app.state.db_path)) as conn:
        [row] = conn.execute("SELECT * FROM v_attempt").fetchall()
    assert (row["domain"], row["level"], row["confidence"], row["time_ms"]) == ("cs", 2, 2, 4200)
    assert row["is_correct"] == 1 and row["is_current_revision"] == 1

    [deck] = client.get("/api/decks").json()
    assert deck["last_finished"]["session_id"] == sid
    assert deck["last_finished"]["n_correct"] == 1


@pytest.mark.parametrize(
    "question_id, selected, status",
    [
        ("nope-001", ["a"], 404),  # not in the session
        ("cs-test-001", ["z"], 422),  # unknown choice
        ("cs-test-001", ["a", "b"], 422),  # several choices on a single-answer question
        ("cs-test-001", [], 422),  # nothing selected
    ],
)
def test_invalid_answers(client, question_id, selected, status):
    sid = start(client)["session_id"]
    assert answer(client, sid, question_id, selected).status_code == status


def test_answer_conflicts_and_missing_resources(client):
    sid = start(client)["session_id"]
    assert answer(client, sid, "cs-test-001", ["a"], confidence=4).status_code == 422
    assert answer(client, sid, "cs-test-001", ["a"]).status_code == 200
    assert answer(client, sid, "cs-test-001", ["a"]).status_code == 409  # already answered
    client.post(f"/api/sessions/{sid}/finish")
    assert answer(client, sid, "ds-test-001", ["a"]).status_code == 409  # session finished

    assert answer(client, 999, "cs-test-001", ["a"]).status_code == 404
    assert client.get("/api/sessions/999/summary").status_code == 404
    assert client.post("/api/sessions", json={"deck_id": "nope"}).status_code == 404
    assert client.post("/api/sessions", json={"deck_id": "test-deck", "mode": "blitz"}).status_code == 422


def test_grading_uses_the_revision_that_was_served(client):
    sid = start(client)["session_id"]

    # The deck is edited while the session is open: the correct answer becomes "b".
    decks_dir = client.app.state.decks_dir
    write_test_deck(decks_dir, single=make_question(answer=["b"]))
    with closing(connect(client.app.state.db_path)) as conn:
        import_decks(conn, load_decks(decks_dir))

    assert answer(client, sid, "cs-test-001", ["a"]).json()["is_correct"] is True
    new_sid = start(client)["session_id"]
    assert answer(client, new_sid, "cs-test-001", ["a"]).json()["is_correct"] is False

    with closing(connect(client.app.state.db_path)) as conn:
        rows = conn.execute("SELECT session_id, is_current_revision FROM v_attempt ORDER BY session_id").fetchall()
    assert [tuple(r) for r in rows] == [(sid, 0), (new_sid, 1)]


def test_serves_the_built_web_ui(tmp_path):
    decks_dir = tmp_path / "decks"
    decks_dir.mkdir()
    write_test_deck(decks_dir)
    web = tmp_path / "dist"
    web.mkdir()
    (web / "index.html").write_text("<h1>quizz</h1>", encoding="utf-8")
    app = create_app(db_path=tmp_path / "q.sqlite", decks_dir=decks_dir, web_dist=web)
    with TestClient(app) as c:
        assert c.get("/").text == "<h1>quizz</h1>"
        assert c.get("/api/decks").status_code == 200
