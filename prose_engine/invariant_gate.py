"""
Invariant Verification Gate for the Noir Module 1 Prose Engine.
Enforces upstream drama invariants before any proposed rewrite can become a candidate proposal:
1. Protected canonical dialogue and required tokens must remain intact.
2. Prop FSM state consistency (e.g. cannot illuminate or interact with a destroyed prop).
3. Epistemic boundaries (no unearned secret reveals or telepathic knowledge).
4. Meta-commentary stripping (strips conversational preamble like 'Here is your prose:').
"""

import re
import uuid
from typing import List, Tuple
from .canon_rules import find_rule_violations
from .diagnostics import ProseDiagnosticsAnalyzer
from .models import (
    ProseDiagnosticReport,
    ProseRewriteProposal,
    ProseRewriteRequest,
)
from .protected_spans import ProtectedSpanProtector


class InvariantGate:
    """Referee that audits candidate prose text against dramatic and physical invariants."""

    @staticmethod
    def clean_candidate_text(raw_text: str) -> str:
        """Strips markdown code fences and conversational preamble if the model emitted them."""
        text = raw_text.strip()
        # Strip outer markdown block ```markdown ... ``` or ``` ... ```
        fence_match = re.search(r"```(?:markdown|text)?\s*([\s\S]*?)\s*```", text)
        if fence_match:
            text = fence_match.group(1).strip()

        # Strip conversational AI prefixes
        prefixes = [
            r"^(?:here(?:'s| is) (?:the|your) (?:rewritten|improved|conditioned) prose:?\s*)",
            r"^(?:sure,? here(?:'s| is) (?:the|a) rewrite:?\s*)",
            r"^(?:rewritten prose:?\s*)",
        ]
        for p in prefixes:
            text = re.sub(p, "", text, flags=re.IGNORECASE).strip()

        return text

    @classmethod
    def verify_prop_states(
        cls, candidate_text: str, active_props: dict[str, str]
    ) -> List[str]:
        """
        Ensures the candidate text does not violate physical states of props.
        For example: cannot turn on, illuminate, or drink from an empty/broken prop.
        """
        violations = []
        lowered = candidate_text.lower()

        for prop_name, state in active_props.items():
            state_lower = state.lower()
            tokens = [w for w in prop_name.lower().split("_") if len(w) > 2]
            if not tokens:
                tokens = [prop_name.lower()]

            # Match either the primary keyword or tokens with intervening words (e.g. 'Gloria the flamingo lamp')
            joined_pattern = r"\b" + r"\b.*?\b".join(re.escape(t) for t in tokens) + r"\b"
            primary_token = re.escape(tokens[0])

            if state_lower in ("broken", "destroyed", "shattered"):
                # Check for impossible active usage verbs
                patterns = [
                    rf"\b(?:turns\s+on|switches\s+on|lights|illuminates|plugs\s+in)\s+.*?(?:{joined_pattern}|\b{primary_token}\b)",
                    rf"\b(?:{joined_pattern}|\b{primary_token}\b)\s+(?:glows|shines|lights\s+up|stands\s+sturdy)\b",
                ]
                for pat in patterns:
                    if re.search(pat, lowered):
                        violations.append(
                            f"Physical impossibility: Prop '{prop_name}' is {state}, "
                            f"but proposed prose attempts to activate or illuminate it."
                        )

            elif state_lower == "empty":
                # Check for drinking/consuming from empty prop
                if re.search(rf"\b(?:drinks|sips|gulps)\s+(?:from\s+)?.*?(?:{joined_pattern}|\b{primary_token}\b)", lowered):
                    violations.append(
                        f"Physical impossibility: Prop '{prop_name}' is empty, "
                        f"but proposed prose depicts drinking from it."
                    )

        return violations

    @classmethod
    def verify_epistemic_bounds(
        cls,
        candidate_text: str,
        character_epistemic_scope: dict[str, List[str]],
        epistemic_unknown: dict[str, List[dict]] | None = None,
    ) -> List[str]:
        """
        Ensures characters do not speak or act upon unlearned secrets or facts.
        Supports both explicit 'unknown_'/'unrevealed_' tokens and complement-based unknown fact keywords.
        """
        from .canon_rules import is_negated

        violations: List[str] = []
        lowered = candidate_text.lower()

        def _non_negated_match(token: str) -> bool:
            pat = rf"(?<!\w){re.escape(token.lower())}(?!\w)"
            for m in re.finditer(pat, lowered):
                if not is_negated(lowered, m):
                    return True
            return False

        for char, secrets in character_epistemic_scope.items():
            for secret in secrets:
                if secret.startswith("unknown_") or "unrevealed" in secret:
                    secret_token = secret.replace("unknown_", "").replace("unrevealed_", "").replace("_", " ").strip()
                    if secret_token and _non_negated_match(secret_token):
                        violations.append(
                            f"Epistemic leak: Character '{char}' is not yet aware of '{secret_token}', "
                            f"but it was referenced or revealed in dialogue/action."
                        )

        if epistemic_unknown:
            for char, unknown_items in epistemic_unknown.items():
                for item in unknown_items:
                    fid = str(item.get("id") or "")
                    tokens = [str(k).strip() for k in item.get("keywords", []) if str(k).strip()]
                    if not tokens and fid:
                        tokens = [fid.replace("_", " ")]
                    for tok in tokens:
                        if len(tok) >= 4 and _non_negated_match(tok):
                            violations.append(
                                f"Epistemic leak: Character '{char}' does not know fact '{fid}' ('{tok}')."
                            )
                            break

        return violations

    @classmethod
    def verify_ontological_invariants(
        cls, candidate_text: str, request: ProseRewriteRequest
    ) -> List[str]:
        """
        Audits candidate text against absolute biological, kinship, and morph invariants.
        """
        violations = []
        text = candidate_text

        # 1. Evaluate Negative Regex Constraints (negation-aware)
        for neg, matched in find_rule_violations(text, request.negative_constraints):
            violations.append(
                f"Ontological Violation [{neg.get('id', 'rule')}]: Matched forbidden token '{matched}'. "
                f"Reason: {neg.get('why')}"
            )

        # 2. Morph Permission Verification
        for char, can_morph in request.character_morph_permissions.items():
            if not can_morph:
                # Character is forbidden from morphing (e.g. Haley)
                morph_pattern = rf"\b{re.escape(char)}\b[^.?!;]{{0,60}}\b(morph(?:s|ed|ing)?|shapeshift(?:s|ed|ing)?|transform(?:s|ed|ing)?|grows?\s+a?\s*(?:tail|ears?))\b"
                m = re.search(morph_pattern, text, flags=re.IGNORECASE)
                if m:
                    violations.append(
                        f"Morph Permission Violation: Character '{char}' is restricted from shapeshifting, "
                        f"but proposed text depicts: '{m.group(0)}'."
                    )

        return violations

    @classmethod
    def audit_rewrite(
        cls, candidate_text: str, request: ProseRewriteRequest
    ) -> Tuple[bool, List[str], str]:
        """
        Runs complete invariant audit.
        Returns (is_valid, list_of_violations, cleaned_text).
        """
        cleaned_text = cls.clean_candidate_text(candidate_text)
        violations: List[str] = []

        if not cleaned_text:
            return False, ["Candidate text is empty."], ""

        # 1. Protected Spans & Canonical Words
        is_spans_valid, span_errors = ProtectedSpanProtector.verify_all(
            cleaned_text, request.protected_spans
        )
        if not is_spans_valid:
            violations.extend(span_errors)

        # 2. Prop FSM State Integrity
        prop_errors = cls.verify_prop_states(cleaned_text, request.active_props)
        violations.extend(prop_errors)

        # 3. Epistemic Knowledge Boundaries
        epistemic_errors = cls.verify_epistemic_bounds(
            cleaned_text,
            request.character_epistemic_scope,
            epistemic_unknown=getattr(request, "epistemic_unknown", None),
        )
        violations.extend(epistemic_errors)

        # 4. Ontological Invariants & Negative Constraints
        onto_errors = cls.verify_ontological_invariants(cleaned_text, request)
        violations.extend(onto_errors)

        return len(violations) == 0, violations, cleaned_text

    @classmethod
    def create_verified_proposal(
        cls,
        candidate_text: str,
        request: ProseRewriteRequest,
        diagnostics_before: ProseDiagnosticReport,
        model_provider: str = "mock",
        model_name: str = "synthetic-v1",
    ) -> Tuple[ProseRewriteProposal, List[str]]:
        """
        Validates candidate rewrite, runs post-rewrite diagnostics, and returns typed ProseRewriteProposal.
        """
        is_valid, violations, cleaned_text = cls.audit_rewrite(candidate_text, request)

        # Post-rewrite diagnostics
        diagnostics_after = ProseDiagnosticsAnalyzer.analyze(
            cleaned_text,
            span_id=request.target_span_id,
            target_psychic_distance=request.target_psychic_distance,
        )

        proposal = ProseRewriteProposal(
            proposal_id=f"prop_{uuid.uuid4().hex[:12]}",
            request_id=request.request_id,
            project_id=request.project_id,
            document_id=request.document_id,
            base_revision=request.base_revision,
            target_span_id=request.target_span_id,
            proposed_text=cleaned_text,
            diagnostics_before=diagnostics_before,
            diagnostics_after=diagnostics_after,
            protected_words_verified=is_valid and len(violations) == 0,
            epistemic_verified=len(violations) == 0,
            model_provider=model_provider,
            model_name=model_name,
        )

        return proposal, violations
