"""
Curated public-domain candidates for the Spring Break-Up / Hot Scoomp prose voice.

Each entry is a Project Gutenberg text chosen for farce, glamour, social satire,
Hollywood/theatre, appetite/body comedy, or domestic comedy. The `themes` are used by
the recommender to rank the batch against the spring story's profile.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple


@dataclass(frozen=True)
class CuratedBook:
    gutenberg_id: str
    title: str
    author: str
    year: str
    themes: Tuple[str, ...] = field(default_factory=tuple)
    reason: str = ""

    @property
    def slug(self) -> str:
        import re

        value = f"{self.title} {self.author}"
        return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:80]


SPRING_BATCH: Tuple[CuratedBook, ...] = (
    CuratedBook(
        "11052",
        "The Custom of the Country",
        "Edith Wharton",
        "1913",
        ("social climbing", "divorce", "glamour", "satire", "marriage", "ambition"),
        "Undine Spragg's social climbing and serial marriages are the closest public-domain "
        "match to the Susann/Collins glamour-satire voice.",
    ),
    CuratedBook(
        "3472",
        "Merton of the Movies",
        "Harry Leon Wilson",
        "1922",
        ("hollywood", "farce", "ambition", "comedy", "celebrity", "movies"),
        "A Hollywood farce about a naive extra who takes the movies literally; strong "
        "American-Dad-style showbiz absurdity.",
    ),
    CuratedBook(
        "9830",
        "The Beautiful and Damned",
        "F. Scott Fitzgerald",
        "1922",
        ("glamour", "marriage", "decadence", "parties", "romance", "wealth"),
        "Glamorous, self-destructive marriage; useful for the spring story's wealth/party "
        "texture and marital comedy.",
    ),
    CuratedBook(
        "599",
        "Vanity Fair",
        "William Makepeace Thackeray",
        "1848",
        ("social climbing", "satire", "ambition", "marriage", "farce"),
        "Becky Sharp is the ur-social-climber; a deep well of satirical narration and "
        "status comedy.",
    ),
    CuratedBook(
        "7031",
        "The Sheik",
        "E. M. Hull",
        "1919",
        ("romance", "glamour", "desert", "captivity", "melodrama"),
        "A 1919 romance phenomenon; matches the lush, overheated glamour register and "
        "the cult-of-desirability material.",
    ),
    CuratedBook(
        "233",
        "Sister Carrie",
        "Theodore Dreiser",
        "1900",
        ("desire", "consumption", "city", "ambition", "romance", "rise and fall"),
        "Desire and consumer appetite in the city; a grounded counterweight to the "
        "glamour books.",
    ),
    CuratedBook(
        "2084",
        "The Way of All Flesh",
        "Samuel Butler",
        "1903",
        ("domestic satire", "family", "hypocrisy", "comedy", "generational"),
        "Domestic and generational satire; useful for the Ling-household comedy of "
        "parenting styles and family hypocrisy.",
    ),
    CuratedBook(
        "3178",
        "The Gilded Age",
        "Mark Twain and Charles Dudley Warner",
        "1873",
        ("satire", "ambition", "wealth", "social climbing", "farce"),
        "Twain's Gilded Age satire of speculative ambition and social display.",
    ),
    CuratedBook(
        "580",
        "The Pickwick Papers",
        "Charles Dickens",
        "1837",
        ("farce", "episodic", "comedy", "travel", "ensemble"),
        "Episodic ensemble farce; a strong structural model for set-piece comedy.",
    ),
    CuratedBook(
        "64317",
        "The Great Gatsby",
        "F. Scott Fitzgerald",
        "1925",
        ("glamour", "parties", "desire", "wealth", "romance"),
        "The canonical party/glamour novel; public domain in the US since 2021.",
    ),
    CuratedBook(
        "67138",
        "The Sun Also Rises",
        "Ernest Hemingway",
        "1926",
        ("expat", "parties", "romance", "ennui", "ensemble"),
        "Expat party ensemble and romantic drift; public domain in the US since 2022.",
    ),
)
