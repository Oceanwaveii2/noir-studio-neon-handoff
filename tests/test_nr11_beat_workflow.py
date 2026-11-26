import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import numpy as np

from story_graph.episode_timeline import TimelineStore
from story_graph.beat_map import map_episode, _link_unique_dialogue
from story_graph.character_forms import AFM_JUNCTIONS
from prose_engine.notebook import NotebookStore, DraftStore
from prose_engine.beat_workflow import generate_group


class Provider:
    def __init__(self): self.prompts=[]
    def generate_rewrite(self,request,prompt):
        self.prompts.append(prompt)
        return request.original_text+' revised.'


class BeatWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=TimelineStore(Path(self.temp.name)/'timeline.sqlite')
        self.store.create_episode('sample','Sample','main',1)
        self.text='INT. ROOM\r\n\r\nA quiet arrival.\r\n\r\nA later response.\r\n\r\nEXT. GARDEN\r\n\r\nA new scene.'
        self.store.save('sample',0,script=self.text,source_name='fixture')
        self.nb=NotebookStore(self.store);n=self.nb.open('sample')
        self.nb.save('sample',n['revision'],1,n['blocks'],25,n['masks'])
        self.mapping=map_episode(self.store,'sample',1)
        self.req={'episode':'sample','revision':1,'project':self.mapping['project_id'],
            'universe':self.mapping['universe_id'],'branch':'main','source_sha256':self.mapping['source_sha256'],
            'beats':[b['id'] for b in self.mapping['beats'][:2]],'provider':'codex-session',
            'references':'none','scene_function':'comedy','direction':'Give the pause a lighter touch.'}

    def test_mapping_preserves_source_ranges_and_never_guesses_timeline(self):
        self.assertEqual([s['title'] for s in self.mapping['scenes']],['INT. ROOM','EXT. GARDEN'])
        self.assertEqual([b['text'] for b in self.mapping['beats']],['A quiet arrival.','A later response.','A new scene.'])
        for beat in self.mapping['beats']:
            self.assertEqual(self.text[beat['start']:beat['end']],beat['text'])
            self.assertEqual((beat['scope_beat'],beat['timing']),(0,'unverified'))
        self.assertEqual(map_episode(self.store,'sample',1),self.mapping)
        with self.assertRaisesRegex(ValueError,'changed'):map_episode(self.store,'sample',0)

    def test_existing_graph_links_only_unique_unambiguous_dialogue(self):
        def node(name,*lines):return SimpleNamespace(name=name,raw_dialogue=[{'text':line} for line in lines])
        graph=SimpleNamespace(validate=lambda:['g1','g2'],nodes={
            'g1':node('Arrival','Hello there.','Repeated phrase.','One line.'),
            'g2':node('Departure','Goodbye.','Another line.')})
        texts=['“Hello there.”','Repeated phrase.','Repeated phrase.',
               'One line. Another line.','Goodbye.','Unmatched prose.']
        beats=[{'text':text,'scope_beat':0} for text in texts]
        _link_unique_dialogue('\n\n'.join(texts),beats,graph)
        self.assertEqual(beats[0]['graph_match']['beat_id'],'g1')
        self.assertEqual(beats[4]['graph_match']['beat_id'],'g2')
        self.assertNotIn('graph_match',beats[1]);self.assertNotIn('graph_match',beats[2])
        self.assertEqual(beats[3]['graph_match_status'],'ambiguous')
        self.assertNotIn('graph_match',beats[3]);self.assertNotIn('graph_match',beats[5])
        self.assertTrue(all(b['scope_beat']==0 for b in beats))

    def test_markdown_scene_headings_are_not_passage_beats(self):
        self.store.create_episode('heading','Heading','main',2)
        self.store.save('heading',0,script='## SCENE 1: KITCHEN\n\nA paragraph.',source_name='fixture')
        mapped=map_episode(self.store,'heading',1)
        self.assertEqual(len(mapped['scenes']),1)
        self.assertTrue(mapped['scenes'][0]['explicit'])
        self.assertEqual([b['text'] for b in mapped['beats']],['A paragraph.'])

    def test_graph_evidence_requires_matching_episode_and_source_version(self):
        root=Path(self.temp.name)/'references';(root/'work/americandad').mkdir(parents=True)
        (root/'story_graph/scenarios').mkdir(parents=True)
        (root/'work/americandad/foxy_mo2_hybrid_novel.md').write_text('Hello there.',encoding='utf-8')
        (root/'work/americandad/foxy_spring_breakup_prose_engine_master.md').write_text('Goodbye.',encoding='utf-8')
        (root/'story_graph/scenarios/foxy_mo2_dag.py').write_text('mo2 graph',encoding='utf-8')
        (root/'story_graph/scenarios/spring_breakup_dag.py').write_text('legacy graph',encoding='utf-8')
        node=lambda text:SimpleNamespace(name='A graph beat',raw_dialogue=[{'text':text}])
        mo2=SimpleNamespace(validate=lambda:['mo2'],nodes={'mo2':node('Hello there.')})
        legacy=SimpleNamespace(validate=lambda:['legacy'],nodes={'legacy':node('Goodbye.')})
        store=TimelineStore(Path(self.temp.name)/'afm.sqlite');store.add_starter_cards()
        store.save('spring-break',0,script='Hello there.',source_name='fixture')
        store.save('hot-scoomp',0,script='Hello there.',source_name='fixture')
        with patch('story_graph.beat_map._REFERENCE_ROOT',root), \
             patch('story_graph.scenarios.foxy_mo2_dag.build_foxy_mo2_dag',return_value=mo2), \
             patch('story_graph.scenarios.spring_breakup_dag.build_spring_breakup_dag',return_value=legacy):
            mapped=map_episode(store,'spring-break',1)
            self.assertEqual(mapped['graph_evidence']['id'],'spring-break-mo2')
            self.assertEqual(mapped['beats'][0]['graph_match']['beat_id'],'mo2')
            self.assertNotIn('graph_evidence',map_episode(store,'hot-scoomp',1))
            store.save('spring-break',1,script='Hello there. changed',source_name='fixture')
            self.assertNotIn('graph_evidence',map_episode(store,'spring-break',2))
            store.save('spring-break',2,script='Goodbye.',source_name='fixture')
            mapped=map_episode(store,'spring-break',3)
            self.assertEqual(mapped['graph_evidence']['id'],'spring-breakup-legacy')
            self.assertEqual(mapped['beats'][0]['graph_match']['beat_id'],'legacy')

    def test_group_generates_separate_packets_and_one_recoverable_draft(self):
        self.store.add_event('future','sample',2,'Hidden future secret arrives.',status='approved',permitted=True,source_id='fixture',reviewer='author')
        provider=Provider()
        result=generate_group(self.store,self.req,provider_factory=lambda:provider)
        self.assertEqual(result['status'],'PROPOSED',result)
        self.assertEqual(len(provider.prompts),2)
        self.assertIn('Give the pause a lighter touch.',provider.prompts[0])
        self.assertNotIn('A later response.',provider.prompts[0])
        self.assertNotIn('Hidden future secret arrives.',provider.prompts[0])
        self.assertEqual(self.store.get_episode('sample')['script'],self.text)
        drafts=DraftStore(self.nb);draft=drafts.open('sample','main',result['draft_id'])
        self.assertEqual(draft['issue']['kind'],'beat_group')
        state=self.nb.existing('sample')
        applied=drafts.use('sample','main',result['draft_id'],state['revision'],1)
        self.assertIn('A quiet arrival. revised.',self.store.get_episode('sample')['script'])
        self.nb.undo('sample',applied['revision'],applied['timeline_revision'])
        self.assertEqual(self.store.get_episode('sample')['script'],self.text)

    def test_stale_selection_and_missing_book_policy_send_no_requests(self):
        provider=Provider()
        with self.assertRaisesRegex(ValueError,'Source changed'):
            generate_group(self.store,{**self.req,'source_sha256':'stale'},provider_factory=lambda:provider)
        with self.assertRaises(Exception):
            generate_group(self.store,{**self.req,'references':'topic'},books_root=Path(self.temp.name),provider_factory=lambda:provider)
        self.assertEqual(provider.prompts,[])

    def test_eligible_book_passages_are_bound_to_group_draft(self):
        from prose_engine.embedding_store import EmbeddingIndex
        root=Path(self.temp.name)/'books';root.mkdir()
        (root/'reference_policy.json').write_text(json.dumps({'schema_version':1,'sources':{'allowed':{'enabled':True,'permissions':['rank_local','prompt','remote_transfer']}}}),encoding='utf-8')
        (root/'vector_index.joblib').write_bytes(b'fixture index')
        passage='A licensed passage demonstrating the rise and fall of a sentence.'
        model=SimpleNamespace(encode=lambda texts,**kw:np.ones((len(texts),1),dtype='float32'))
        index=EmbeddingIndex([passage],[{'book':'allowed'}],np.ones((1,1),dtype='float32'),_model=model)
        provider=Provider()
        with patch('prose_engine.embedding_store.load_index',return_value=index):
            result=generate_group(self.store,{**self.req,'references':'topic'},books_root=root,provider_factory=lambda:provider)
        self.assertEqual(result['status'],'PROPOSED',result)
        self.assertTrue(all(passage in prompt for prompt in provider.prompts))
        draft=DraftStore(self.nb).open('sample','main',result['draft_id'])
        self.assertEqual(len(draft['reference_receipts']),2)
        (root/'vector_index.joblib').write_bytes(b'changed index')
        state=self.nb.existing('sample')
        with self.assertRaisesRegex(ValueError,'changed'):
            DraftStore(self.nb).use('sample','main',result['draft_id'],state['revision'],1,books_root=root)
        self.assertEqual(self.store.get_episode('sample')['script'],self.text)

    def test_failure_retains_completed_passage_draft_without_combining(self):
        class Interrupted(Provider):
            def generate_rewrite(self,request,prompt):
                if self.prompts: raise RuntimeError('Session interrupted')
                return super().generate_rewrite(request,prompt)
        provider=Interrupted()
        result=generate_group(self.store,self.req,provider_factory=lambda:provider)
        self.assertEqual(result['status'],'PARTIAL')
        self.assertEqual(len(result['completed']),1)
        drafts=DraftStore(self.nb).list('sample','main')
        self.assertEqual([d['status'] for d in drafts],['PROPOSED','UNKNOWN'])
        self.assertEqual(self.store.get_episode('sample')['script'],self.text)

    def test_exact_protection_keeps_passages_without_a_writer(self):
        state=self.nb.existing('sample')
        self.nb.save('sample',state['revision'],1,state['blocks'],100,state['masks'])
        provider=Provider()
        result=generate_group(self.store,self.req,provider_factory=lambda:provider)
        self.assertEqual(result['status'],'PROPOSED')
        self.assertEqual(len(provider.prompts),0)
        draft=DraftStore(self.nb).open('sample','main',result['draft_id'])
        self.assertEqual(draft['source_text'],draft['text'])
        self.assertEqual(self.store.get_episode('sample')['script'],self.text)

    def test_scene_boundaries_and_unfinished_empty_block(self):
        ids=[self.mapping['beats'][1]['id'],self.mapping['beats'][2]['id']]
        with self.assertRaisesRegex(ValueError,'one scene'):
            generate_group(self.store,{**self.req,'beats':ids},provider_factory=lambda:Provider())
        state=self.nb.existing('sample')
        state=self.nb.append_block('sample',state['revision'],1,'narrator')
        count=len(state['blocks'])
        state=self.nb.append_block('sample',state['revision'],state['timeline_revision'],'character','roger',junctions=AFM_JUNCTIONS)
        self.assertEqual(len(state['blocks']),count)
        self.assertEqual((state['blocks'][-1]['kind'],state['blocks'][-1]['speaker']),('character','roger'))

    def test_group_draft_and_scope_survive_sqlite_backup_restore(self):
        from tools.u10_backup import backup
        self.store.add_event('future','sample',2,'A hidden later event.',status='approved',permitted=True,source_id='fixture',reviewer='author')
        provider=Provider()
        result=generate_group(self.store,self.req,provider_factory=lambda:provider)
        self.assertEqual(result['status'],'PROPOSED',result)
        destination=Path(self.temp.name)/'restored.sqlite'
        backup(Path(self.store.path),destination)
        restored=TimelineStore(destination);notebook=NotebookStore(restored);drafts=DraftStore(notebook)
        self.assertEqual(restored.scope(),self.store.scope())
        self.assertEqual(restored.get_episode('sample'),self.store.get_episode('sample'))
        self.assertEqual(map_episode(restored,'sample',1),self.mapping)
        self.assertEqual(restored.resolve('sample',0),[])
        self.assertEqual(notebook.existing('sample'),self.nb.existing('sample'))
        self.assertEqual(drafts.open('sample','main',result['draft_id']),DraftStore(self.nb).open('sample','main',result['draft_id']))
        self.assertEqual(len(drafts.list('sample','main')),3)
        state=notebook.existing('sample')
        drafts.use('sample','main',result['draft_id'],state['revision'],1)
        self.assertIn('A quiet arrival. revised.',restored.get_episode('sample')['script'])
        self.assertEqual(self.store.get_episode('sample')['script'],self.text)

    def test_character_and_narrator_blocks_survive_save_and_undo(self):
        state=self.nb.existing('sample')
        with self.assertRaisesRegex(ValueError, 'character graph'):
            self.nb.append_block('sample',state['revision'],1,'character','made-up',junctions=AFM_JUNCTIONS)
        state=self.nb.append_block('sample',state['revision'],1,'character','francine',junctions=AFM_JUNCTIONS)
        self.assertEqual((state['blocks'][-1]['kind'],state['blocks'][-1]['speaker']),('character','francine'))
        end=len(''.join(b['text'] for b in state['blocks']))
        state=self.nb.edit_text('sample',state['revision'],state['timeline_revision'],end,end,'Hello.')
        self.assertEqual((state['blocks'][-1]['kind'],state['blocks'][-1]['text']),('character','Hello.'))
        before=state
        state=self.nb.append_block('sample',state['revision'],state['timeline_revision'],'narrator')
        self.assertEqual(state['blocks'][-1]['kind'],'narrator')
        state=self.nb.undo('sample',state['revision'],state['timeline_revision'])
        self.assertEqual(state['blocks'],before['blocks'])


if __name__=='__main__':unittest.main()
