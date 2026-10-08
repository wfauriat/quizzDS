import yaml


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
