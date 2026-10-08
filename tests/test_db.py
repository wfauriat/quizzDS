import sqlite3
from contextlib import closing

import pytest

from quizz.db import SCHEMA_VERSION, connect, import_decks, question_hash
from quizz.decks import load_decks
from quizz.models import Question
from tests.helpers import make_question, write_deck


@pytest.fixture
def conn(tmp_path):
    with closing(connect(tmp_path / "q.sqlite")) as c:
        yield c


def test_connect_creates_schema(tmp_path, conn):
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
    expected = {"deck", "question", "question_revision", "deck_question", "quiz_session", "session_question"}
    assert expected | {"attempt", "v_attempt"} <= names
    connect(tmp_path / "q.sqlite").close()  # reopening an up-to-date database is a no-op


def test_unsupported_schema_version_is_rejected(tmp_path):
    path = tmp_path / "future.sqlite"
    with closing(sqlite3.connect(path)) as raw:
        raw.execute("PRAGMA user_version = 99")
    with pytest.raises(RuntimeError, match="v99"):
        connect(path)


def test_import_is_idempotent_and_keeps_every_revision(tmp_path, conn):
    decks_dir = tmp_path / "decks"
    decks_dir.mkdir()
    deck_file = decks_dir / "a.yaml"
    write_deck(deck_file, "deck-a", [make_question(), make_question(id="cs-test-002")])

    assert import_decks(conn, load_decks(decks_dir)) == {"new": 2}
    assert import_decks(conn, load_decks(decks_dir)) == {"unchanged": 2}

    edited = make_question(prompt="3 + 3?")
    write_deck(deck_file, "deck-a", [edited, make_question(id="cs-test-002")])
    assert import_decks(conn, load_decks(decks_dir)) == {"changed": 1, "unchanged": 1}

    revisions = conn.execute("SELECT count(*) FROM question_revision WHERE question_id = 'cs-test-001'").fetchone()[0]
    assert revisions == 2
    current = conn.execute("SELECT current_hash FROM question WHERE id = 'cs-test-001'").fetchone()[0]
    assert current == question_hash(Question.model_validate(edited))


def test_deck_order_follows_the_file(tmp_path, conn):
    decks_dir = tmp_path / "decks"
    decks_dir.mkdir()
    write_deck(decks_dir / "a.yaml", "deck-a", [make_question(id="q-2"), make_question(id="q-1")])
    import_decks(conn, load_decks(decks_dir))
    write_deck(decks_dir / "a.yaml", "deck-a", [make_question(id="q-1"), make_question(id="q-2")])
    import_decks(conn, load_decks(decks_dir))
    rows = conn.execute("SELECT question_id FROM deck_question WHERE deck_id = 'deck-a' ORDER BY position")
    assert [r[0] for r in rows] == ["q-1", "q-2"]


def test_import_repo_decks(conn):
    decks = load_decks()
    counts = import_decks(conn, decks)
    assert counts["new"] == sum(len(d.questions) for _, d in decks)
    assert conn.execute("SELECT count(*) FROM deck").fetchone()[0] == len(decks)
