"""Closed-loop Gemini session controller: gemini-session drives pipelines while Noir systems control output."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from uuid import uuid4

from story_graph.character_forms import CharacterJunction
from story_graph.episode_timeline import TimelineStore
from story_graph.form_graph_store import FormGraphStore
from story_graph.fx06_scene import PERFUME_LINE

from .canon_corrector import auto_correct_canon
from .mean_girls_minds import attach_mean_girls_minds_to_form_graph, build_three_little_bitches_minds
from .models import ProseRewriteRequest
from .notebook import DraftStore, NotebookStore, joined
from .providers.composer_bridge import load_isolated_composer_bridge
from .providers.primary_session import PrimarySessionProvider
from .scoped_pipeline import build_packet
from .scoped_service import execute_scoped
from .spring_alternate import build_alternate_spring_packet, validate_alternate_spring_candidate
from .tapped_out_graph import cook_with_character_graph_synthesis, synthesize_character_graph_for_script
from .voice.slop_critic import SlopCritic
from .voice.world_state import WorldState

DEFAULT_DRIVER_LEDGER = Path(__file__).resolve().parents[1] / ".app-steward/local/gemini-track7/session_usage.jsonl"
DEFAULT_SCENT_PATH = (
    Path(__file__).resolve().parents[1]
    / "deliverables"
    / "NOIR_FX06_GAG_COLLECTION_20261116"
    / "rainee_split_mind_support.json"
)
DEFAULT_SPRING_VARIANTS_DIR = (
    Path(__file__).resolve().parents[1]
    / ".app-steward"
    / "local"
    / "noir-spring-variants-tapped-out-20261117"
)
_FENCE_RE = re.compile(r"^\s*```[A-Za-z0-9_-]*\s*\r?\n(.*?)\r?\n```\s*$", re.DOTALL)


def _strip_fences(text: str) -> str:
    raw = str(text or "").strip()
    m = _FENCE_RE.match(raw)
    cleaned = m.group(1).strip() if m else raw
    scene_hit = re.search(r"(?m)^###\s+SCENE\b", cleaned)
    if scene_hit and 0 < scene_hit.start() < 240:
        preamble = cleaned[: scene_hit.start()].casefold()
        if any(tok in preamble for tok in ("proposal", "replacement scene", "author review", "here is")):
            cleaned = cleaned[scene_hit.start() :]
    return cleaned.strip()


def _make_gemini_provider(
    *,
    session_handler: Optional[Callable[[str], str]] = None,
    max_calls: int = 2,
    ledger: Path | str = DEFAULT_DRIVER_LEDGER,
    recovery_scope: str = "gemini-driver",
    max_prompt_bytes: int = 28_000,
) -> PrimarySessionProvider:
    if max_calls < 1 or max_calls > 6:
        raise ValueError("Keep Gemini driver max_calls bounded between 1 and 6.")
    ledger_path = Path(ledger)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    handler = session_handler or load_isolated_composer_bridge("gemini")
    return PrimarySessionProvider(
        "gemini",
        session_handler=handler,
        max_calls=max_calls,
        ledger=ledger_path,
        job_id=f"gemini-driver-{uuid4().hex[:12]}",
        recovery_scope=recovery_scope,
        max_prompt_bytes=max_prompt_bytes,
    )


def control_candidate_output(
    raw_text: str,
    *,
    episode_id: str,
    branch: str = "main",
    beat: int = 0,
    viewpoint: Optional[str] = None,
    protected_ranges: Sequence[Tuple[int, int]] = (),
    extra_validators: Sequence[Callable[[str], Sequence[str]]] = (),
    use_slop_model: bool = True,
) -> Dict[str, Any]:
    """Run Noir deterministic canon auto-correction, SlopCritic, and custom gatekeepers over Gemini output."""
    cleaned = _strip_fences(raw_text)
    try:
        world_state = WorldState.load()
    except FileNotFoundError:
        world_state = None
    corr = auto_correct_canon(
        cleaned,
        apply=True,
        world_state=world_state,
        episode_id=episode_id,
        branch=branch,
        beat=beat,
        viewpoint=viewpoint,
        protected_ranges=tuple(protected_ranges),
    )
    candidate = corr.corrected_text
    critic = SlopCritic(use_saved_model=use_slop_model).critique(candidate)

    hard_issues: List[str] = []
    for v in corr.remaining_violations:
        hard_issues.append(v.get("reason") or v.get("message") or str(v))
    if not critic.passed:
        hard_issues.extend(critic.hard_blocks or [f"SlopCritic exceeded limit (score {critic.slop_score})"])
    for fn in extra_validators:
        for msg in fn(candidate) or ():
            if msg:
                hard_issues.append(str(msg))

    dedup_issues = list(dict.fromkeys(hard_issues))
    return {
        "passed": not dedup_issues,
        "text": candidate,
        "raw_sha256": sha256(cleaned.encode("utf-8")).hexdigest(),
        "controlled_sha256": sha256(candidate.encode("utf-8")).hexdigest(),
        "canon_corrections": [c.to_dict() for c in corr.corrections],
        "remaining_canon_violations": list(corr.remaining_violations),
        "slop_critique": critic.to_dict(),
        "hard_issues": dedup_issues,
    }


def generate_controlled_prose(
    provider: PrimarySessionProvider,
    initial_prompt: str,
    *,
    control_fn: Callable[[str], Dict[str, Any]],
    strategy: str = "gemini_closed_loop",
    project_id: str = "afm",
    document_id: str = "scene",
    base_revision: int = 0,
    target_span_id: str = "slot-0",
) -> Dict[str, Any]:
    """Dispatch initial Gemini generation and perform bounded feedback repair if Noir gates block."""
    turns: List[Dict[str, Any]] = []
    attempt_ids: List[str] = []
    prompt = initial_prompt
    last_verdict: Optional[Dict[str, Any]] = None

    while provider.calls < provider.max_calls:
        req = ProseRewriteRequest(
            project_id=project_id,
            document_id=document_id,
            base_revision=base_revision,
            target_span_id=target_span_id,
            original_text="",
            strategy=strategy,
            protected_spans=(),
            request_id=f"scoped-{uuid4().hex}",
        )
        raw = provider.generate_rewrite(req, prompt)
        if getattr(provider, "last_attempt_id", None):
            attempt_ids.append(provider.last_attempt_id)
        verdict = control_fn(raw)
        last_verdict = verdict
        turns.append({
            "turn": len(turns) + 1,
            "attempt_id": getattr(provider, "last_attempt_id", None),
            "passed": verdict["passed"],
            "canon_corrections_count": len(verdict["canon_corrections"]),
            "hard_issues": list(verdict["hard_issues"]),
            "controlled_sha256": verdict["controlled_sha256"],
        })
        if verdict["passed"]:
            return {
                "status": "PASSED",
                "accepted": True,
                "text": verdict["text"],
                "provider_calls": provider.calls,
                "attempt_ids": attempt_ids,
                "turns": turns,
                "verdict": verdict,
            }
        # Build targeted gate-repair feedback for remaining budget turns.
        issues_block = "\n".join(f"- {issue}" for issue in verdict["hard_issues"])
        prompt = (
            "Your previous draft failed Noir deterministic validation gates:\n"
            f"{issues_block}\n\n"
            "Revise ONLY to satisfy every failed requirement while keeping the scene style, formatting, and speaker cues crisp.\n"
            "Return ONLY the revised scene text (no commentary or markdown fences).\n\n"
            "ORIGINAL BRIEF:\n"
            f"{initial_prompt}\n\n"
            "PREVIOUS DRAFT TO FIX:\n"
            f"{verdict['text']}"
        )

    assert last_verdict is not None
    return {
        "status": "BLOCKED",
        "accepted": False,
        "text": last_verdict["text"],
        "provider_calls": provider.calls,
        "attempt_ids": attempt_ids,
        "turns": turns,
        "verdict": last_verdict,
    }


def _load_full_spring_source(leaving_mode: str) -> str:
    """Load the archived full 7-scene Spring Break episode source when present."""
    name = "RELAPSE-FULL-EPISODE.md" if leaving_mode == "relapse" else "CLOTHES-FULL-EPISODE.md"
    path = DEFAULT_SPRING_VARIANTS_DIR / name
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return (
        "### SCENE 1: KITCHEN BRIEFING & THE ANCESTRAL MASSAGE\n"
        "INT. LING HOUSE - KITCHEN / LIVING ROOM - 07:31 A.M.\n\n"
        "Francine: Okay, troops—three nights of lasagna, two nights of orange chicken, and Baba's ancestral farting.\n"
        "Haley: Let me go check on Mom 2.\n"
        "Stella: Sweet, in a newspaper-origami way.\n\n"
        "### SCENE 2: MASTER SUITE & THE SUDDEN COUP\n"
        "Rainee cramps at her vanity and bolts toward the bathroom in puffs of French perfume.\n\n"
        "### SCENE 3: THE DOUBLE COMMODE & THE TWO-CHAIR RULE\n"
        "The toilet widens into a double-wide black lotus throne. Floral vapor creeps under the oak door.\n\n"
        f"Haley: {PERFUME_LINE}\n\n"
        "### SCENE 4: THE THREE LITTLE BITCHES\n"
        "[EDITABLE FULL ALTERNATIVE SCENE 4-6]\n\n"
        "### SCENE 7: ROGER'S RUTGERS SPRING BREAK TAKEOVER\n"
        "Roger greets the Rutgers Spring Break '08 charter bus with cape, scepter, megaphone, and goody bags.\n"
    )


def drive_gemini_alternate_spring_break(
    workspace: Path,
    *,
    leaving_mode: str = "relapse",
    session_handler: Optional[Callable[[str], str]] = None,
    max_calls: int = 2,
    mean_girls_dir: Optional[Path] = None,
    linked_evidence: Optional[Dict[str, Any]] = None,
    donor_override: Optional[Dict[str, Any]] = None,
    srt_cues: Optional[Sequence[Any]] = None,
    use_movie_dir: bool = True,
    apply_to_notebook: bool = True,
    full_story: bool = False,
    require_named_splits: bool = False,
    out_story: Optional[Path] = None,
) -> Dict[str, Any]:
    """Drive Alternate Spring Break (Scene 4 slot or full 7-scene story) via gemini-session + Noir controls."""
    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    tl = TimelineStore(root / "timeline.sqlite")
    forms = FormGraphStore(root / "forms.sqlite")
    if not tl.cards():
        tl.add_starter_cards()

    scent_rules = (
        json.loads(DEFAULT_SCENT_PATH.read_text(encoding="utf-8"))
        if DEFAULT_SCENT_PATH.is_file()
        else None
    )
    compiled_minds = build_three_little_bitches_minds(
        mean_girls_dir=mean_girls_dir,
        linked_evidence=linked_evidence,
        donor_override=donor_override,
        srt_cues=srt_cues,
        scent_rules=scent_rules,
        timing_cues=(
            "Keep the conversation moving through small interruptions and distinct speaker turns.",
            "Hold half a beat before flipping an excuse or landing a callback.",
        ),
        include_movie_dir=use_movie_dir,
    )
    graph_attach = attach_mean_girls_minds_to_form_graph(forms, compiled_minds)

    source_reference = ""
    if full_story:
        prefix = ""
        suffix = ""
        source_reference = _load_full_spring_source(leaving_mode)
        slot_placeholder = f"[OPENING SLOT]\n\nHaley: {PERFUME_LINE}\n\n[CLOSING SLOT]"
    else:
        prefix = f"INT. HALL - MORNING\nHaley stops outside the bathroom.\n\nHaley: {PERFUME_LINE}\n\n"
        suffix = "\n\n### SCENE 7: ROGER RUTGERS TAKEOVER\nRoger steps into the sun in full Rutgers regalia.\n"
        slot_placeholder = "[EDITABLE SCENE 4 AND ALTERNATIVE LEAVING]"
    packet = build_alternate_spring_packet(
        prefix,
        slot_placeholder,
        suffix,
        compiled_minds,
        form_store=forms,
        leaving_mode=leaving_mode,
        timing_notes=("Hold half a beat before flipping the excuse.",),
        full_story=full_story,
        require_named_splits=require_named_splits,
    )

    ep_id = packet["episode"]
    if not any(card["id"] == ep_id for card in tl.cards()):
        tl.fork(f"branch-{leaving_mode}", "main", "spring-break", 0)
        tl.create_episode(ep_id, f"Spring Break · Three Little Bitches ({leaving_mode})", f"branch-{leaving_mode}", 10)
        tl.save(ep_id, 0, script=packet["full_text"], source_name="gemini-driver-seed")
    j_supplier = lambda: {g["character_id"]: CharacterJunction.from_record(g) for g in forms.read()["junctions"]}
    j_map = j_supplier()
    existing_evs = {ev["id"] for ev in tl.episode_events(ep_id)}
    for idx, (cid, fid) in enumerate((
        ("rainee", "rainee-split-1"),
        ("rainee", "rainee-split-2"),
        ("rainee", "rainee-split-3"),
        ("rainee", "peter_griffin_celestial_variant"),
        ("francine", "nurse_pamela_franny_anderson"),
        ("roger", "mtv_beach_host"),
        ("roger", "rutgers_royal_persona"),
    )):
        if cid in j_map and any(f.id == fid for f in j_map[cid].forms):
            ev_id = f"form-unlock-{ep_id}-{idx}"
            if ev_id not in existing_evs:
                tl.add_event(ev_id, ep_id, 0, f"Authorized form {fid} for {cid}.", status="draft", permitted=True, source_id="gemini-driver")
                tl.bind_form_event(ep_id, ev_id, cid, fid, "available", j_map)
                tl.review_event(ep_id, ev_id, "Author", "gemini-driver", True)
    nb_store = NotebookStore(tl)
    nb_state = nb_store.open(ep_id)
    nb_text = joined(nb_state["blocks"])
    init_masks = [
        {
            "id": "haley-lock",
            **packet["locked_spans"][0],
            "sha256": sha256(nb_text[packet["locked_spans"][0]["start"] : packet["locked_spans"][0]["end"]].encode("utf-8")).hexdigest(),
        },
    ]
    if not full_story:
        init_masks.append({
            "id": "roger-lock",
            **packet["locked_spans"][1],
            "sha256": sha256(nb_text[packet["locked_spans"][1]["start"] : packet["locked_spans"][1]["end"]].encode("utf-8")).hexdigest(),
        })
    nb_state = nb_store.save(
        ep_id,
        nb_state["revision"],
        nb_state["timeline_revision"],
        nb_state["blocks"],
        25,
        init_masks,
    )

    leaving_req = (
        "Scene 5 (Hallway Tag) & Scene 6 (Departure): Nurse Franny leaves the house keys and three trays of lasagna "
        "with Haley and Stella, then drives the three Rainees off in the red sedan."
        if leaving_mode == "relapse"
        else "Scene 5A (The Clothes) & Scene 6 (Red Sedan): Nurse Franny takes the three Rainees upstairs to pack outfits "
        "into a red overnight bag (arguing via Mean Girls tactics), leaves the house keys and three trays of lasagna with "
        "Haley and Stella, and drives off in the red sedan."
    )
    split_names_req = (
        "Use their full split names as speaker cues throughout Scenes 4–6 (`Rainee Sade:`, `Rainee Becky:`, `Rainee Clarie:`), "
        "establishing on first split that Rainee 1 is Rainee Sade, Rainee 2 is Rainee Becky, and Rainee 3 is Rainee Clarie.\n"
        if require_named_splits
        else "Use distinct speaker cues (`Rainee 1:` / `Rainee Sade:`, `Rainee 2:` / `Rainee Becky:`, `Rainee 3:` / `Rainee Clarie:`).\n"
    )
    if full_story:
        prefix = ""
        suffix = ""
        cache_path = root / "stages_cache.json"
        stages_cache: Dict[str, Any] = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.is_file() else {}
        stage_key = f"{leaving_mode}:{int(require_named_splits)}"
        cached_entry = stages_cache.get(stage_key, {})

        opening_prompt = (
            "Write ONLY Scenes 1 to 3 at full vivid script-novel scale (headings `### SCENE 1: ...`, `### SCENE 2: ...`, `### SCENE 3: ...`; "
            "plain `Speaker: line` cues + rich sensory action lines; NO markdown fences, NO commentary, vary short/long sentences).\n"
            "Continuity: Ling family (NEVER Smith), Jeff is Haley's boyfriend (NEVER husband). Francine is STILL INSIDE the house preparing to leave (she does NOT drive off yet).\n"
            "Include:\n"
            "- `### SCENE 1: KITCHEN BRIEFING & THE ANCESTRAL MASSAGE`: Francine Ling packs by her red wheeled overnight bag, briefing Haley and origami-paper Stella "
            "on three nights of lasagna, two nights of orange chicken, mystery casserole, and Baba's hernia 'ancestral farting'. Haley heads upstairs.\n"
            "- `### SCENE 2: MASTER SUITE & THE SUDDEN COUP`: Rainee at her vanity in red robe-dress, fox ears, orange-and-cream tail cramps sharply and sprints to the bathroom in perfume puffs.\n"
            "- `### SCENE 3: THE DOUBLE COMMODE & THE TWO-CHAIR RULE`: Toilet expands into a double-wide black lotus porcelain throne; floral mist seeps under the door.\n"
            f"- End Scene 3 verbatim with:\nHaley: {PERFUME_LINE}\n"
        )
        opening_provider = _make_gemini_provider(
            session_handler=session_handler,
            max_calls=max(1, min(max_calls, 2)),
            ledger=root / "gemini_opening_usage.jsonl",
            recovery_scope=f"spring-alt-{leaving_mode}-open",
        )

        def _control_opening(cand_text: str) -> Dict[str, Any]:
            def _check_open(txt: str) -> List[str]:
                errs: List[str] = []
                for num in ("1", "2", "3"):
                    if not re.search(rf"###\s+SCENE\s+{num}\b", txt, re.IGNORECASE):
                        errs.append(f"Opening must include heading `### SCENE {num}`.")
                if PERFUME_LINE not in txt:
                    errs.append(f"Scene 3 must include Haley's exact line: {PERFUME_LINE}")
                low_t = txt.casefold()
                if "francine" not in low_t or "stella" not in low_t or "rainee" not in low_t:
                    errs.append("Opening scenes must include Francine, Stella, and Rainee.")
                return errs

            return control_candidate_output(
                cand_text,
                episode_id="spring-break",
                branch="main",
                beat=0,
                extra_validators=[_check_open],
            )

        if isinstance(cached_entry.get("opening"), dict) and cached_entry["opening"].get("accepted"):
            opening_loop = cached_entry["opening"]
        else:
            opening_loop = generate_controlled_prose(
                opening_provider,
                opening_prompt,
                control_fn=_control_opening,
                strategy="gemini_spring_opening",
                project_id=tl.scope()["project_id"],
                document_id=ep_id,
                base_revision=nb_state["timeline_revision"],
                target_span_id="scenes-1-3",
            )
            if opening_loop["accepted"]:
                stages_cache[stage_key] = {**cached_entry, "opening": opening_loop}
                cache_path.write_text(json.dumps(stages_cache, indent=2, ensure_ascii=False), encoding="utf-8")
                cached_entry = stages_cache[stage_key]
        if not opening_loop["accepted"]:
            return {
                "mode": "spring-alternate",
                "leaving_mode": leaving_mode,
                "full_story": True,
                "require_named_splits": require_named_splits,
                "status": "BLOCKED",
                "accepted": False,
                "provider_calls": opening_loop["provider_calls"],
                "attempt_ids": opening_loop["attempt_ids"],
                "turns": opening_loop["turns"],
                "opening_loop": opening_loop,
                "mean_girls_minds": {
                    "admitted_window_count": compiled_minds["admitted_window_count"],
                    "srt_cue_count": compiled_minds["srt_cue_count"],
                    "quarantined_or_rejected": compiled_minds["quarantined_or_rejected"],
                    "attached_ports": graph_attach["attached"],
                },
                "text": opening_loop["text"],
                "assembled_text": opening_loop["text"],
                "verdict": opening_loop["verdict"],
                "graph_result": None,
                "scoped_validation": None,
                "history_check": None,
                "notebook_revision": nb_state["revision"],
            }
        generated_opening = opening_loop["text"].rstrip() + "\n\n"
        middle_packet = build_alternate_spring_packet(
            generated_opening,
            "[EDITABLE SCENES 4-6]",
            "\n\n### SCENE 7: ROGER RUTGERS TAKEOVER\nRoger greets the Rutgers bus.\n",
            compiled_minds,
            form_store=forms,
            leaving_mode=leaving_mode,
            timing_notes=("Hold half a beat before flipping the excuse.",),
            full_story=False,
            require_named_splits=require_named_splits,
        )
        prompt = (
            "Write ONLY Scenes 4 to 6 at full vivid, expanded script-novel scale (`### SCENE 4`, `### SCENE 5A` or `### SCENE 5`, `### SCENE 6`; "
            "plain `Speaker: line` cues + rich comedic and sensory staging; NO markdown fences, NO commentary, vary short/long sentences).\n"
            "Continuity: Ling household, Jeff is boyfriend, NO Shocker, NEVER bare `Peter:` (always `Rainee Peter Griffen:`). "
            "Francine is still upstairs in the house and Nurse Franny is Francine's own morph (Francine NEVER calls out to Nurse Franny as a separate person).\n"
            "Strict Causal Beat Order:\n"
            "1. `### SCENE 4: THE THREE LITTLE BITCHES`: Behind the door Rainee farts and splits into `Rainee Sade` (Rainee 1, Frame Setter), "
            "`Rainee Becky` (Rainee 2, Alliance Keeper), and `Rainee Clarie` (Rainee 3, Literal Interrupter), who roast Haley mercilessly. "
            + split_names_req +
            "Regular `Francine:` steps in by voice alone and puts them back together into one `Rainee:`. Rainee then swells and transforms into `Rainee Peter Griffen:`; "
            "Francine laughs and shifts into her own `Nurse Franny:` morph. `Rainee Peter Griffen:` rips a massive fart blast sending Haley down the hall (fart blast #1), then destabilizes back into "
            "Rainee Sade, Rainee Becky, and Rainee Clarie. Together they rip a second fart blast of `tuberose`, `orange`, and `sandalwood` hitting Haley farther down the hall, "
            "followed by a sharp 3-voice roast and a quick Haley comeback.\n"
            f"2. {leaving_req}\n\n"
            "GRAPH MINDS:\n"
            f"{middle_packet['writer_brief']}"
        )
    else:
        opening_loop = None
        middle_packet = packet
        generated_opening = ""
        prompt = (
            "Write the replacement text ONLY for the editable Scene 4 + Alternative Leaving slot in plain text script format "
            "(zero markdown code fences, zero preamble).\n"
            "You MUST include:\n"
            "1. Heading `### SCENE 4: THE THREE LITTLE BITCHES`.\n"
            "2. Behind the bathroom door, Rainee first splits into three manifestations (`Rainee 1` Rainee Sade, `Rainee 2` Rainee Becky, `Rainee 3` Rainee Clarie), "
            "each taking a sharp turn shaped by her attached Mean-Girls-derived Digital Mind.\n"
            "3. " + split_names_req +
            "4. Regular `Francine:` steps in by voice alone (NO nurse form yet, NO Shocker prop) and reunites them into one Rainee.\n"
            "5. Rainee swells into `Rainee Peter Griffen:` (NEVER bare `Peter:` or `she was Peter`). Francine laughs, asks her "
            "spouse for Nurse Franny, `Nurse Franny:` appears, and `Rainee Peter Griffen:` unleashes a massive fart blast sending Haley down the hall.\n"
            "6. Rainee Peter Griffen immediately destabilizes back into the same Three Little Bitches (Rainee Sade, Rainee Becky, Rainee Clarie).\n"
            "7. Together they rip a second fart blast smelling of `tuberose`, `orange`, and `sandalwood` that farts their bitch daughter Haley "
            "farther down the hall, followed by their three-voice roast and a quick Haley comeback.\n"
            f"8. {leaving_req}\n\n"
            "GRAPH CONTEXT & ACTIVE MINDS:\n"
            f"{packet['writer_brief']}"
        )

    provider = _make_gemini_provider(
        session_handler=session_handler,
        max_calls=max_calls,
        ledger=root / "gemini_driver_usage.jsonl",
        recovery_scope=f"spring-alt-{leaving_mode}",
    )

    def _control(cand_text: str) -> Dict[str, Any]:
        return control_candidate_output(
            cand_text,
            episode_id="spring-break",
            branch="main",
            beat=0,
            extra_validators=[lambda txt: validate_alternate_spring_candidate(txt, middle_packet)["issues"]],
        )

    if full_story and isinstance(cached_entry.get("middle"), dict) and cached_entry["middle"].get("accepted"):
        loop_result = cached_entry["middle"]
    else:
        loop_result = generate_controlled_prose(
            provider,
            prompt,
            control_fn=_control,
            strategy="gemini_spring_alt",
            project_id=tl.scope()["project_id"],
            document_id=ep_id,
            base_revision=nb_state["timeline_revision"],
            target_span_id="scene4-slot",
        )
        if full_story and loop_result["accepted"]:
            stages_cache[stage_key] = {**cached_entry, "middle": loop_result}
            cache_path.write_text(json.dumps(stages_cache, indent=2, ensure_ascii=False), encoding="utf-8")
            cached_entry = stages_cache[stage_key]
    closing_loop = None
    generated_closing = ""
    if full_story and loop_result["accepted"]:
        closing_prompt = (
            "Write ONLY Scene 7 at full vivid script-novel scale (heading `### SCENE 7: ROGER'S RUTGERS SPRING BREAK TAKEOVER`; "
            "plain `Speaker: line` cues + vivid action; NO markdown fences, NO commentary, vary short/long sentences).\n"
            "Continuity: Ling family, Jeff is boyfriend.\n"
            "Beats: Outside on the driveway (`EXT. LING HOUSE - DRIVEWAY / LAWN`), `Roger:` in a spiky bleached-blonde wig shoves backpacks at `Haley:` and `Stella:` "
            "pitching a freeway motel ('They'll buy you jewelry!'). Haley and Stella refuse. Roger pulls out a purple ermine cape, gold scepter, and megaphone as a `RUTGERS!` "
            "Spring Break charter bus screeches up and students swarm in grabbing VIP goody bags from a `Frat Guy:`.\n"
        )
        closing_provider = _make_gemini_provider(
            session_handler=session_handler,
            max_calls=max_calls,
            ledger=root / "gemini_closing_usage.jsonl",
            recovery_scope=f"spring-alt-{leaving_mode}-close",
        )

        def _control_closing(cand_text: str) -> Dict[str, Any]:
            def _check_close(txt: str) -> List[str]:
                errs: List[str] = []
                if not re.search(r"###\s+SCENE\s+7\b", txt, re.IGNORECASE):
                    errs.append("Closing scene must include heading `### SCENE 7`.")
                low_c = txt.casefold()
                for req_tok in ("roger", "rutgers", "haley", "stella"):
                    if req_tok not in low_c:
                        errs.append(f"Closing Scene 7 must include {req_tok.title()}.")
                return errs

            return control_candidate_output(
                cand_text,
                episode_id="spring-break",
                branch="main",
                beat=0,
                extra_validators=[_check_close],
            )

        if isinstance(cached_entry.get("closing"), dict) and cached_entry["closing"].get("accepted"):
            closing_loop = cached_entry["closing"]
        else:
            closing_loop = generate_controlled_prose(
                closing_provider,
                closing_prompt,
                control_fn=_control_closing,
                strategy="gemini_spring_closing",
                project_id=tl.scope()["project_id"],
                document_id=ep_id,
                base_revision=nb_state["timeline_revision"],
                target_span_id="scene-7",
            )
            if closing_loop["accepted"]:
                stages_cache[stage_key] = {**cached_entry, "closing": closing_loop}
                cache_path.write_text(json.dumps(stages_cache, indent=2, ensure_ascii=False), encoding="utf-8")
        if closing_loop["accepted"]:
            generated_closing = "\n\n" + closing_loop["text"].lstrip()

    history_check = None
    graph_result = None
    scoped_validation = None
    final_notebook = nb_state
    all_accepted = loop_result["accepted"] and (not full_story or (closing_loop is not None and closing_loop["accepted"]))

    if all_accepted and apply_to_notebook:
        assembled = (generated_opening + loop_result["text"].rstrip() + generated_closing) if full_story else (prefix + loop_result["text"] + suffix)
        if full_story:
            idx = assembled.index(PERFUME_LINE)
            cur_text = joined(nb_state["blocks"])
            close_pos = cur_text.index("[CLOSING SLOT]")
            step1 = nb_store.edit_text(
                ep_id,
                nb_state["revision"],
                nb_state["timeline_revision"],
                close_pos,
                close_pos + len("[CLOSING SLOT]"),
                assembled[idx + len(PERFUME_LINE) :].lstrip("\n"),
            )
            step1_text = joined(step1["blocks"])
            open_end = step1_text.index(PERFUME_LINE)
            # Replace opening up to locked PERFUME_LINE plus single gap before closing split cleanly.
            saved = nb_store.edit_text(
                ep_id,
                step1["revision"],
                step1["timeline_revision"],
                0,
                open_end,
                assembled[:idx],
            )
            # Repair exact spacing right after PERFUME_LINE if stripped above:
            cur_after = joined(saved["blocks"])
            if cur_after != assembled:
                after_start = idx + len(PERFUME_LINE)
                saved = nb_store.edit_text(
                    ep_id,
                    saved["revision"],
                    saved["timeline_revision"],
                    after_start,
                    len(cur_after),
                    assembled[after_start:],
                )
            undo_count = 0
            cur_u = saved
            while joined(cur_u["blocks"]) != slot_placeholder and undo_count < 5:
                cur_u = nb_store.undo(ep_id, cur_u["revision"], cur_u["timeline_revision"])
                undo_count += 1
            undone = cur_u
            redone = cur_u
            for _ in range(undo_count):
                redone = nb_store.redo(ep_id, redone["revision"], redone["timeline_revision"])
        else:
            saved = nb_store.save_document(ep_id, nb_state["revision"], nb_state["timeline_revision"], assembled, None)
            undone = nb_store.undo(ep_id, saved["revision"], saved["timeline_revision"])
            redone = nb_store.redo(ep_id, undone["revision"], undone["timeline_revision"])
        final_notebook = redone
        re_check = validate_alternate_spring_candidate(assembled if full_story else loop_result["text"], packet)
        graph_result = cook_with_character_graph_synthesis(tl, forms, ep_id)
        nb_after_cook = nb_store.existing(ep_id)
        scoped_raw = execute_scoped(
            tl,
            "validate",
            {
                "episode": ep_id,
                "beat": 1,
                "revision": nb_after_cook["timeline_revision"],
                "start": 0,
                "end": len(assembled),
                "text": assembled,
                "semantic_review": True,
            },
            junctions=j_supplier,
        )
        scoped_validation = {
            "issues": scoped_raw["issues"],
            "semantic_review": scoped_raw["semantic_review"],
            "suggested_corrections": scoped_raw["suggested_corrections"],
        }
        if out_story is not None:
            out_path = Path(out_story)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(assembled, encoding="utf-8")
        history_check = {
            "applied_revision": saved["revision"],
            "cook_revision": nb_after_cook["revision"],
            "undone_restored_placeholder": slot_placeholder[:80] in joined(undone["blocks"]),
            "redone_matches_assembled": joined(redone["blocks"]) == assembled,
            "haley_lock_preserved": PERFUME_LINE in joined(redone["blocks"]),
            "roger_suffix_preserved": ("Roger" in joined(redone["blocks"]) and "Rutgers" in joined(redone["blocks"])) if full_story else joined(redone["blocks"]).endswith(suffix),
            "post_apply_valid": re_check["valid"],
        }
        final_notebook = nb_after_cook

    full_output = (generated_opening + loop_result["text"].rstrip() + generated_closing) if (full_story and all_accepted) else loop_result["text"]
    total_calls = (
        loop_result["provider_calls"]
        + (opening_loop["provider_calls"] if opening_loop else 0)
        + (closing_loop["provider_calls"] if closing_loop else 0)
    )
    final_status = "PASSED" if all_accepted else ("BLOCKED" if (closing_loop and not closing_loop["accepted"]) else loop_result["status"])
    return {
        "mode": "spring-alternate",
        "leaving_mode": leaving_mode,
        "full_story": full_story,
        "require_named_splits": require_named_splits,
        "status": final_status,
        "accepted": all_accepted,
        "provider_calls": total_calls,
        "opening_calls": opening_loop["provider_calls"] if opening_loop else 0,
        "closing_calls": closing_loop["provider_calls"] if closing_loop else 0,
        "attempt_ids": ([
            *(opening_loop["attempt_ids"] if opening_loop else ()),
            *loop_result["attempt_ids"],
            *(closing_loop["attempt_ids"] if closing_loop else ()),
        ]),
        "turns": loop_result["turns"],
        "opening_turns": opening_loop["turns"] if opening_loop else [],
        "closing_turns": closing_loop["turns"] if closing_loop else [],
        "mean_girls_minds": {
            "admitted_window_count": compiled_minds["admitted_window_count"],
            "srt_cue_count": compiled_minds["srt_cue_count"],
            "quarantined_or_rejected": compiled_minds["quarantined_or_rejected"],
            "attached_ports": graph_attach["attached"],
        },
        "text": full_output,
        "assembled_text": full_output if (full_story and all_accepted) else ((prefix + loop_result["text"] + suffix) if all_accepted else loop_result["text"]),
        "verdict": loop_result["verdict"],
        "opening_verdict": opening_loop["verdict"] if opening_loop else None,
        "closing_verdict": closing_loop["verdict"] if closing_loop else None,
        "graph_result": graph_result,
        "scoped_validation": scoped_validation,
        "history_check": history_check,
        "notebook_revision": final_notebook["revision"],
    }


def drive_gemini_tapped_out_rewrite(
    workspace: Path,
    *,
    seed_script: Optional[str] = None,
    session_handler: Optional[Callable[[str], str]] = None,
    max_calls: int = 2,
    apply_to_notebook: bool = True,
) -> Dict[str, Any]:
    """Drive Tapped Out rewrite via gemini-session, control output, then smart-sync existing/new characters & Stella forms."""
    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    tl = TimelineStore(root / "timeline.sqlite")
    forms = FormGraphStore(root / "forms.sqlite")
    if not tl.cards():
        tl.add_starter_cards()

    ep_id = "tapped-out"
    initial_script = seed_script or (
        "INT. STUDIO CORRIDOR - DAY\n\n"
        "Haley waits beside the lighting rig.\n"
        "Stella adjusts her canary-yellow polo while Francine and Rainee confer by the console.\n"
    )
    cur_ep = tl.get_episode(ep_id)
    if not cur_ep or not cur_ep.get("script") or seed_script is not None:
        tl.save(ep_id, cur_ep["head"] if cur_ep else 0, script=initial_script, source_name="tapped-out-driver-seed")
    nb_store = NotebookStore(tl)
    nb_state = nb_store.open(ep_id)
    nb_state = nb_store.save(ep_id, nb_state["revision"], nb_state["timeline_revision"], nb_state["blocks"], 50, [])

    existing_chars = [g["character_id"] for g in forms.read()["junctions"]]
    prompt = (
        "Rewrite this Tapped Out scene in plain screenplay cue format (`Speaker: line` + short action lines; "
        "NO markdown fences, NO commentary).\n"
        f"Existing characters already on the graph: {', '.join(existing_chars)}.\n"
        "Requirements:\n"
        "1. Reuse `Francine:`, `Haley:`, and `Stella:` cleanly.\n"
        "2. Trigger Stella's transformation into Big Tiddy Steve (`Stella transforms into Big Tiddy Steve` in her canary-yellow polo) "
        "and give `STELLA (Big Tiddy Steve):` at least two speaking turns.\n"
        "3. Introduce new studio boss character `Holly:` (`Holly Graham`) into the scene with speaking dialogue.\n"
        "4. Stay faithful to AFM continuity (surname is Ling, not Smith; Haley is married to Jeff in Tapped Out).\n\n"
        "SEED SCENE:\n"
        f"{joined(nb_state['blocks'])}"
    )

    provider = _make_gemini_provider(
        session_handler=session_handler,
        max_calls=max_calls,
        ledger=root / "gemini_driver_usage.jsonl",
        recovery_scope="tapped-out-rewrite",
    )

    def _check_tapped(txt: str) -> List[str]:
        issues: List[str] = []
        low = txt.casefold()
        if "holly:" not in low and "holly graham" not in low:
            issues.append("Rewrite must introduce Holly / Holly Graham.")
        if "big tiddy steve" not in low:
            issues.append("Rewrite must stage Stella's Big Tiddy Steve transformation.")
        if "stella" not in low and "francine" not in low and "haley" not in low:
            issues.append("Rewrite must reuse existing characters from the graph.")
        return issues

    def _control(cand_text: str) -> Dict[str, Any]:
        return control_candidate_output(
            cand_text,
            episode_id="tapped-out",
            branch="main",
            beat=0,
            extra_validators=[_check_tapped],
        )

    loop_result = generate_controlled_prose(
        provider,
        prompt,
        control_fn=_control,
        strategy="gemini_tapped_out",
        project_id=tl.scope()["project_id"],
        document_id=ep_id,
        base_revision=nb_state["timeline_revision"],
        target_span_id="tapped-out-rewrite",
    )
    graph_result = None
    history_check = None

    if loop_result["accepted"] and apply_to_notebook:
        saved = nb_store.save_document(ep_id, nb_state["revision"], nb_state["timeline_revision"], loop_result["text"], None)
        graph_result = cook_with_character_graph_synthesis(tl, forms, ep_id)
        nb_after_cook = nb_store.existing(ep_id)
        # Undo past cook structure revision (if added) and document save back to initial seed, then redo back.
        cur = nb_after_cook
        undo_steps = 0
        while joined(cur["blocks"]) != initial_script and undo_steps < 3:
            cur = nb_store.undo(ep_id, cur["revision"], cur["timeline_revision"])
            undo_steps += 1
        undone = cur
        redone = cur
        for _ in range(undo_steps):
            redone = nb_store.redo(ep_id, redone["revision"], redone["timeline_revision"])
        # Run an idempotent second synthesis check to prove Holly and Stella are reused, never duplicated!
        second_sync = synthesize_character_graph_for_script(joined(redone["blocks"]), form_store=forms)
        history_check = {
            "saved_revision": saved["revision"],
            "cook_revision": nb_after_cook["revision"],
            "undo_restored_seed": joined(undone["blocks"]) == initial_script,
            "redo_restored_rewrite": joined(redone["blocks"]) == loop_result["text"],
            "second_pass_added_characters": second_sync["added_characters"],
            "second_pass_reused_characters": second_sync["reused_characters"],
        }

    return {
        "mode": "tapped-out",
        "status": loop_result["status"],
        "accepted": loop_result["accepted"],
        "provider_calls": loop_result["provider_calls"],
        "attempt_ids": loop_result["attempt_ids"],
        "turns": loop_result["turns"],
        "text": loop_result["text"],
        "verdict": loop_result["verdict"],
        "graph_result": graph_result,
        "history_check": history_check,
    }


def _detect_intake_workflow(prompt: str, source_text: str, explicit: Optional[str] = None) -> str:
    mode = str(explicit or "auto").strip().casefold()
    if mode in ("spring-alternate", "tapped-out", "rewrite"):
        return mode
    combined = f"{prompt}\n{source_text}".casefold()
    if any(tok in combined for tok in ("three little bitches", "sade", "becky", "clarie", "mean girls", "spring break", "rainee split")):
        return "spring-alternate"
    if any(tok in combined for tok in ("tapped out", "big tiddy steve", "holly graham", "holly:")):
        return "tapped-out"
    return "rewrite"


def _authorize_spring_forms(tl: TimelineStore, forms: FormGraphStore, ep_id: str) -> None:
    j_map = {g["character_id"]: CharacterJunction.from_record(g) for g in forms.read()["junctions"]}
    existing_evs = {ev["id"] for ev in tl.episode_events(ep_id)}
    for idx, (cid, fid) in enumerate((
        ("rainee", "rainee-split-1"),
        ("rainee", "rainee-split-2"),
        ("rainee", "rainee-split-3"),
        ("rainee", "peter_griffin_celestial_variant"),
        ("francine", "nurse_pamela_franny_anderson"),
        ("roger", "mtv_beach_host"),
        ("roger", "rutgers_royal_persona"),
    )):
        if cid in j_map and any(f.id == fid for f in j_map[cid].forms):
            ev_id = f"form-unlock-{ep_id}-{idx}"
            if ev_id not in existing_evs:
                tl.add_event(ev_id, ep_id, 0, f"Authorized form {fid} for {cid}.", status="draft", permitted=True, source_id="intake-launch")
                tl.bind_form_event(ep_id, ev_id, cid, fid, "available", j_map)
                tl.review_event(ep_id, ev_id, "Author", "intake-launch", True)


def _director_log_path(timeline: TimelineStore, ep_id: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(ep_id))[:80] or "episode"
    return Path(timeline.path).parent / "ai_director_logs" / f"{safe_id}.json"


def get_intake_director_history(timeline: TimelineStore, ep_id: str) -> Dict[str, Any]:
    """Return persistent conversational turns + system execution traces for an episode."""
    path = _director_log_path(timeline, ep_id)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("entries"), list):
                return {"episode": ep_id, "entries": data["entries"]}
        except Exception:
            pass
    return {"episode": ep_id, "entries": []}


def _append_director_history(timeline: TimelineStore, ep_id: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    path = _director_log_path(timeline, ep_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    current = get_intake_director_history(timeline, ep_id)
    entries = [*current["entries"], entry][-30:]
    payload = {"episode": ep_id, "entries": entries}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


DEFAULT_FART_MEDIA_INDEX = (
    Path(__file__).resolve().parents[1]
    / "deliverables"
    / "NOIR_FX06_GAG_COLLECTION_20261116"
    / "Fart Media"
    / "episode_index.json"
)


def _load_fart_media_timing_notes(limit: int = 3) -> Tuple[str, ...]:
    """Load real pacing/timing cues from Fart Media catalog when present on disk."""
    if not DEFAULT_FART_MEDIA_INDEX.is_file():
        return (
            "Right after coming downstairs from the bathroom, let Rainee's stomach warning land half a beat before she splits.",
            "Keep the first Peter blast punchy with delayed comic reaction before Francine turns into Nurse Franny.",
            "Let the second triple-scent blast stagger three distinct beats (tuberose, orange, sandalwood) before the 3-voice roast.",
        )
    try:
        rows = json.loads(DEFAULT_FART_MEDIA_INDEX.read_text(encoding="utf-8")).get("rows", ())
    except (OSError, ValueError):
        return ()
    notes: List[str] = []
    for row in rows:
        if row.get("writing_eligible") and isinstance(row.get("timing"), str) and row["timing"].strip():
            title = str(row.get("title") or row.get("id") or "clip").strip()
            notes.append(f"[{title}] {row['timing'].strip()}")
            if len(notes) >= limit:
                break
    return tuple(notes)


def _retrieve_hybrid_book_craft(
    timeline: TimelineStore,
    episode_id: str,
    query_text: str,
    *,
    backend: str = "hybrid",
    provider: str = "gemini-session",
    scene_function: str = "comedy",
    books_root: Optional[Path] = None,
) -> Tuple[str, List[Dict[str, Any]], str]:
    """Retrieve real craft excerpts from the 190-book library (hybrid style+luar+topic) + voice_card.md."""
    from .scoped_references import DEFAULT_BOOKS, ReferenceUnavailable, select_references

    root = Path(books_root) if books_root is not None else DEFAULT_BOOKS
    voice_card_text = ""
    vc_path = root / "voice_card.md"
    if vc_path.is_file():
        voice_card_text = vc_path.read_text(encoding="utf-8", errors="ignore").strip()[:1800]

    if backend == "none":
        block = f"VOICE CARD:\n{voice_card_text}\n\n" if voice_card_text else ""
        return block, [], "disabled"

    scope = timeline.scope()
    base_query = (query_text or "").strip()[:2400] or "vivid comedic character scene"
    if scene_function == "comedy":
        base_query += "\ncomedic fart slapstick escalation sharp banter vivid physical reactions"
    pkt_stub = SimpleNamespace(
        context=SimpleNamespace(project_id=scope["project_id"], universe_id=scope["universe_id"]),
        target=base_query,
        continuation=None,
        hidden_phrases=(),
    )
    try:
        bundle = select_references(
            pkt_stub,
            root=root,
            backend=backend,
            provider=provider,
            scene_function=scene_function,
        )
    except (ReferenceUnavailable, ValueError, OSError) as exc:
        block = f"VOICE CARD:\n{voice_card_text}\n\n" if voice_card_text else ""
        return block, [], f"unavailable: {exc}"

    parts: List[str] = []
    if voice_card_text:
        parts.append("VOICE CARD (craft style rules):\n" + voice_card_text)
    if bundle["texts"]:
        ex_lines = [
            f"ELIGIBLE 190-BOOK CRAFT EXCERPTS ({backend}; draw freely on their rhythm, sensory texture, slapstick/fart timing, and vivid non-robotic phrasing — break repetitive AI sentence patterns and expand physical staging):"
        ]
        for text, rec in zip(bundle["texts"], bundle["receipts"]):
            tag = rec.get("hybrid_backend") or backend
            genre = rec.get("source_genre") or ""
            title = rec.get("source_title") or rec.get("source_id") or "book"
            use = rec.get("prose_usefulness") or ""
            label = f"{tag} | {genre} | {title}" if genre else f"{tag} | {title}"
            hint = f" ({use})" if use else ""
            ex_lines.append(f"- [{label}]{hint} {text[:1350]}")
        parts.append("\n".join(ex_lines))
    return ("\n\n".join(parts) + "\n\n") if parts else "", list(bundle["receipts"]), "ready"


def plan_episode_from_intake(
    timeline: TimelineStore,
    form_store: Optional[FormGraphStore],
    request: Dict[str, Any],
    *,
    books_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Read-only Chat/Plan mode for Studio AI Director: inspects beats, locks, character-node data, and 190-book excerpts without modifying the notebook."""
    ep_id = request["episode"]
    ep = timeline.get_episode(ep_id)
    if not ep:
        raise ValueError("Open or create an episode before planning.")
    forms = form_store or FormGraphStore(Path(timeline.path).parent / "forms.sqlite")
    nb_store = NotebookStore(timeline)
    nb_state = nb_store.existing(ep_id) or nb_store.open(ep_id)
    source_text = joined(nb_state["blocks"])
    attachment_text = str(request.get("attachment_text") or "").strip()
    attachment_name = str(request.get("attachment_name") or "").strip()

    from .intake import saved_brief
    with timeline._connect() as c:
        brief_row = saved_brief(c, ep_id) or {}
    user_prompt = str(request.get("prompt") or brief_row.get("prompt") or "").strip()
    writer_name = str(request.get("provider") or brief_row.get("provider") or "gemini-session").strip()
    references_backend = str(request.get("references") or "hybrid").strip()
    craft_mode = str(request.get("craft_mode") or "expand").strip()
    workflow_mode = _detect_intake_workflow(user_prompt, f"{source_text}\n{attachment_text}", request.get("workflow_mode"))
    leaving_mode = "relapse" if "relapse" in user_prompt.casefold() and "clothes" not in user_prompt.casefold() else "clothes"
    require_named = any(k in f"{user_prompt}\n{source_text[:1500]}".casefold() for k in ("sade", "becky", "clarie", "three little bitches"))

    hard_locks = [
        {"id": m.get("id"), "start": m["start"], "end": m["end"], "text": source_text[m["start"]:m["end"]][:160]}
        for m in nb_state.get("masks", ())
        if m.get("hard")
    ]
    existing_chars = [g["character_id"] for g in forms.read()["junctions"]]
    beat_plan: List[Dict[str, Any]] = []
    if workflow_mode == "spring-alternate":
        scent_rules = json.loads(DEFAULT_SCENT_PATH.read_text(encoding="utf-8")) if DEFAULT_SCENT_PATH.is_file() else None
        minds = build_three_little_bitches_minds(scent_rules=scent_rules, include_movie_dir=True)
        has_slots = "### SCENE 4:" in source_text and "### SCENE 7:" in source_text
        if has_slots:
            s4_i, s7_i = source_text.index("### SCENE 4:"), source_text.index("### SCENE 7:")
            pkt = build_alternate_spring_packet(
                source_text[:s4_i],
                source_text[s4_i:s7_i],
                source_text[s7_i:],
                minds,
                form_store=forms,
                leaving_mode=leaving_mode,
                sequence_mode="downstairs_peter_split",
                timing_notes=_load_fart_media_timing_notes(),
                full_story=False,
                require_named_splits=require_named,
            )
        else:
            pkt = build_alternate_spring_packet(
                f"INT. HALL - MORNING\nHaley: {PERFUME_LINE}\n\n",
                "[EDITABLE]",
                "\n\n### SCENE 7: ROGER RUTGERS TAKEOVER\nRoger steps into the sun.\n",
                minds,
                form_store=forms,
                leaving_mode=leaving_mode,
                sequence_mode="downstairs_peter_split",
                timing_notes=_load_fart_media_timing_notes(),
                full_story=True,
                require_named_splits=require_named,
            )
        beat_plan = list(pkt["beats"])

    query_for_books = f"{user_prompt}\n{source_text[:2000]}"
    _, ref_receipts, ref_status = _retrieve_hybrid_book_craft(
        timeline,
        ep_id,
        query_for_books,
        backend=references_backend,
        provider=writer_name,
        scene_function="comedy" if workflow_mode == "spring-alternate" else "scene",
        books_root=books_root,
    )
    system_steps = [
        f"PLAN ONLY (Read-Only · 0 notebook writes) · Workflow: {workflow_mode} · Craft: {craft_mode}",
        f"190-Book Retrieval ({references_backend}): {ref_status} ({len(ref_receipts)} passages)",
        f"Character Graph Nodes: {len(existing_chars)} · Hard-Locked Spans: {len(hard_locks)}",
    ]
    top_titles = ", ".join(dict.fromkeys(r.get("source_title") or r.get("source_id", "") for r in ref_receipts[:4]))
    ai_summary = (
        f"Ready to {craft_mode} ({len(source_text.split())} source words, {len(hard_locks)} exact locks preserved, "
        f"{len(beat_plan)} causal beats). "
        + (f"Retrieved {len(ref_receipts)} craft passages from: {top_titles}." if ref_receipts else f"Book retrieval status: {ref_status}.")
        + " Click Run & Expand when you want to execute."
    )
    history = _append_director_history(
        timeline,
        ep_id,
        {
            "user_prompt": user_prompt or "(plan request)",
            "attachment": attachment_name or None,
            "workflow_mode": workflow_mode,
            "provider": writer_name,
            "status": "PLANNED",
            "accepted": True,
            "read_only": True,
            "system_steps": system_steps,
            "ai_summary": ai_summary,
            "notebook_revision": nb_state["revision"],
        },
    )
    return {
        "status": "PLANNED",
        "read_only": True,
        "episode": ep_id,
        "workflow_mode": workflow_mode,
        "craft_mode": craft_mode,
        "references_backend": references_backend,
        "reference_status": ref_status,
        "reference_receipts": ref_receipts,
        "source_words": len(source_text.split()),
        "protected_locks": hard_locks,
        "character_nodes": existing_chars,
        "beat_plan": beat_plan,
        "system_steps": system_steps,
        "ai_summary": ai_summary,
        "director_history": history["entries"],
    }


def drive_episode_from_intake(
    timeline: TimelineStore,
    form_store: Optional[FormGraphStore],
    request: Dict[str, Any],
    *,
    provider_factory: Optional[Callable[[], Any]] = None,
    session_handler: Optional[Callable[[str], str]] = None,
    max_calls: int = 2,
    books_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run the full Noir + Gemini closed-loop system on an episode with persistent multi-turn AI dialogue."""
    ep_id = request["episode"]
    ep = timeline.get_episode(ep_id)
    if not ep:
        raise ValueError("Open or create an episode before launching the pipeline.")
    forms = form_store or FormGraphStore(Path(timeline.path).parent / "forms.sqlite")
    nb_store = NotebookStore(timeline)
    nb_state = nb_store.existing(ep_id) or nb_store.open(ep_id)
    source_text = joined(nb_state["blocks"])
    attachment_text = str(request.get("attachment_text") or "").strip()
    attachment_name = str(request.get("attachment_name") or "").strip()

    from .intake import saved_brief
    with timeline._connect() as c:
        brief_row = saved_brief(c, ep_id) or {}
    user_prompt = str(request.get("prompt") or brief_row.get("prompt") or "").strip()
    writer_name = str(request.get("provider") or brief_row.get("provider") or "gemini-session").strip()
    references_backend = str(request.get("references") or "hybrid").strip()
    craft_mode = str(request.get("craft_mode") or "expand").strip()
    workflow_mode = _detect_intake_workflow(user_prompt, f"{source_text}\n{attachment_text}", request.get("workflow_mode"))
    leaving_mode = "relapse" if "relapse" in user_prompt.casefold() and "clothes" not in user_prompt.casefold() else "clothes"
    require_named = any(k in f"{user_prompt}\n{source_text[:1500]}".casefold() for k in ("sade", "becky", "clarie", "three little bitches"))

    prior_history = get_intake_director_history(timeline, ep_id)["entries"]
    convo_block = ""
    if prior_history:
        recent = prior_history[-4:]
        lines = []
        for item in recent:
            lines.append(f"USER: {item.get('user_prompt', '')}")
            lines.append(f"SYSTEM TRACE: {'; '.join(item.get('system_steps', ()))}" )
            if item.get("ai_summary"):
                lines.append(f"AI: {item['ai_summary']}")
        convo_block = "CONVERSATION SO FAR WITH USER:\n" + "\n".join(lines) + "\n\n"
    if attachment_text:
        convo_block += f"NEW DROPPED REFERENCE ({attachment_name or 'attachment'}):\n{attachment_text[:4000]}\n\n"

    craft_block, ref_receipts, ref_status = _retrieve_hybrid_book_craft(
        timeline,
        ep_id,
        f"{user_prompt}\n{source_text[:2500]}",
        backend=references_backend,
        provider=writer_name,
        scene_function="comedy" if workflow_mode == "spring-alternate" else "scene",
        books_root=books_root,
    )

    if session_handler is None and provider_factory is not None:
        custom = provider_factory()
        session_handler = lambda p: custom.generate_rewrite(SimpleNamespace(request_id=uuid4().hex), p)
    elif session_handler is None:
        bridge_name = "codex" if writer_name.startswith("codex") else "gemini"
        session_handler = load_isolated_composer_bridge(bridge_name)

    ledger = Path(timeline.path).parent / "gemini_intake_usage.jsonl"
    provider_kind = "codex" if writer_name.startswith("codex") else "gemini"
    provider = PrimarySessionProvider(
        provider_kind,
        session_handler=session_handler,
        max_calls=max(1, min(int(max_calls), 4)),
        ledger=ledger,
        job_id=f"intake-{uuid4().hex[:12]}",
        recovery_scope=f"intake-{ep_id}",
        max_prompt_bytes=48_000,
    )

    extra_validators: List[Callable[[str], Sequence[str]]] = []
    if workflow_mode == "spring-alternate":
        scent_rules = json.loads(DEFAULT_SCENT_PATH.read_text(encoding="utf-8")) if DEFAULT_SCENT_PATH.is_file() else None
        minds = build_three_little_bitches_minds(scent_rules=scent_rules, include_movie_dir=True)
        attach_mean_girls_minds_to_form_graph(forms, minds)
        _authorize_spring_forms(timeline, forms, ep_id)
        timing_notes = _load_fart_media_timing_notes()
        slot_rewrite = "### SCENE 4:" in source_text and "### SCENE 7:" in source_text and PERFUME_LINE in source_text[:source_text.index("### SCENE 4:")]
        if slot_rewrite:
            s4_idx = source_text.index("### SCENE 4:")
            s7_idx = source_text.index("### SCENE 7:")
            frozen_prefix = source_text[:s4_idx]
            editable_slot_src = source_text[s4_idx:s7_idx]
            frozen_suffix = source_text[s7_idx:]
            pkt = build_alternate_spring_packet(
                frozen_prefix,
                editable_slot_src,
                frozen_suffix,
                minds,
                form_store=forms,
                leaving_mode=leaving_mode,
                sequence_mode="downstairs_peter_split",
                timing_notes=timing_notes,
                full_story=False,
                require_named_splits=True,
            )
            prompt_text = (
                convo_block
                + craft_block
                + f"AUTHOR PROMPT:\n{user_prompt or 'Rewrite Scenes 4–6 using the downstairs Three-Bitches split -> Reunion -> Rainee Peter Griffen -> Nurse Franny -> Destabilize & repeat gag workflow.'}\n\n"
                "Requirements: Write ONLY replacement Scenes 4, 5, and 6 at full vivid script-novel scale (~1,200–1,600 words across Scenes 4–6; `### SCENE 4:`, `### SCENE 5:`, `### SCENE 6:`; "
                "pure story prose and `Speaker: line` cues with NO preamble commentary and NO markdown fences; vary sentence lengths rhythmically). "
                "Do NOT repeat Scenes 1–3, do NOT repeat Haley's Scene 3 flower-shop line, do NOT mention Dad/Stan, and do NOT write Scene 7 — Scenes 1–3 and 7 are frozen verbatim. Keep `### SCENE 4: THE THREE LITTLE BITCHES` as the Scene 4 title.\n"
                "Exact Downstairs Causal Order:\n"
                "1. Right after the bathroom scene, Rainee comes downstairs into the living room (`INT. LING HOUSE - STAIRCASE & LIVING ROOM`), and at the point she would turn into Peter, she farts and splits into `Rainee Sade`, `Rainee Becky`, and `Rainee Clarie` (Mean Girls mind attached to Peter's transformation hub) and they roast Haley.\n"
                "2. Regular `Francine:` puts them back together into one `Rainee:`.\n"
                "3. Reunited `Rainee:` turns into `Rainee Peter Griffen:` briefly, then farts and blows Haley away across the living room.\n"
                "4. AFTER Haley is blown away, `Francine:` turns into `Nurse Franny:` via `Rainee Peter Griffen:`'s powers (finger-guns / nanites).\n"
                "5. THEN `Rainee Peter Griffen:` destabilizes back into `Rainee Sade`, `Rainee Becky`, and `Rainee Clarie` from another fart (`tuberose`, `orange`, `sandalwood`), repeating the gag and blowing Haley around + delivering a Mean Girls 3-voice roast, then leaving with Nurse Franny (keys, three lasagna trays, red sedan"
                + (" & red overnight bag/clothes" if leaving_mode == "clothes" else "")
                + ").\n\n"
                f"ACTIVE MINDS (STORED IN PETER GRIFFIN HUB + SPLIT NODES):\n{pkt['writer_brief']}\n\n"
                f"ORIGINAL SCENES 4–6 (baseline length & comedic scale to expand upon):\n{editable_slot_src}"
            )
        else:
            prefix_ref = f"INT. HALL - MORNING\nHaley: {PERFUME_LINE}\n\n"
            suffix_ref = "\n\n### SCENE 7: ROGER RUTGERS TAKEOVER\nRoger steps into the sun.\n"
            pkt = build_alternate_spring_packet(
                prefix_ref,
                "[EDITABLE]",
                suffix_ref,
                minds,
                form_store=forms,
                leaving_mode=leaving_mode,
                sequence_mode="downstairs_peter_split",
                timing_notes=timing_notes,
                full_story=True,
                require_named_splits=require_named,
            )
            prompt_text = (
                convo_block
                + craft_block
                + f"AUTHOR PROMPT:\n{user_prompt or 'Write the alternate Spring Break Three Little Bitches story.'}\n\n"
                "Requirements: Write a rich, vivid, expanded Scenes 1–7 hybrid script-novel (NO condensed summaries; `### SCENE N:` headings + "
                "`Speaker: line` cues; zero markdown fences). Preserve Haley's exact line "
                f"`{PERFUME_LINE}` ONCE in Scene 3. Right after the bathroom scene when Rainee comes downstairs, "
                "Rainee farts and splits into `Rainee Sade`, `Rainee Becky`, `Rainee Clarie` (Mean Girls mind attached on Peter's node) and they roast Haley -> "
                "regular `Francine:` puts them back together into one `Rainee:` -> Rainee turns into `Rainee Peter Griffen:` briefly -> "
                "she farts and blows Haley away -> AFTER that, Francine turns into `Nurse Franny:` via `Rainee Peter Griffen:`'s powers -> "
                "THEN `Rainee Peter Griffen:` destabilizes back into `Rainee Sade`, `Rainee Becky`, `Rainee Clarie` from another fart (`tuberose`, `orange`, `sandalwood`), "
                "repeating the gag and blowing Haley around + 3-voice roast -> "
                f"{'Hallway Tag & Departure (keys + three lasagna trays + red sedan)' if leaving_mode == 'relapse' else 'Clothes overnight bag & Red Sedan (keys + three lasagna trays)'} -> "
                "`### SCENE 7: ROGER'S RUTGERS SPRING BREAK TAKEOVER`.\n\n"
                f"ACTIVE MINDS (STORED IN PETER GRIFFIN HUB + SPLIT NODES):\n{pkt['writer_brief']}\n\n"
                f"DROPPED SOURCE TEXT:\n{source_text[:18000]}"
            )
        extra_validators.append(lambda txt: validate_alternate_spring_candidate(txt, pkt)["issues"])
    elif workflow_mode == "tapped-out":
        pre_sync = synthesize_character_graph_for_script(source_text, form_store=forms) if source_text.strip() else {"reused_characters": [g["character_id"] for g in forms.read()["junctions"]]}
        existing_chars = [g["character_id"] for g in forms.read()["junctions"]]
        prompt_text = (
            convo_block
            + craft_block
            + f"AUTHOR PROMPT:\n{user_prompt or 'Rewrite Tapped Out scene cleanly using existing characters, Holly, and Stella -> Big Tiddy Steve.'}\n\n"
            f"Existing characters on graph: {', '.join(existing_chars)}.\n"
            "Format: plain `Speaker: line` screenplay cues + vivid, expanded action lines (zero markdown fences). "
            "Reuse existing characters cleanly; stage `Stella transforms into Big Tiddy Steve` with `STELLA (Big Tiddy Steve):` cues; introduce `Holly:` (`Holly Graham`).\n\n"
            f"DROPPED SOURCE TEXT:\n{source_text[:18000]}"
        )
        def _chk_tapped(txt: str) -> List[str]:
            low = txt.casefold()
            errs: List[str] = []
            if "holly" not in low:
                errs.append("Must introduce Holly / Holly Graham.")
            if "big tiddy steve" not in low:
                errs.append("Must stage Stella's Big Tiddy Steve transformation.")
            return errs
        extra_validators.append(_chk_tapped)
    else:
        pre_sync = synthesize_character_graph_for_script(source_text, form_store=forms) if source_text.strip() else {"reused_characters": []}
        existing_chars = [g["character_id"] for g in forms.read()["junctions"]]
        prompt_text = (
            convo_block
            + craft_block
            + f"AUTHOR PROMPT:\n{user_prompt or 'Expand and vividly rewrite the unlocked prose using the 190-book craft excerpts and active character-node data.'}\n\n"
            f"Active characters on graph: {', '.join(existing_chars) or 'none yet'}.\n"
            "Format: `### SCENE N:` headings + clean `Speaker: line` cues + vivid, non-robotic expanded prose (zero markdown fences, vary sentence lengths).\n\n"
            f"DROPPED SOURCE TEXT:\n{source_text[:18000]}"
        )

    loop_result = generate_controlled_prose(
        provider,
        prompt_text,
        control_fn=lambda cand: control_candidate_output(
            cand,
            episode_id=ep_id,
            branch=ep["branch"],
            beat=0,
            extra_validators=extra_validators,
        ),
        strategy=f"intake_{workflow_mode}",
        project_id=timeline.scope()["project_id"],
        document_id=ep_id,
        base_revision=nb_state["timeline_revision"],
        target_span_id="intake-full",
    )

    graph_result = None
    scoped_validation = None
    final_nb = nb_state
    if loop_result["accepted"]:
        generated = loop_result["text"]
        if workflow_mode == "spring-alternate" and "### SCENE 4:" in source_text and "### SCENE 7:" in source_text and PERFUME_LINE in source_text[:source_text.index("### SCENE 4:")]:
            s4_i, s7_i = source_text.index("### SCENE 4:"), source_text.index("### SCENE 7:")
            generated = source_text[:s4_i] + generated.strip() + "\n\n" + source_text[s7_i:]
        hard_locks = [m for m in nb_state.get("masks", ()) if m.get("hard")]
        cur_nb = nb_state
        if cur_nb.get("default_protection", 100) >= 75 or any(not m.get("hard") for m in cur_nb.get("masks", ())):
            cur_nb = nb_store.save(
                ep_id,
                cur_nb["revision"],
                cur_nb["timeline_revision"],
                cur_nb["blocks"],
                25,
                hard_locks,
            )
        new_masks = []
        for m in hard_locks:
            snippet = source_text[m["start"] : m["end"]]
            if snippet and snippet in generated:
                pos = generated.index(snippet)
                new_masks.append({**m, "start": pos, "end": pos + len(snippet), "sha256": sha256(snippet.encode("utf-8")).hexdigest()})
            else:
                raise ValueError(f"Generated output must preserve protected range {m.get('id')}.")
        saved = nb_store.save(
            ep_id,
            cur_nb["revision"],
            cur_nb["timeline_revision"],
            [{"id": f"intake-{uuid4().hex[:8]}", "kind": "narrator", "speaker": None, "form": None, "text": generated, "source": None}],
            25,
            new_masks,
        )
        graph_result = cook_with_character_graph_synthesis(timeline, forms, ep_id)
        final_nb = nb_store.existing(ep_id) or saved
        j_supplier = lambda: {g["character_id"]: CharacterJunction.from_record(g) for g in forms.read()["junctions"]}
        try:
            scoped_raw = execute_scoped(
                timeline,
                "validate",
                {
                    "episode": ep_id,
                    "beat": 1 if workflow_mode == "spring-alternate" else 0,
                    "revision": final_nb["timeline_revision"],
                    "start": 0,
                    "end": len(generated),
                    "text": generated,
                    "semantic_review": True,
                },
                junctions=j_supplier,
            )
            scoped_validation = {
                "issues": scoped_raw["issues"],
                "semantic_review": scoped_raw["semantic_review"],
                "suggested_corrections": scoped_raw["suggested_corrections"],
            }
        except ValueError as exc:
            scoped_validation = {
                "issues": [{"reason": f"Scoped validation failed: {exc}"}],
                "semantic_review": None,
                "suggested_corrections": [],
                "error": str(exc),
            }

    slop_score = loop_result["verdict"]["slop_critique"]["slop_score"] if loop_result.get("verdict") else None
    corr_count = len(loop_result["verdict"].get("canon_corrections", ())) if loop_result.get("verdict") else 0
    system_steps: List[str] = [
        f"Workflow: {workflow_mode} · Craft: {craft_mode} · Provider: {writer_name}",
        f"190-Book Retrieval ({references_backend}): {ref_status} ({len(ref_receipts)} passages)",
    ]
    if workflow_mode == "spring-alternate":
        system_steps.append(f"Mean Girls Minds attached ({'named: Sade/Becky/Clarie' if require_named else 'Rainee 1/2/3'}, leaving={leaving_mode})")
    system_steps.append(f"Closed-loop turns: {len(loop_result['turns'])} ({loop_result['provider_calls']} calls) · Canon auto-fixes: {corr_count} · Slop score: {slop_score}")
    if graph_result and graph_result.get("synthesis"):
        syn = graph_result["synthesis"]
        system_steps.append(
            f"Graph & Cook: reused {len(syn.get('reused_characters', ()))}, added {len(syn.get('added_characters', ()))}, unresolved {graph_result['cook']['stage2']['unresolved_blocks']}"
        )
    if scoped_validation is not None:
        system_steps.append(f"Scoped validate issues: {len(scoped_validation.get('issues', ()))}")
    validation_error = scoped_validation.get("error") if scoped_validation else None
    final_accepted = bool(loop_result["accepted"]) and not validation_error
    final_status = "VALIDATION_ERROR" if validation_error else loop_result["status"]
    preview_line = (loop_result["text"] or "").strip().splitlines()[0][:160] if loop_result.get("text") else ""
    ai_summary = (
        f"Updated notebook (r{final_nb['revision']}) with {len((loop_result['text'] or '').split())} words ({final_status})."
        + (f" Opening: {preview_line}" if preview_line else "")
        if final_accepted
        else (f"Validation error: {validation_error}" if validation_error else f"Blocked: {', '.join(loop_result['verdict'].get('hard_issues', ()))}")
    )
    history = _append_director_history(
        timeline,
        ep_id,
        {
            "user_prompt": user_prompt or "(default workflow brief)",
            "attachment": attachment_name or None,
            "workflow_mode": workflow_mode,
            "provider": writer_name,
            "status": final_status,
            "accepted": final_accepted,
            "system_steps": system_steps,
            "ai_summary": ai_summary,
            "notebook_revision": final_nb["revision"],
        },
    )
    return {
        "episode": ep_id,
        "status": final_status,
        "accepted": final_accepted,
        "workflow_mode": workflow_mode,
        "craft_mode": craft_mode,
        "references_backend": references_backend,
        "reference_status": ref_status,
        "reference_receipts": ref_receipts,
        "leaving_mode": leaving_mode if workflow_mode == "spring-alternate" else None,
        "provider": writer_name,
        "provider_calls": loop_result["provider_calls"],
        "slop_score": slop_score,
        "turns": loop_result["turns"],
        "system_steps": system_steps,
        "ai_summary": ai_summary,
        "director_history": history["entries"],
        "graph_result": graph_result,
        "scoped_validation": scoped_validation,
        "notebook_revision": final_nb["revision"],
        "timeline_revision": final_nb["timeline_revision"],
        "notice": (
            f"Ran {workflow_mode} via {writer_name} ({loop_result['provider_calls']} call(s), Slop {slop_score}, Cooked to nb r{final_nb['revision']})."
            if loop_result["accepted"]
            else f"Pipeline blocked after {loop_result['provider_calls']} call(s): {', '.join(loop_result['verdict'].get('hard_issues', ()))}"
        ),
    }


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("spring-alternate", "tapped-out", "both"), default="both")
    parser.add_argument("--leaving", choices=("relapse", "clothes"), default="clothes")
    parser.add_argument("--full-story", action="store_true", help="Generate full 7-scene alternative Spring Break story.")
    parser.add_argument("--named-splits", action="store_true", help="Require Rainee Sade, Rainee Becky, and Rainee Clarie names/cues.")
    parser.add_argument("--workspace", type=Path, default=None)
    parser.add_argument("--out-report", type=Path, default=None)
    parser.add_argument("--out-story", type=Path, default=None)
    parser.add_argument("--max-calls", type=int, default=2)
    parser.add_argument("--live", action="store_true", help="Dispatch to real signed-in gemini-session (agy.exe).")
    args = parser.parse_args()

    def _offline_handler(prompt: str) -> str:
        if "ONLY Scenes 1 to 3" in prompt:
            return (
                "### SCENE 1: KITCHEN BRIEFING & THE ANCESTRAL MASSAGE\n"
                "Francine Ling zips her cherry-red wheeled bag beside the stacked lasagna trays.\n"
                "Francine: Three nights of lasagna, two nights of orange chicken, and Baba's ancestral farting.\n"
                "Stella: Origami newspaper bows stay sharp all morning.\n"
                "Haley: Let me check on Mom Two.\n\n"
                "### SCENE 2: MASTER SUITE & THE SUDDEN COUP\n"
                "Rainee cramps on her vanity stool and sprints for the bath in puffs of French perfume.\n\n"
                "### SCENE 3: THE DOUBLE COMMODE & THE TWO-CHAIR RULE\n"
                "The black porcelain toilet widens into a double-wide lotus throne while jasmine vapor rolls under the oak door.\n"
                f"Haley: {PERFUME_LINE}\n"
            )
        if "ONLY Scene 7" in prompt:
            return (
                "### SCENE 7: ROGER'S RUTGERS SPRING BREAK TAKEOVER\n"
                "Roger: Take these backpacks to the freeway motel — they'll buy you jewelry!\n"
                "Haley: Nobody's leaving, Roger.\n"
                "Stella: Keep the three trays of lasagna right where they are.\n"
                "Roger throws on his purple ermine cape and blows a whistle as the Rutgers Spring Break charter bus roars up.\n"
                "Frat Guy: Clear plastic bags!\n"
            )
        if "THREE LITTLE BITCHES" in prompt:
            if args.full_story:
                return (
                    "### SCENE 4: THE THREE LITTLE BITCHES\n"
                    "Rainee splits into three little bitches behind the bathroom door: Rainee 1 (Rainee Sade), Rainee 2 (Rainee Becky), and Rainee 3 (Rainee Clarie).\n"
                    "Rainee Sade: Verdict first — nobody touches that fan.\n"
                    "Rainee Becky: Follow house rules and verify your loyalty, Haley.\n"
                    "Rainee Clarie: Her left shoelace is untied.\n"
                    "Francine: Eyes here, all three of you.\n"
                    "Regular Francine brings them together, then Rainee swells into Rainee Peter Griffen.\n"
                    "Francine laughs at her spouse and asks for Nurse Franny.\n"
                    "Rainee Peter Griffen: Nurse uniform granted, stand clear!\n"
                    "Nurse Franny steps aside as Rainee Peter Griffen lets loose a huge fart blast sending Haley down the hall.\n"
                    "Rainee Peter Griffen destabilizes back into the same Three Little Bitches: Rainee Sade, Rainee Becky, and Rainee Clarie.\n"
                    "Together they rip a second fart blast smelling of tuberose, orange, and sandalwood that farts their bitch daughter Haley farther down the hall.\n"
                    "Rainee Sade: Hallway clearance approved.\n"
                    "Rainee Becky: Next time follow basic scheduling rules.\n"
                    "Rainee Clarie: She slid three picture frames past the stairs.\n"
                    "Haley: Keep your three perfume counters to yourselves.\n\n"
                    "### SCENE 5A: THE CLOTHES\n"
                    "Nurse Franny: Pack the red overnight bag. Keys and three trays of lasagna stay with Haley and Stella.\n"
                    "Rainee Sade: The red wrap dress comes first.\n"
                    "Rainee Becky: Formal silk follows dinner protocol.\n"
                    "Rainee Clarie: There is mascara on the cuff.\n\n"
                    "### SCENE 6: THE RED SEDAN\n"
                    "Nurse Franny drives Rainee Sade, Rainee Becky, and Rainee Clarie off in the red sedan.\n"
                )
            return (
                "### SCENE 4: THE THREE LITTLE BITCHES\n"
                "Rainee splits into Rainee Sade, Rainee Becky, and Rainee Clarie behind the bathroom door.\n"
                "Rainee Sade: Verdict first — nobody touches the fan.\n"
                "Rainee Becky: Follow the rules and back me up, Haley.\n"
                "Rainee Clarie: The indicator light isn't even plugged in.\n"
                "Francine: Eyes here, all three of you.\n"
                "Regular Francine brings them back together, then Rainee swells into Rainee Peter Griffen.\n"
                "Francine laughs at her spouse and asks for Nurse Franny.\n"
                "Rainee Peter Griffen: Nurse uniform granted, stand clear!\n"
                "Nurse Franny steps aside as Rainee Peter Griffen lets loose a huge fart blast sending Haley down the hall.\n"
                "Rainee Peter Griffen destabilizes back into the same Three Little Bitches (Rainee Sade, Rainee Becky, Rainee Clarie).\n"
                "Together they rip a second fart blast of tuberose, orange, and sandalwood that farts their bitch daughter farther down the hall.\n"
                "Rainee Sade: Hallway's ours.\n"
                "Rainee Becky: Next time check the schedule.\n"
                "Rainee Clarie: That was three coat hooks past the stairs.\n"
                "Haley: Fine. Take your keys and three lasagna trays.\n"
                "Nurse Franny zips the clothes into her red overnight bag and drives the three Rainees off in the red sedan.\n"
            )
        return (
            "INT. STUDIO CORRIDOR - DAY\n\n"
            "Francine: Everyone on marks.\n"
            "Haley: Ready.\n"
            "Stella transforms into Big Tiddy Steve in her canary-yellow polo.\n"
            "STELLA (Big Tiddy Steve): Adjusting the cube readout now.\n"
            "STELLA (Big Tiddy Steve): Audio level is green.\n"
            "Holly: Good — Holly Graham is rolling take one.\n"
        )

    handler = None if args.live else _offline_handler
    if args.workspace is not None:
        ws = args.workspace
        tmp_cm = None
    else:
        tmp_cm = tempfile.TemporaryDirectory(prefix="noir-gemini-driver-")
        ws = Path(tmp_cm.name)

    try:
        report: Dict[str, Any] = {"live": bool(args.live), "results": {}}
        if args.mode in ("spring-alternate", "both"):
            report["results"]["spring-alternate"] = drive_gemini_alternate_spring_break(
                ws / "spring",
                leaving_mode=args.leaving,
                session_handler=handler,
                max_calls=args.max_calls,
                full_story=args.full_story,
                require_named_splits=args.named_splits,
                out_story=args.out_story,
            )
        if args.mode in ("tapped-out", "both"):
            report["results"]["tapped-out"] = drive_gemini_tapped_out_rewrite(
                ws / "tapped", session_handler=handler, max_calls=args.max_calls
            )
        if args.out_report is not None:
            args.out_report.parent.mkdir(parents=True, exist_ok=True)
            args.out_report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps({
            "live": report["live"],
            "modes": {k: {"status": v["status"], "accepted": v["accepted"], "calls": v["provider_calls"]} for k, v in report["results"].items()},
        }, indent=2))
        return 0 if all(v["accepted"] for v in report["results"].values()) else 1
    finally:
        if tmp_cm is not None:
            tmp_cm.cleanup()


if __name__ == "__main__":
    raise SystemExit(_cli())
