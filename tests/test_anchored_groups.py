import json
from pathlib import Path
from unittest.mock import patch

from tests.test_beat_anchors import AnchorFixture
from story_graph.beat_rhythm import BeatRhythmStore, defaults
from prose_engine.beat_workflow import generate_group, preview_group
from prose_engine.notebook import NotebookStore, DraftStore
from prose_engine.scoped_service import execute_scoped


class Provider:
    def __init__(self,callback=None,poison=False):self.prompts=[];self.callback=callback;self.poison=poison
    def generate_rewrite(self,request,prompt):
        self.prompts.append(prompt)
        if self.callback:self.callback()
        return request.original_text+(' The violet crown glowed at dawn.' if self.poison else ' Lena waited.')


class AnchoredGroupTests(AnchorFixture):
    def setUp(self):
        super().setUp();self.bind();self.bind(1,'late')
        rhythm=BeatRhythmStore(self.store)
        rhythm.save('sample',1,1,0,{**defaults(),'pace':'slow','pause':'held'})
        rhythm.save('sample',5,1,0,{**defaults(),'pace':'fast','cadence':'punchy'})
        m=self.mapping()
        self.group={'episode':'sample','revision':1,'project':m['project_id'],'universe':m['universe_id'],'branch':'main',
                    'source_sha256':m['source_sha256'],'beats':[p['id'] for p in m['beats']],
                    'provider':'codex-session','references':'none','scene_function':'scene'}

    def generate(self,provider=None):return generate_group(self.store,self.group,provider_factory=lambda:provider or Provider())

    def apply(self,result,**kwargs):
        return self.drafts.use('sample','main',result['draft_id'],self.nb.existing('sample')['revision'],1,**kwargs)

    def test_mixed_cutoffs_preview_generate_apply_and_undo(self):
        preview=preview_group(self.store,self.group);provider=Provider();result=self.generate(provider)
        self.assertEqual(result['status'],'PROPOSED',result);self.assertEqual(len(provider.prompts),2)
        self.assertEqual([p['plan']['binding']['context']['beat'] for p in preview['rhythm_guidance']['passages']],[1,5])
        self.assertNotIn('violet crown',provider.prompts[0]);self.assertIn('violet crown',provider.prompts[1])
        self.assertIn('Give existing perceptions',provider.prompts[0]);self.assertIn('Compress redundant',provider.prompts[1])
        draft=self.drafts.open('sample','main',result['draft_id'])
        self.assertEqual([p['beat'] for p in draft['writing_context']['composite_scopes']],[1,5])
        self.assertEqual(draft['composite_segments'][1]['separator'],'\r\n\r\n')
        used=self.apply(result);self.assertIn('Lena waited.',self.store.get_episode('sample')['script'])
        self.nb.undo('sample',used['revision'],used['timeline_revision']);self.assertEqual(self.store.get_episode('sample')['script'],self.text)
        self.assertEqual(self.mapping()['beats'][0]['timing'],'stale')

    def test_earlier_candidate_cannot_use_later_fact(self):
        provider=Provider(poison=True);result=self.generate(provider)
        self.assertEqual(result['status'],'PARTIAL',result);self.assertEqual(len(provider.prompts),1)
        draft=self.drafts.list('sample','main')[0]
        self.assertEqual(draft['status'],'BLOCKED');self.assertIsNotNone(draft['passage_anchor'])
        self.assertIsNotNone(draft['rhythm_evidence']);self.assertEqual(self.store.get_episode('sample')['script'],self.text)

    def test_each_anchored_child_resolves_its_own_character_form(self):
        from story_graph.character_forms import CharacterForm, CharacterJunction
        junctions={'lena':CharacterJunction('lena',(CharacterForm('lena','Lena','base'),
                   CharacterForm('crowned_lena','Crowned Lena','transformation')))}
        self.store.add_event('form-change','sample',4,'Lena takes her crowned form.')
        self.store.bind_form_event('sample','form-change','lena','crowned_lena','active',junctions)
        self.store.review_event('sample','form-change','fixture author','fixture',True)
        self.bind(1,'late')
        result=generate_group(self.store,self.group,junctions=lambda:junctions,provider_factory=Provider)
        self.assertEqual(result['status'],'PROPOSED',result)
        contexts=self.drafts.open('sample','main',result['draft_id'])['writing_context']['composite_scopes']
        self.assertEqual([f['id'] for f in contexts[0]['forms']['lena']['forms']],['lena'])
        self.assertEqual(contexts[1]['characters']['lena']['active_form'],'crowned_lena')
        self.apply(result,junctions=junctions)

    def test_scoped_apply_adapter_uses_composite_not_request_latest_beat(self):
        result=self.generate();draft=self.drafts.open('sample','main',result['draft_id'])
        request={**self.group,'beat':5,'start':draft['start'],'end':draft['end'],
                 'draft':result['draft_id'],'notebook_revision':self.nb.existing('sample')['revision']}
        applied=execute_scoped(self.store,'apply-draft',request)
        self.assertEqual(applied['status'],'APPLIED')

    def test_displayed_anchor_token_prevents_silent_new_cutoff(self):
        token=self.mapping()['anchor_token'];self.bind(event='late')
        with self.assertRaisesRegex(ValueError,'anchors changed'):
            preview_group(self.store,{**self.group,'anchor_token':token})

    def test_single_child_apply_also_has_atomic_anchor_guard(self):
        result=self.generate();child=result['completed'][0]['draft_id'];original=self.nb.edit_text
        def race(*args,**kwargs):
            self.anchors.change('unbind',self.request())
            return original(*args,**kwargs)
        with patch.object(self.nb,'edit_text',side_effect=race):
            with self.assertRaises(ValueError):self.drafts.use('sample','main',child,self.nb.existing('sample')['revision'],1)
        self.assertEqual(self.store.get_episode('sample')['script'],self.text)

    def test_anchor_change_during_call_retains_stale_child_and_stops(self):
        provider=Provider(callback=lambda:self.bind(event='late'));result=self.generate(provider)
        self.assertEqual(result['status'],'PARTIAL');self.assertEqual(len(provider.prompts),1)
        draft=self.drafts.list('sample','main')[0];self.assertEqual(draft['status'],'STALE');self.assertIsNotNone(draft['text'])

    def test_anchor_change_before_apply_blocks_all_text(self):
        result=self.generate();self.assertEqual(result['status'],'PROPOSED',result)
        self.bind(event='late')
        with self.assertRaises(ValueError):self.apply(result)
        self.assertEqual(self.store.get_episode('sample')['script'],self.text)

    def test_rhythm_change_for_second_child_blocks_whole_apply(self):
        result=self.generate();BeatRhythmStore(self.store).save('sample',5,1,1,{**defaults(),'pace':'slow'})
        with self.assertRaises(ValueError):self.apply(result)
        self.assertEqual(self.store.get_episode('sample')['script'],self.text)

    def test_atomic_guard_catches_binding_change_after_reconstruction(self):
        result=self.generate();original=self.nb.edit_text
        def race(*args,**kwargs):
            self.bind(event='late')
            return original(*args,**kwargs)
        with patch.object(self.nb,'edit_text',side_effect=race):
            with self.assertRaises(ValueError):self.apply(result)
        self.assertEqual(self.store.get_episode('sample')['script'],self.text)

    def test_atomic_guard_checks_every_child_rhythm_not_only_first(self):
        result=self.generate();original=self.nb.edit_text
        def race(*args,**kwargs):
            BeatRhythmStore(self.store).save('sample',5,1,1,{**defaults(),'pause':'held'})
            return original(*args,**kwargs)
        with patch.object(self.nb,'edit_text',side_effect=race):
            with self.assertRaisesRegex(ValueError,'Beat direction changed'):self.apply(result)
        self.assertEqual(self.store.get_episode('sample')['script'],self.text)

    def test_partial_apply_is_explicitly_rejected_not_widened(self):
        result=self.generate()
        with self.assertRaisesRegex(ValueError,'Partial composite'):self.apply(result,source_start=0,source_end=1,candidate_start=0,candidate_end=1)
        child=result['completed'][0]['draft_id'];n=self.nb.existing('sample')
        used=self.drafts.use('sample','main',child,n['revision'],1)
        self.assertGreater(used['timeline_revision'],1)

    def test_native_sqlite_restore_preserves_anchor_history_and_composite_apply(self):
        from tools.u10_backup import backup
        result=self.generate();destination=Path(self.tmp.name)/'restore.sqlite';backup(Path(self.store.path),destination)
        restored=type(self.store)(destination);drafts=DraftStore(NotebookStore(restored))
        self.assertEqual(drafts.open('sample','main',result['draft_id']),self.drafts.open('sample','main',result['draft_id']))
        self.assertEqual(restored.get_episode('sample')['script'],self.text)
        n=self.nb.existing('sample');drafts.use('sample','main',result['draft_id'],n['revision'],1)
        with restored._connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM passage_anchor_revisions').fetchone()[0],2)

    def test_legacy_group_accepts_only_built_in_relationship_projection(self):
        result = self.generate()
        self.assertEqual(result['status'], 'PROPOSED')
        edge = {'from': {'character': 'francine', 'form': 'francine'},
                'to': {'character': 'rainee', 'form': 'rainee'}, 'kind': 'spouse',
                'source': 'foxy-mo2-ontology:kinship:francine:rainee'}
        override = edge | {'override': {'guidance': 'Use a new tone.'}}
        # The second child can gain a projection independently of the first.
        with patch('story_graph.character_relationships.project',
                   side_effect=lambda *args, beat, **kwargs: (override,) if beat == 5 else ()):
            with self.assertRaisesRegex(ValueError, 'relationship guidance'):
                self.apply(result)
        self.assertEqual(self.store.get_episode('sample')['script'], self.text)
        with patch('story_graph.character_relationships.project',
                   side_effect=lambda *args, beat, **kwargs: (edge,) if beat == 5 else ()):
            used = self.apply(result)
        self.assertGreater(used['timeline_revision'], 1)

    def test_interrupted_provider_keeps_prior_child_and_failure_record(self):
        provider=Provider();count=[]
        def factory():
            count.append(1)
            if len(count)==2:raise RuntimeError('injected connection interruption')
            return provider
        result=generate_group(self.store,self.group,provider_factory=factory)
        self.assertEqual(result['status'],'PARTIAL');self.assertEqual(len(result['completed']),1)
        self.assertEqual([d['status'] for d in self.drafts.list('sample','main')],['PROPOSED','FAILED'])

    def test_exact_masks_survive_composite_apply_and_recovery(self):
        n=self.nb.existing('sample');first=self.mapping()['beats'][0]
        from prose_engine.notebook import digest
        mask={'id':'exact','start':first['start'],'end':first['end'],'value':100,'hard':True,'sha256':digest(first['text'])}
        self.nb.save('sample',n['revision'],1,n['blocks'],25,[mask])
        class ExactProvider(Provider):
            def generate_rewrite(self,request,prompt):
                return request.original_text if 'Lena turned' in request.original_text else request.original_text+' Lena waited.'
        result=self.generate(ExactProvider());self.assertEqual(result['status'],'PROPOSED',result)
        used=self.apply(result);self.assertEqual(used['masks'][0]['sha256'],mask['sha256'])
        self.assertIn(first['text'],self.store.get_episode('sample')['script'])

    def test_composite_preserves_block_boundary_at_an_exact_child(self):
        from prose_engine.notebook import digest

        n = self.nb.existing('sample')
        first, second = self.mapping()['beats']
        mask = {'id': 'exact', 'start': first['start'], 'end': first['end'], 'value': 100,
                'hard': True, 'sha256': digest(first['text'])}
        self.nb.save('sample', n['revision'], 1, n['blocks'], 25, [mask])
        before = self.nb.existing('sample')
        replacement = 'A jewelled crown flashed with dawn light.'

        class Rephrase(Provider):
            def generate_rewrite(self, request, prompt):
                return request.original_text if request.original_text == first['text'] else replacement

        proposed = self.generate(Rephrase())
        self.assertEqual(proposed['status'], 'PROPOSED', proposed)
        applied = self.apply(proposed)
        self.assertEqual(applied['masks'], [mask])
        self.assertEqual(self.store.get_episode('sample')['script'], self.text[:second['start']] + replacement)
        metadata = lambda state: [{k: v for k, v in b.items() if k != 'text'} for b in state['blocks']]
        self.assertEqual(metadata(applied), metadata(before))
        undone = self.nb.undo('sample', applied['revision'], applied['timeline_revision'])
        self.assertEqual(undone['blocks'], before['blocks'])
        self.assertEqual(undone['masks'], before['masks'])

    def test_forged_composite_text_cannot_be_applied_under_later_cutoff(self):
        result=self.generate()
        with self.store._connect() as c:
            row=c.execute('SELECT payload FROM episode_drafts WHERE id=?',(result['draft_id'],)).fetchone()
            record=json.loads(row['payload']);record['text']='The violet crown glowed at dawn. '+record['text']
            c.execute('UPDATE episode_drafts SET payload=? WHERE id=?',(json.dumps(record),result['draft_id']))
        with self.assertRaisesRegex(ValueError,'boundaries'):self.apply(result)
        self.assertEqual(self.store.get_episode('sample')['script'],self.text)
