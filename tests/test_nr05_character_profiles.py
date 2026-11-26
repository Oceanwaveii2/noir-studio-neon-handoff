import copy
from dataclasses import replace
import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from story_graph.character_forms import AFM_JUNCTIONS, CharacterJunction, FormLink
from story_graph.character_profiles import CharacterProfileStore
from story_graph.episode_timeline import TimelineStore
from prose_engine.notebook import DraftStore, NotebookStore
from prose_engine.scoped_pipeline import build_packet, prompt_for, validate_output
from prose_engine.scoped_service import execute_scoped
from tools.studio_form_store import FormGraphStore
from tools.studio_ui import StudioRequestHandler, form_targets


def field(ident,category,text,source_type='universal_author',source_id='author-note',confidence='author'):
    return {'id':ident,'category':category,'text':text,'source_type':source_type,'source_id':source_id,'confidence':confidence}


def link_forms():
    groups=dict(AFM_JUNCTIONS);group=groups['roger'];forms=[]
    for form in group.forms:
        forms.append(replace(form,link=FormLink('digital_mind','node-'+form.id)))
    groups['roger']=CharacterJunction('roger',tuple(forms));return groups


class Provider:
    def __init__(self,on_call=None):self.prompts=[];self.on_call=on_call
    def generate_rewrite(self,request,prompt):
        self.prompts.append(prompt)
        if self.on_call:self.on_call()
        return 'A dim room.'


class CharacterProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'timeline.sqlite'
        self.store=TimelineStore(self.path);self.store.add_starter_cards()
        for episode in ('spring-break','hot-scoomp','tapped-out'):
            self.store.save(episode,0,script='A quiet room.',source_name='fixture')
        self.profiles=CharacterProfileStore(self.store);self.forms=link_forms()
        self.req={'episode':'spring-break','beat':1,'revision':1,'start':0,'end':13,'provider':'codex-session'}

    def packet(self,episode='spring-break',beat=1,viewpoint=None,forms=None):
        return build_packet(self.store,episode,beat,1,0,13,viewpoint,junctions=forms or self.forms)

    def add_event(self,ident,episode,beat,content,viewpoint=None):
        self.store.add_event(ident,episode,beat,content,status='approved',permitted=True,source_id='fixture-source',reviewer='author',viewpoint=viewpoint)

    def save(self,form,fields,revision=0):
        return self.profiles.save('roger',form,'node-'+form,'digital_mind',revision,fields,self.forms)

    def test_missing_ports_and_links_are_not_claimed_as_nodes(self):
        packet=build_packet(self.store,'spring-break',1,1,0,13)
        self.assertEqual(packet.characters['roger']['profiles'][0]['status'],'unlinked')
        self.assertEqual(packet.characters['roger']['status'],'incomplete')
        linked=self.packet();part=linked.characters['roger']['profiles'][0]
        self.assertEqual(part['status'],'linked_no_profile');self.assertEqual(part['fields'],[])
        self.assertIn('do not invent personality',prompt_for(linked))
        with self.store._connect() as c:
            self.assertFalse(c.execute("SELECT 1 FROM sqlite_master WHERE name='character_profile_heads'").fetchone())

    def test_save_reopen_conflict_and_explicit_evidence(self):
        self.add_event('private','spring-break',2,'Roger learns a private clue.',viewpoint='roger')
        entries=[field('voice','voice','Dry observant voice.'),field('secret','knowledge','Roger knows a private clue.','event','private')]
        saved=self.save('roger',entries);self.assertEqual(saved['revision'],1)
        reopened=CharacterProfileStore(TimelineStore(self.path)).open('roger','roger','node-roger')
        self.assertEqual(reopened['fields'],entries)
        with self.assertRaisesRegex(ValueError,'Stale'):self.save('roger',entries,0)
        with self.assertRaisesRegex(ValueError,'timeline event'):self.save('roger',[field('bad','relationship','Invented relation.')],1)
        self.add_event('public','spring-break',3,'A public event.')
        with self.assertRaisesRegex(ValueError,'private event'):
            self.save('roger',[field('bad','knowledge','Unproven knowledge.','event','public')],1)
        with self.assertRaisesRegex(ValueError,'exact form port'):
            self.profiles.save('roger','roger','missing-node','digital_mind',1,entries,self.forms)
        self.assertEqual(self.profiles.open('roger','roger','node-roger')['revision'],1)
        undone=self.profiles.undo('roger','roger','node-roger','digital_mind',1,self.forms)
        self.assertEqual(undone['revision'],2);self.assertEqual(undone['fields'],[])

    def test_profile_snapshots_do_not_cross_universes(self):
        self.save('roger',[field('p','personality','One universe personality.')])
        other=TimelineStore(self.root/'other.sqlite');other.add_starter_cards()
        other.save('spring-break',0,script='A quiet room.',source_name='fixture')
        packet=build_packet(other,'spring-break',1,1,0,13,junctions=self.forms)
        self.assertEqual(packet.characters['roger']['profiles'][0]['status'],'linked_no_profile')
        self.assertNotIn('One universe personality',prompt_for(packet))

    def test_profile_conflicting_with_world_law_is_not_in_prompt(self):
        forms=dict(AFM_JUNCTIONS);group=forms['haley']
        forms['haley']=CharacterJunction('haley',(replace(group.forms[0],link=FormLink('digital_mind','node-haley')),*group.forms[1:]))
        self.profiles.save('haley','haley','node-haley','digital_mind',0,
                           [field('bad','personality','Haley has a father.')],forms)
        packet=self.packet(forms=forms)
        self.assertEqual(packet.characters['haley']['status'],'incomplete')
        self.assertNotIn('Haley has a father.',prompt_for(packet))

    def test_forms_private_knowledge_and_future_facts_are_scoped(self):
        self.add_event('private','spring-break',2,'Roger learns a private clue.',viewpoint='roger')
        self.add_event('future','tapped-out',1,'A distant future relationship becomes known.')
        self.store.add_event('host','spring-break',5,'Roger begins hosting.',status='draft')
        self.store.bind_form_event('spring-break','host','roger','mtv_beach_host','active',self.forms)
        self.store.review_event('spring-break','host','author','host-evidence',True)
        self.store.add_event('royal','spring-break',7,'Roger adopts a royal persona.',status='draft')
        self.store.bind_form_event('spring-break','royal','roger','rutgers_royal_persona','active',self.forms)
        self.store.review_event('spring-break','royal','author','royal-evidence',True)
        self.save('roger',[field('base','personality','Dry observant manner.'),
            field('secret','knowledge','Private clue known to Roger.','event','private'),
            field('later','relationship','A future relationship with someone.','event','future')])
        self.save('mtv_beach_host',[field('host-style','behavior','The host speaks in bright bursts.')])
        self.save('rutgers_royal_persona',[field('royal-style','behavior','The royal persona speaks grandly.')])
        self.store.fork('sibling','main','spring-break',4)
        self.store.create_episode('sibling-episode','Sibling','sibling',0)
        self.store.save('sibling-episode',0,script='A quiet room.',source_name='fixture')
        early=self.packet(beat=1,viewpoint='roger');host=self.packet(beat=6,viewpoint='roger');royal=self.packet(beat=8,viewpoint='roger')
        public=self.packet(beat=6);other=self.packet(beat=6,viewpoint='francine');sibling=self.packet('sibling-episode',30,'roger')
        self.assertEqual(early.characters['roger']['active_form'],'roger')
        self.assertEqual(host.characters['roger']['active_form'],'mtv_beach_host')
        self.assertEqual(host.characters['roger']['status'],'incomplete')
        self.assertEqual(host.characters['roger']['data_status'],'author_supplied')
        self.assertEqual(royal.characters['roger']['active_form'],'rutgers_royal_persona')
        self.assertEqual(sibling.characters['roger']['active_form'],'roger')
        self.assertIn('Dry observant manner',prompt_for(host));self.assertIn('host speaks in bright',prompt_for(host))
        self.assertNotIn('royal persona speaks grandly',prompt_for(host));self.assertIn('royal persona speaks grandly',prompt_for(royal))
        self.assertNotIn('host speaks in bright',prompt_for(sibling))
        self.assertIn('Private clue known to Roger',prompt_for(host));self.assertNotIn('Private clue known to Roger',prompt_for(public));self.assertNotIn('Private clue known to Roger',prompt_for(other))
        self.assertNotIn('future relationship with someone',json.dumps(host.public()))
        later=self.packet('tapped-out',2,'roger')
        self.assertIn('future relationship with someone',prompt_for(later))

    def test_profile_change_during_generation_and_before_apply_is_stale(self):
        original=[field('p','personality','Dry observant manner.')];self.save('roger',original)
        book=NotebookStore(self.store);state=book.open('spring-break');book.save('spring-break',0,1,state['blocks'],25,[])
        def change(): self.save('roger',[field('p','personality','A different author statement.')],1)
        with self.assertRaisesRegex(ValueError,'changed during'):
            execute_scoped(self.store,'generate',self.req,junctions=lambda:self.forms,provider_factory=lambda:Provider(change))
        self.assertEqual(DraftStore(book).list('spring-break','main')[-1]['status'],'STALE')
        result=execute_scoped(self.store,'generate',self.req,junctions=lambda:self.forms,provider_factory=Provider)
        receipt=next(r for r in DraftStore(book).open('spring-break','main',result['draft_id'])['character_receipts'] if r['character_id']=='roger')
        self.assertEqual(receipt['revision'],2);self.assertEqual(receipt['fields'][0]['source']['id'],'author-note')
        self.assertNotIn('A different author statement.',json.dumps(receipt))
        self.save('roger',original,2)
        with self.assertRaisesRegex(ValueError,'profile'):
            execute_scoped(self.store,'apply-draft',{**self.req,'draft':result['draft_id'],'notebook_revision':1},junctions=lambda:self.forms)
        self.assertEqual(self.store.get_episode('spring-break')['script'],'A quiet room.')

    def test_profile_change_during_provider_setup_prevents_dispatch(self):
        self.save('roger',[field('p','personality','Dry observant manner.')])
        provider=Provider()
        def factory():
            self.save('roger',[field('p','personality','Changed setup data.')],1);return provider
        with self.assertRaisesRegex(ValueError,'before generation'):
            execute_scoped(self.store,'generate',self.req,junctions=lambda:self.forms,provider_factory=factory)
        self.assertEqual(provider.prompts,[])
        self.assertEqual(DraftStore(NotebookStore(self.store)).list('spring-break','main')[-1]['status'],'STALE')

    def test_older_draft_remains_usable_when_no_profiles_exist(self):
        book=NotebookStore(self.store);state=book.open('spring-break');book.save('spring-break',0,1,state['blocks'],25,[])
        result=execute_scoped(self.store,'generate',self.req,provider_factory=Provider)
        with self.store._connect() as c:
            row=c.execute('SELECT payload FROM episode_drafts WHERE id=?',(result['draft_id'],)).fetchone()
            payload=json.loads(row['payload']);payload.pop('character_store_token');payload.pop('character_receipts')
            c.execute('UPDATE episode_drafts SET payload=? WHERE id=?',(json.dumps(payload),result['draft_id']))
        applied=execute_scoped(self.store,'apply-draft',{**self.req,'draft':result['draft_id'],'notebook_revision':1})
        self.assertEqual(applied['status'],'APPLIED')

    def test_authoring_endpoint_saves_only_connected_port(self):
        form_store=FormGraphStore(self.root/'forms.sqlite',form_targets())
        added=form_store.change({'action':'add_node','revision':0,'kind':'digital_mind','label':'Fixture Mind'})
        node=next(n['id'] for n in added['nodes'] if n['label']=='Fixture Mind')
        form_store.change({'action':'set_link','revision':1,'port':'character:roger:form:roger','node_id':node})
        server=ThreadingHTTPServer(('127.0.0.1',0),StudioRequestHandler);server.timeline_path=self.path;server.timeline_only=True;server.form_graph=form_store
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':0.01},daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)
        def post(body):
            request=urllib.request.Request(base+'/api/character-profiles',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Origin':base})
            with urllib.request.urlopen(request) as response:return json.load(response)
        try:
            req={'character':'roger','form':'roger','node':node,'kind':'digital_mind'}
            self.assertEqual(post({**req,'action':'open'})['status'],'missing')
            saved=post({**req,'action':'save','revision':0,'fields':[field('p','personality','Fixture personality.')]})
            self.assertEqual(saved['status'],'author_supplied');self.assertEqual(post({**req,'action':'open'})['revision'],1)
        finally:server.shutdown();server.server_close();thread.join()

    def test_form_graph_node_data_projects_into_scoped_generation_and_respects_active_form(self):
        form_store=FormGraphStore(self.root/'forms.sqlite',form_targets())
        g0=form_store.change({'action':'save_node_data','revision':0,'character':'rainee','node':'character:rainee:form:rainee',
                              'content':{'text_fields':{'personality':'Base Rainee poise.','voice':'Dry cadence.','notes':'Never rushes.'},
                                         'structured_data':{'tics':'adjusts collar'}}})
        peter_form=next(f for f in next(j['forms'] for j in g0['junctions'] if j['character_id']=='rainee') if f['id']!='rainee')
        form_store.change({'action':'save_node_data','revision':g0['revision'],'character':'rainee','node':peter_form['port_id'],
                           'content':{'text_fields':{'voice':'Loud Peter cadencephrase','notes':'Future persona note'}}})
        self.store.add_event('peter-on','spring-break',5,'Rainee shifts to Peter.',status='draft')
        self.store.bind_form_event('spring-break','peter-on','rainee',peter_form['id'],'active',form_store.junctions())
        self.store.review_event('spring-break','peter-on','author','peter-evidence',True)
        early=build_packet(self.store,'spring-break',1,1,0,13,viewpoint='rainee',junctions=form_store.junctions())
        early_prompt=prompt_for(early)
        self.assertIn('Base Rainee poise.',early_prompt)
        self.assertIn('Dry cadence.',early_prompt)
        self.assertIn('tics: adjusts collar',early_prompt)
        self.assertNotIn('Loud Peter cadencephrase',early_prompt)
        self.assertTrue(any('loud peter cadencephrase' in phrase.lower() for phrase in early.hidden_phrases))
        self.assertEqual(validate_output(early,'A quiet room. Loud Peter cadencephrase'),
                         ['Output contains information unavailable at this beat'])
        later=build_packet(self.store,'spring-break',6,1,0,13,viewpoint='rainee',junctions=form_store.junctions())
        later_prompt=prompt_for(later)
        self.assertIn('Base Rainee poise.',later_prompt)
        self.assertIn('Loud Peter cadencephrase',later_prompt)
        self.assertEqual(validate_output(later,'A quiet room. Loud Peter cadencephrase'),[])
        book=NotebookStore(self.store);state=book.open('spring-break');book.save('spring-break',0,1,state['blocks'],25,[])
        draft=execute_scoped(self.store,'generate',self.req,junctions=form_store.junctions,provider_factory=Provider)
        latest=form_store.read()['revision']
        form_store.change({'action':'save_node_data','revision':latest,'character':'rainee','node':'character:rainee:form:rainee',
                           'content':{'text_fields':{'personality':'Edited base Rainee poise.'}}})
        with self.assertRaisesRegex(ValueError,'profile'):
            execute_scoped(self.store,'apply-draft',{**self.req,'draft':draft['draft_id'],'notebook_revision':1},junctions=form_store.junctions)


if __name__=='__main__':unittest.main()
