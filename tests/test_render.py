from quizz.decks import load_decks
from quizz.models import Deck
from quizz.render import render_deck


def test_every_question_rendered_with_answers_collapsed():
    for _, deck in load_decks():
        html = render_deck(deck)
        for q in deck.questions:
            assert f'id="{q.id}"' in html
        assert html.count("<details>") == len(deck.questions)


def test_reveal_expands_answers():
    _, deck = load_decks()[0]
    assert render_deck(deck, reveal=True).count("<details open>") == len(deck.questions)


def test_markdown_is_escaped_and_code_highlighted():
    deck = Deck.model_validate(
        {
            "id": "d",
            "title": "<b>T</b>",
            "questions": [
                {
                    "id": "cs-test-001",
                    "domain": "cs",
                    "topic": "test",
                    "level": 1,
                    "kind": "concept",
                    "prompt": "<script>alert(1)</script>\n\n```python\nx = 1\n```",
                    "choices": [{"id": "a", "text": "p < 0.05"}, {"id": "b", "text": "no"}],
                    "answer": ["a"],
                    "explanation": "e",
                }
            ],
        }
    )
    html = render_deck(deck)
    assert "<script>alert(1)" not in html and "&lt;script&gt;alert(1)" in html
    assert "<title>&lt;b&gt;T&lt;/b&gt;</title>" in html
    assert "p &lt; 0.05" in html
    assert '<code class="language-python"><span class="n">x</span>' in html
