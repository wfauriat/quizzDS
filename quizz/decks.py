"""Load and validate the YAML decks in ``decks/``."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from quizz.models import Deck, Question

ROOT = Path(__file__).resolve().parent.parent
DECKS_DIR = ROOT / "decks"


class DeckError(Exception):
    """One or more decks are invalid; ``errors`` holds one message per problem."""

    def __init__(self, errors: list[str]):
        super().__init__("\n".join(errors))
        self.errors = errors


def longest_choice_bias(deck: Deck) -> tuple[int, int]:
    """Count single-answer questions whose correct choice is also the longest one.

    Authors tend to make the right answer the most detailed, which gives it away; with ~4 choices,
    chance is ~25%, so aim for roughly 10-40%. Returns (hits, number of single-answer questions).
    """
    singles = [q for q in deck.questions if q.type == "single"]
    hits = sum(max(q.choices, key=lambda c: len(c.text)).id in q.answer for q in singles)
    return hits, len(singles)


def load_deck(path: Path) -> Deck:
    with path.open(encoding="utf-8") as f:
        return Deck.model_validate(yaml.safe_load(f))


def load_decks(decks_dir: Path = DECKS_DIR) -> list[tuple[Path, Deck]]:
    """Load every ``*.yaml`` deck and check ids are consistent across decks.

    A question id may appear in several decks, but only with identical content.
    All problems are collected and raised together as a ``DeckError``.
    """
    errors: list[str] = []
    loaded: list[tuple[Path, Deck]] = []
    for path in sorted(decks_dir.glob("*.yaml")):
        try:
            loaded.append((path, load_deck(path)))
        except (yaml.YAMLError, ValidationError) as e:
            errors.append(f"{path.name}: {e}")

    deck_files: dict[str, str] = {}
    first_seen: dict[str, tuple[str, Question]] = {}
    for path, deck in loaded:
        if deck.id in deck_files:
            errors.append(f"{path.name}: deck id {deck.id!r} is already used by {deck_files[deck.id]}")
        deck_files.setdefault(deck.id, path.name)
        for q in deck.questions:
            origin, original = first_seen.setdefault(q.id, (path.name, q))
            if original != q:
                errors.append(f"{path.name}: question {q.id!r} differs from the one in {origin}")

    if errors:
        raise DeckError(errors)
    return loaded
