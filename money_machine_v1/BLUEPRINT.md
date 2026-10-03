# MONEY MACHINE V1

## Architecture

Market Data
  -> MONEY_MAKER_01
  -> Candidate
  -> AI Judge
  -> PASS / WAIT
  -> Risk Authority
  -> APPROVED / WAIT
  -> Paper Engine
  -> Trade Result
  -> Performance / Feedback

## Rules
- Existing project files are read-only references.
- New system lives only in money_machine_v1/.
- WAIT is a valid decision.
- AI cannot override Risk.
- Risk can reject every candidate.
- Paper only; no live execution.
- No guessing: use verified interfaces and real data.
- Research and production logic remain separated.
