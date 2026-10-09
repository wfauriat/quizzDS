"""Command line: ``python -m quizz <command>``."""

from __future__ import annotations

import json
import webbrowser
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import Annotated, Optional

import typer

from quizz.db import DB_PATH, connect, import_decks
from quizz.decks import DECKS_DIR, DeckError, length_bias_warning, load_decks, longest_choice_bias
from quizz.models import Deck, deck_json_schema
from quizz import service
from quizz.render import RENDER_DIR, render_deck, render_session
from quizz.report import build_report

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
        hits, singles = longest_choice_bias(deck)
        typer.echo(f"    lint    correct choice is the longest in {hits}/{singles} single-answer questions")
        if warning := length_bias_warning(deck):
            typer.secho(f"    ⚠ {warning}", fg="yellow")


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


@app.command("import")
def import_(
    decks_dir: Annotated[Path, typer.Option(help="Directory of *.yaml decks.")] = DECKS_DIR,
    db_path: Annotated[Path, typer.Option(help="SQLite database file.")] = DB_PATH,
) -> None:
    """Load the decks into the database (also done automatically when the server starts)."""
    decks = _load_or_exit(decks_dir)
    with closing(connect(db_path)) as conn:
        counts = import_decks(conn, decks)
    summary = ", ".join(f"{counts[k]} {k}" for k in ("new", "changed", "unchanged"))
    typer.echo(f"imported {len(decks)} deck(s) into {db_path}: {summary} questions")


@app.command()
def report(
    deck: Annotated[Optional[str], typer.Option(help="Only answers from sessions on this deck.")] = None,
    since: Annotated[Optional[str], typer.Option(help="Only answers on or after this date (YYYY-MM-DD).")] = None,
    session: Annotated[Optional[list[int]], typer.Option(help="Only these session ids (repeatable).")] = None,
    out: Annotated[Optional[Path], typer.Option(help="Write to this file instead of stdout.")] = None,
    db_path: Annotated[Path, typer.Option(help="SQLite database file.")] = DB_PATH,
) -> None:
    """Markdown report of the answer history: accuracy, calibration, misses, coverage."""
    with closing(connect(db_path)) as conn:
        text = build_report(conn, deck=deck, since=since, session_ids=session)
    if out:
        out.write_text(text, encoding="utf-8")
        typer.echo(f"wrote {out}")
    else:
        typer.echo(text)


@app.command()
def sessions(
    db_path: Annotated[Path, typer.Option(help="SQLite database file.")] = DB_PATH,
) -> None:
    """List past sessions, newest first (ids for `review` and `report --session`)."""
    with closing(connect(db_path)) as conn:
        rows = service.list_sessions(conn)
    if not rows:
        typer.echo("no session yet")
    for s in rows:
        status = "" if s.finished_at else "  (unfinished)"
        typer.echo(
            f"{s.session_id:>4}  {s.started_at[:16].replace('T', ' ')} UTC  {s.mode:<5}  "
            f"{s.n_correct:>2}/{s.n_questions:<2} correct  {s.deck_id}{status}"
        )


@app.command()
def review(
    session_id: Annotated[Optional[int], typer.Argument(help="Session id (default: the latest finished one).")] = None,
    out: Annotated[Optional[Path], typer.Option(help="Output file (default: data/render/session-<id>.html).")] = None,
    open_browser: Annotated[bool, typer.Option("--open", help="Open the page in a browser.")] = False,
    db_path: Annotated[Path, typer.Option(help="SQLite database file.")] = DB_PATH,
) -> None:
    """Render a past session's results as an HTML page, like the UI summary screen."""
    with closing(connect(db_path)) as conn:
        if session_id is None:
            session_id = conn.execute("SELECT max(id) FROM quiz_session WHERE finished_at IS NOT NULL").fetchone()[0]
            if session_id is None:
                typer.secho("no finished session yet", fg="red", err=True)
                raise typer.Exit(1)
        try:
            summary = service.summarize(conn, session_id)
        except (service.NotFound, service.Conflict) as e:
            typer.secho(str(e), fg="red", err=True)
            raise typer.Exit(1)
    out = out or RENDER_DIR / f"session-{session_id}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_session(summary), encoding="utf-8")
    typer.echo(f"wrote {out}")
    if open_browser:
        webbrowser.open(out.resolve().as_uri())


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Interface to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port.")] = 8000,
    reload: Annotated[bool, typer.Option(help="Restart on code changes (development).")] = False,
) -> None:
    """Run the API (and the web UI once built), importing the decks at startup."""
    import uvicorn

    _load_or_exit(DECKS_DIR)  # report deck errors clearly instead of as a startup traceback
    uvicorn.run("quizz.api:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
