"""
Aesthetic & Somatic Feature Lexicon for the Prose Engine Pre-Pass.
Milestone M-PE1: Aesthetic & Element Feature Ledger Extractor.
Defines semantic patterns, sensory anchors, vector queries, and routing hints.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .models import FeatureCategory


LEXICON_REGISTRY: List[Dict[str, Any]] = [
    # -------------------------------------------------------------------------
    # Anatomy & Physical Morphs
    # -------------------------------------------------------------------------
    {
        "id": "bubble_butt",
        "category": FeatureCategory.ANATOMY_MORPH,
        "label": "Voluptuous Bubble Butt & Gluteal Expansion",
        "patterns": [
            r"\bbubble\s*butt\b",
            r"\bbootylicious\b",
            r"\bvoluptuous\s*(rear|behind|curves|shelves|butt)\b",
            r"\bspill(s|ing)?\s*off\s*the\s*seat\b",
            r"\bterritorial\s*dominance\b",
            r"\bpeach\s*silk\s*taut\b",
            r"\btwo\s*spheres\b",
        ],
        "sensory_anchors": [
            "two proud, sculpted spheres asserting territorial dominance",
            "peach silk stretched taut across generous Brazilian curves",
            "voluptuous bubble butt filling every contour of sun-warmed silk",
            "curves that defied all austere northern geometry with lush tropical abundance",
        ],
        "routing_hint": "brazilian_sensual",
        "vector_queries": [
            "voluptuous bubble butt filling sun-warmed silk with radiant pride",
            "hips rolling like Atlantic breakers kissing the sands of Copacabana",
            "two proud sculpted spheres asserting total territorial dominance",
            "generous curves that defied all austere northern geometry with lush tropical abundance",
        ],
    },
    {
        "id": "cleft_chin",
        "category": FeatureCategory.ANATOMY_MORPH,
        "label": "Butt Chin / Cleft Chin & Masculine Cartoon Jaw",
        "patterns": [
            r"\b(butt|cleft)\s*chin\b",
            r"\bdouble\s*cleft\b",
            r"\bbulbous\s*(jaw|chin)\b",
            r"\bdoughy\s*(jaw|chin|cheeks)\b",
            r"\bpeter\s*griffin\b",
        ],
        "sensory_anchors": [
            "deep cleft chin dividing the jawline with unmistakable comedic gravity",
            "doughy cartoon jaw contrasting against pristine scarlet lipstick",
            "facial features softening into a heavy, bulbous contour",
        ],
        "routing_hint": "body_morph",
        "vector_queries": [
            "facial features melting and reassembling into a heavy doughy double-cleft chin",
            "deep cleft chin dividing her jawline with unmistakable comedic gravity",
            "the comic absurdity of high-glamour cosmetics resting on a bulbous cartoon jaw",
        ],
    },
    {
        "id": "guitar_curves",
        "category": FeatureCategory.ANATOMY_MORPH,
        "label": "Brazilian Acoustic Guitar Hips & Rio Swagger",
        "patterns": [
            r"\b(guitar|samba)\s*hips\b",
            r"\bbrazilian\s*(acoustic\s*guitar|swagger|curves)\b",
            r"\bundulat(ing|e|ion)\b",
            r"\bcloves?\s*and\s*cinnamon\b",
        ],
        "sensory_anchors": [
            "curves sculpted like a Brazilian acoustic guitar",
            "undulating with the irresistible rhythm of a coastal Bahian samba",
            "intoxicating scent of crushed cloves and raw cinnamon",
        ],
        "routing_hint": "brazilian_sensual",
        "vector_queries": [
            "curves sculpted like a Brazilian acoustic guitar swaying with sensual mastery",
            "the intoxicating scent of crushed cloves and raw cinnamon rising from sun-baked skin",
            "undulating with the irresistible hypnotic rhythm of a coastal Bahian samba",
        ],
    },

    # -------------------------------------------------------------------------
    # Somatic & Digestive Farce
    # -------------------------------------------------------------------------
    {
        "id": "dead_flower_shop_clash",
        "category": FeatureCategory.SOMATIC_FARCE,
        "label": "Perfumed Methane & Dead Flower Shop Olfactory Disaster",
        "patterns": [
            r"\bflower\s*shop\s*died\b",
            r"\bperfumed?\s*(gas|methane|flatulence)\b",
            r"\baromatherapy\s*bath\s*bomb\b",
            r"\bgardenia\s*(and|or)?\s*sulfur\b",
            r"\bdead\s*flower\b",
            r"\bweaponized\s*orchid\b",
        ],
        "sensory_anchors": [
            "a heavy draft rolling under the bathroom door smelling like a flower shop died",
            "French gardenia body butter and rosewater colliding with superheated digestive sulfur",
            "a toxic, weaponized orchid mist that makes the hallway paint blister",
        ],
        "routing_hint": "farce_fart",
        "vector_queries": [
            "fart proudly Benjamin Franklin perfume pleasant smell digestive gas sweet fragrance",
            "Mary Roach Gulp digestive sulfur hydrogen sulfide methyl mercaptans perfume collision",
            "it smells like a flower shop died gardenia and digestive gas catastrophe",
        ],
    },
    {
        "id": "porcelain_acoustics",
        "category": FeatureCategory.SOMATIC_FARCE,
        "label": "Porcelain Tile Acoustic Amplification & Octave Jumps",
        "patterns": [
            r"\bair\s*horn\b",
            r"\bsquash\s*court\b",
            r"\bracquetball\b",
            r"\boctave\s*jump\b",
            r"\bdoppler\s*effect\b",
            r"\brattle\s*(the\s*)?(floorboards|picture\s*frames|toothbrush)\b",
            r"\bconcussive\b",
            r"\bwhizzpop(ping)?\b",
        ],
        "sensory_anchors": [
            "acoustic crack echoing off glazed subway tiles like an air horn in a squash court",
            "percussive concussion that had an octave jump and a Doppler effect",
            "sharp pressurized blast that lifted her an inch off the porcelain seat",
        ],
        "routing_hint": "farce_fart",
        "vector_queries": [
            "Roald Dahl BFG whizzpopping loud explosive flatulence musical notes octave jump",
            "David Sedaris porcelain toilet acoustic reverberation tile echo chamber shame",
            "concussive air horn blast vibrating through the floorboards and plumbing",
        ],
    },
    {
        "id": "acute_gut_colic",
        "category": FeatureCategory.SOMATIC_FARCE,
        "label": "Acute Peristaltic Colic & Meat Machine Revolt",
        "patterns": [
            r"\b(acute|colic|spasmodic)\s*cramp\b",
            r"\bgut\s*(state|coup|rebellion|revolt)\b",
            r"\bmeat\s*machine\b",
            r"\boutboard\s*motor\b",
            r"\bchainsaw\b",
            r"\bbattery\s*acid\b",
        ],
        "sensory_anchors": [
            "meat machine of her insides completely severing diplomatic relations",
            "subterranean rumble like a two-stroke outboard motor being pull-started in wet cement",
            "white-hot colicky cramp stealing her breath and locking her jaw",
        ],
        "routing_hint": "farce_fart",
        "vector_queries": [
            "Kurt Vonnegut Breakfast of Champions meat machine digestive chemical reactions absurd body",
            "Stephen King Dreamcatcher Byrus deep woods belly rumble outboard motor shudder",
            "Mary Roach Gulp transverse colon trapped gas pressure peristaltic wave violent cramp",
        ],
    },
    {
        "id": "towel_muffle_failure",
        "category": FeatureCategory.SOMATIC_FARCE,
        "label": "Towel Sound Dampening Failure & Squealing Venting",
        "patterns": [
            r"\bwad(ded)?\s*(a\s*)?towel\b",
            r"\bsound\s*dampen(er)?\b",
            r"\btea\s*kettle\b",
            r"\bshriek(s|ing)?\s*around\s*the\s*edges?\b",
            r"\begyptian\s*cotton\b",
        ],
        "sensory_anchors": [
            "wadding an Egyptian cotton guest towel to construct a futile sound dampener",
            "high-pressure gas shrieking around the towel edges like a tea kettle at full boil",
        ],
        "routing_hint": "farce_fart",
        "vector_queries": [
            "David Sedaris Me Talk Pretty One Day bathroom panic muffling with guest towel failure",
            "high-pressure gas shrieking around cotton edges vibrating towel bar",
        ],
    },
    {
        "id": "jeff_burrito_blame",
        "category": FeatureCategory.COMEDIC_DYNAMICS,
        "label": "Street Food Autopsy & Jeff Burrito Blame",
        "patterns": [
            r"\bjeff('s)?\s*burrito\b",
            r"\bfood\s*truck\s*burrito\b",
            r"\bcart\s*(burrito|carnitas)\b",
            r"\bhabanero\s*verde\b",
            r"\brefried\s*(black\s*)?beans\b",
        ],
        "sensory_anchors": [
            "cursing Jeff for buying four-dollar carnitas from a cart with two wheels",
            "refried black beans and habanero verde burning through the lining like battery acid",
        ],
        "routing_hint": "cynical_satire",
        "vector_queries": [
            "Carl Hiaasen Bad Monkey cheap greasy street food toxic digestive consequences",
            "Justin Halpern Shit My Dad Says cynical domestic food blame cursing cheap takeout",
        ],
    },

    # -------------------------------------------------------------------------
    # Domestic Staging & Authority
    # -------------------------------------------------------------------------
    {
        "id": "suburban_dinner_authority",
        "category": FeatureCategory.DOMESTIC_STAGING,
        "label": "Suburban Matriarch Preparedness & Casserole Protocol",
        "patterns": [
            r"\bpreparedness\s*briefing\b",
            r"\bmystery\s*casserole\b",
            r"\bthree\s*nights\s*of\s*lasagna\b",
            r"\borange\s*chicken\b",
            r"\bhernia\s*operation\b",
            r"\bcherry\s*cough\s*syrup\s*(bag|duffel)\b",
            r"\bwhite\s*jeans\b",
        ],
        "sensory_anchors": [
            "three nights of lasagna, two nights of orange chicken, and one mystery casserole",
            "overnight duffel bag the color of cherry cough syrup",
            "crisp linen blazer and white jeans that somehow never wrinkle",
            "pressing down on his abdomen to release gas or fart him",
        ],
        "routing_hint": "domestic_farce",
        "vector_queries": [
            "P.G. Wodehouse domestic authority crisp military household scheduling",
            "suburban housewife organized down to the second casserole lasagna refrigerator protocol",
        ],
    },
    {
        "id": "slacker_cynicism",
        "category": FeatureCategory.COMEDIC_DYNAMICS,
        "label": "Slacker Cynicism & TikTok Disconnection",
        "patterns": [
            r"\bpapasan\s*chair\b",
            r"\bnirvana\s*t-?shirt\b",
            r"\btiktok\b",
            r"\barchaeologist\b",
            r"\bancestral\s*toot\b",
        ],
        "sensory_anchors": [
            "curled sideways in the papasan chair like a cat that lost the will to care",
            "oversized charcoal Nirvana shirt glowing TikTok-blue against her face",
            "Ah, the ancient art of ancestral toot-massage",
        ],
        "routing_hint": "sitcom_timing",
        "vector_queries": [
            "cynical young woman slacker deadpan phone scrolling horizontal teenager sarcasm",
            "Haley Ling dry deadpan reaction ancestral toot massage papasan chair",
        ],
    },
]
