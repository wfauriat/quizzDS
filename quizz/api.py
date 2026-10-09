"""HTTP API (FastAPI) over the service layer; also serves the built web UI when present.

Run with ``python -m quizz serve``; interactive docs at http://localhost:8000/docs.
"""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager, closing
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from quizz import design, service
from quizz.db import DB_PATH, connect, import_decks
from quizz.decks import DECKS_DIR, ROOT, load_decks
from quizz.models import Domain, Kind, QuestionType
from quizz.service import DeckInfo, Mode, SessionInfo, Summary

WEB_DIST = ROOT / "web" / "dist"


class PublicChoice(BaseModel):
    id: str
    text: str


class PublicQuestion(BaseModel):
    """A question as served before answering: no answer, notes or explanation."""

    id: str
    domain: Domain
    topic: str
    tags: list[str]
    level: int
    kind: Kind
    type: QuestionType
    prompt: str
    choices: list[PublicChoice]


class SessionCreate(BaseModel):
    deck_id: str
    mode: Mode = "learn"


class SessionOut(BaseModel):
    session_id: int
    deck_id: str
    mode: Mode
    questions: list[PublicQuestion]


class AnswerIn(BaseModel):
    question_id: str
    selected: list[str] = Field(min_length=1, description="Chosen choice ids.")
    confidence: Literal[1, 2, 3] = Field(description="1 guess, 2 unsure, 3 sure.")
    time_ms: int = Field(ge=0, description="Time from display to submit.")


class GeneratedDeckIn(BaseModel):
    text: str = Field(min_length=1, max_length=1_000_000, description="The YAML deck (a whole LLM reply works too).")


class ImportedDeck(BaseModel):
    deck_id: str
    title: str
    n_questions: int
    file: str
    renamed: dict[str, str] = Field(description="Question ids renumbered because other decks use them: old → new.")


class Feedback(BaseModel):
    """Exam mode: only `recorded`. Learn mode: also the correction."""

    recorded: bool = True
    is_correct: bool | None = None
    answer: list[str] | None = None
    explanation: str | None = None
    why: dict[str, str] | None = None


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    with closing(connect(request.app.state.db_path)) as conn:
        yield conn


Db = Annotated[sqlite3.Connection, Depends(get_db)]
router = APIRouter(prefix="/api")


@router.get("/decks")
def list_decks(db: Db) -> list[DeckInfo]:
    return service.list_decks(db)


@router.get("/sessions")
def list_sessions(db: Db) -> list[SessionInfo]:
    """Past sessions, newest first; review one with GET /api/sessions/{id}/summary."""
    return service.list_sessions(db)


@router.post("/sessions", status_code=201)
def create_session(body: SessionCreate, db: Db) -> SessionOut:
    session_id = service.create_session(db, body.deck_id, body.mode)
    questions = [PublicQuestion.model_validate(q.model_dump()) for q in service.session_questions(db, session_id)]
    return SessionOut(session_id=session_id, deck_id=body.deck_id, mode=body.mode, questions=questions)


@router.post("/sessions/{session_id}/answers", response_model_exclude_none=True)
def answer(session_id: int, body: AnswerIn, db: Db) -> Feedback:
    graded = service.record_answer(db, session_id, body.question_id, body.selected, body.confidence, body.time_ms)
    if graded.mode == "exam":
        return Feedback()
    q = graded.question
    return Feedback(
        is_correct=graded.is_correct,
        answer=q.answer,
        explanation=q.explanation,
        why={c.id: c.why for c in q.choices if c.why},
    )


@router.post("/sessions/{session_id}/finish")
def finish(session_id: int, db: Db) -> Summary:
    service.finish_session(db, session_id)
    return service.summarize(db, session_id)


@router.get("/sessions/{session_id}/summary")
def summary(session_id: int, db: Db) -> Summary:
    return service.summarize(db, session_id)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: int, db: Db) -> None:
    """Delete a session and its answers from the history (cannot be undone)."""
    service.delete_session(db, session_id)


@router.post("/design/prompt")
def design_prompt(body: design.DesignRequest, request: Request, db: Db) -> design.DesignPrompt:
    """Build the prompt asking an LLM to write a deck with this shape."""
    decks = [deck for _, deck in load_decks(request.app.state.decks_dir)]
    taken = {d.id for d in decks} | {r["id"] for r in db.execute("SELECT id FROM deck")}
    deck_id = design.suggest_deck_id(body.title, taken)
    prompt = design.build_prompt(body, decks, deck_id, date.today())
    return design.DesignPrompt(deck_id=deck_id, n_questions=body.total, prompt=prompt)


@router.post("/design/import", status_code=201)
def design_import(body: GeneratedDeckIn, request: Request, db: Db) -> ImportedDeck:
    """Validate a generated deck, save it in decks/ and load it, ready to play."""
    decks_dir = request.app.state.decks_dir
    deck, path, renamed = design.save_generated_deck(body.text, decks_dir, date.today())
    import_decks(db, load_decks(decks_dir))
    return ImportedDeck(
        deck_id=deck.id, title=deck.title, n_questions=len(deck.questions), file=path.name, renamed=renamed
    )


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
def unknown_endpoint(path: str) -> None:
    """Must stay last. Without it, unknown /api paths fall through to the static UI (405 on POST)."""
    raise service.NotFound(
        f"no API endpoint /api/{path}: if the UI is newer than the server, restart `python -m quizz serve`"
    )


_STATUS = {service.NotFound: 404, service.Conflict: 409, service.Invalid: 422}


def _error_handler(status: int):
    async def handler(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    return handler


def create_app(db_path: Path = DB_PATH, decks_dir: Path = DECKS_DIR, web_dist: Path = WEB_DIST) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
        with closing(connect(db_path)) as conn:
            import_decks(conn, load_decks(decks_dir))
        yield

    app = FastAPI(title="quizzDS", lifespan=lifespan)
    app.state.db_path = db_path
    app.state.decks_dir = decks_dir
    app.include_router(router)
    for exc_type, status in _STATUS.items():
        app.add_exception_handler(exc_type, _error_handler(status))
    if web_dist.is_dir():
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")
    return app


app = create_app()
