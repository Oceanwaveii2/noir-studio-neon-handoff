"""Real scoped draft machinery with a small offline replay and writer fixture."""
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from prose_engine.episode_commands import EpisodeCommands
from prose_engine.notebook import NotebookStore, joined
from prose_engine import replay_minds
from story_graph import fx06_scene as scene
from story_graph.episode_timeline import TimelineStore
from story_graph.form_graph_store import FormGraphStore
from story_graph.scene_fragments import SceneFragmentError
from story_graph.scene_override import SceneReplayStore
from story_graph.source_imports import junctions
from story_graph.world_laws import WorldLawStore
from tools.fx06_studio import prepare


CANDIDATE = ('Rainee 1: The cloud moved out. Case closed.\nAction: She lifts a hand.\n'
             'Rainee 2: It moved into the hall.\nAction: She points past Haley.\n'
             'Rainee 3: Tell the fan.\nAction: She taps its dark indicator.')


class ReplayMindTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root=Path(temp.name)
        actors=[{'form_id':fid,'speaker':label,'role':role,'mind_label':role,'constraint':'Keep the scene facts.',
                 'tendencies':[{'when':'challenged','try':tactic,'evidence':['source']}]} for fid,label,role,tactic
                in zip(scene.CAST,scene.SPEAKERS,scene.ROLES,['Frame it','Back the verdict','Notice the light'])]
        bundle={'actors':actors,'evidence':{'source':{'id':'source','source':'fixture','span_ms':[0,200]}},'relationships':[],
                'timing':[{'hint':'Pause after the third action.'}], 'manifests':{},'cutaway':{}}
        with patch('tools.fx06_studio.scene.load_bundle',return_value=bundle):
            saved=prepare(root/'workspace',root)
        self.scope=saved['scope']
        self.store=TimelineStore(Path(saved['timeline']))
        with self.store._connect() as c:
            self.forms=FormGraphStore(Path(saved['forms']),imported=junctions(c,{}))
        self.notebook=NotebookStore(self.store)
        self.before=self.notebook.existing(scene.EPISODE)
        self.calls=[]
        self.response=CANDIDATE
        test=self

        class Writer:
            def generate_rewrite(self,request,prompt):
                test.calls.append((request.request_id,prompt))
                return test.response

        self.commands=EpisodeCommands(self.store,junctions=self.forms.junctions,provider_factory=Writer)
        text=joined(self.before['blocks'])
        graph=self.commands.execute('scene.fragment.import',self.scope|{'timeline_revision':1,
                      'selection':{'start':0,'end':len(text)}})['fragment']
        nodes={n['key']:n['id'] for n in graph['graph']['nodes']}
        basis=self.scope|{'timeline_revision':1,'fragment':graph['id'],'fragment_revision':1,'law_revision':0}
        profile={'schema_version':1,'id':'roast-profile','root':'rainee','cutoff':0,
                 'locations':['hall'],'portals':[],'actors':[{'id':k,'location':'hall'} for k in ('rainee','haley','francine')],
                 'members':[{'id':k,'mind':v} for k,v in saved['mind_nodes'].items()],'interveners':['francine'],
                 'anchors':{'split':nodes['n4'],'rejoin':nodes['n5'],'transform':{}},
                 'protected_line':{'lock':'fx06-exact-D09','speaker':'haley','node':nodes['n3']},
                 'emission':{'form':'rainee','strength':{'severe':'overpowering_floral','normal':'floral'}},
                 'force':None,'patterns':[]}
        def at(ident,n,op,actor,args=None,after=()):
            return {'id':ident,'node':nodes[n],'op':op,'actor':actor,'args':args or {},'after':list(after)}
        recipe={'schema_version':1,'overrides':[],'events':[
            at('first-release','n2','release','rainee',{'severity':'severe'}),
            at('notice','n2','notice','haley',{'release':'first-release'}),
            at('haley-line','n3','line','haley',{'observation':'notice'}),
            at('split','n4','split','rainee',{'members':list(scene.CAST)}),
            at('roast','n4','beat',None,after=['split'])]}
        engine=SceneReplayStore(self.store)
        engine.install_profile(basis,profile)
        trace=engine.execute('scene.override.replay',basis|{'profile':profile['id'],'recipe':recipe})['receipt']
        replay_minds.install(self.store,self.scope,trace['id'])

    def command(self,action,**fields):
        return self.commands.execute(action,self.scope|fields)

    def test_conditions_change_only_cards_and_save_separate_idempotent_drafts(self):
        for tag in replay_minds.CONDITIONS:
            result=self.command('scene.minds.preview',condition=tag)
            self.assertEqual(result['provider_calls'],0)
            self.assertFalse(result['generation_started'])
            self.assertEqual(len(result['scope']['fx06']['active_cast']),3)
        self.assertEqual(self.calls,[])
        drafts=[self.command('scene.minds.run',condition=tag) for tag in replay_minds.CONDITIONS]
        self.assertTrue(all(x['status']=='PROPOSED' for x in drafts))
        self.assertEqual(len({x['draft_id'] for x in drafts}),3)
        self.assertEqual(len({x[0] for x in self.calls}),3)
        a,b,c=(prompt for _,prompt in self.calls)
        strip=lambda p:re.sub(r'(?<=MIND GUIDANCE DATA \(optional tactics only\):\n)[^\n]*','',p)
        self.assertEqual(strip(a),strip(b));self.assertEqual(strip(a),strip(c))
        self.assertIn('Alliance keeper',a);self.assertNotIn('Alliance keeper',b);self.assertIn('Deadpan defector',c)
        self.assertNotIn('Rainee Peter',a+b+c)
        opened=self.command('scene.minds.open')
        self.assertEqual([e['draft']['id'] for e in opened['variants']],[d['draft_id'] for d in drafts])
        self.assertTrue(self.command('scene.minds.run',condition='all')['replayed'])
        self.assertEqual(len(self.calls),3)

    def test_board_edit_changes_only_its_writer_card_and_preserves_saved_draft(self):
        first=self.command('scene.minds.run',condition='all')['draft_id']
        original=self.command('draft.open',draft=first)['writing_context']['fx06']['guidance']
        node='data:character:rainee:form:rainee-split-2'
        state=self.forms.read()
        group=next(g for g in state['junctions'] if g['character_id']=='rainee')
        content=group['node_data'][node]
        direction='Wait for Francine to speak first, then quietly back Haley.'
        content['text_fields']['behavior']=direction
        self.forms.change({'action':'save_node_data','character':'rainee','node':node,
                           'content':content,'revision':state['revision']})
        fresh=self.command('scene.minds.preview',condition='all')['scope']['fx06']['guidance']
        self.assertIn(direction,str(fresh[1]))
        self.assertNotIn('Back the verdict',str(fresh[1]))
        self.assertEqual(original[::2],fresh[::2])
        second=self.command('scene.minds.run',condition='all')['draft_id']
        self.assertNotEqual(first,second)
        self.assertIn(direction,self.calls[-1][1])
        self.assertNotIn(direction,self.calls[0][1])
        self.assertEqual(self.command('draft.open',draft=first)['writing_context']['fx06']['guidance'],original)
        self.assertEqual(self.command('scene.minds.open')['variants'][0]['draft']['id'],second)
        self.forms.change({'action':'move_node','character':'rainee','node':node,'position':{'x':24,'y':8},
                           'revision':self.forms.read()['revision']})
        self.assertEqual(self.command('scene.minds.run',condition='all')['draft_id'],second)
        self.forms.change({'action':'undo_node_data','character':'rainee','node':node,'revision':self.forms.read()['revision']})
        self.assertEqual(self.command('scene.minds.preview',condition='all')['scope']['fx06']['guidance'],original)
        self.assertEqual(self.command('scene.minds.run',condition='all')['draft_id'],first)

    def test_apply_and_history_keep_everything_outside_the_roast(self):
        result=self.command('scene.minds.run',condition='one-changed')
        draft=self.command('draft.open',draft=result['draft_id'])
        before=joined(self.before['blocks'])
        expected=before[:draft['start']]+CANDIDATE+before[draft['end']:]
        state=self.before
        for action,target,extra in (('draft.apply',expected,{'draft':draft['id']}),
                                    ('notebook.undo',before,{}),('notebook.redo',expected,{})):
            change=self.command(action,notebook_revision=state['revision'],timeline_revision=state['timeline_revision'],**extra)
            state=change['notebook']
            text=joined(state['blocks'])
            self.assertEqual(text,target)
            mask=next(m for m in state['masks'] if m['id']=='fx06-exact-D09')
            self.assertEqual(text[mask['start']:mask['end']],scene.PERFUME_LINE)
            self.assertTrue(mask['hard'])

    def test_inspection_keeps_witnesses_and_saved_auditions_independent_of_board_edits(self):
        scope = {key: self.scope[key] for key in ('project','universe','episode','branch')}
        request = scope | {'source':'roast', 'timeline_revision':1, 'character':'rainee', 'form':'rainee-split-2'}
        def inspect(**changes):
            return self.commands.execute('mind.inspect', request | changes)
        saved = self.command('scene.minds.run', condition='all')['draft_id']
        first = inspect()
        self.assertFalse(first['selected']['knowledge'])
        cue = first['selected']['card']['tendencies'][0]
        self.assertEqual(cue['evidence'][0]['span_ms'], [0, 200])
        self.assertEqual(first['auditions'][0]['dialogue'], CANDIDATE.splitlines()[2])
        witness = self.commands.execute('mind.inspect', scope |
                                        {'source':'roast', 'timeline_revision':1, 'character':'haley'})
        self.assertEqual(witness['selected']['knowledge'][0]['observed_at'], 'notice')
        change = 'Let the pause do the work.'
        graph = self.forms.read()
        node = 'data:character:rainee:form:rainee-split-2'
        group = next(g for g in graph['junctions'] if g['character_id']=='rainee')
        content = group['node_data'][node]
        content['text_fields']['behavior'] = change
        self.forms.change({'action':'save_node_data','character':'rainee','node':node,
                           'content':content,'revision':graph['revision']})
        current = inspect()
        historic = inspect(draft=saved)
        self.assertEqual(current['selected']['card']['tendencies'][0]['try'], change)
        self.assertFalse(current['selected']['card']['tendencies'][0]['evidence'])
        self.assertEqual(first['selected'], historic['selected'])
        self.assertEqual(first['auditions'], historic['auditions'])
        self.assertEqual([a['mind_revision'] for a in first['subjects'] if a['form']!=request['form']],
                         [a['mind_revision'] for a in current['subjects'] if a['form']!=request['form']])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(current['provider_calls'], 0)

    def test_stale_law_or_missing_mind_cannot_start_or_apply(self):
        result=self.command('scene.minds.run',condition='all')
        disconnected=EpisodeCommands(self.store,junctions=lambda:{})
        with self.assertRaisesRegex(SceneFragmentError,'three original'):
            disconnected.execute('scene.minds.preview',self.scope|{'condition':'none'})
        laws=WorldLawStore(self.store)
        now=laws.open()
        laws.save(now['revision'],now['laws'])
        with self.assertRaisesRegex(ValueError,'Stale world law revision'):
            self.command('scene.minds.run',condition='none')
        with self.assertRaisesRegex(SceneFragmentError,'earlier world-law'):
            self.command('draft.apply',draft=result['draft_id'],notebook_revision=self.before['revision'],timeline_revision=1)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.notebook.existing(scene.EPISODE),self.before)

    def test_future_form_is_rejected_without_repeat_spend(self):
        self.response=CANDIDATE.replace('She lifts a hand.','Peter lifts a hand.')
        result=self.command('scene.minds.run',condition='none')
        self.assertEqual(result['status'],'BLOCKED')
        self.assertIn('later form',result['issues'][0])
        self.assertEqual(self.command('scene.minds.run',condition='none')['status'],'BLOCKED')
        self.assertEqual(len(self.calls),1)
