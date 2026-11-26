import base64
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from prose_engine.cook import run_cook_pipeline
from prose_engine.episode_commands import EpisodeCommands
from prose_engine.notebook import NotebookStore, digest, joined
from story_graph.beat_map import map_episode
from story_graph.episode_timeline import TimelineStore
from story_graph.form_graph_store import FormGraphStore
from story_graph.scene_fragments import SceneFragmentStore
from story_graph.source_imports import junctions
from tools.bundle_books import bundle


class LosslessPreparationTests(unittest.TestCase):
    def test_reconcile_cue_layout_preserves_text_and_can_be_undone(self):
        with tempfile.TemporaryDirectory() as directory:
            timeline = TimelineStore(Path(directory) / 'timeline.sqlite')
            timeline.create_episode('pilot', 'Pilot', 'main', 0)
            cue = 'CHARACTER'
            text = cue + 'Hello 🗝!\r\n\r\nA stage direction.\r\n'
            timeline.save('pilot', 0, script=text, source_name='original.txt')
            notebooks = NotebookStore(timeline)
            state = notebooks.open('pilot')
            start = text.index('Hello')
            mask = dict(id='lock', start=start, end=start + 7, value=100, hard=True,
                        sha256=digest(text[start:start + 7]))
            state = notebooks.save('pilot', 0, 1, state['blocks'], 50, [mask])
            # Recreate the older, divergent-head condition without changing the episode.
            old = dict(state, blocks=[dict(b) for b in state['blocks']])
            old['blocks'][-1]['text'] += 'An unsynced note.'
            with timeline._connect() as c:
                c.execute('INSERT INTO notebook_revisions VALUES(?,?,?,?)', ('pilot', 2, 1, json.dumps(old)))
                c.execute("UPDATE notebook_heads SET head=2 WHERE episode='pilot'")
            request = dict(preference='episode', timeline_head=1, notebook_head=2,
                           episode_sha=digest(text), notebook_sha=digest(joined(old['blocks'])))
            block = state['blocks'][0]
            spec = dict(block=block['id'], prefix=cue, speaker='character', form=None,
                        block_sha256=digest(block['text']))
            with self.assertRaisesRegex(ValueError, 'no longer matches'):
                notebooks.reconcile_versions('pilot', **request, speaker_cues=[dict(spec, prefix='DIFFERENT')])
            self.assertEqual((timeline.get_episode('pilot')['head'], notebooks.existing('pilot')['revision']), (1, 2))

            current = notebooks.reconcile_versions('pilot', **request, speaker_cues=[spec])
            self.assertEqual((current['timeline_revision'], current['revision']), (2, 4))
            self.assertEqual(current['blocks'][0]['cue_prefix'], cue)
            self.assertEqual(current['masks'], [mask])
            self.assertEqual(joined(current['blocks']).encode(), text.encode())
            undone = notebooks.undo('pilot', 4, 2)
            self.assertNotIn('cue_prefix', undone['blocks'][0])
            redone = notebooks.redo('pilot', undone['revision'], 2)
            self.assertEqual(redone['blocks'], current['blocks'])
            self.assertEqual(redone['masks'], [mask])
            self.assertEqual(timeline.get_episode('pilot')['script'], text)

    def test_prepare_preserves_exact_text_and_protection_repeats_and_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timeline, forms = TimelineStore(root/'timeline.sqlite'), FormGraphStore(root/'forms.sqlite')
            timeline.create_episode('pilot', 'Pilot', 'main', 0)
            raw = ('\r\n## Atrium\r\n  Intro 🗝.  \r\n\t\r\n'
                   'FRANCINE (quiet): Exact 🗝.\r\n(pause)\r\n'
                   '## Corridor\r\n  Wait here. \nUNLISTED: Continue.\r\n')
            timeline.save('pilot', 0, script=raw, source_name='pilot.txt')
            nb = NotebookStore(timeline)
            original = nb.open('pilot')
            start = raw.index('Exact')
            text = 'Exact 🗝.'
            masks = [dict(id='exact', start=start, end=start + len(text), value=100,
                          hard=True, sha256=digest(text))]
            original = nb.save('pilot', original['revision'], 1, original['blocks'], 100, masks)
            with patch('story_graph.beat_map.map_episode', side_effect=ValueError('Map fault')):
                with self.assertRaisesRegex(ValueError, 'Map fault'):
                    run_cook_pipeline(timeline, forms, 'pilot', expected_timeline_revision=1)
            self.assertEqual(nb.existing('pilot'), original)
            self.assertEqual(forms.read()['revision'], 0)
            self.assertEqual(timeline.get_episode('pilot')['script'], raw)
            with timeline._connect() as connection:
                self.assertFalse(junctions(connection, {}))
            with patch.object(SceneFragmentStore, '_insert', side_effect=ValueError('Graph write fault')):
                with self.assertRaisesRegex(ValueError, 'Graph write fault'):
                    run_cook_pipeline(timeline, forms, 'pilot')
            self.assertEqual(nb.existing('pilot'), original)
            with timeline._connect() as connection:
                self.assertFalse(junctions(connection, {}))
            with self.assertRaisesRegex(ValueError, 'changed'):
                run_cook_pipeline(timeline, forms, 'pilot', expected_timeline_revision=0)

            result = run_cook_pipeline(timeline, forms, 'pilot', expected_timeline_revision=1,
                                       expected_notebook_revision=original['revision'])
            self.assertEqual(result['revision'], original['revision'] + 1)
            prepared = NotebookStore(TimelineStore(root/'timeline.sqlite')).existing('pilot')
            self.assertEqual(joined(prepared['blocks']).encode(), raw.encode())
            self.assertEqual(prepared['masks'], masks)
            self.assertEqual(timeline.get_episode('pilot')['head'], 1)
            self.assertEqual(timeline.get_episode('pilot')['script_sha256'], digest(raw))
            for block in prepared['blocks']:
                source = block['source']
                self.assertEqual(raw[source['start']:source['end']], block['text'])
                self.assertEqual(source['sha256'], digest(block['text']))
            self.assertIn('francine', [b.get('speaker') for b in prepared['blocks']])
            self.assertTrue(any(b['kind'] == 'stage-direction' for b in prepared['blocks']))
            fresh, = [b for b in prepared['blocks'] if b.get('cue_label') == 'UNLISTED']
            self.assertEqual(fresh['kind'], 'character')
            self.assertEqual(fresh['cue_prefix'], 'UNLISTED:')
            self.assertTrue(fresh['speaker'].startswith('cue-character-'))
            self.assertEqual(result['stage2']['characters_added'], 1)
            self.assertEqual(forms.read()['revision'], 0)
            repeated = run_cook_pipeline(timeline, forms, 'pilot')
            self.assertEqual(repeated['revision'], result['revision'])
            self.assertTrue(repeated['reused'])
            self.assertEqual(repeated['receipt'], result['receipt'])
            mapping = map_episode(timeline, 'pilot', 1)
            self.assertEqual([s['title'] for s in mapping['scenes']], ['## Atrium', '## Corridor'])
            self.assertTrue(all(beat['timing'] == 'unverified' for beat in mapping['beats']))
            self.assertTrue(all(raw[b['start']:b['end']] == b['text'] for b in mapping['beats']))
            rolled_back = nb.undo('pilot', prepared['revision'], 1)
            self.assertEqual(rolled_back['blocks'], original['blocks'])
            self.assertEqual(rolled_back['masks'], masks)

    def test_fresh_import_prepares_fountain_cues_graphs_and_reopenable_empty_sockets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'timeline.sqlite'
            timeline = TimelineStore(path)
            api = EpisodeCommands(timeline)
            raw = ('INT. GLASS ARCHIVE - NIGHT\r\n'
                   'World: The hall echoes. 🗝\r\n'
                   'STAGE DIRECTION: A bell sounds.\r\n\r\n'
                   '@Zélie\r\n(quietly)\r\nI know which shelf.\r\n\r\n'
                   'Inez Vale: This is the right door.\r\n\r\n'
                   'EXT. QUAY - DAWN\r\nInez Vale: A boat is waiting.\r\n')
            document = {'name':'unseen.fountain','base64':base64.b64encode(raw.encode()).decode()}
            preview = api.execute('intake.preview', {'document':document})['source']
            card = api.execute('intake.create', {
                'document':document, 'request_id':'unseen-import', 'title':'The glass archive',
                'file_sha256':preview['sha256'], 'text_sha256':preview['text_sha256'],
            })
            episode = card['episode']
            request = {'project':timeline.scope()['project_id'], 'universe':timeline.scope()['universe_id'],
                       'episode':episode, 'branch':'main', 'timeline_revision':0, 'notebook_revision':0}
            result = api.execute('episode.prepare', request)
            self.assertEqual(result['stage2']['characters_added'], 2)
            receipt = result['receipt']
            self.assertEqual(receipt['provider_calls'], 0)
            self.assertEqual([row['location']['label'] for row in receipt['fragments']], ['GLASS ARCHIVE', 'QUAY'])
            self.assertEqual(len(receipt['sockets']), 2)
            self.assertTrue(all(row['mind'] is None for row in receipt['sockets']))
            notebook = NotebookStore(timeline).existing(episode)
            self.assertEqual(joined(notebook['blocks']), raw)
            self.assertEqual(notebook['default_protection'], 100)
            self.assertTrue(any(b['kind']=='narrator' and b['text'].startswith('World:') for b in notebook['blocks']))
            utterance, = [b for b in notebook['blocks'] if b['text'].startswith('I know')]
            cue, = [b for b in notebook['blocks'] if b.get('cue_prefix') == '@Zélie']
            self.assertEqual(utterance['speaker'], cue['speaker'])
            reopened = EpisodeCommands(TimelineStore(path))
            self.assertEqual(reopened.execute('episode.preparation.open', request)['receipt'], receipt)
            for row in receipt['fragments']:
                scene = reopened.execute('scene.fragment.open', request | {'fragment':row['id']})['fragment']
                graph = scene['graph']
                self.assertEqual([e['kind'] for e in graph['edges']], ['sequence'] * (len(graph['nodes'])-1))
                for passage in graph['passages']:
                    self.assertEqual(digest(raw[passage['start']:passage['end']]), passage['sha256'])
                self.assertTrue(all(role['character_hint'] in {s['character'] for s in receipt['sockets']}
                                    for role in graph['roles']))
            story = api.execute('scene.timeline.open', {k:v for k,v in request.items() if k!='notebook_revision'})
            self.assertEqual(story['fragment'], receipt['fragments'][0]['id'])
            self.assertTrue(story['scenes'][0]['beats'])
            with timeline._connect() as connection:
                graph = FormGraphStore(timeline.form_graph_path, imported=junctions(connection, {}))
                self.assertEqual(connection.execute('SELECT count(*) FROM events').fetchone()[0], 0)
            port = receipt['sockets'][0]['port']
            graph.change({'action':'create_mind_link','revision':0,'port':port,'label':'Author-selected mind',
                          'kind':'digital_mind'})
            new = reopened.execute('episode.prepare', request | {'notebook_revision':result['revision']})
            self.assertEqual(new['stage2']['characters_added'], 0)
            self.assertEqual(new['receipt']['fragments'], receipt['fragments'])
            self.assertTrue(next(s['mind'] for s in new['receipt']['sockets'] if s['port'] == port))

    def test_book_export_refuses_existing_destination_and_excludes_duplicate_copies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            books = root/'library'
            (books/'text').mkdir(parents=True)
            (books/'text'/'book.txt').write_bytes(b'one exact book')
            (books/'duplicate.txt').write_bytes(b'one exact book')
            with self.assertRaisesRegex(ValueError, 'outside'):
                bundle(books, books/'export')
            out = root/'export'
            archive, rows = bundle(books, out)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['source'], 'text/book.txt')
            with zipfile.ZipFile(archive) as z:
                self.assertEqual(z.read('export/text/book.txt'), b'one exact book')
            before = archive.read_bytes()
            with self.assertRaisesRegex(ValueError, 'new'):
                bundle(books, out)
            self.assertEqual(archive.read_bytes(), before)
            self.assertEqual((books/'duplicate.txt').read_bytes(), b'one exact book')
