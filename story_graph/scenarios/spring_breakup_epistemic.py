"""
Spring Breakup Canonical Epistemic Ledger.
Milestone M-SG3: Epistemic Scoping & Character Knowledge Ledger.
"""

from __future__ import annotations

from ..epistemic import EpistemicLedger, Fact


def build_spring_breakup_epistemic_ledger() -> EpistemicLedger:
    ledger = EpistemicLedger()

    # 1. Register Canonical Facts
    ledger.register_fact(Fact(
        id="fact_baba_hernia",
        description="Baba is recovering from a hernia operation at Nana and Baba's house.",
        keywords=["hernia", "baba's hernia"],
        origin_tick=0,
        is_private=False
    ))

    ledger.register_fact(Fact(
        id="fact_ancestral_toot_massage",
        description="Francine will be pressing down on Baba's abdomen to release gas / 'fart' him.",
        keywords=["toot-massage", "toot massage", "fart him", "release gas"],
        origin_tick=0,
        is_private=False
    ))

    ledger.register_fact(Fact(
        id="fact_preparedness_dinners",
        description="Dinners in fridge: 3 nights lasagna, 2 nights orange chicken, 1 mystery casserole.",
        keywords=["mystery casserole", "preparedness briefing", "orange chicken", "lasagna"],
        origin_tick=0,
        is_private=False
    ))

    ledger.register_fact(Fact(
        id="fact_rainee_bathroom_distress",
        description="Rainee is trapped on the master bathroom toilet with acute gas and violent colic.",
        keywords=["flower shop died", "aromatherapy bath bomb", "farting up there"],
        origin_tick=4,
        is_private=True
    ))

    ledger.register_fact(Fact(
        id="fact_jeff_burrito_cause",
        description="The digestive disaster was caused by Jeff buying street-cart burritos with refried black beans and carnitas.",
        keywords=["burrito", "carnitas", "habanero verde", "jeff to buy us dinner", "jeff's burrito"],
        origin_tick=7,
        is_private=True
    ))

    # 2. Register Characters with Initial Knowledge
    # Francine knows about Baba's hernia, the farting duty, and the dinners
    ledger.register_character("francine", initial_fact_ids=[
        "fact_baba_hernia",
        "fact_ancestral_toot_massage",
        "fact_preparedness_dinners"
    ])

    # Haley initially knows nothing about Baba's hernia or the dinners until Francine briefs her in Beat 1
    ledger.register_character("haley", initial_fact_ids=[])

    # Rainee initially knows about her morning vanity routine, but does NOT know about Jeff's burrito being the cause until Beat 7
    ledger.register_character("rainee", initial_fact_ids=[])

    return ledger
