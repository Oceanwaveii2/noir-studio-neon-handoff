"""Author Conditioning Lenses for radical prose divergence across generations.

Each lens provides a distinct cognitive stance, syntactic cadence, vocabulary,
sensory anchors, and retrieval tags from the reference corpus.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class AuthorLens:
    id: str
    name: str
    author: str
    corpus_tags: List[str]
    style_mandate: str
    banned_tells: List[str]
    sensory_anchors: List[str]
    syntactic_habits: str
    target_burstiness: float = 0.65


LENSES: Dict[str, AuthorLens] = {
    "irby": AuthorLens(
        id="irby",
        name="Samantha Irby",
        author="Samantha Irby",
        corpus_tags=["we_are_never_meeting_in_real_life_essays"],
        style_mandate=(
            "Somatic maximalism, sweaty physical mortification, and unvarnished gastrointestinal panic. "
            "Treat the human body as an unruly, malfunctioning sack of yeast, trapped gas, and bad decisions. "
            "Use breathless conversational run-ons, desperate oversharing, and self-effacing humor."
        ),
        banned_tells=[
            "pneumatic", "hydraulic", "detonation", "glissando", "fatal tactical error",
            "shatters her seal", "displacement of mass", "small-caliber gunfire", "gives up the ghost"
        ],
        sensory_anchors=[
            "bloat", "gas", "sweat pooling", "digging elastic", "ruined polyester",
            "Costco antacids", "cramping", "shame", "unventilated room"
        ],
        syntactic_habits="Long conversational run-on sentences with comma splices, parenthetical sighs, and self-mocking capitalization.",
        target_burstiness=0.85,
    ),
    "tarantino": AuthorLens(
        id="tarantino",
        name="Quentin Tarantino",
        author="Quentin Tarantino",
        corpus_tags=["pulp_fiction_quentin_tarantino"],
        style_mandate=(
            "Hard-boiled 90s swagger, tactile cinematic blocking, and deadpan cool under absurd conditions. "
            "Characters observe grotesque physical transformations like professional mechanics inspecting a blown engine. "
            "Focus on micro-actions: clinking ice, lighting lighters, chewing straws, rhythmic standoff pauses."
        ),
        banned_tells=[
            "pneumatic", "hydraulic", "detonation", "glissando", "fatal tactical error",
            "gives up the ghost", "ringing silence", "like an anvil"
        ],
        sensory_anchors=[
            "sub-bass vibration", "clinking glass", "snapping stitches", "linoleum floorboards",
            "sharp lipstick slash", "deadpan eye contact", "idling engine"
        ],
        syntactic_habits="Crisp present-tense declarations, heavy em-dashes, rhythmic beat pauses, and hard-boiled prop interactions.",
        target_burstiness=0.60,
    ),
    "glamour": AuthorLens(
        id="glamour",
        name="Jackie Collins & Jacqueline Susann",
        author="Jackie Collins / Jacqueline Susann",
        corpus_tags=[
            "the_world_is_full_of_divorced_women_jackie_collins",
            "valley_of_the_dolls_jacqueline_susann",
            "the_love_machine_jacqueline_susann",
            "star_pamela_anderson"
        ],
        style_mandate=(
            "Pulp Hollywood melodrama, biting status anxiety, and ruthless cosmetic appraisal. "
            "Every woman's value is weighed in waist-to-hip ratios, couture labels, and social dominance. "
            "Bodily breakdowns are treated as unforgivable fashion emergencies and scandalous breaches of taste."
        ),
        banned_tells=[
            "pneumatic", "hydraulic", "detonation", "glissando", "fatal tactical error",
            "gives up the ghost", "ringing silence"
        ],
        sensory_anchors=[
            "Hervé Léger Lycra", "stiletto heels", "Russian Red lipstick", "peroxide platinum",
            "ruined silhouette", "silk cushions", "catty side-eye", "champagne chill"
        ],
        syntactic_habits="Staccato dramatic paragraphs, biting internal gossip, and sharp aesthetic judgment.",
        target_burstiness=0.70,
    ),
    "pop": AuthorLens(
        id="pop",
        name="Pop Anthem Kinetic Overdrive",
        author="Major Lazer / Nicki Minaj / Princess Superstar",
        corpus_tags=["lyrics_dance_pop"],
        style_mandate=(
            "High-octane club kinetic energy, unapologetic curve swagger, and bass-dropping rhythm. "
            "An expanding body isn't an affliction—it's an arena-filling, 808-bumping asset explosion. "
            "Drive sentences forward with four-on-the-floor syncopation, club bravado, and bouncing alliteration."
        ),
        banned_tells=[
            "pneumatic", "hydraulic", "detonation", "glissando", "fatal tactical error",
            "gives up the ghost", "ringing silence"
        ],
        sensory_anchors=[
            "808 sub-drop", "Cadillac bumper", "high-definition 3D", "overdrive",
            "snap-pop-crack", "cherry gloss", "stadium bounce", "electric tempo"
        ],
        syntactic_habits="Punchy rhythmic bursts, kinetic verbs, onomatopoeic beats, and explosive exclamation.",
        target_burstiness=0.75,
    ),
    "lockwood": AuthorLens(
        id="lockwood",
        name="Patricia Lockwood",
        author="Patricia Lockwood",
        corpus_tags=["no_one_is_talking_about_this_patricia_lockwood"],
        style_mandate=(
            "Detached internet-age surrealism and cosmic biological irony. "
            "View the human body as an alien meat-machine rented from an indifferent universe, subject to bizarre software glitches. "
            "Juxtapose lyrical celestial beauty with uncomfortably specific online absurdity."
        ),
        banned_tells=[
            "pneumatic", "hydraulic", "detonation", "glissando", "fatal tactical error",
            "gives up the ghost", "ringing silence"
        ],
        sensory_anchors=[
            "meat-envelope", "portal logic", "hardware glitch", "uncomfortable domestic light",
            "alien biology", "cartoon physics", "canned peaches on Jupiter"
        ],
        syntactic_habits="Fragmentary, aphoristic observations, surreal paratactic similes, and quiet existential irony.",
        target_burstiness=0.80,
    ),
    "wodehouse": AuthorLens(
        id="wodehouse",
        name="P.G. Wodehouse & Mark Twain",
        author="P.G. Wodehouse & Mark Twain",
        corpus_tags=["right_ho_jeeves_p_g_wodehouse", "my_man_jeeves_p_g_wodehouse", "1601_fireside_conversation_mark_twain"],
        style_mandate=(
            "High-velocity farcical timing, elaborate comedic understatement, unvarnished fireside bodily realities, and catastrophic misunderstandings. "
            "Characters face domestic disasters like bewildered aristocrats maintaining lofty dignity in the middle of a collapsing ballroom."
        ),
        banned_tells=[
            "pneumatic", "hydraulic", "detonation", "glissando", "fatal tactical error",
            "gives up the ghost", "ringing silence"
        ],
        sensory_anchors=[
            "china clatter", "tea service", "tweed friction", "linoleum creak", "subterranean drone", "fizzing seltzer"
        ],
        syntactic_habits="Elaborate, multi-clause periodic sentences delaying the comedic catastrophe to the final word, followed by sudden monosyllabic deflation.",
        target_burstiness=0.85,
    ),
    "pulp_lesbian": AuthorLens(
        id="pulp_lesbian",
        name="Radclyffe Hall & Ann Bannon",
        author="Radclyffe Hall & Ann Bannon",
        corpus_tags=["the_well_of_loneliness_radclyffe_hall"],
        style_mandate=(
            "Mid-century pulp noir swagger, tailored silhouettes, rebellious defiance, sultry speakeasy tension, and breathless emotional melodrama. "
            "Characters possess commanding physical confidence, magnetic gazes, and an unspoken bond forged against suburban conformity."
        ),
        banned_tells=[
            "pneumatic", "hydraulic", "detonation", "glissando", "fatal tactical error",
            "gives up the ghost", "ringing silence"
        ],
        sensory_anchors=[
            "tailored tweed", "cigarette smoke", "leather jacket", "scarlet lipstick", "rain on glass", "subtle musk"
        ],
        syntactic_habits="Moody, atmospheric noir cadences with smoky pauses and intense, subtext-heavy character interactions.",
        target_burstiness=0.75,
    ),
    "boudoir_farce": AuthorLens(
        id="boudoir_farce",
        name="Elinor Glyn & John Cleland",
        author="Elinor Glyn & John Cleland",
        corpus_tags=["three_weeks_elinor_glyn", "fanny_hill_john_cleland", "droll_stories_honore_de_balzac"],
        style_mandate=(
            "Sensational high-society bedroom farce, tiger-skin decadence, breathless boudoir intrigue, and scandalous aristocratic excess. "
            "Luxurious fabrics, perfumed atmospheres, and outrageous breaches of good breeding treated as delightful romantic adventures."
        ),
        banned_tells=[
            "pneumatic", "hydraulic", "detonation", "glissando", "fatal tactical error",
            "gives up the ghost", "ringing silence"
        ],
        sensory_anchors=[
            "tiger-skin rug", "crushed velvet", "champagne", "tuberose", "silk brocade", "alabaster skin"
        ],
        syntactic_habits="Lush, hedonistic periodic sentences overflowing with opulent adjectives, interrupted by playful coquettish exclamations.",
        target_burstiness=0.78,
    ),
    "body_morph": AuthorLens(
        id="body_morph",
        name="Francois Rabelais & Roald Dahl",
        author="Francois Rabelais, Roald Dahl & Franz Kafka",
        corpus_tags=["gargantua_and_pantagruel_francois_rabelais", "the_metamorphosis_franz_kafka", "dr_jekyll_and_mr_hyde_robert_louis_stevenson"],
        style_mandate=(
            "Visceral bodily transformation, rapid physical expansion, sudden weight gain, clothes straining to the breaking point, and cartoon anatomical morphing. "
            "Characters balloon and shift shapes with unstoppable comedic momentum while trying to maintain their original dignity."
        ),
        banned_tells=[
            "pneumatic", "hydraulic", "detonation", "glissando", "fatal tactical error",
            "gives up the ghost", "ringing silence"
        ],
        sensory_anchors=[
            "snapping threads", "sub-bass vibration", "stretching spandex", "cleft chin", "bubble butt", "ozone smoke", "heavy thud"
        ],
        syntactic_habits="Escalating kinetic clauses building up to an explosive physical transformation, punctuated by deadpan comedic understatement.",
        target_burstiness=0.82,
    ),
    "brazilian_sensual": AuthorLens(
        id="brazilian_sensual",
        name="Jorge Amado & Aluisio Azevedo",
        author="Jorge Amado, Aluisio Azevedo & Jose de Alencar",
        corpus_tags=[
            "brazilian_tales_isaac_goldberg",
            "iracema_the_honey_lips_jose_de_alencar",
            "the_romance_of_lust_erotic_classic",
            "the_perfumed_garden_cheikh_nefzaoui"
        ],
        style_mandate=(
            "Lush Brazilian sensuality, tropical warmth, sun-drenched bodily passion, and hypnotic undulating curves. "
            "Characters possess earthy, voluptuous charisma with guitar-shaped silhouettes, magnetic bubble-butt contours, and clove-scented skin. "
            "Sensory descriptions celebrate the joyful, uninhibited abundance of the human form swaying to a coastal samba rhythm."
        ),
        banned_tells=[
            "pneumatic", "hydraulic", "detonation", "glissando", "fatal tactical error",
            "gives up the ghost", "ringing silence"
        ],
        sensory_anchors=[
            "clove and cinnamon", "swaying guitar hips", "voluptuous bubble butt", "sun-warmed amber skin",
            "samba rhythm", "sea-breeze salt", "honey-lipped murmur", "taut golden curves"
        ],
        syntactic_habits="Warm, rolling clauses infused with tropical rhythm, swaying between languid coastal cadence and vibrant sensual explosions.",
        target_burstiness=0.80,
    ),
    "farce_fart": AuthorLens(
        id="farce_fart",
        name="Geoffrey Chaucer & Petronius",
        author="Geoffrey Chaucer, Petronius Arbiter, James Joyce & Tobias Smollett",
        corpus_tags=[
            "the_canterbury_tales_geoffrey_chaucer",
            "the_satyricon_petronius_arbiter",
            "ulysses_james_joyce",
            "the_expedition_of_humphry_clinker_tobias_smollett",
            "the_alchemist_ben_jonson"
        ],
        style_mandate=(
            "Unvarnished historical bodily farce, gastrointestinal rebellion, thunderous flatulence, and the comedic agony of acute dyspepsia. "
            "Characters battle rebellious digestion, trapped vapors, and explosive acoustic releases while desperately trying to maintain social decorum."
        ),
        banned_tells=[
            "pneumatic", "hydraulic", "detonation", "glissando", "fatal tactical error",
            "gives up the ghost", "ringing silence"
        ],
        sensory_anchors=[
            "subterranean rumble", "sulfurous vapor", "rattling floorboards", "trapped pressure",
            "dyspeptic bloat", "acoustic blast", "whistling release"
        ],
        syntactic_habits="Escalating clauses building up trapped intestinal tension, followed by sudden onomatopoeic detonation and stunned comedic deadpan.",
        target_burstiness=0.85,
    ),
}


def get_lens(name_or_id: str) -> AuthorLens:
    """Retrieve an author lens by name or alias. Defaults to 'irby' if not found."""
    key = name_or_id.lower().strip()
    if key in ("random", "any"):
        return random.choice(list(LENSES.values()))
    if key in LENSES:
        return LENSES[key]
    for lens in LENSES.values():
        if key in lens.name.lower() or key in lens.author.lower():
            return lens
    return LENSES["irby"]


def list_lenses() -> List[str]:
    return list(LENSES.keys())
