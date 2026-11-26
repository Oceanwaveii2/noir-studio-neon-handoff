"""FX06-08 replay state, alternate activation and the continuation boundary."""
from copy import deepcopy
import unittest

from prose_engine.branch_continuations import NURSE, validate_output
from story_graph.epistemic import Fact
from story_graph.fx06_scene import CAST, PETER
from story_graph.models import Transaction
from story_graph.replay_world import SceneReplayWorld
from story_graph.scene_branches import seed


def trial(repeat, *, corrected=False):
    profile={'root':'rainee','locations':['hall','far-hall'],'portals':[],
             'actors':[{'id':v,'location':'hall'} for v in ('rainee','haley','francine')],
             'members':[{'id':v,'mind':f'mind-{i}'} for i,v in enumerate(CAST,1)],
             'interveners':['francine'],'emission':None,'protected_line':None,
             'force':{'form':PETER,'recipient':'haley','visible_from':['hall'],'destination':'far-hall'},
             'anchors':{'split':'first','rejoin':'return','transform':{}},
             'branch_rules':{'transforms':[{'id':NURSE,'actor':'francine','from_form':'francine','node':'nurse','needs_reunion':False},
                                            {'id':PETER,'actor':'rainee','from_form':'rainee','node':'peter','needs_reunion':True}],
                             'reactivation':{'form':PETER,'node':'again','release':'blast'} if repeat else None}}
    if corrected:
        rules = profile['branch_rules']
        rules['intervention_forms'] = {'francine': 'francine'}
        rules['transforms'][0]['requires_actor_form'] = {'actor': 'rainee', 'form': PETER}
        if repeat:
            profile['locations'].append('farther')
            rules['reactivated_group_force'] = {'node': 'blast-two', 'visible_from': ['far-hall'],
                                               'destination': 'farther'}
    return SceneReplayWorld(deepcopy(profile),{'rainee':{PETER:'peter'},'francine':{NURSE:'nurse'}})


class AlternateBranchTests(unittest.TestCase):
    def fire(self,world,op,actor,beat,**params):
        return world.execute(Transaction('scene_'+op,actor,world.root,params),beat_id=beat)

    def prepare(self,w):
        def run(op,actor,beat,**params):
            return self.fire(w,op,actor,beat,**params).success
        self.assertFalse(run('transform','rainee','peter',avatar_id=PETER))
        self.assertFalse(run('transform','francine','before-nurse',avatar_id=NURSE))
        self.assertTrue(run('split','rainee','first',members=list(CAST)))
        w.ledger.register_fact(Fact('first-private','First activation only',is_private=True))
        w.ledger.grant_knowledge(CAST[0],'first-private','private_deduction',0)
        self.assertTrue(run('transform','francine','nurse',avatar_id=NURSE))
        self.assertTrue(run('intervene','francine','call'))
        self.assertTrue(run('rejoin','rainee','return',intervention='call'))
        self.assertEqual(w.projection()['manifestations'],[])
        self.assertTrue(run('transform','rainee','peter',avatar_id=PETER))
        return run

    def test_repeat_needs_payoff_then_reuses_minds_without_first_activation_memory(self):
        w=trial(True); run=self.prepare(w)
        self.assertFalse(run('split','rainee','again',members=list(CAST),reactivate=True))
        self.assertTrue(run('release','rainee','blast',severity='severe'))
        self.assertFalse(run('split','rainee','again',members=list(CAST),reactivate=True))
        self.assertTrue(run('force','haley','reaction',release='blast'))
        self.assertFalse(run('split','rainee','again',members=list(CAST)[:2],reactivate=True))
        self.assertTrue(run('split','rainee','again',members=list(CAST),reactivate=True))
        state=w.projection()
        self.assertEqual(state['root_form'],'split')
        self.assertEqual(state['split_origin'],PETER)
        self.assertEqual(state['actors']['francine']['form'],NURSE)
        self.assertEqual([x['mind'] for x in state['manifestations']],['mind-1','mind-2','mind-3'])
        self.assertEqual(state['knowledge'][CAST[0]],[])
        self.assertFalse(w.ledger.knows(CAST[0],'first-private',tick=0))

    def test_peter_holds_in_sibling(self):
        w=trial(False); run=self.prepare(w)
        self.assertTrue(run('release','rainee','blast',severity='severe'))
        self.assertTrue(run('force','haley','reaction',release='blast'))
        self.assertFalse(run('split','rainee','again',members=list(CAST),reactivate=True))
        final=w.projection()
        self.assertEqual(final['root_form'],PETER)
        self.assertEqual(final['manifestations'],[])
        self.assertEqual(final['actors']['haley']['location'],'far-hall')

    def test_corrected_activation_and_group_blast_follow_separate_prerequisites(self):
        w = trial(True, corrected=True)

        def run(op, actor, beat, **params):
            return self.fire(w, op, actor, beat, **params).success

        self.assertTrue(run('split', 'rainee', 'first', members=list(CAST)))
        self.assertFalse(run('group_release', 'rainee', 'blast-two', after_reactivation='first'))
        self.assertFalse(run('transform', 'francine', 'nurse', avatar_id=NURSE))
        self.assertTrue(run('intervene', 'francine', 'call'))
        self.assertTrue(run('rejoin', 'rainee', 'return', intervention='call'))
        self.assertTrue(run('transform', 'rainee', 'peter', avatar_id=PETER))
        self.assertTrue(run('transform', 'francine', 'nurse', avatar_id=NURSE))
        self.assertTrue(run('release', 'rainee', 'blast', severity='severe'))
        self.assertTrue(run('force', 'haley', 'first-hit', release='blast'))
        self.assertTrue(run('split', 'rainee', 'again', members=list(CAST), reactivate=True))
        self.assertEqual(w.projection()['actors']['haley']['location'], 'far-hall')
        self.assertFalse(run('intervene', 'francine', 'call-again'))
        self.assertFalse(run('group_release', 'rainee', 'blast-two', after_reactivation='first'))
        self.assertTrue(run('group_release', 'rainee', 'blast-two', after_reactivation='again'))
        self.assertFalse(run('group_release', 'rainee', 'extra-blast', after_reactivation='again'))
        self.assertTrue(run('force', 'haley', 'second-hit', release='blast-two'))
        self.assertFalse(run('force', 'haley', 'third-hit', release='blast-two'))
        self.assertEqual(w.projection()['actors']['haley']['location'], 'farther')
        self.assertEqual([r['release'] for r in w.projection()['reactions']], ['blast', 'blast-two'])
        self.assertEqual([m['id'] for m in w.projection()['manifestations']], list(CAST))

    def test_continuation_rejects_inactive_forms_and_extra_causal_actions(self):
        ctx={'cast':{'n':'Nurse Franny','h':'Haley','r1':'Rainee 1'},'known_forms':[NURSE,PETER]}
        body=('Action: One hand lifts.\nNurse Franny: Stay there.\nHaley: Plan on it.\nRainee 1: Before or after the applause?')
        self.assertEqual(validate_output(ctx,body),[])
        self.assertTrue(validate_output(ctx,body.replace('Rainee 1:','Rainee Peter:')))
        self.assertTrue(validate_output(ctx,body.replace('One hand lifts.','She reaches for the Shocker.')))
        self.assertTrue(validate_output(ctx,body.replace('One hand lifts.','She transforms again.')))

    def test_seed_remaps_roles_without_story_history(self):
        result=seed({'lead':'quill','listener':'mara','helper':'kit'})
        self.assertEqual(result['inherited_facts'],[])
        self.assertEqual(result['roles']['lead'],'quill')
        with self.assertRaisesRegex(ValueError,'distinct'):
            seed({'lead':'quill','listener':'quill','helper':'kit'})
