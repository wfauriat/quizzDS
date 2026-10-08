-- quizzDS database, schema version 1.
--
-- Content tables (deck, question, question_revision, deck_question) mirror decks/*.yaml and are
-- refreshed on import. Event tables (quiz_session, session_question, attempt) are the learning
-- history: rows are only ever added (finished_at is the one field set later).
-- To change the schema: bump SCHEMA_VERSION in db.py and add a migration step there.
-- All timestamps are ISO-8601 UTC strings.

CREATE TABLE deck (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    author      TEXT NOT NULL,
    source_path TEXT NOT NULL,
    imported_at TEXT NOT NULL
);

-- Every distinct content version of a question, keyed by a hash of its full body.
CREATE TABLE question_revision (
    hash        TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    body_json   TEXT NOT NULL,           -- the full question (prompt, choices, answer, explanation...)
    first_seen  TEXT NOT NULL
);
CREATE INDEX question_revision_by_question ON question_revision (question_id);

-- Current metadata of each question, used to slice the history (domain, topic, level...).
CREATE TABLE question (
    id           TEXT PRIMARY KEY,
    domain       TEXT NOT NULL,
    topic        TEXT NOT NULL,
    tags_json    TEXT NOT NULL,
    level        INTEGER NOT NULL CHECK (level BETWEEN 1 AND 5),
    kind         TEXT NOT NULL,
    type         TEXT NOT NULL CHECK (type IN ('single', 'multi')),
    current_hash TEXT NOT NULL REFERENCES question_revision (hash),
    updated_at   TEXT NOT NULL
);

CREATE TABLE deck_question (
    deck_id     TEXT NOT NULL REFERENCES deck (id),
    question_id TEXT NOT NULL REFERENCES question (id),
    position    INTEGER NOT NULL,
    PRIMARY KEY (deck_id, question_id)
);

CREATE TABLE quiz_session (
    id          INTEGER PRIMARY KEY,
    deck_id     TEXT NOT NULL REFERENCES deck (id),
    mode        TEXT NOT NULL CHECK (mode IN ('learn', 'exam')),
    started_at  TEXT NOT NULL,
    finished_at TEXT
);

-- The questions served in a session, in order, with the exact revision shown.
-- A served question without an attempt was skipped or abandoned.
CREATE TABLE session_question (
    session_id    INTEGER NOT NULL REFERENCES quiz_session (id),
    position      INTEGER NOT NULL,
    question_id   TEXT NOT NULL REFERENCES question (id),
    question_hash TEXT NOT NULL REFERENCES question_revision (hash),
    PRIMARY KEY (session_id, question_id),
    UNIQUE (session_id, position)
);

CREATE TABLE attempt (
    id            INTEGER PRIMARY KEY,
    session_id    INTEGER NOT NULL,
    question_id   TEXT NOT NULL,
    selected_json TEXT NOT NULL,         -- sorted choice ids, e.g. ["a","c"]
    is_correct    INTEGER NOT NULL CHECK (is_correct IN (0, 1)),
    confidence    INTEGER CHECK (confidence BETWEEN 1 AND 3),  -- 1 guess, 2 unsure, 3 sure
    time_ms       INTEGER CHECK (time_ms >= 0),
    answered_at   TEXT NOT NULL,
    UNIQUE (session_id, question_id),
    FOREIGN KEY (session_id, question_id) REFERENCES session_question (session_id, question_id)
);

-- One row per answer, with session context and current question metadata:
-- the starting point for any analysis (sqlite3, pandas, duckdb...).
CREATE VIEW v_attempt AS
SELECT
    a.id                            AS attempt_id,
    a.session_id,
    s.deck_id,
    s.mode,
    s.started_at                    AS session_started_at,
    sq.position,
    a.question_id,
    q.domain,
    q.topic,
    q.tags_json,
    q.level,
    q.kind,
    q.type,
    a.selected_json,
    a.is_correct,
    a.confidence,
    a.time_ms,
    a.answered_at,
    sq.question_hash,
    sq.question_hash = q.current_hash AS is_current_revision
FROM attempt a
JOIN quiz_session s      ON s.id = a.session_id
JOIN session_question sq ON sq.session_id = a.session_id AND sq.question_id = a.question_id
JOIN question q          ON q.id = a.question_id;

PRAGMA user_version = 1;
