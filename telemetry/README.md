# Telemetry

Every file here is evidence produced by a command. Numbers in docs must cite a file here.

| Path | Produced by | What it shows |
|---|---|---|
| `books/voice_eval*.json` | `tools/eval_voice.py` | per-paragraph corpus typicality (diagnostic only; see `docs/RETRACTIONS.md`) |
| `books/slop_eval.json` | `tools/eval_slop.py` | held-out fold; currently **insufficient labels** |
| `reports/best_of_n*.json` | `tools/eval_best_of_n.py` | accept rate and selected similarity per configuration |
| `reports/copies_sample.md` | `tools/inspect_candidates.py` | reference-conditioned drafts beside the source (copy evidence) |
| `reports/steering_v2.json` | `tools/calibrate_steering_v2.py` | layer/alpha sweep; calibration only |
| `eval/decisions.jsonl` | pipeline | one row per decision |
| `eval/proposals.jsonl` | conditioner | accepted and rejected proposals with reason |
| `eval/api_usage.jsonl`, `session_usage.jsonl` | providers | spend/usage guard |
| `reports/archive/` | S0 cleanup | old bench/evidence runs, kept but not current |

## Rules

1. Never quote a number from `archive/` as a result.
2. A number without a file path is not evidence.
3. Retracted numbers: `docs/RETRACTIONS.md`.
4. New reports use forward slashes in path fields.
