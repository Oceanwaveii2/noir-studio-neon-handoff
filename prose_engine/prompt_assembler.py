"""
Prompt Assembler for the Noir Module 1 Prose Engine.
Synthesizes:
- Prose rewrite request & target span
- Diagnostic findings (filter words to kill, cadence targets)
- Inviolable protected spans and dialogue lines
- Show style profile & voice rules
- Few-shot approved author corrections
- Reference passages from Semantic Drive
into an unambiguous, structured prompt for Gemini 3.8 Flash.
"""

from typing import List, Optional
from .approved_edits import ApprovedEditPair
from .models import (
    ProseDiagnosticReport,
    ProseRewriteRequest,
    SpanCategory,
)
from .semantic_drive import ReferencePassage
from .style_engine import StyleProfile


class PromptAssembler:
    """Assembles prompt packets for narrative prose conditioning."""

    @classmethod
    def assemble(
        cls,
        request: ProseRewriteRequest,
        diagnostics: ProseDiagnosticReport,
        style_profile: StyleProfile,
        approved_edits: List[ApprovedEditPair],
        reference_passages: List[ReferencePassage],
        lens_id: Optional[str] = None,
    ) -> str:
        sections = []

        # 1. Header & Identity
        sections.append(
            f"=== SYSTEM: NOIR PROSE CONDITIONER ===\n"
            f"SHOW PROFILE: {style_profile.name} (ID: {style_profile.profile_id})\n"
            f"TARGET SPAN ID: {request.target_span_id} (Category: {request.category.value})\n"
            f"TARGET PSYCHIC DISTANCE: Level {request.target_psychic_distance} / 5\n"
            f"TARGET CADENCE BURSTINESS: >= {style_profile.target_cadence_burstiness:.1f}"
        )

        # 2. Inviolable Protected Words & Dialogue
        prot_lines = []
        for span in request.protected_spans:
            if span.category == SpanCategory.DIALOGUE:
                prot_lines.append(f"- CANONICAL DIALOGUE (MUST PRESERVE EXACTLY): \"{span.text}\"")
            else:
                prot_lines.append(
                    f"- PROTECTED TOKENS (CANNOT BE REMOVED/ALTERED): {', '.join(span.required_tokens)}"
                )

        if prot_lines:
            sections.append(
                "=== INVIOLABLE PROTECTED SPANS ===\n"
                "The following words, tokens, and spoken dialogue lines MUST appear intact in the rewritten prose.\n"
                "You are forbidden from mutating, dropping, or replacing them:\n"
                + "\n".join(prot_lines)
            )

        # 3. Active Props & Dramatic Facts
        fact_lines = []
        if request.active_props:
            fact_lines.append("ACTIVE PROPS IN SCENE:")
            for prop, state in request.active_props.items():
                fact_lines.append(f"  * {prop}: {state}")

        if request.prop_locations or request.character_inventory:
            fact_lines.append("PHYSICAL PROP LOCATIONS AND INVENTORY:")
            for prop, location in request.prop_locations.items():
                fact_lines.append(f"  * {prop} at {location}")
            for actor, items in request.character_inventory.items():
                fact_lines.append(f"  * {actor} holds: {', '.join(items)}")

        if request.character_epistemic_scope:
            fact_lines.append("CHARACTER KNOWLEDGE (keep separate by character):")
            for char, facts in request.character_epistemic_scope.items():
                fact_lines.append(f"  * {char} knows: {', '.join(facts)}")
        if request.reader_reveals is not None:
            fact_lines.append("READER REVEALS (separate from character knowledge):")
            fact_lines.extend(f"  * {reveal}" for reveal in request.reader_reveals)
            if not request.reader_reveals:
                fact_lines.append("  * No new reveal at this beat.")
        elif request.character_epistemic_scope:
            fact_lines.append("Reader visibility is unverified. Do not reveal private knowledge merely because a character has it.")

        if request.permitted_facts:
            fact_lines.append("PERMITTED SCENE FACTS:")
            for fact in request.permitted_facts:
                fact_lines.append(f"  * {fact}")

        if fact_lines:
            sections.append("=== DRAMATIC STATE & EPISTEMIC BOUNDARIES ===\n" + "\n".join(fact_lines))

        # 3b. Inviolable Ontological & Biological Invariants
        onto_lines = []
        if request.ontological_invariants:
            for inv in request.ontological_invariants:
                onto_lines.append(f"- [CANON RULE] {inv}")

        if onto_lines:
            sections.append(
                "=== INVIOLABLE ONTOLOGICAL & BIOLOGICAL INVARIANTS ===\n"
                "The following biological, species, and relationship invariants are ABSOLUTE:\n"
                + "\n".join(onto_lines)
                + "\n\nCRITICAL ANTI-EXPOSITION DIRECTIVE: DRAMATIZE, DO NOT EXPLAIN.\n"
                "These rules are invisible physical laws of the stage (like gravity). You are STRICTLY FORBIDDEN from explaining,\n"
                "lecturing, or justifying these rules to the reader in narration or dialogue (e.g. do NOT write 'because under the laws of...',\n"
                "'which meant that her form required...', or 'serving as a reminder of her heritage').\n"
                "Stage the physical reality, somatic resistance, and concrete actions directly without instructional meta-commentary.\n\n"
                "CRITICAL ANTI-PUNCHLINE FRONT-RUNNING DIRECTIVE: NEVER PRE-EXPLAIN THE JOKE.\n"
                "Never put the punchline, subtext, or realization into the setup before a character reacts.\n"
                "Let setups be clean and understated (e.g. 'just because you inherited your boyfriend's ass is no reason to be catty'),\n"
                "leaving the realization entirely to the responding character ('Wait... what...? Are you saying I have a flat white boy butt?!').\n"
                "Do not editorialize or telegraph punchlines before they land."
            )

        # 3c. Character Morph Permissions
        if request.character_morph_permissions:
            morph_lines = []
            for char, allowed in request.character_morph_permissions.items():
                status = "PERMITTED to shapeshift / morph" if allowed else "STRICTLY FORBIDDEN from shapeshifting / morphing (dormant genes)"
                morph_lines.append(f"- {char.upper()}: {status}")
            sections.append(
                "=== CHARACTER SHAPESHIFTING PERMISSIONS ===\n"
                + "\n".join(morph_lines)
            )

        # 3d. Active Sensory & Siren Auras
        if request.active_auras:
            aura_lines = []
            for aura in request.active_auras:
                aura_lines.append(
                    f"- {aura.get('field_id', 'aura')} (Emitter: {aura.get('emitter', 'unknown')}): "
                    f"{aura.get('effect', '')}"
                )
            sections.append(
                "=== ACTIVE BIOLOGICAL SIREN AURAS & SENSORY FIELDS ===\n"
                + "\n".join(aura_lines)
            )

        # 3e. Negative Constraints (Forbidden Hallucinations)
        neg_lines = []
        if request.negative_constraints:
            for neg in request.negative_constraints:
                neg_lines.append(f"- FORBIDDEN: {neg.get('pattern', '')} -> REASON: {neg.get('why', '')}")

        if neg_lines:
            sections.append(
                "=== NEGATIVE CONSTRAINTS (FORBIDDEN HALLUCINATIONS) ===\n"
                "You are STRICTLY FORBIDDEN from generating any of the following entities, terms, or errors:\n"
                + "\n".join(neg_lines)
            )

        # 4. Diagnostic Repair Instructions
        repair_items = []
        if diagnostics.filter_word_count > 0:
            repair_items.append(
                f"ELIMINATE FILTER WORDS ({diagnostics.filter_word_count} found: {', '.join(diagnostics.filter_words_found)}). "
                "Do not write 'she noticed' or 'she saw'; depict the physical reaction directly."
            )
        if diagnostics.label_syntax_detected:
            repair_items.append(
                f"FIX EMOTION LABELS ({len(diagnostics.label_examples)} found: {', '.join(diagnostics.label_examples)}). "
                "Show emotion through bodily movement, micro-expressions, and prop interaction."
            )
        if diagnostics.sensory_details_count == 0:
            pref = ", ".join(style_profile.sensory_preferences[:4]) if style_profile.sensory_preferences else "smell, sound, texture"
            repair_items.append(
                f"INCREASE SENSORY GROUNDING: Add at least one sensory anchor (e.g. {pref})."
            )
        if diagnostics.burstiness_score < 2.0:
            repair_items.append(
                "VARY CADENCE: Current sentence lengths are too uniform. Mix short 2-3 word punches with longer clauses."
            )

        if repair_items:
            sections.append("=== DIAGNOSTIC REPAIR INSTRUCTIONS ===\n" + "\n".join(f"[FIX] {r}" for r in repair_items))

        # 5. Show Voice Principles
        voice_lines = [f"- {p}" for p in style_profile.voice_principles]
        if style_profile.banned_cliches:
            voice_lines.append(f"- BANNED CLICHES: {', '.join(style_profile.banned_cliches)}")
        sections.append("=== SHOW VOICE PRINCIPLES ===\n" + "\n".join(voice_lines))

        # 5b. Active Stylistic Injection
        if lens_id:
            from .voice.injection import format_injection_prompt
            inj = format_injection_prompt(lens_id)
            if inj:
                sections.append(inj)

        # 6. Few-Shot Author-Approved Edits (Isolated to this profile)
        if approved_edits:
            edit_lines = []
            for i, edit in enumerate(approved_edits, 1):
                edit_lines.append(
                    f"Example {i} ({edit.defect_type}):\n"
                    f"  DRAFT: \"{edit.original_text}\"\n"
                    f"  APPROVED REWRITE: \"{edit.approved_text}\""
                )
            sections.append("=== FEW-SHOT APPROVED AUTHOR EXAMPLES ===\n" + "\n\n".join(edit_lines))

        # 7. Semantic Reference Passages
        if reference_passages:
            ref_lines = []
            for i, ref in enumerate(reference_passages, 1):
                ref_lines.append(f"Reference {i} [{ref.scene_type}]:\n\"{ref.text}\"")
            sections.append("=== GOLD-STANDARD REFERENCE PASSAGES ===\n" + "\n\n".join(ref_lines))

        # 8. Target Draft & Final Prompt
        sections.append(
            f"=== ORIGINAL DRAFT TEXT TO REWRITE ===\n"
            f"\"{request.original_text}\"\n\n"
            f"CRITICAL ANTI-SLOP & CRAFT RULES:\n"
            f"1. Zero World-Rule Lecturing: Never explain why a magic/nanite/biological rule exists; dramatize the physical consequence only.\n"
            f"2. Zero Subtext Explaining: Never attach gerund tails explaining what an action 'signaled', 'meant', or 'betrayed'.\n"
            f"3. Zero Punchline Echoes: Deliver comedic jokes and absurd escalations with hard deadpan timing; never paraphrase or soften them.\n"
            f"4. Zero Negative Parallelism: Do NOT use 'Not X, but Y' or 'It was not anger, but sadness'.\n"
            f"5. Zero Moralizing Codas: End the beat cleanly on an unresolved physical action, punchline, or departure; never summarize the moral meaning.\n\n"
            f"Rewrite this draft text following all voice rules, protected words, and diagnostic repairs.\n"
            f"Output ONLY the improved prose text."
        )

        return "\n\n".join(sections)
