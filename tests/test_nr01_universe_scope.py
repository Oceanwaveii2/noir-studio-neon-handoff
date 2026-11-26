import hashlib
from contextlib import closing
import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from story_graph.episode_timeline import TimelineStore
from story_graph.universe_scope import migrate_legacy_copy
from story_graph.world_laws import WorldLawStore
from prose_engine.scoped_pipeline import build_packet, export_packet, generate_recorded


def rule(name):
    return {'id':name,'name':name,'statement':'Rule '+name,'enabled':True,
            'matcher':'literal','phrases':[name]}


class UniverseScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def store(self,name):
        path=self.root/(name+'.sqlite')
        store=TimelineStore(path,project_id='project-shared',universe_id='universe-'+name)
        store.create_episode('episode','Episode','main',1)
        store.save('episode',0,script='A quiet room.',source_name='fixture')
        return store

    def packet(self,store,**kw):
        return build_packet(store,'episode',0,1,0,13,**kw)

    def test_isolation_scope_reload_branch_and_laws(self):
        a,b=self.store('a'),self.store('b')
        la,lb=WorldLawStore(a),WorldLawStore(b)
        self.assertEqual(la.open()['laws'],[])
        law_a,law_b=rule('only_a'),rule('only_b')
        law_a['statement']='The moon must be red.'
        law_b['statement']='The moon must be blue.'
        la.save(0,[law_a]);lb.save(0,[law_b])
        pa,pb=self.packet(a),self.packet(b)
        self.assertEqual(pa.context.project_id,'project-shared')
        self.assertEqual(pa.context.universe_id,'universe-a')
        self.assertEqual(pa.context.world_law_revision,1)
        self.assertIn('only_a',export_packet(pa));self.assertNotIn('only_a',export_packet(pb))
        self.assertIn('moon must be red',export_packet(pa));self.assertNotIn('moon must be red',export_packet(pb))
        self.assertNotIn('haley',json.dumps(pb.public()).lower())
        with self.assertRaisesRegex(ValueError,'Universe'):
            self.packet(a,universe_id='universe-b')
        with self.assertRaisesRegex(ValueError,'Branch'):
            self.packet(a,branch='other')
        with self.assertRaisesRegex(ValueError,'law revision'):
            self.packet(a,law_revision=0)
        a.fork('alt','main','episode',0)
        a.create_episode('alt-episode','Alternative','alt',0)
        a.save('alt-episode',0,script='A quiet room.',source_name='fixture')
        reopened=TimelineStore(a.path,project_id='project-shared',universe_id='universe-a')
        branch=build_packet(reopened,'alt-episode',0,1,0,13,branch='alt')
        self.assertEqual(branch.context.branch,'alt')
        self.assertEqual(WorldLawStore(b).open()['laws'],[law_b])
        with self.assertRaisesRegex(ValueError,'Universe'):
            TimelineStore(a.path,project_id='project-shared',universe_id='universe-b')

    def test_law_changes_block_dispatch_and_inflight_result(self):
        store=self.store('a'); laws=WorldLawStore(store); packet=self.packet(store)
        laws.save(0,[rule('new_rule')]); calls=[]
        with self.assertRaisesRegex(ValueError,'laws changed'):
            generate_recorded(store,packet,'fixture',lambda: calls.append(1),lambda:self.packet(store))
        self.assertEqual(calls,[])
        packet=self.packet(store)
        class Provider:
            def generate_rewrite(inner,request,prompt):
                calls.append(1); laws.save(1,[rule('newer_rule')]); return 'A quiet room.'
        with self.assertRaisesRegex(ValueError,'changed during'):
            generate_recorded(store,packet,'fixture',Provider,lambda:self.packet(store))
        self.assertEqual(calls,[1])

    def test_starter_rule_is_opt_in_even_if_laws_were_opened_first(self):
        store=TimelineStore(self.root/'starter.sqlite')
        laws=WorldLawStore(store)
        self.assertEqual(laws.open()['laws'],[])
        store.add_starter_cards()
        self.assertEqual(laws.open()['laws'][0]['id'],'haley-parentage')
        self.assertEqual(laws.open()['revision'],1)

    def test_http_context_rejects_wrong_universe_before_processing(self):
        from tools.studio_ui import StudioRequestHandler
        store=self.store('a')
        server=ThreadingHTTPServer(('127.0.0.1',0),StudioRequestHandler)
        server.timeline_path=Path(store.path);server.timeline_only=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        def post(body):
            request=urllib.request.Request(base+'/api/scoped',data=json.dumps(body).encode(),
                    headers={'Content-Type':'application/json','Origin':base})
            with urllib.request.urlopen(request) as response: return json.load(response)
        request={'action':'export','episode':'episode','beat':0,'revision':1,'start':0,'end':13,
                 'project':'project-shared','universe':'universe-a','branch':'main'}
        try:
            result=post(request)
            self.assertEqual(result['scope']['context']['universe_id'],'universe-a')
            with self.assertRaises(urllib.error.HTTPError) as error:
                post({**request,'universe':'universe-b'})
            self.assertEqual(error.exception.code,400)
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_legacy_copy_preserves_original_and_history(self):
        src=self.root/'old.sqlite';out=self.root/'copy.sqlite'
        with closing(sqlite3.connect(src)) as db:
            db.executescript('''CREATE TABLE branches(id TEXT PRIMARY KEY,parent TEXT,fork_episode TEXT,fork_beat INTEGER);
              INSERT INTO branches(id) VALUES('main');
              CREATE TABLE episodes(id TEXT PRIMARY KEY,title TEXT,branch TEXT,position INTEGER,cover TEXT,status TEXT,head INTEGER,finished_revision INTEGER);
              CREATE TABLE revisions(episode TEXT,revision INTEGER,graph TEXT,script TEXT,source_name TEXT,script_sha256 TEXT,PRIMARY KEY(episode,revision));
              CREATE TABLE world_law_head(singleton INTEGER PRIMARY KEY,revision INTEGER);
              INSERT INTO world_law_head VALUES(1,1);
              CREATE TABLE world_law_revisions(revision INTEGER PRIMARY KEY,payload TEXT);''')
            db.execute('INSERT INTO world_law_revisions VALUES(0,?)',(json.dumps([]),))
            db.execute('INSERT INTO world_law_revisions VALUES(1,?)',(json.dumps([rule('legacy')]),))
            db.commit()
        before=hashlib.sha256(src.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError,'unscoped'): TimelineStore(src)
        result=migrate_legacy_copy(src,out,project_id='old-project',universe_id='old-universe')
        self.assertEqual(result['scope']['kind'],'legacy-unverified')
        self.assertEqual(hashlib.sha256(src.read_bytes()).hexdigest(),before)
        copied=TimelineStore(out,project_id='old-project',universe_id='old-universe')
        self.assertEqual(WorldLawStore(copied).open()['laws'],[rule('legacy')])
        with copied._connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM world_law_revisions').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM universe_law_revisions').fetchone()[0],2)
        restored=self.root/'restored.sqlite'
        with closing(sqlite3.connect(out)) as source_db, closing(sqlite3.connect(restored)) as restored_db:
            source_db.backup(restored_db)
        self.assertEqual(WorldLawStore(TimelineStore(restored)).open()['laws'],[rule('legacy')])
        with self.assertRaises(FileExistsError):
            migrate_legacy_copy(src,out,project_id='old-project',universe_id='old-universe')
        self.assertEqual(hashlib.sha256(src.read_bytes()).hexdigest(),before)


if __name__ == '__main__': unittest.main()
