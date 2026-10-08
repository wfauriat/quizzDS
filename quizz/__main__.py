"""Command line: ``python -m quizz <command>``."""

from __future__ import annotations

import json
import webbrowser
from collections import Counter
from pathlib import Path
from typing import Annotated, Optional

import typer

from quizz.decks import DECKS_DIR, DeckError, load_decks
from quizz.models import Deck, deck_json_schema
from quizz.render import RENDER_DIR, render_deck

app = typer.Typer(add_completion=False, no_args_is_help=True)


def _load_or_exit(decks_dir: Path) -> list[tuple[Path, Deck]]:
    try:
        decks = load_decks(decks_dir)
    except DeckError as e:
        for err in e.errors:
            typer.secho(err, fg="red", err=True)
        raise typer.Exit(1)
    if not decks:
        typer.secho(f"no *.yaml deck in {decks_dir}", fg="yellow", err=True)
        raise typer.Exit(1)
    return decks


@app.command()
def validate(
    decks_dir: Annotated[Path, typer.Option(help="Directory of *.yaml decks.")] = DECKS_DIR,
) -> None:
    """Validate all decks and print their breadth/depth distribution."""
    decks = _load_or_exit(decks_dir)
    for path, deck in decks:
        qs = deck.questions
        typer.secho(f"✓ {path.name} ({deck.id}): {len(qs)} questions", fg="green")
        for axis in ("domain", "level", "kind", "type"):
            counts = Counter(getattr(q, axis) for q in qs)
            typer.echo(f"    {axis:<7} " + "  ".join(f"{k}:{n}" for k, n in sorted(counts.items())))


@app.command()
def schema(
    out: Annotated[Path, typer.Option(help="Output file.")] = DECKS_DIR / "deck.schema.json",
) -> None:
    """Export the deck JSON Schema (used by editors and deck authors)."""
    out.write_text(json.dumps(deck_json_schema(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    typer.echo(f"wrote {out}")


@app.command()
def render(
    deck_ids: Annotated[Optional[list[str]], typer.Argument(help="Deck ids to render (default: all).")] = None,
    out_dir: Annotated[Path, typer.Option(help="Output directory.")] = RENDER_DIR,
    reveal: Annotated[bool, typer.Option(help="Expand all answers and explanations.")] = False,
    open_browser: Annotated[bool, typer.Option("--open", help="Open the pages in a browser.")] = False,
    decks_dir: Annotated[Path, typer.Option(help="Directory of *.yaml decks.")] = DECKS_DIR,
) -> None:
    """Render decks as static HTML pages for reading (answers collapsed unless --reveal)."""
    decks = {deck.id: deck for _, deck in _load_or_exit(decks_dir)}
    if unknown := sorted(set(deck_ids or []) - decks.keys()):
        typer.secho(f"unknown deck ids: {unknown}; available: {sorted(decks)}", fg="red", err=True)
        raise typer.Exit(1)
    out_dir.mkdir(parents=True, exist_ok=True)
    for deck_id in deck_ids or decks:
        out = out_dir / f"{deck_id}.html"
        out.write_text(render_deck(decks[deck_id], reveal=reveal), encoding="utf-8")
        typer.echo(f"wrote {out}")
        if open_browser:
            webbrowser.open(out.as_uri())


if __name__ == "__main__":
    app()
