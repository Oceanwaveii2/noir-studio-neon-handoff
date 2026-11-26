# Acceptance

A change is accepted only when all three hold:

1. **Machine checks pass.** `python tools/ci.py` — unit tests, performance bench, quality budget, manifest.
2. **Quality budget respected.** `ci_budget.json`: zero canon violations, zero staging/ledger violations,
   zero dialogue bytes changed, zero invented-entity false accepts, zero copy false accepts, tic rate at
   or below the human baseline p90, and at least three distinct takes when a variation report exists.
3. **An author decision exists.** A row in `eval/proposals.jsonl` with `author_decision` and a reviewer
   name. The implementer cannot self-sign acceptance.

If a budget fails, the build fails and prints which check and by how much. Do not weaken a budget to
make it pass; change the code or record a retraction in `docs/RETRACTIONS.md`.

`python -B tools/ci.py --core` is the focused development gate documented in
[PROJECT_STEWARDSHIP.md](PROJECT_STEWARDSHIP.md). Its result is recorded separately from full release
CI, the current master canon check, and a named author's acceptance. Historical receipts are retained.
