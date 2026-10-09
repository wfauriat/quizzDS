import re
from datetime import date

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from quizz.api import create_app
from quizz.decks import load_decks
from quizz.design import DesignRequest, apportion, build_prompt, save_generated_deck, suggest_deck_id
from quizz.models import Deck
from quizz.service import Conflict, Invalid
from tests.helpers import make_question, write_deck

TODAY = date(2026, 10, 9)


def request(**overrides):
    body = {
        "title": "Streaming & concurrency",
        "domains": [
            {"domain": "stack", "level": 3, "count": 3},
            {"domain": "de", "level": 4, "count": 4, "focus": "Kafka, Spark streaming"},
            {"domain": "ds", "level": 2, "count": 0},
        ],
    }
    return DesignRequest.model_validate(body | overrides)


def generated(deck_id="new-deck", questions=None):
    questions = questions or [make_question(id="cs-new-001"), make_question(id="cs-new-002", level=3)]
    return yaml.safe_dump({"id": deck_id, "title": "New deck", "questions": questions}, sort_keys=False)


@pytest.fixture
def decks_dir(tmp_path):
    path = tmp_path / "decks"
    path.mkdir()
    write_deck(path / "old.yaml", "old-deck", [make_question()])  # owns cs-test-001
    return path


# ---------------------------------------------------------------- prompt


def test_prompt_describes_the_requested_deck():
    existing = [Deck.model_validate({"id": "d", "title": "d", "questions": [make_question(tags=["arith"])]})]
    prompt = build_prompt(request(), existing, "streaming-concurrency", TODAY)
    assert "`id`: `streaming-concurrency` · `title`: \"Streaming & concurrency\" · **7 questions**" in prompt
    # Rows in domain order, empty domains left out.
    assert "| `de` | Data engineering | L4 · senior | 4 | Kafka, Spark streaming |\n| `stack`" in prompt
    assert "| `ds` |" not in prompt
    assert "- `infra` (Infra & ops): cloud," in prompt  # every domain's scope, to place questions
    assert "Every question must be exactly at its domain's target level." in prompt
    assert "1 `multi` question(s)" in prompt  # 15% of 7, rounded
    assert "Kinds: mix the four kinds" in prompt
    assert "- cs/test: `cs-test-001` L2 [arith]" in prompt  # existing ids to avoid
    assert '"$schema": "https://json-schema.org/draft/2020-12/schema"' in prompt
    assert "write `decks/streaming-concurrency.yaml`" in prompt


def test_prompt_options():
    prompt = build_prompt(
        request(spread=True, multi_share=0, kinds={"practical": 2, "internals": 1, "design": 1, "concept": 0}),
        [],
        "x",
        TODAY,
    )
    assert "one level above or below" in prompt
    assert "Only `single` questions" in prompt
    assert "Kinds: about 3 practical, 2 internals, 2 design." in prompt
    assert "(none yet)" in prompt


def test_prompt_can_ignore_existing_questions():
    existing = [Deck.model_validate({"id": "d", "title": "d", "questions": [make_question()]})]
    assert "## Existing questions" in build_prompt(request(), existing, "x", TODAY)
    prompt = build_prompt(request(avoid_existing=False), existing, "x", TODAY)
    assert "Existing questions" not in prompt and "cs-test-001" not in prompt
    assert "the app renumbers\n   ids that other decks already use" in prompt


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"domains": [{"domain": "de", "count": 0}]}, "at least one question"),
        ({"domains": [{"domain": "de", "count": 1}, {"domain": "de", "count": 2}]}, "only once"),
        ({"kinds": {"concept": 0}}, "non-zero weight"),
        ({"domains": [{"domain": "de", "level": 6, "count": 1}]}, "less than or equal to 5"),
    ],
)
def test_invalid_design_requests(overrides, message):
    with pytest.raises(ValidationError, match=message):
        request(**overrides)


def test_helpers():
    assert suggest_deck_id("Streaming & Concurrency!", {"streaming-concurrency"}) == "streaming-concurrency-2"
    assert suggest_deck_id("???", set()) == "custom"
    assert apportion(7, {"a": 2, "b": 1, "c": 1}) == {"a": 3, "b": 2, "c": 2}


# ---------------------------------------------------------------- import


def test_import_saves_a_valid_deck_from_a_whole_llm_reply(decks_dir):
    reply = f"Here is your deck:\n\n```yaml\n{generated()}```\n\nEnjoy!"
    deck, path, renamed = save_generated_deck(reply, decks_dir, TODAY)
    assert (deck.id, path.name, renamed) == ("new-deck", "new-deck.yaml", {})
    assert path.read_text(encoding="utf-8").startswith("# yaml-language-server: $schema=./deck.schema.json\n")
    assert {d.id for _, d in load_decks(decks_dir)} == {"old-deck", "new-deck"}


@pytest.mark.parametrize(
    "text, message",
    [
        ("id: [unclosed", "not valid YAML"),
        (generated(questions=[make_question(id="cs-new-001", answer=["z"])]), "questions.0 (id cs-new-001)"),
        (generated(deck_id="old-deck"), "deck id 'old-deck' is already used"),
        (  # a clashing id that can't be renumbered: flow-style YAML has no `id:` lines to edit
            yaml.safe_dump(
                {"id": "new-deck", "title": "t", "questions": [make_question(prompt="Another question?")]},
                default_flow_style=True,
            ),
            "'cs-test-001' is already used",
        ),
        (
            generated(
                questions=[
                    make_question(id=f"cs-new-{i}", choices=[{"id": "a", "text": "long correct"}, {"id": "b", "text": "x"}])
                    for i in range(8)
                ]
            ),
            "longest one in 8/8",
        ),
    ],
)
def test_import_rejects_problems_with_actionable_messages(decks_dir, text, message):
    with pytest.raises(Invalid, match=re.escape(message)):
        save_generated_deck(text, decks_dir, TODAY)
    assert sorted(p.name for p in decks_dir.iterdir()) == ["old.yaml"]  # nothing written


def test_import_accepts_a_question_identical_to_an_existing_one(decks_dir):
    deck, _, renamed = save_generated_deck(generated(questions=[make_question()]), decks_dir, TODAY)
    assert deck.questions[0].id == "cs-test-001" and renamed == {}


def test_import_renumbers_ids_used_by_other_decks(decks_dir):
    # old-deck owns cs-test-001; the new deck reuses that id for a different question.
    questions = [make_question(prompt="Another question?"), make_question(id="cs-test-002", prompt="Third?")]
    deck, path, renamed = save_generated_deck(generated(questions=questions), decks_dir, TODAY)
    assert renamed == {"cs-test-001": "cs-test-003"}
    assert [q.id for q in deck.questions] == ["cs-test-003", "cs-test-002"]
    text = path.read_text(encoding="utf-8")
    assert "id: cs-test-003" in text and "cs-test-001" not in text
    assert {d.id for _, d in load_decks(decks_dir)} == {"old-deck", "new-deck"}  # consistent across decks


def test_import_never_overwrites_a_file(decks_dir):
    write_deck(decks_dir / "new-deck.yaml", "named-differently", [make_question(id="cs-other-001")])
    with pytest.raises(Conflict, match="new-deck.yaml already exists"):
        save_generated_deck(generated(), decks_dir, TODAY)


def test_import_reports_broken_existing_decks(decks_dir):
    (decks_dir / "broken.yaml").write_text("id: [unclosed", encoding="utf-8")
    with pytest.raises(Invalid, match="fix the existing decks first"):
        save_generated_deck(generated(), decks_dir, TODAY)


# ---------------------------------------------------------------- API


@pytest.fixture
def client(tmp_path, decks_dir):
    app = create_app(db_path=tmp_path / "q.sqlite", decks_dir=decks_dir, web_dist=tmp_path / "no-web")
    with TestClient(app) as c:
        yield c


def test_design_endpoints_round_trip(client):
    r = client.post("/api/design/prompt", json=request().model_dump())
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["deck_id"], body["n_questions"]) == ("streaming-concurrency", 7)
    assert "`cs-test-001`" in body["prompt"]

    r = client.post("/api/design/import", json={"text": generated()})
    assert r.status_code == 201, r.text
    assert r.json() == {
        "deck_id": "new-deck",
        "title": "New deck",
        "n_questions": 2,
        "file": "new-deck.yaml",
        "renamed": {},
    }
    assert "new-deck" in [d["id"] for d in client.get("/api/decks").json()]  # playable right away

    r = client.post("/api/design/import", json={"text": generated()})
    assert r.status_code == 422 and "already used" in r.json()["detail"]
    assert client.post("/api/design/prompt", json={"title": "x", "domains": []}).status_code == 422
