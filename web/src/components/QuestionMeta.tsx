import type { PublicQuestion } from "../api";
import { domainLabel } from "../labels";

export function QuestionMeta({ question }: { question: PublicQuestion }) {
  return (
    <div className="chips">
      <span className="chip chip-domain">{domainLabel(question.domain)}</span>
      <span className="chip">{question.topic}</span>
      <span className="chip">L{question.level}</span>
      <span className="chip">{question.kind}</span>
      {question.type === "multi" && <span className="chip chip-accent">select all that apply</span>}
    </div>
  );
}
