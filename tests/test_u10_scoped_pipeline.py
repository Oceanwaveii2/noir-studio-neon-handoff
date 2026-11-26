import json
from dataclasses import replace
import tempfile
import unittest
from pathlib import Path
from prose_engine.scoped_pipeline import build_packet, retrieve, validate_claims, validate_output, prompt_for, generate, export_packet
from story_graph.character_forms import AFM_JUNCTIONS, CharacterJunction, FormLink
from story_graph.episode_timeline import TimelineStore
from story_graph.form_graph_store import FormGraphStore

class Provider:
    def __init__(self, result='A quiet room.'): self.prompts=[]; self.result=result
    def generate_rewrite(self, request, prompt): self.prompts.append(prompt); return self.result

class ScopedPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store=TimelineStore(Path(self.tmp.name)/'scope.sqlite'); self.store.add_starter_cards()
        for ep in ('spring-break','hot-scoomp','tapped-out'):
            self.store.save(ep,0,script='A quiet room.',source_name='fixture.txt')
        self.store.add_event('past','spring-break',1,'The kitchen was quiet.',status='approved',permitted=True,source_id='fixture',reviewer='owner')
        self.store.add_event('haley-awakening','hot-scoomp',1,'Haley awakened after the festival.',status='draft',permitted=True)
        self.store.bind_form_event('hot-scoomp','haley-awakening','haley','awakened_haley_fox','active',AFM_JUNCTIONS)
        self.store.review_event('hot-scoomp','haley-awakening','owner','fixture',True)
        self.store.add_event('future','tapped-out',1,'A glitter prank destroyed the makeup kit.',status='approved',permitted=True,source_id='fixture',reviewer='owner')
        self.store.add_event('private','hot-scoomp',2,'A private revelation from Haley.',status='approved',permitted=True,viewpoint='haley',source_id='fixture',reviewer='owner')

    def packet(self, ep, beat=10, viewpoint=None):
        return build_packet(self.store,ep,beat,1,0,len('A quiet room.'),viewpoint)

    def test_removed_episode_no_longer_contributes_events_or_hidden_phrases(self):
        before=self.packet('tapped-out',0)
        self.assertIn('haley-awakening',[event['id'] for event in before.events])
        self.store.set_archived('hot-scoomp',1,True)
        after=self.packet('tapped-out',0)
        self.assertNotIn('haley-awakening',[event['id'] for event in after.events])
        self.assertNotIn('Haley awakened after the festival.',after.hidden_phrases)
        self.assertNotIn('awakened after the festival',prompt_for(after))
        self.assertTrue(self.store.prerequisites('tapped-out'))
        self.store.set_archived('hot-scoomp',1,False)
        self.assertIn('haley-awakening',[event['id'] for event in self.packet('tapped-out',0).events])

    def test_frozen_dialogue_and_explicit_unicode_span_survive_exactly(self):
        script='🕯 A brass key.\r\nFrancine said, “Did you hear that?”'
        ep='spring-break'
        self.store.save(ep,1,script=script,source_name='fixture.txt')
        key=script.index('brass key')
        packet=build_packet(self.store,ep,1,2,0,len(script),
                            protected_ranges=[[key,key+len('brass key')]])
        for bad in ('A brass key.', 'A brass key. “Did you hear that!”',
                    '“Did you hear that?” A brass key.', 'A silver key. “Did you hear that?”'):
            self.assertEqual(generate(packet,Provider(bad))['status'],'BLOCKED')
        good=generate(packet,Provider('She held a brass key. “Did you hear that?”'))
        self.assertEqual(good['status'],'PROPOSED')
        self.assertEqual(good['scope']['revision'],2)
        self.assertEqual(packet.public()['protected_ranges'][0],[key,key+len('brass key')])
        with self.assertRaisesRegex(ValueError,'Protected range'):
            build_packet(self.store,ep,1,2,0,len(script),protected_ranges=[[key,len(script)+1]])
        with self.assertRaisesRegex(ValueError,'Stale'):
            build_packet(self.store,ep,1,1,0,4)

    def test_old_scope_excludes_future_across_prompt_search_export_and_forms(self):
        p=self.packet('spring-break')
        self.assertEqual([e['id'] for e in retrieve(p)],['past'])
        self.assertEqual(retrieve(p,'glitter'),[])
        self.assertNotIn('awakened_haley_fox',json.dumps(p.public()))
        for content in (prompt_for(p),export_packet(p)):
            self.assertNotIn('awakened after the festival',content)
            self.assertNotIn('glitter prank',content)
        self.assertTrue(validate_claims(p,[{'kind':'active_form','subject':'haley','value':'awakened_haley_fox'}]))
        self.assertTrue(validate_output(p,'A glitter prank destroyed the makeup kit.'))
        provider=Provider('A glitter prank destroyed the makeup kit.')
        self.assertEqual(generate(p,provider)['status'],'BLOCKED')
        self.assertNotIn('glitter prank',provider.prompts[0])

    def test_later_scope_resolves_approved_active_form_and_private_view(self):
        public=self.packet('tapped-out',0)
        self.assertEqual([e['id'] for e in public.events],['past','haley-awakening'])
        self.assertEqual(validate_claims(public,[{'kind':'active_form','subject':'haley','value':'awakened_haley_fox'}]),[])
        private=self.packet('tapped-out',0,'haley')
        self.assertEqual([e['id'] for e in private.events],['past','haley-awakening','private'])
        self.assertEqual(generate(private,Provider())['status'],'PROPOSED')

    def test_snapshot_branch_and_stale_scope_fail_closed(self):
        self.store.fork('mini','main','hot-scoomp',0)
        self.store.create_episode('mini-ep','Mini','mini',0)
        self.store.save('mini-ep',0,script='A quiet room.',source_name='fixture.txt')
        p=self.packet('mini-ep')
        self.assertEqual([e['id'] for e in p.events],['past'])
        self.assertTrue(validate_claims(p,[{'kind':'available_form','subject':'haley','value':'awakened_haley_fox'}]))
        with self.assertRaises(ValueError): build_packet(self.store,'spring-break',0,0,0,4)
        with self.assertRaises(ValueError): build_packet(self.store,'spring-break',0,1,0,999)
        with self.assertRaises(ValueError): build_packet(self.store,'missing',0,1,0,4)
        self.store.save('spring-break',1,script='A glitter prank destroyed the makeup kit.',source_name='fixture.txt')
        with self.assertRaisesRegex(ValueError,'unavailable'): build_packet(self.store,'spring-break',10,2,0,len('A glitter prank destroyed the makeup kit.'))

    def test_selected_legacy_source_and_form_port(self):
        legacy=TimelineStore(Path(self.tmp.name)/'legacy.sqlite');legacy.add_starter_cards()
        p=build_packet(legacy,'spring-break',0,0,0,6,legacy_spring_text='A room. Other text.')
        self.assertEqual(p.target,'A room')
        junctions=dict(AFM_JUNCTIONS)
        old=junctions['haley']; fox=replace(old.forms[1],link=FormLink('digital_mind','fox-mind'))
        junctions['haley']=CharacterJunction('haley',(old.forms[0],fox))
        p=build_packet(self.store,'tapped-out',0,1,0,len('A quiet room.'),junctions=junctions)
        fox=next(f for f in p.forms['haley']['forms'] if f['id']=='awakened_haley_fox')
        self.assertEqual(fox['status'],'active');self.assertEqual(fox['link']['node_id'],'fox-mind')
        earlier=build_packet(self.store,'spring-break',10,1,0,len('A quiet room.'),junctions=junctions)
        self.assertNotIn('fox-mind',json.dumps(earlier.public()))

    def test_unknown_forms_and_changes_after_approval_fail_closed(self):
        with self.assertRaises(ValueError): self.store.bind_form_event('hot-scoomp','haley-awakening','haley','awakened_haley_fox','active',AFM_JUNCTIONS)
        self.store.add_event('draft','hot-scoomp',3,'another',status='draft')
        with self.assertRaises(ValueError): self.store.bind_form_event('hot-scoomp','draft','haley','made-up','active',AFM_JUNCTIONS)

    def test_u4_disclosures_have_source_and_freeze_at_fork(self):
        store=self.store
        store.fork('before-u4','main','spring-break',12)
        store.fork('after-u4','main','spring-break',13)
        for name in ('before-u4','after-u4'):
            store.create_episode(name+'-ep',name,name,0)
            store.save(name+'-ep',0,script='A room.',source_name='fixture')
        def forms(episode,beat,viewpoint=None):
            return build_packet(store,episode,beat,1,0,6,viewpoint)
        form='peter_griffin_celestial_variant'
        self.assertNotIn(form,json.dumps(forms('spring-break',12).public()))
        disclosed=forms('spring-break',13)
        self.assertIn(form,json.dumps(disclosed.public()))
        self.assertEqual(disclosed.form_sources[0]['source_id'],'spring-break/u4/beat_13_peter_griffin_metamorphosis')
        prior_edges = forms('spring-break', 12).public().get('relationships', [])
        self.assertTrue(any(edge['from']['character'] == 'francine' and edge['to']['form'] == 'rainee'
                            for edge in prior_edges))
        self.assertFalse(any(edge['to']['form'] == form for edge in prior_edges))
        self.assertTrue(any(edge['from']['character'] == 'francine' and edge['to']['form'] == form
                            and edge['to']['character'] == 'rainee' and edge['kind'] == 'spouse'
                            for edge in disclosed.public().get('relationships', [])))
        self.assertNotIn(form,json.dumps(forms('spring-break',13,'haley').public()))
        self.assertNotIn(form,json.dumps(forms('before-u4-ep',99).public()))
        self.assertIn(form,json.dumps(forms('after-u4-ep',0).public()))

    def test_form_relationship_cue_is_directed_and_scoped_to_one_beat(self):
        graph = FormGraphStore(self.store.form_graph_path)
        peter = 'peter_griffin_celestial_variant'
        port = 'character:rainee:form:' + peter
        cue = 'Let Francine finish before answering her.'
        args = {'character': 'rainee', 'node': port}
        def save(guidance):
            return graph.change({**args, 'action': 'save_node_data', 'revision': graph.read()['revision'],
                                 'content': {'structured_data': {'relationship_overrides': [{
                                     'target': 'francine', 'episode': 'spring-break', 'branch': 'main',
                                     'beat': 13, 'guidance': guidance}]}}})

        saved = save(cue)

        def packet(episode, beat):
            return build_packet(self.store, episode, beat, 1, 0, len('A quiet room.'), junctions=graph.junctions())

        active = packet('spring-break', 13)
        overridden = [edge for edge in active.relationships if 'override' in edge]
        self.assertEqual(len(overridden), 1)
        self.assertEqual(overridden[0]['from'], {'character': 'rainee', 'form': peter})
        self.assertEqual(overridden[0]['to'], {'character': 'francine', 'form': 'francine'})
        self.assertEqual(overridden[0]['override']['port'], port)
        self.assertEqual(prompt_for(active).count(cue), 1)
        self.assertNotIn(cue, prompt_for(packet('spring-break', 12)))
        self.assertNotIn(cue, prompt_for(packet('spring-break', 14)))
        self.store.fork('cue-sibling', 'main', 'spring-break', 13)
        self.store.create_episode('sibling-ep', 'Sibling', 'cue-sibling', 0)
        self.store.save('sibling-ep', 0, script='A quiet room.', source_name='fixture.txt')
        self.assertNotIn(cue, prompt_for(packet('sibling-ep', 13)))
        graph.change({**args, 'action': 'undo_node_data', 'revision': saved['revision']})
        self.assertNotIn(cue, prompt_for(packet('spring-break', 13)))
        withheld = 'Haley awakened after the festival.'
        save(withheld)
        active = packet('spring-break', 13)
        self.assertTrue(any('withheld_override' in edge for edge in active.relationships))
        self.assertNotIn(withheld, prompt_for(active))
