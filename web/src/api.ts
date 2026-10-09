// Typed client for the FastAPI backend (quizz/api.py, quizz/service.py).

export type Mode = "learn" | "exam";
export type Confidence = 1 | 2 | 3; // guess, unsure, sure
export type Domain = "ds" | "de" | "cs" | "swe" | "stack" | "infra";
export type Kind = "concept" | "practical" | "internals" | "design";

export interface SessionStats {
  session_id: number;
  mode: Mode;
  started_at: string;
  finished_at: string | null;
  n_questions: number;
  n_answered: number;
  n_correct: number;
}

export interface SessionInfo extends SessionStats {
  deck_id: string;
  deck_title: string;
}

export interface DeckInfo {
  id: string;
  title: string;
  description: string;
  author: string;
  n_questions: number;
  domains: Record<string, number>;
  levels: Record<string, number>;
  last_finished: SessionStats | null;
}

interface QuestionBase {
  id: string;
  domain: Domain;
  topic: string;
  tags: string[];
  level: number;
  kind: Kind;
  type: "single" | "multi";
  prompt: string;
}

/** A question as served before answering: no answer, notes or explanation. */
export interface PublicQuestion extends QuestionBase {
  choices: { id: string; text: string }[];
}

/** The full question, only sent after answering. */
export interface Question extends QuestionBase {
  choices: { id: string; text: string; why: string | null }[];
  answer: string[];
  explanation: string;
}

export interface SessionOut {
  session_id: number;
  deck_id: string;
  mode: Mode;
  questions: PublicQuestion[];
}

export interface AnswerIn {
  question_id: string;
  selected: string[];
  confidence: Confidence;
  time_ms: number;
}

/** Exam mode: only `recorded`. Learn mode: also the correction. */
export interface Feedback {
  recorded: boolean;
  is_correct?: boolean;
  answer?: string[];
  explanation?: string;
  why?: Record<string, string>;
}

export interface Bucket {
  key: string;
  n: number;
  answered: number;
  correct: number;
}

export interface ReviewItem {
  question: Question;
  selected: string[] | null;
  is_correct: boolean | null;
  confidence: Confidence | null;
  time_ms: number | null;
}

export interface Summary extends SessionInfo {
  by_domain: Bucket[];
  by_level: Bucket[];
  items: ReviewItem[];
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error("Can't reach the API. Is `python -m quizz serve` running?");
  }
  if (!res.ok) {
    const detail = await res.json().then((j) => j.detail, () => res.statusText);
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

export const api = {
  listDecks: () => request<DeckInfo[]>("GET", "/decks"),
  createSession: (deck_id: string, mode: Mode) => request<SessionOut>("POST", "/sessions", { deck_id, mode }),
  answer: (sessionId: number, body: AnswerIn) => request<Feedback>("POST", `/sessions/${sessionId}/answers`, body),
  finish: (sessionId: number) => request<Summary>("POST", `/sessions/${sessionId}/finish`),
  listSessions: () => request<SessionInfo[]>("GET", "/sessions"),
  summary: (sessionId: number) => request<Summary>("GET", `/sessions/${sessionId}/summary`),
};
