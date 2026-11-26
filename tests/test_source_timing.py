import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from prose_engine.notebook import digest
from prose_engine.scoped_pipeline import build_packet, export_packet, generate, retrieve, validate_claims
from story_graph import source_timing
from story_graph.beat_map import map_episode
from story_graph.episode_timeline import TimelineStore


class SourceTimingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = TimelineStore(Path(tmp.name) / 'timeline.sqlite')
        self.store.add_starter_cards()
        early = 'They enter.\r\n\r\nThe change happens.\r\n\r\n'
        aftermath = 'She looks in a mirror.\r\n\r\n'
        self.text = early + aftermath + 'Five minutes earlier.\r\n'
        self.after = len(early)
        self.cut = len(early + aftermath)
        for name, value in (
            ('SCRIPT_SHA256', digest(self.text)),
            ('CUTS', (source_timing.SourceCut('lead', 0, self.after, 1, 4, 1),
                      source_timing.SourceCut('after', self.after, self.cut, 5, 6, 2))),
        ):
            p = patch.object(source_timing, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.store.save('hot-scoomp', 0, script=self.text, source_name=source_timing.EDITION)
        self.store.save('spring-break', 0, script='An earlier episode.', source_name='spring.txt')
        self.store.add_event(source_timing.EVENT, 'hot-scoomp', 0, source_timing.EVENT_TEXT,
                             status='approved', permitted=True, source_id='fixture', reviewer='author')
        # An older branch carried the historical beat-zero placeholder.
        self.store.fork('old-branch', 'main', 'hot-scoomp', 0)
        with self.store._connect() as c:
            c.executescript('''
                CREATE TABLE imported_editions (id TEXT PRIMARY KEY, payload TEXT, sha256 TEXT);
                CREATE TABLE imported_episode_sources (episode TEXT PRIMARY KEY, edition TEXT,
                    start INTEGER, end INTEGER, revision INTEGER, graph_sha256 TEXT);
            ''')
            payload = json.dumps({'edition': source_timing.EDITION, 'text': self.text,
                                  'graph': {'state_instances': []}, 'definitions': {},
                                  'diagnostics': {'canon_leaks': [], 'unresolved_cues': []}})
            c.execute('INSERT INTO imported_editions VALUES(?,?,?)', (source_timing.EDITION, payload, digest(payload)))
            graph_sha = digest(c.execute("SELECT graph FROM revisions WHERE episode='hot-scoomp' AND revision=1").fetchone()[0])
            c.execute('INSERT INTO imported_episode_sources VALUES(?,?,?,?,?,?)',
                      ('hot-scoomp', source_timing.EDITION, 0, len(self.text), 1, graph_sha))

    def packet(self, start, end, *, beat=0, viewpoint=None, episode='hot-scoomp', revision=1):
        return build_packet(self.store, episode, beat, revision, start, end, viewpoint)

    def test_exact_source_separates_physical_state_from_point_of_view(self):
        early = self.packet(0, len('They enter.'))
        later = self.packet(self.after, self.cut - 4)
        witnessed = self.packet(self.after, self.cut - 4, viewpoint='holly')
        unknown = self.packet(self.after, self.cut - 4, viewpoint='roger')
        self.assertEqual((early.beat, later.beat, unknown.beat), (1, 2, 2))
        self.assertEqual(later.passage_anchor['status'], 'source-verified')
        self.assertEqual([e['perspective'] for e in later.events], ['reader-revealed'])
        self.assertEqual([e['perspective'] for e in witnessed.events], ['witnessed'])
        claim = {'kind': 'active_form', 'subject': 'haley', 'value': 'awakened_haley_fox'}
        self.assertEqual(validate_claims(later, [claim]), [])
        for packet in (early, unknown, self.packet(self.cut, len(self.text)-2, beat=99)):
            self.assertFalse(retrieve(packet, 'awakens'))
            self.assertNotIn(source_timing.EVENT, export_packet(packet))
            self.assertTrue(validate_claims(packet, [claim]))

        class Capture:
            def generate_rewrite(self, request, prompt):
                self.facts = request.permitted_facts
                self.knowledge = request.character_epistemic_scope
                self.prompt = prompt
                return request.original_text

        capture = Capture()
        self.assertEqual(generate(witnessed, capture)['status'], 'PROPOSED')
        self.assertEqual(capture.knowledge, {'holly': [source_timing.EVENT]})
        self.assertIn(source_timing.EVENT_TEXT, capture.facts)
        self.assertEqual(generate(unknown, capture)['status'], 'PROPOSED')
        self.assertFalse(capture.facts)
        self.assertNotIn(source_timing.EVENT_TEXT, capture.prompt)

    def test_earlier_episodes_and_forks_do_not_inherit_the_placeholder(self):
        self.assertFalse(self.packet(0, 15, beat=99, episode='spring-break').events)
        self.store.fork('early', 'main', 'hot-scoomp', 1)
        self.store.fork('later', 'main', 'hot-scoomp', 2)
        for branch in ('old-branch', 'early', 'later'):
            self.store.create_episode(branch + '-ep', 'Branch episode', branch, 1)
        self.assertFalse(self.store.resolve('old-branch-ep', 99))
        self.assertFalse(self.store.resolve('early-ep', 99))
        self.assertEqual([ev['id'] for ev in self.store.resolve('later-ep', 0)], [source_timing.EVENT])
        self.assertFalse(self.store.prerequisites('tapped-out'))

    def test_revised_source_cannot_use_a_previously_displayed_cutoff(self):
        before = map_episode(self.store, 'hot-scoomp', 1)
        self.assertTrue(any(b['timing'] == 'source-verified' for b in before['beats']))
        self.store.save('hot-scoomp', 1, script=self.text + 'An edit.', source_name=source_timing.EDITION)
        after = map_episode(self.store, 'hot-scoomp', 2)
        self.assertTrue(all(b['timing'] == 'unverified' for b in after['beats']))
        self.assertFalse(self.packet(self.after, self.cut - 4, beat=99, revision=2).events)
        self.assertTrue(self.store.prerequisites('tapped-out'))
