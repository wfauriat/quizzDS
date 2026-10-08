import type { Confidence, Domain } from "./api";

export const DOMAIN_LABELS: Record<Domain, string> = {
  ds: "Data science",
  de: "Data engineering",
  cs: "Computer science",
  swe: "Software engineering",
  stack: "Modern stack",
  infra: "Cloud & infra",
};

export const LEVEL_LABELS: Record<string, string> = {
  "1": "L1 · junior",
  "2": "L2 · junior+",
  "3": "L3 · mid",
  "4": "L4 · senior",
  "5": "L5 · staff",
};

export const CONFIDENCE_OPTIONS: { value: Confidence; label: string; key: string }[] = [
  { value: 1, label: "Guess", key: "G" },
  { value: 2, label: "Unsure", key: "U" },
  { value: 3, label: "Sure", key: "S" },
];

export const confidenceLabel = (c: Confidence | null) =>
  CONFIDENCE_OPTIONS.find((o) => o.value === c)?.label ?? "—";

export const domainLabel = (d: string) => DOMAIN_LABELS[d as Domain] ?? d;

export const letter = (index: number) => String.fromCharCode(65 + index);

export function formatDuration(ms: number): string {
  const s = Math.round(ms / 1000);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}
