"""
Future Heritage: planned canon that is NOT active in the S04E16 Spring Break story.

Canon rules here are accumulative across episodes and inherited from the
American Dad! progression:
- Origin / S04E16 Spring Break-Up (2008): Haley was born to Francine and Rainee
  via genetic nanomachinery (no father), mostly human with dormant fox genetics
  destined to activate later. In Spring Break-Up she is dating boyfriend Jeff.
- Gradual progression -> Hot Scoomp (S18): Haley has already married Jeff
  (husband Jeff). Episodic hints build until her fox heritage awakens fully in
  Hot Scoomp; mirroring her mothers' extreme aversion, she loses attraction and
  is physically repulsed by her husband Jeff, cheating on him with Holly Graham
  (the gym cult leader). Note: foxes cannot have sons, and foxes are overwhelmingly
  female-attracted (rare male attraction is possible, e.g. Noir dated a guy).
- Subsequent Tapped Out arc: Haley and Jeff's marriage is salvaged by giving
  Jeff a device to turn into Jess during intimacy and related scenes so Haley can
  preserve the marriage while remaining fulfilled sexually with Jess.

This module is data only. The current-story ontology must not inject these
records into S04E16 prompts or gates; see `current_story_guard`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple


@dataclass(frozen=True)
class FutureHeritageBeat:
    beat_id: str
    act: str
    summary: str
    characters: Tuple[str, ...] = field(default_factory=tuple)
    canon_note: str = ""


@dataclass(frozen=True)
class HotScoompVariant:
    """One version of the Hot Scoomp story, for comparison only."""

    variant_id: str
    name: str
    source: str
    status: str  # AFM_CANON | SOURCE_SHOW | REWRITE | REWRITE_SKELETON | FUTURE_S18
    cia_role: str
    cult: str
    haley_role: str
    transformation: str
    jeff_status: str
    jeff_tag: str
    notes: str


@dataclass(frozen=True)
class FutureHeritage:
    heritage_id: str
    title: str
    source_story: str
    source_airdate: str
    first_active_season: str
    status: str
    canon_variant: str
    premise: str
    timeline: Tuple[Tuple[str, str], ...]
    beats: Tuple[FutureHeritageBeat, ...]
    canon_rules: Tuple[str, ...]
    current_story_guard: str


HOT_SCOOMP_VARIANTS: Dict[str, HotScoompVariant] = {
    "source_show_2021": HotScoompVariant(
        variant_id="source_show_2021",
        name="Original American Dad! 'Hot Scoomp' (2021)",
        source="Broadcast episode, first aired 2021-06-28.",
        status="SOURCE_SHOW",
        cia_role="None. The CIA is not part of the rescue.",
        cult="HG dance-cardio studio / Holly Graham; relocates to a Congo jungle compound.",
        haley_role="Journalism student who follows 'cool butts' to HG, signs up, and is brainwashed.",
        transformation="No fox awakening or serum transformation in the broadcast recap. The original Holly-is-controlled-by-a-fat-man twist is rejected by the rewrites.",
        jeff_status="The recap calls Jeff her 'boyfriend'; AFM canon agrees.",
        jeff_tag="No Brazil tag in the broadcast recap; Jeff is simply ditched early.",
        notes="The production baseline. It has the cult, Holly, and the mother-daughter rescue, but not the Roger-DNA serum or the AFM CIA case.",
    ),
    "vanilla_rewrite": HotScoompVariant(
        variant_id="vanilla_rewrite",
        name="Vanilla Hot Scoomp Rewrite",
        source="Combined Hot Scoomp Dark Edition, Part I.",
        status="REWRITE",
        cia_role="None. Francine and Roger drive the rescue.",
        cult="Cult of Cheeks / HG / Holly Graham; the cult worships the Roger persona Vanderbooben.",
        haley_role="Cult recruit, then the first human test subject for the butt serum.",
        transformation="Roger-DNA serum: Vanderbooben-Hayley (bigger head, thicker thighs, massive ass, Roger cadence), then Influencer BBL Hayley after the corrected second injection.",
        jeff_status="Jeff exits through the car-wash flaps early and is forgotten; the tag asks what happened to him.",
        jeff_tag="Packet tag: 'somewhere halfway across America,' passed out and getting robbed.",
        notes="Fixes the original plot holes and centers Roger as the cult's idol and DNA source. No CIA, no fox awakening, no Rainee.",
    ),
    "transformation_cheeks": HotScoompVariant(
        variant_id="transformation_cheeks",
        name="Transformation Cheeks 1: Hot Scoomp Rewrite Skeleton",
        source="Combined Hot Scoomp Dark Edition, Part II.",
        status="REWRITE_SKELETON",
        cia_role="None. Francine and Roger drive the rescue.",
        cult="Cult of Cheeks / HG / Holly Graham; the cult wants the perfect-butt serum.",
        haley_role="Cult recruit, seduced into being the test subject; three-stage transformation.",
        transformation="Normal Haley -> Vanderbooben-Hayley -> Influencer BBL Hayley; the final tag says 'What about your husband, Jeff?'",
        jeff_status="Married husband Jeff ('What about your husband, Jeff?') matches post-100 A.D. show inheritance, though she forgets him in this rewrite skeleton.",
        jeff_tag="Packet tag: 'somewhere halfway across America,' passed out and getting robbed; Haley has forgotten him.",
        notes="The most detailed rewrite skeleton; supplies the transformation stages and the 'husband Jeff' status. Still no CIA case and no fox awakening.",
    ),
    "afm_canon": HotScoompVariant(
        variant_id="afm_canon",
        name="American Foxy Momma canon",
        source="Author's AFM canon (accumulating through Spring Break -> Hot Scoomp -> Tapped Out).",
        status="AFM_CANON",
        cia_role="The CIA is trying to stop the Cult and puts Rainee on the case.",
        cult="The booty cult (HG / Cult of Cheeks), led by Holly Graham.",
        haley_role="Drawn into the booty cult while Rainee works the CIA case; cheats on husband Jeff with Holly Graham.",
        transformation="S18 arc: fox heritage finishes awakening, mirrors her mothers strongly, ass inflates, Rainee-like powers, physical repulsion to Jeff, multiple avatars.",
        jeff_status="Already Haley's husband by Hot Scoomp (inherited from American Dad! timeline after Spring Break). Awakening makes her physically repulsed by him and she cheats with Holly Graham; later salvaged in Tapped Out via Jeff-to-Jess transformation device.",
        jeff_tag="Author's canon: Jeff ends up in Brazil and gets robbed (husband Jeff by Hot Scoomp).",
        notes="Canonical AFM continuity: accumulative across episodes. Francine Ling never married Stan; Rainee is CIA case officer; Haley dates Jeff in Spring Break and is married to husband Jeff by Hot Scoomp; salvaged later via Jeff-to-Jess device in Tapped Out.",
    ),
    "s18_future": HotScoompVariant(
        variant_id="s18_future",
        name="S18 Hot Scoomp: Haley's Fox Awakening",
        source="Future Heritage / S18 + Tapped Out follow-up outline.",
        status="FUTURE_S18",
        cia_role="Rainee is already on the CIA case; Roger and Francine are captured with Haley.",
        cult="The booty cult plus the butt relic.",
        haley_role="Drawn in, cheats on husband Jeff with Holly Graham, captured, then awakened by Roger's plan.",
        transformation="Fox heritage finishes awakening; mirrors mothers strongly; ass inflates; inherits Rainee's powers; personality switching and multiple avatars.",
        jeff_status="Already her husband; Haley loses attraction and is physically repulsed by Jeff, leading to Holly Graham affair; marriage is later salvaged in Tapped Out via a device turning Jeff into Jess.",
        jeff_tag="The Hot Scoomp tag lands husband Jeff in Brazil, robbed; S18 adds the post-awakening repulsion rift before Tapped Out's Jess-device salvage.",
        notes="Future evolution of afm_canon. Jeff is boyfriend at S04E16 Spring Break-Up, husband by Hot Scoomp, and transformed to Jess during intimacy in Tapped Out.",
    ),
}


def get_hot_scoomp_variant(variant_id: str) -> HotScoompVariant:
    """Returns a Hot Scoomp variant by id, or raises KeyError."""
    return HOT_SCOOMP_VARIANTS[variant_id]


def hot_scoomp_variant_ids() -> Tuple[str, ...]:
    return tuple(HOT_SCOOMP_VARIANTS)


HOT_SCOOMP_S18 = FutureHeritage(
    heritage_id="future_hot_scoomp_s18",
    title="Hot Scoomp S18: Haley's Fox Awakening",
    source_story="American Foxy Momma canon (CIA vs. the Cult) + S18 future arc",
    source_airdate=(
        "Hot Scoomp first aired 2021-06-28; the S18 awakening arc is future/unaired."
    ),
    first_active_season="S18",
    status="PLANNED_NOT_ACTIVE",
    canon_variant="afm_canon",
    premise=(
        "The CIA is trying to stop the Cult and puts Rainee on the case, while Haley is "
        "drawn into the booty cult. Having inherited the American Dad! marriage timeline, "
        "Haley is already married to her husband Jeff, while her dormant fox genetics (born "
        "to two mothers with no father) gradually activate until full awakening triggers in "
        "Hot Scoomp to charge the butt relic via Roger's counter-plan. Mirroring her mothers' "
        "genetics strongly, awakened Haley loses all attraction to Jeff, is physically "
        "repulsed by him, and cheats on him with gym cult leader Holly Graham while gaining "
        "Rainee's powers and multiple avatars. Later in Tapped Out, the marriage is salvaged "
        "by giving Jeff a device to transform into Jess during intimacy."
    ),
    timeline=(
        (
            "S04E16 Spring Break-Up (2008)",
            "Haley is mostly human with dormant fox genes (destined to activate); Jeff is her boyfriend (not husband yet in Spring Break).",
        ),
        (
            "Post-Spring Break -> Hot Scoomp (2021)",
            "Inherits American Dad! marriage timeline: Haley has already married husband Jeff while subtle fox-awakening cues build across episodes; AFM frames Hot Scoomp as CIA (Rainee) vs. the Booty Cult (Holly Graham).",
        ),
        (
            "S18 Hot Scoomp Awakening",
            "Haley's fox heritage awakens fully; mirroring her mothers, she is physically repulsed by husband Jeff, cheats with Holly Graham, and inherits Rainee-like powers and avatars.",
        ),
        (
            "Tapped Out Recovery",
            "Haley and Jeff salvage their marriage via a transformation device that turns Jeff into Jess during intimacy and related scenes.",
        ),
    ),
    beats=(
        FutureHeritageBeat(
            beat_id="s18_01_cia_case",
            act="Act One",
            summary=(
                "The CIA is trying to stop the Cult and puts Rainee on the case as the "
                "operative who knows the cult's alien/biological angle."
            ),
            characters=("Rainee", "CIA"),
            canon_note="AFM canon framing: Rainee is the case officer, not a captured bystander.",
        ),
        FutureHeritageBeat(
            beat_id="s18_02_haley_drawn_in",
            act="Act One",
            summary=(
                "Haley is drawn into the booty cult (HG / Cult of Cheeks) while chasing the "
                "story, and becomes entangled with the gym-cult leader."
            ),
            characters=("Haley", "Holly Graham"),
            canon_note="The AFM canon keeps the booty cult / Holly Graham from Hot Scoomp.",
        ),
        FutureHeritageBeat(
            beat_id="s18_03_capture",
            act="Act Two",
            summary="Roger and Francine are captured alongside Haley at the cult stronghold.",
            characters=("Roger", "Francine", "Haley"),
        ),
        FutureHeritageBeat(
            beat_id="s18_04_roger_plan",
            act="Act Two",
            summary=(
                "Roger devises a plan to supercharge Haley's dormant fox genetics rather "
                "than let the cult drain her."
            ),
            characters=("Roger", "Haley"),
        ),
        FutureHeritageBeat(
            beat_id="s18_05_awakening",
            act="Act Three",
            summary=(
                "Haley's fox heritage awakens: her body transforms, her ass inflates, and "
                "she inherits Rainee's powers. The cult's butt relic is charged."
            ),
            characters=("Haley", "Rainee"),
            canon_note="The awakening is a future divergence, not a Hot Scoomp serum side effect.",
        ),
        FutureHeritageBeat(
            beat_id="s18_06_jeff_rift",
            act="Act Three",
            summary=(
                "The awakening kills Haley's attraction to Jeff. She cannot kiss him "
                "without throwing up, and their relationship is radically altered."
            ),
            characters=("Haley", "Jeff"),
        ),
        FutureHeritageBeat(
            beat_id="s18_07_avatars",
            act="Act Four",
            summary=(
                "Haley can now change her own personality and occupy multiple avatars, "
                "like Rainee and Stella."
            ),
            characters=("Haley", "Rainee", "Stella"),
        ),
    ),
    canon_rules=(
        "AFM CANON FRAMING: the CIA is trying to stop the Cult and puts Rainee on the case; Haley is drawn into the booty cult.",
        "ACCUMULATIVE TIMELINE: In S04E16 Spring Break-Up, Haley is mostly human with dormant fox genetics (destined to awaken) and dating boyfriend Jeff prior to marriage.",
        "BY HOT SCOOMP (S18): Haley has already married Jeff per inherited American Dad! progression; Jeff is her husband here, and she cheats on him with gym cult leader Holly Graham as awakening completes.",
        "UNIVERSE BIOLOGY: Foxes cannot have biological sons (female-only lineage) and emit female-only siren pheromones. Foxes are strongly attracted to women and weakly or unattracted to men, though rare exceptions are possible (e.g., Noir dated a man alongside her wives and girlfriends).",
        "HALEY MATERNAL GENETIC MIRROR: Unlike rare exceptions, awakened Haley mirrors her mothers strongly: attraction to men dies completely and she is physically repulsed by husband Jeff.",
        "TAPPED OUT RECOVERY: Haley and Jeff's marriage is later salvaged by giving Jeff a device to transform into Jess during intimacy so Haley keeps her marriage and is fulfilled sexually with Jess.",
        "LING IDENTITY GUARD: Francine Ling never married Stan Smith, Haley/Stella have no father (two-mom nanomachinery), and the household is strictly Ling House.",
        "Rainee is the CIA case officer in the AFM canon; Roger and Francine are the ones captured alongside Haley.",
        "The S18 awakening is triggered across episodic buildup plus the cult butt relic and Roger's plan, not by the Hot Scoomp serum alone.",
        "Post-awakening Haley mirrors Rainee: self-morph, personality switching, and multiple avatars. Stella can self-morph only.",
        "Jeff's Hot Scoomp tag: he ends up in Brazil and gets robbed. The packet's 'halfway across America' is the earlier placeholder.",
        "The cult leader is Holly Graham (HG); the relic is the working 'butt relic'; the cult is the Cult of Cheeks. The source-show and rewrite variants are not AFM canon.",
        "Do not inject S18 awakening/married facts backward into S04E16 Spring Break-Up prompts or gates.",
    ),
    current_story_guard=(
        "Do not apply to S04E16 Spring Break-Up: Haley is human, dormant, dating Jeff, "
        "with no fox traits and no avatars. This record is metadata for a future season only."
    ),
)


FUTURE_HERITAGE: Dict[str, FutureHeritage] = {
    HOT_SCOOMP_S18.heritage_id: HOT_SCOOMP_S18,
}


def get_future_heritage(heritage_id: str) -> FutureHeritage:
    """Returns a future-heritage record by id, or raises KeyError."""
    return FUTURE_HERITAGE[heritage_id]


def future_heritage_ids() -> Tuple[str, ...]:
    return tuple(FUTURE_HERITAGE)
