"""
Telemetry Engine Run Logger & Audit Dashboard.

Provides crystal-clear, transparent audit logging for every execution of the
prose conditioner and hybrid realizer so authors and developers can verify
that the engine is doing its job:
  1. Tracks which paragraphs were flagged and by which specific rules/AI-isms.
  2. Tracks the cut-first deletion vs. rewrite decisions.
  3. Audits all multi-gate invariant checks (no Smith surname, no false patriarchs,
     no blacklisted clichés, 0 dialogue drift, burstiness >= 4.0).
  4. Records acceptance vs. rejection reasons per paragraph.
  5. Emits both machine-readable JSON logs and a human-readable Markdown run report:
     `telemetry/engine_runs/LATEST_RUN_LOG.md`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass
class ProposalAuditEntry:
    paragraph_index: int
    char_range: Tuple[int, int]
    original_snippet: str
    proposed_snippet: str
    operation: str  # "delete", "replace", "unchanged"
    detected_warnings: List[str]
    blacklisted_cliches_caught: List[str]
    gate_checks: Dict[str, str]  # gate_name -> "PASS" or violation reason
    accepted: bool
    verdict_reason: str
    style_distance_delta: float
    corpus_similarity_delta: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "paragraph_index": self.paragraph_index,
            "char_range": list(self.char_range),
            "original_snippet": self.original_snippet,
            "proposed_snippet": self.proposed_snippet,
            "operation": self.operation,
            "detected_warnings": self.detected_warnings,
            "blacklisted_cliches_caught": self.blacklisted_cliches_caught,
            "gate_checks": self.gate_checks,
            "accepted": self.accepted,
            "verdict_reason": self.verdict_reason,
            "style_distance_delta": round(self.style_distance_delta, 4),
            "corpus_similarity_delta": round(self.corpus_similarity_delta, 4),
        }


@dataclass
class EngineRunReport:
    run_id: str
    timestamp: str
    source_document: str
    total_paragraphs: int
    flagged_paragraphs: int
    cut_first_deletions: int
    rewrites_attempted: int
    proposals_accepted: int
    proposals_rejected: int
    ai_cliches_blocked: int
    ontological_breaches_blocked: int
    input_burstiness: float
    output_burstiness: float
    entries: List[ProposalAuditEntry] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "source_document": self.source_document,
            "metrics": {
                "total_paragraphs": self.total_paragraphs,
                "flagged_paragraphs": self.flagged_paragraphs,
                "cut_first_deletions": self.cut_first_deletions,
                "rewrites_attempted": self.rewrites_attempted,
                "proposals_accepted": self.proposals_accepted,
                "proposals_rejected": self.proposals_rejected,
                "ai_cliches_blocked": self.ai_cliches_blocked,
                "ontological_breaches_blocked": self.ontological_breaches_blocked,
                "input_burstiness": self.input_burstiness,
                "output_burstiness": self.output_burstiness,
            },
            "entries": [e.to_dict() for e in self.entries],
        }

    def to_markdown(self) -> str:
        lines = [
            f"# ENGINE EXECUTION AUDIT LOG: `{self.run_id}`",
            f"**Timestamp:** {self.timestamp} UTC  ",
            f"**Source Document:** `{self.source_document}`  ",
            "",
            "## 1. Execution Summary Dashboard",
            "",
            "| Metric | Count / Value | Status |",
            "|---|---|---|",
            f"| **Total Paragraphs Scanned** | {self.total_paragraphs} | Scanned |",
            f"| **Flagged Paragraphs** | {self.flagged_paragraphs} | Analyzed |",
            f"| **Cut-First Deletions** | {self.cut_first_deletions} | " + ("Applied" if self.cut_first_deletions > 0 else "None") + " |",
            f"| **Rewrites Attempted** | {self.rewrites_attempted} | Processed |",
            f"| **Proposals Accepted** | {self.proposals_accepted} | Clean |",
            f"| **Proposals Rejected** | {self.proposals_rejected} | Guarded |",
            f"| **AI Tells / Clichés Blocked** | {self.ai_cliches_blocked} | Blocked |",
            f"| **Ontological Breaches Blocked** | {self.ontological_breaches_blocked} | Blocked |",
            f"| **Input Burstiness (σ)** | {self.input_burstiness:.2f} | Baseline |",
            f"| **Output Burstiness (σ)** | {self.output_burstiness:.2f} | " + ("PASS (>= 4.0)" if self.output_burstiness >= 4.0 else "REVIEW") + " |",
            "",
            "---",
            "",
            "## 2. Paragraph-by-Paragraph Audit Trail",
            "",
        ]

        if not self.entries:
            lines.append("*All paragraphs passed initial diagnostics without flags. Zero intervention required.*")
            return "\n".join(lines)

        for e in self.entries:
            status_badge = "✅ ACCEPTED" if e.accepted else f"❌ REJECTED ({e.verdict_reason})"
            op_label = "✂️ CUT-FIRST DELETION" if e.operation == "delete" else ("🔄 REWRITE" if e.operation == "replace" else "⏸️ UNCHANGED")
            lines.extend([
                f"### Paragraph ¶{e.paragraph_index} — {op_label} — {status_badge}",
                f"- **Character Span:** `[{e.char_range[0]}:{e.char_range[1]}]`",
                f"- **Diagnostics Warnings:** {', '.join(e.detected_warnings) if e.detected_warnings else 'None'}",
                f"- **Blacklisted Clichés Caught:** {', '.join(e.blacklisted_cliches_caught) if e.blacklisted_cliches_caught else '0 (Clean)'}",
                f"- **Style Metric Delta:** Style Distance $\\Delta$: `{e.style_distance_delta:+.2f}`, Corpus Similarity $\\Delta$: `{e.corpus_similarity_delta:+.2f}`",
                "",
                "**Gate Audit Results:**",
            ])
            for gate, result in e.gate_checks.items():
                lines.append(f"  - `{gate}`: {result}")

            lines.extend([
                "",
                "**Original Text:**",
                f"> {e.original_snippet}",
                "",
                "**Proposed Result:**",
                f"> {e.proposed_snippet if e.proposed_snippet else '*(Empty / Dropped)*'}",
                "",
                "---",
                "",
            ])

        return "\n".join(lines)


class EngineRunLogger:
    """Manages the creation, persistence, and reporting of engine run logs."""

    RUNS_DIR = Path("telemetry/engine_runs")

    @classmethod
    def log_run(
        cls,
        source_document: str,
        proposals: Sequence[Any],
        input_text: str,
        output_text: str,
        burstiness_calculator: Optional[Any] = None,
        *,
        cliche_findings: Sequence[Sequence[str]],
    ) -> EngineRunReport:
        if len(cliche_findings) != len(proposals) or any(
            isinstance(group, (str, bytes)) or any(not isinstance(item, str) for item in group)
            for group in cliche_findings
        ):
            raise ValueError("Provide cliché findings for each proposal in order.")
        cls.RUNS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc)
        run_id = f"run_{stamp.strftime('%Y%m%d_%H%M%S')}"

        # Compute burstiness
        in_b = burstiness_calculator(input_text) if burstiness_calculator else 0.0
        out_b = burstiness_calculator(output_text) if burstiness_calculator else 0.0

        cut_count = sum(1 for p in proposals if getattr(p, "op", "") == "delete" and p.accepted)
        rewrite_count = sum(1 for p in proposals if getattr(p, "op", "") == "replace")
        accepted_count = sum(1 for p in proposals if p.accepted)
        rejected_count = sum(1 for p in proposals if not p.accepted)

        cliches_blocked = 0
        onto_blocked = 0
        entries: List[ProposalAuditEntry] = []

        for p, findings in zip(proposals, cliche_findings):
            # Check clichés in candidate
            cliches = list(findings)
            if cliches:
                cliches_blocked += len(cliches)

            gate_checks = {
                "invariants": "PASS" if not ("violation" in p.reason.lower() or "smith" in p.reason.lower()) else p.reason,
                "world_state": "PASS" if "world state" not in p.reason.lower() else p.reason,
                "dialogue_integrity": "PASS" if "frozen" not in p.reason.lower() else p.reason,
                "cliche_blacklist": "PASS" if not cliches and "blacklisted" not in p.reason.lower() else (p.reason or "Banned cliché detected"),
                "voice_similarity": f"Similarity: {p.original_similarity:.2f} -> {p.rewrite_similarity:.2f}",
            }

            if "breaks world state" in p.reason.lower() or "ontology" in p.reason.lower():
                onto_blocked += 1

            entries.append(
                ProposalAuditEntry(
                    paragraph_index=p.index,
                    char_range=(p.start, p.end),
                    original_snippet=p.original[:300].strip(),
                    proposed_snippet=p.proposed[:300].strip(),
                    operation=getattr(p, "op", "replace"),
                    detected_warnings=p.warnings,
                    blacklisted_cliches_caught=cliches,
                    gate_checks=gate_checks,
                    accepted=p.accepted,
                    verdict_reason=p.reason or ("accepted" if p.accepted else "rejected"),
                    style_distance_delta=(p.style_after - p.style_before) if hasattr(p, "style_after") else 0.0,
                    corpus_similarity_delta=(p.rewrite_similarity - p.original_similarity) if hasattr(p, "rewrite_similarity") else 0.0,
                )
            )

        report = EngineRunReport(
            run_id=run_id,
            timestamp=stamp.isoformat(),
            source_document=source_document,
            total_paragraphs=len(input_text.split("\n\n")),
            flagged_paragraphs=len(proposals),
            cut_first_deletions=cut_count,
            rewrites_attempted=rewrite_count,
            proposals_accepted=accepted_count,
            proposals_rejected=rejected_count,
            ai_cliches_blocked=cliches_blocked,
            ontological_breaches_blocked=onto_blocked,
            input_burstiness=in_b,
            output_burstiness=out_b,
            entries=entries,
        )

        # Write machine-readable JSON
        json_path = cls.RUNS_DIR / f"{run_id}.json"
        json_path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

        # Write latest human-readable markdown dashboard
        md_path = cls.RUNS_DIR / "LATEST_RUN_LOG.md"
        md_path.write_text(report.to_markdown(), encoding="utf-8")

        # Append to manifest
        manifest_path = cls.RUNS_DIR / "runs_manifest.jsonl"
        with manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "run_id": run_id,
                "timestamp": report.timestamp,
                "source": source_document,
                "accepted": accepted_count,
                "rejected": rejected_count,
                "output_burstiness": out_b
            }) + "\n")

        return report
