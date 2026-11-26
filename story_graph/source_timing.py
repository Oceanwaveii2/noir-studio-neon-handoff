"""Passage cutoffs attested against a retained, exact imported manuscript.

An attestation locates an existing approved event. It neither approves the
event nor turns file order, graph guesses, or the legacy beat zero into canon.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib


EPISODE = 'hot-scoomp'
EVENT = 'haley-awakening'
EDITION = 'ag1-c66b8bc76aa2552bc47c'
SCRIPT_SHA256 = '1a1d18a165ad62ae603be85cda8100910c8168768571672b7faed3a85ab7875f'
EVENT_TEXT = 'Haley awakens her fox power.'
FORM = ('haley', 'awakened_haley_fox', 'active')
# Keep the historical edition's alternate form label behind the same boundary.
IMPORTED_FORM = f'{EDITION}:haley.state.bbl_influencer'
AWAKENING_BEAT = 2
WITNESSES = ('francine', 'haley', 'holly')
SPRING_EPISODE = 'spring-break'
SPRING_SOURCE = 'work/americandad/foxy_mo2_hybrid_novel.md'
SPRING_SCRIPT_SHA256 = 'ef72ddba4f98496b06bc5e53236413082c4679d0a976e284e4ba03529f524895'
SPRING_GRAPH_SHA256 = '324cc33f8718d9c776dd2212bcf067aa937056db24d7fcec772142d19b757386'


@dataclass(frozen=True)
class SourceCut:
    id: str
    start: int
    end: int
    first_line: int
    last_line: int
    beat: int
    source: str = EDITION

    def public(self):
        return {'id': self.id, 'first_line': self.first_line, 'last_line': self.last_line,
                'beat': self.beat, 'source': self.source}


# Code-point ranges in the retained CRLF episode; line numbers in the complete
# Antigravity chronology. The bedroom flashback and other scenes stay unbound.
CUTS = (
    SourceCut('alley-through-reveal', 25411, 26987, 1739, 1773, 1),
    SourceCut('alley-aftermath', 26987, 29178, 1774, 1838, AWAKENING_BEAT),
    SourceCut('living-room-followup', 34382, 35104, 1909, 1914, 3),
)

# The saved MO2 graph already numbers the nanite transfer and the resulting
# form 13 and 14. An exact manuscript receipt locates those same graph beats.
SPRING_CUTS = (
    SourceCut('spring-nanite-transfer', 13283, 13560, 153, 161, 13, SPRING_SOURCE),
    SourceCut('spring-nurse-arrival', 13560, 15182, 162, 167, 14, SPRING_SOURCE),
)


def managed(c):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='imported_episode_sources'").fetchone():
        return False
    return c.execute('SELECT 1 FROM imported_episode_sources WHERE episode=? AND edition=?',
                     (EPISODE, EDITION)).fetchone() is not None


def approved(c):
    """Return the source receipt only if its saved text and existing permission match."""
    if not managed(c):
        return None
    row = c.execute("""SELECT ep.branch,ep.head,r.script,r.source_name,r.script_sha256,
        ev.status,ev.permitted,ev.viewpoint,ev.reviewer,ev.content,
        fb.character_id,fb.form_id,fb.action
        FROM episodes ep
        JOIN revisions r ON r.episode=ep.id AND r.revision=ep.head
        JOIN events ev ON ev.episode=ep.id AND ev.id=?
        LEFT JOIN event_form_bindings fb ON fb.event=ev.id
        WHERE ep.id=? AND ep.status!='archived'""", (EVENT, EPISODE)).fetchone()
    if (not row or row['branch'] != 'main' or row['status'] != 'approved' or not row['permitted']
            or row['viewpoint'] is not None or not row['reviewer'].strip() or row['content'] != EVENT_TEXT
            or row['source_name'] != EDITION or row['script_sha256'] != SCRIPT_SHA256
            or hashlib.sha256(row['script'].encode('utf-8')).hexdigest() != SCRIPT_SHA256
            or (row['form_id'] and (row['character_id'], row['form_id'], row['action']) != FORM)):
        return None
    return {'edition': EDITION, 'episode_revision': row['head'], 'script_sha256': SCRIPT_SHA256,
            'first_line': 1772, 'last_line': 1772, 'start': 26539, 'end': 26985}


def windows(c, episode):
    if episode == EPISODE:
        return CUTS if approved(c) else ()
    if episode != SPRING_EPISODE:
        return ()
    row = c.execute("""SELECT ep.branch,r.source_name,r.script_sha256,r.script,r.graph
        FROM episodes ep JOIN revisions r ON r.episode=ep.id AND r.revision=ep.head
        JOIN project_scope p ON p.singleton=1 AND p.kind='afm-starters'
        WHERE ep.id=? AND ep.status!='archived'""", (SPRING_EPISODE,)).fetchone()
    if (row and row['branch'] == 'main' and row['source_name'] == SPRING_SOURCE
            and row['script_sha256'] == SPRING_SCRIPT_SHA256
            and hashlib.sha256(row['script'].encode('utf-8')).hexdigest() == SPRING_SCRIPT_SHA256
            and hashlib.sha256(row['graph'].encode('utf-8')).hexdigest() == SPRING_GRAPH_SHA256):
        return SPRING_CUTS
    return ()


def cut_for(start, end, cuts=None):
    windows = CUTS if cuts is None else cuts
    return next((cut for cut in windows if cut.start <= start < end <= cut.end), None)


def project_event(row, receipt):
    """Project the effective time and form without changing the original event."""
    character, form, action = FORM
    return dict(row, beat=AWAKENING_BEAT, form_character=character, form_id=form, form_action=action,
                source_id=f'{EDITION}:HOT_SCOOMP_COMPLETE_CHRONOLOGY.md:1772',
                source_timing=receipt, known_to=list(WITNESSES))


def visible_to(event, viewpoint):
    if 'source_timing' in event:
        return viewpoint is None or viewpoint in event['known_to']
    return event['viewpoint'] is None or event['viewpoint'] == viewpoint
