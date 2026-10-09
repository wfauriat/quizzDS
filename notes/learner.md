# Learner notes

Maintained by Claude after each analysis (see "Session loop" in CLAUDE.md). The raw history is in
`data/quizz.sqlite` (summarized by `python -m quizz report`). This file holds the interpretation:
what the numbers suggest, what to target next, and, in the dated log at the end, how that judgment
evolved.

_Last updated: 2026-10-09 · based on 20 first attempts (1 exam session)_

## Current estimate

| Domain | Estimated level | Evidence |
|---|---|---|
| swe | L4+ (ceiling not found yet) | 3/3, including an L4 design multi-select (idempotency keys) |
| ds | L3 | fundamentals right up to L3 (leakage, p-values); missed the L4 probability correction |
| de | L3 | L3 2/2 (window functions, idempotent pipelines); Parquet statistics missed (partial 2/3); Kafka exactly-once (L5) wrong |
| cs | L3 | LSM trade-offs (L4) right; amortized analysis (L3) guessed wrong |
| stack | L2–L3 | Docker caching right; dbt incremental and asyncio semantics wrong |
| infra | L2, uneven | containers right; k8s probes guessed wrong; NAT/S3 endpoint (L4) right but **guessed** |

All estimates are low-confidence: there are only 3–4 questions per domain.

## Strengths
- Engineering judgment and trade-offs: git on shared branches, blocking calls in async code,
  idempotent APIs and pipelines, storage-engine trade-offs.
- ML and statistics fundamentals: leakage in cross-validation, p-value interpretation (slow but
  correct).
- SQL ranking semantics (RANK vs ROW_NUMBER).

## Gaps to target
- **The exact semantics of specific tools** (internals: 1/4 correct, 48% partial credit). The pattern
  is a plausible mental model with a wrong detail:
  - Kafka exactly-once applies to the effects inside Kafka, not to processing.
  - dbt incremental: the `where` filter drops late rows before `unique_key` ever applies.
  - asyncio: mixed up `gather` (raises the plain error, siblings keep running) with `TaskGroup`
    (cancels the siblings, raises an `ExceptionGroup`).
  - Parquet: knew columnar layout and compression, missed row-group min/max statistics.
- **Kubernetes operations:** probes were a guess, so likely little hands-on experience.
- **Complexity theory:** amortized analysis (confused the number of reallocations with the total
  copy cost).
- **Probability calibration:** picked the half-true option ("ranking is unchanged, so use p as is").
  Knows the fact but drew the wrong conclusion.

## Habits and calibration
- Confidence matches results well: sure 3/3, unsure 9/13, guess 1/4. There are **no sure-but-wrong
  answers**, so the misses look like knowledge gaps rather than misconceptions.
- Uses "unsure" a lot (13/20), even when right (9 times). Knowledge is probably sounder than the
  self-assessment suggests.
- Pace: ~30 min for 20 questions. Sure answers take ~30 s; the others ~95 s. Takes time on DS
  reasoning questions and gets them right.

## Next deck recommendation
- A **targeted L3–L4 deck** on the gaps: streaming semantics (Kafka, Spark watermarks), Python
  concurrency (asyncio, GIL, threads vs processes), dbt and table formats (incremental models,
  Delta/Iceberg, Parquet internals), Kubernetes basics (probes, deployments, services), complexity
  and amortized analysis, probability calibration and thresholds.
- Add 2–3 **swe/design questions at L4–L5** to find the ceiling.
- `easy-01` (L1–L2 breadth, not taken yet) should be mostly easy. It works as a quick check on
  topics calibration-01 didn't cover.

## Analysis log

### 2026-10-09 — calibration-01, exam mode (session 5): 13/20 (65%), 30 min
- First baseline. Questions 1–2 had been seen in earlier Learn-mode trial sessions, which were
  deleted at the user's request, so the clean score is 11/18.
- By level: L1 3/3, L2 3/5, L3 4/6, L4 3/4, L5 0/2. The curve isn't monotonic because both L2 misses
  were tool-specific (Parquet statistics, k8s probes). Level labels mix difficulty with familiarity.
- By kind: design 3/3 (one of them a guess), concept 4/5, practical 5/8, internals 1/4.
- Multi-select graded all-or-nothing scored 1/3, but 64% with partial credit. Partial credit
  (Jaccard) is now in the report.