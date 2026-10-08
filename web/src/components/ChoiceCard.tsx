import { Markdown } from "./Markdown";

/** idle/selected while answering; correct/missed/wrong/neutral once the answer is revealed. */
export type ChoiceState = "idle" | "selected" | "correct" | "missed" | "wrong" | "neutral";

const TAGS: Partial<Record<ChoiceState, string>> = {
  correct: "✓ your answer",
  wrong: "✗ your answer",
  missed: "correct answer",
};

export function revealState(choiceId: string, selected: string[], answer: string[]): ChoiceState {
  const picked = selected.includes(choiceId);
  if (answer.includes(choiceId)) return picked ? "correct" : "missed";
  return picked ? "wrong" : "neutral";
}

interface Props {
  letter: string;
  text: string;
  state: ChoiceState;
  why?: string | null;
  multi?: boolean;
  onClick?: () => void;
}

/** A clickable card while answering (`onClick` given), a static one once revealed. */
export function ChoiceCard({ letter, text, state, why, multi = false, onClick }: Props) {
  const className = `choice choice-${state}${multi ? " choice-multi" : ""}`;
  const content = (
    <>
      <span className="choice-letter">{letter}</span>
      <span className="choice-body">
        <span className="choice-text">
          <Markdown inline>{text}</Markdown>
        </span>
        {why && (
          <span className="choice-why">
            <Markdown inline>{why}</Markdown>
          </span>
        )}
      </span>
      {TAGS[state] && <span className="choice-tag">{TAGS[state]}</span>}
    </>
  );
  return onClick ? (
    <button type="button" className={className} onClick={onClick} aria-pressed={state === "selected"}>
      {content}
    </button>
  ) : (
    <div className={className}>{content}</div>
  );
}
