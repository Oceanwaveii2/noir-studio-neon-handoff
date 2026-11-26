import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prose_engine.notebook import NotebookStore, remap_masks
from prose_engine.source_migration import publish_bundle, publish_workspace, verify_bundle, native_copy
from story_graph.episode_timeline import TimelineStore
from story_graph.source_imports import blocks, load_source, snapshot


class SourceMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'
        (self.source / 'out/graphs').mkdir(parents=True)
        (self.source / 'narrative_composer/config/graph/characters').mkdir(parents=True)
        text = ('# PRELUDE\r\n\r\nEarlier.\r\n\r\n# SPRING BREAK\r\n\r\n'
                'RAINEE\r\n\r\n“Hello there.”\r\n\r\n'
                'PETER ARRIVES\r\n\r\nRAINEE\r\n\r\n“Later words.”\r\n\r\n'
                '# HOT SCOOMP\r\n\r\nLater episode.\r\n')
        (self.source / 'HOT_SCOOMP_COMPLETE_CHRONOLOGY.md').write_bytes(text.encode())
        graph = {'schema_version': 1, 'state_instances': [
            {'id':'previous-episode','entity':'rainee','state_id':'rainee.state.changed','at':{'line':3},'source':'explicit','evidence':'Earlier.'},
            {'id':'first','entity':'rainee','state_id':'rainee.state.base','at':{'line':7},'source':'explicit','evidence':'RAINEE'},
            {'id':'later','entity':'rainee','state_id':'rainee.state.changed','at':{'line':11},'source':'explicit','evidence':'PETER ARRIVES'}],
            'transform_instances': [], 'edges': [], 'canon_leaks': [], 'unresolved_cues': []}
        chain = {'schema_version':1,'nodes':[{'type':'text_source','params':{'text':text.replace('\r\n','\n')}}]}
        report = {'discoveries':{'entities':[]},'violations':[]}
        definition = {'entity_id':'rainee','display_name':'Rainee','base_state':'base','aliases':['RAINEE'],
                      'states':[{'id':'rainee.state.changed','label':'Changed','cue_aliases':[]}],'transforms':[]}
        for rel, data in [('out/graphs/master.graph.json',graph),('out/graphs/master.chain.json',chain),
                          ('out/graphs/master.report.json',report),('narrative_composer/config/graph/characters/rainee.json',definition)]:
            (self.source / rel).write_text(json.dumps(data),encoding='utf-8')

    def make_workspace(self):
        bundle = publish_bundle(self.source, self.root / 'bundles')
        receipt = publish_workspace(bundle, self.root / 'workspace')
        return bundle, receipt, TimelineStore(self.root / 'workspace/timeline.sqlite')

    def test_crlf_correspondence_and_exact_speaker_blocks(self):
        payload = load_source(self.source)
        self.assertEqual(payload['correspondence'], 'CRLF/LF-only; original bytes retained')
        section = payload['sections'][1]
        items = blocks(payload, section)
        self.assertEqual(''.join(x['text'] for x in items), payload['text'][section['start']:section['end']])
        self.assertIn('rainee', [b['speaker'] for b in items if b['kind'] == 'character'])
        chain = self.source / 'out/graphs/master.chain.json'
        data = json.loads(chain.read_text(encoding='utf-8'))
        data['nodes'][0]['params']['text'] += 'changed'
        chain.write_text(json.dumps(data),encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'does not correspond'):
            load_source(self.source)

    def test_workspace_copy_idempotence_and_restore(self):
        bundle, receipt, store = self.make_workspace()
        self.assertEqual(verify_bundle(bundle)['edition'], receipt['edition'])
        self.assertEqual(publish_workspace(bundle,self.root/'workspace')['edition'],receipt['edition'])
        n = NotebookStore(store).open('spring-break')
        self.assertEqual(n['default_protection'],100)
        self.assertTrue(any(b['speaker']=='rainee' for b in n['blocks']))
        backup = self.root/'restored.sqlite'
        native_copy(self.root/'workspace/timeline.sqlite',backup)
        self.assertEqual(NotebookStore(TimelineStore(backup)).open('spring-break')['blocks'],n['blocks'])

    def test_edited_text_retains_only_safe_source_alignment(self):
        _, _, store = self.make_workspace()
        notebooks = NotebookStore(store)
        n = notebooks.open('spring-break')
        n = notebooks.save('spring-break',n['revision'],n['timeline_revision'],n['blocks'],25,n['masks'])
        n = notebooks.edit_text('spring-break',n['revision'],n['timeline_revision'],0,0,'Edited. ')
        from prose_engine.notebook import digest
        with store._connect() as c:
            episode = c.execute('SELECT script,graph FROM revisions WHERE episode=? AND revision=?',
                                ('spring-break',n['timeline_revision'])).fetchone()
            fallback = snapshot(c,'spring-break',n['timeline_revision'],episode['script'],digest(episode['graph']),0,5)
            self.assertEqual(fallback['alignment'],'conservative-episode-start')
            self.assertFalse(any(x['state_id']=='rainee.state.changed' for x in fallback['characters']))
            position = 0
            for block in n['blocks']:
                if block['speaker'] == 'rainee': break
                position += len(block['text'])
            aligned = snapshot(c,'spring-break',n['timeline_revision'],episode['script'],digest(episode['graph']),position,position+5)
            self.assertEqual(aligned['alignment'],'unchanged-source-block')
            self.assertFalse(any(x['state_id']=='rainee.state.changed' for x in aligned['characters']))
            with self.assertRaisesRegex(ValueError,'graph changed'):
                snapshot(c,'spring-break',n['timeline_revision'],episode['script'],'wrong',position,position+5)

    def test_unchanged_and_empty_masks_do_not_compare_long_documents(self):
        text = 'a' * 100000
        with patch('prose_engine.notebook.difflib.SequenceMatcher', side_effect=AssertionError('unnecessary comparison')):
            self.assertEqual(remap_masks(text,text,[]),[])

    def test_imported_character_context_reaches_mock_scoped_generation_after_edit(self):
        from prose_engine.scoped_service import execute_scoped
        _, _, store = self.make_workspace()
        notebooks = NotebookStore(store)
        n = notebooks.open('spring-break')
        n = notebooks.save('spring-break',n['revision'],n['timeline_revision'],n['blocks'],25,n['masks'])
        n = notebooks.edit_text('spring-break',n['revision'],n['timeline_revision'],0,0,'Edited. ')
        position = 0
        for block in n['blocks']:
            if block['speaker'] == 'rainee': break
            position += len(block['text'])
        class Provider:
            prompts = []
            def generate_rewrite(self, request, prompt):
                self.prompts.append(prompt)
                return request.original_text + ' She paused.'
        provider = Provider()
        request = {'episode':'spring-break','beat':0,'revision':n['timeline_revision'],
                   'start':position,'end':position+len(block['text'].strip()),
                   'provider':'codex-session','references':'none','scene_function':'scene'}
        result = execute_scoped(store,'generate',request,provider_factory=lambda:provider)
        self.assertEqual(result['status'],'PROPOSED')
        self.assertEqual(len(provider.prompts),1)
        self.assertIn('unchanged-source-block',provider.prompts[0])
        self.assertNotIn('rainee.state.changed',provider.prompts[0])

    def test_selected_workspace_has_its_own_form_store(self):
        from unittest.mock import MagicMock
        from tools.studio_ui import run_server
        chosen = self.root / 'selected'
        chosen.mkdir()
        server = MagicMock()
        with patch('prose_engine.source_migration.selected_workspace',return_value=(chosen,{'initial_episode':'spring-break'})), \
             patch('tools.studio_ui.ThreadingHTTPServer',return_value=server), \
             patch('tools.studio_ui.FormGraphStore') as form_store:
            run_server(0)
        self.assertEqual(form_store.call_args.args[0],chosen/'character-forms.sqlite')
        self.assertEqual(server.timeline_path,chosen/'timeline.sqlite')
        self.assertEqual(server.initial_episode,'spring-break')

    def test_speaker_correction_preserves_text_and_survives_reopen(self):
        _, _, store = self.make_workspace()
        notebooks = NotebookStore(store)
        state = notebooks.open('spring-break')
        block = next(x for x in state['blocks'] if x['speaker']=='rainee')
        text = store.get_episode('spring-break')['script']
        options = notebooks.speaker_options('spring-break',block['id'])['options']
        self.assertTrue(any(o['character']=='rainee' for o in options))
        state = notebooks.bind_speaker('spring-break',state['revision'],state['timeline_revision'],block['id'],None,None)
        updated = next(x for x in notebooks.open('spring-break')['blocks'] if x['id']==block['id'])
        self.assertEqual(updated['kind'],'narrator')
        self.assertEqual(store.get_episode('spring-break')['script'],text)


if __name__ == '__main__': unittest.main()
