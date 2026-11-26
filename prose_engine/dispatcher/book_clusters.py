"""
Book Clusters & Genre Taxonomy for 105-Book Semantic Prose Drive.
Milestone M-PE2: Segmented Sub-Corpus Dispatcher.
Partitions all 105 active books into distinct thematic and stylistic clusters.
"""

from __future__ import annotations

from typing import Dict, List, Set


# -----------------------------------------------------------------------------
# Canonical Cluster Definitions
# -----------------------------------------------------------------------------

CLUSTERS: Dict[str, List[str]] = {
    # 1. Brazilian Sensual, Tropical Warmth & Bubble Butt Curves
    "brazilian_sensual": [
        "brazilian_tales_isaac_goldberg",
        "iracema_the_honey_lips_jose_de_alencar",
        "lyrics_dance_pop",
    ],

    # 2. Modern Somatic Farce, Flatulence & Gut Comedy (The 15 Ingested Books)
    "modern_somatic_farce": [
        "fart_proudly_benjamin_franklin",
        "gulp_adventures_on_the_alimentary_canal_mary_roach",
        "the_bfg_whizzpopping_chronicles_roald_dahl",
        "shit_my_dad_says_justin_halpern",
        "me_talk_pretty_one_day_david_sedaris",
        "breakfast_of_champions_kurt_vonnegut",
        "filth_the_tapeworm_chronicles_irvine_welsh",
        "the_day_my_bum_went_psycho_andy_griffiths",
        "skin_tight_and_bad_monkey_carl_hiaasen",
        "guards_guards_swamp_dragon_chronicles_terry_pratchett",
        "the_body_a_guide_for_occupants_bill_bryson",
        "dreamcatcher_the_byrus_and_colic_chronicles_stephen_king",
        "choke_somatic_and_visceral_chronicles_chuck_palahniuk",
        "the_lust_lizard_of_melancholy_cove_christopher_moore",
        "wow_no_thank_you_somatic_essays_samantha_irby",
    ],

    # 3. Classical Earthy & Bodily Farce
    "classical_bodily_farce": [
        "1601_fireside_conversation_mark_twain",
        "gargantua_and_pantagruel_francois_rabelais",
        "droll_stories_honore_de_balzac",
        "fanny_hill_john_cleland",
        "01_fool",
    ],

    # 4. Body Morph, Volumetric Expansion & Cartoon Anatomy
    "body_morph": [
        "gargantua_and_pantagruel_francois_rabelais",
        "the_metamorphosis_franz_kafka",
        "dr_jekyll_and_mr_hyde_robert_louis_stevenson",
        "lyrics_dance_pop",
        "the_day_my_bum_went_psycho_andy_griffiths",
    ],

    # 5. Domestic Authority & Suburban Comic Farce (Wodehouse & Halpern)
    "domestic_farce": [
        "right_ho_jeeves_p_g_wodehouse",
        "my_man_jeeves_p_g_wodehouse",
        "a_damsel_in_distress_p_g_wodehouse",
        "piccadilly_jim_p_g_wodehouse",
        "uneasy_money_p_g_wodehouse",
        "something_new_p_g_wodehouse",
        "psmith_in_the_city_p_g_wodehouse",
        "the_little_nugget_p_g_wodehouse",
        "shit_my_dad_says_justin_halpern",
    ],

    # 6. Cynical Satire & Food Truck Greasy Realism
    "cynical_satire": [
        "breakfast_of_champions_kurt_vonnegut",
        "skin_tight_and_bad_monkey_carl_hiaasen",
        "filth_the_tapeworm_chronicles_irvine_welsh",
        "choke_somatic_and_visceral_chronicles_chuck_palahniuk",
        "guards_guards_swamp_dragon_chronicles_terry_pratchett",
    ],

    # 7. Contemporary Dry Humor & Bathroom Mortification
    "contemporary_humor": [
        "me_talk_pretty_one_day_david_sedaris",
        "we_are_never_meeting_in_real_life_essays",
        "wow_no_thank_you_somatic_essays_samantha_irby",
        "no_one_is_talking_about_this_patricia_lockwood",
        "pulp_fiction_quentin_tarantino",
        "luster_raven_leilani",
    ],

    # 8. 1970s Glamour, Romance & Bedroom Melodrama (THE TOXIC INTRUSION CLUSTER)
    # MUST BE HARD-BLOCKED from Farce and Brazilian Sensual scenes!
    "glamour_romance_melodrama": [
        "valley_of_the_dolls_jacqueline_susann",
        "the_love_machine_jacqueline_susann",
        "the_world_is_full_of_divorced_women_jackie_collins",
        "star_pamela_anderson",
        "gentlemenpreferb0000anit",
        "three_weeks_elinor_glyn",
        "the_well_of_loneliness_radclyffe_hall",
    ],
}


def get_cluster_books(cluster_name: str) -> List[str]:
    """Returns the list of book slugs belonging to cluster_name."""
    return CLUSTERS.get(cluster_name, [])


def get_all_blocked_books(blocked_clusters: List[str]) -> Set[str]:
    """Flattens and returns a set of all book slugs belonging to blocked_clusters."""
    blocked: Set[str] = set()
    for c in blocked_clusters:
        blocked.update(CLUSTERS.get(c, []))
    return blocked


# -----------------------------------------------------------------------------
# Canonical Author Mappings
# -----------------------------------------------------------------------------

AUTHOR_MAP: Dict[str, str] = {
    # Brazilian Sensual
    "brazilian_tales_isaac_goldberg": "Isaac Goldberg / Machado de Assis",
    "iracema_the_honey_lips_jose_de_alencar": "Jose de Alencar",
    "lyrics_dance_pop": "Major Lazer / Bruno Mars",

    # Modern Somatic Farce (The 15 Books)
    "fart_proudly_benjamin_franklin": "Benjamin Franklin",
    "gulp_adventures_on_the_alimentary_canal_mary_roach": "Mary Roach",
    "the_bfg_whizzpopping_chronicles_roald_dahl": "Roald Dahl",
    "shit_my_dad_says_justin_halpern": "Justin Halpern",
    "me_talk_pretty_one_day_david_sedaris": "David Sedaris",
    "breakfast_of_champions_kurt_vonnegut": "Kurt Vonnegut",
    "filth_the_tapeworm_chronicles_irvine_welsh": "Irvine Welsh",
    "the_day_my_bum_went_psycho_andy_griffiths": "Andy Griffiths",
    "skin_tight_and_bad_monkey_carl_hiaasen": "Carl Hiaasen",
    "guards_guards_swamp_dragon_chronicles_terry_pratchett": "Terry Pratchett",
    "the_body_a_guide_for_occupants_bill_bryson": "Bill Bryson",
    "dreamcatcher_the_byrus_and_colic_chronicles_stephen_king": "Stephen King",
    "choke_somatic_and_visceral_chronicles_chuck_palahniuk": "Chuck Palahniuk",
    "the_lust_lizard_of_melancholy_cove_christopher_moore": "Christopher Moore",
    "wow_no_thank_you_somatic_essays_samantha_irby": "Samantha Irby",

    # Classical Bodily Farce
    "1601_fireside_conversation_mark_twain": "Mark Twain",
    "gargantua_and_pantagruel_francois_rabelais": "Francois Rabelais",
    "droll_stories_honore_de_balzac": "Honore de Balzac",
    "fanny_hill_john_cleland": "John Cleland",
    "01_fool": "Christopher Moore",

    # Body Morph & Satire
    "the_metamorphosis_franz_kafka": "Franz Kafka",
    "dr_jekyll_and_mr_hyde_robert_louis_stevenson": "Robert Louis Stevenson",

    # Domestic Farce (Wodehouse)
    "right_ho_jeeves_p_g_wodehouse": "P. G. Wodehouse",
    "my_man_jeeves_p_g_wodehouse": "P. G. Wodehouse",
    "a_damsel_in_distress_p_g_wodehouse": "P. G. Wodehouse",
    "piccadilly_jim_p_g_wodehouse": "P. G. Wodehouse",
    "uneasy_money_p_g_wodehouse": "P. G. Wodehouse",
    "something_new_p_g_wodehouse": "P. G. Wodehouse",
    "psmith_in_the_city_p_g_wodehouse": "P. G. Wodehouse",
    "the_little_nugget_p_g_wodehouse": "P. G. Wodehouse",

    # Contemporary Humor & Dialogue
    "we_are_never_meeting_in_real_life_essays": "Samantha Irby",
    "no_one_is_talking_about_this_patricia_lockwood": "Patricia Lockwood",
    "pulp_fiction_quentin_tarantino": "Quentin Tarantino",
    "luster_raven_leilani": "Raven Leilani",

    # Glamour & Romance (Blocked)
    "valley_of_the_dolls_jacqueline_susann": "Jacqueline Susann",
    "the_love_machine_jacqueline_susann": "Jacqueline Susann",
    "the_world_is_full_of_divorced_women_jackie_collins": "Jackie Collins",
    "star_pamela_anderson": "Pamela Anderson",
    "gentlemenpreferb0000anit": "Anita Loos",
    "the_well_of_loneliness_radclyffe_hall": "Radclyffe Hall",
    "three_weeks_elinor_glyn": "Elinor Glyn",
}


def resolve_author(slug: str) -> str:
    """Resolves a book slug to its canonical author name."""
    clean_slug = slug.replace(".txt", "")
    if clean_slug in AUTHOR_MAP:
        return AUTHOR_MAP[clean_slug]
    parts = clean_slug.split("_")
    if len(parts) >= 2:
        return f"{parts[-2].capitalize()} {parts[-1].capitalize()}"
    return clean_slug.capitalize()

