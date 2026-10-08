import json

import pytest
import yaml
from pydantic import ValidationError

from quizz.decks import DECKS_DIR, DeckError, load_decks
from quizz.models import Deck, Question, deck_json_schema


def make_question(**overrides):
    q = {
        "id": "cs-test-001",
        "domain": "cs",
        "topic": "test",
        "level": 2,
        "kind": "concept",
        "prompt": "2 + 2?",
        "choices": [{"id": "a", "text": "4"}, {"id": "b", "text": "5"}],
        "answer": ["a"],
        "explanation": "Arithmetic.",
    }
    return q | overrides


def write_deck(path, deck_id, questions):
    path.write_text(yaml.safe_dump({"id": deck_id, "title": deck_id, "questions": questions}), encoding="utf-8")


def test_repo_decks_are_valid():
    assert load_decks(), "expected at least one deck in decks/"


def test_schema_file_is_up_to_date():
    on_disk = json.loads((DECKS_DIR / "deck.schema.json").read_text(encoding="utf-8"))
    assert on_disk == deck_json_schema(), "regenerate with: python -m quizz schema"


def test_valid_question_defaults_to_single():
    q = Question.model_validate(make_question())
    assert q.type == "single"
    assert q.tags == []


def test_multi_accepts_several_answers():
    q = Question.model_validate(make_question(type="multi", answer=["a", "b"]))
    assert q.answer == ["a", "b"]


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"answer": ["z"]}, "unknown choices"),
        ({"answer": ["a", "b"]}, "exactly one answer"),
        ({"type": "multi", "answer": ["a", "a"]}, "duplicate ids in answer"),
        ({"choices": [{"id": "a", "text": "4"}, {"id": "a", "text": "5"}]}, "duplicate choice ids"),
        ({"choices": [{"id": "a", "text": "4"}]}, "at least 2 items"),
        ({"level": 6}, "less than or equal to 5"),
        ({"domain": "biology"}, "domain"),
        ({"id": "Not A Slug"}, "pattern"),
        ({"explaination": "typo"}, "Extra inputs are not permitted"),
    ],
)
def test_invalid_question(overrides, message):
    with pytest.raises(ValidationError, match=message):
        Question.model_validate(make_question(**overrides))


def test_duplicate_question_ids_within_a_deck():
    with pytest.raises(ValidationError, match="duplicate question ids"):
        Deck.model_validate({"id": "d", "title": "d", "questions": [make_question(), make_question()]})


def test_shared_question_must_be_identical_across_decks(tmp_path):
    write_deck(tmp_path / "a.yaml", "deck-a", [make_question()])
    write_deck(tmp_path / "b.yaml", "deck-b", [make_question()])
    assert len(load_decks(tmp_path)) == 2

    write_deck(tmp_path / "b.yaml", "deck-b", [make_question(prompt="3 + 3?")])
    with pytest.raises(DeckError, match="differs from the one in a.yaml"):
        load_decks(tmp_path)


def test_deck_ids_must_be_unique_across_files(tmp_path):
    write_deck(tmp_path / "a.yaml", "same", [make_question()])
    write_deck(tmp_path / "b.yaml", "same", [make_question(id="cs-test-002")])
    with pytest.raises(DeckError, match="already used by a.yaml"):
        load_decks(tmp_path)


def test_errors_are_collected_across_files(tmp_path):
    (tmp_path / "a.yaml").write_text("id: [unclosed", encoding="utf-8")
    write_deck(tmp_path / "b.yaml", "deck-b", [make_question(level=9)])
    with pytest.raises(DeckError) as excinfo:
        load_decks(tmp_path)
    assert [e.split(":")[0] for e in excinfo.value.errors] == ["a.yaml", "b.yaml"]
