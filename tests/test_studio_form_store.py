from contextlib import contextmanager
from http.server import ThreadingHTTPServer
import json
import base64
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from tools.studio_form_store import FormGraphStore
from tools.studio_ui import HTML_TEMPLATE, StudioRequestHandler, form_targets
from story_graph.scenarios.foxy_mo2 import run_foxy_mo2
from story_graph.character_relationships import project
from prose_engine.dialogue_dial import relationship_delivery_context


class LiveCharacterStagingTests(unittest.TestCase):
    def test_routes_and_direction_persist_with_independent_mind_payload(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'forms.sqlite'
            forms = FormGraphStore(path)
            scope = dict(episode='first', branch='main', _episode_position=1)

            def change(action, **fields):
                return forms.change(dict(action=action, revision=forms.read()['revision'], **scope, **fields))

            with self.assertRaisesRegex(ValueError, 'locked'):
                change('stage_form', character='rainee', form='peter_griffin_celestial_variant')
            self.assertEqual(forms.read()['revision'], 0)
            change('add_form', character='rainee', form_id='disguise', label='Disguise')
            opaque = {'voices': [{'pacing': 'measured', 'nested': {'untyped': [1, False, None]}}]}
            change('create_mind_link', port='character:rainee:form:disguise', kind='super_character',
                   label='Demo mind', mind_payload=opaque)
            change('stage_form', character='rainee', form='disguise')
            change('set_relationship', character='rainee', form='disguise', target_character='roger',
                   target_form='roger', patience=0.2, friction=0.9, bridging_direction='Pause before answering.')
            change('set_relationship', character='roger', form='roger', target_character='rainee',
                   target_form='disguise', patience=0.9, friction=0.1)

            reopened = FormGraphStore(path)
            graph = reopened.read()
            node = next(item for item in graph['nodes'] if item['label'] == 'Demo mind')
            self.assertEqual((node['schema_mode'], node['mind_payload']), ('open', opaque))
            groups = reopened.junctions()
            self.assertEqual(groups['rainee'].route_at('first', 'main', 1), ('disguise', {'disguise', 'rainee'}))
            self.assertEqual(groups['rainee'].route_at('second', 'main', 1), (None, set()))
            edges = project({'rainee': ['disguise'], 'roger': ['roger']}, groups,
                            kind='generic', episode='first', branch='main', beat=0)
            self.assertEqual([row['patience'] for row in edges], [0.2, 0.9])
            cues = relationship_delivery_context(edges, {'disguise': 'Disguise'})
            self.assertIn('Disguise → Roger: short clipped impatience', cues)
            self.assertIn('Roger → Disguise: measured patient pacing', cues)
            self.assertFalse(project({'rainee': ['rainee'], 'roger': ['roger']}, groups,
                                     kind='generic', episode='first', branch='main', beat=0))
            change('undo_graph')
            self.assertEqual(len(reopened.read()['relationship_edges']), 1)
            self.assertEqual(reopened.junctions()['rainee'].forms, groups['rainee'].forms)


@contextmanager
def studio(path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), StudioRequestHandler)
    server.form_graph = FormGraphStore(path, form_targets())
    if (path.parent / 'timeline.sqlite').exists():
        server.timeline_path = path.parent / 'timeline.sqlite'
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def call(base, change=None, *, origin=None):
    headers = {"Content-Type": "application/json", "Origin": origin or base}
    request = Request(base + "/api/form-graph",
                      data=json.dumps(change).encode("utf-8") if change is not None else None,
                      headers=headers)
    try:
        response = urlopen(request, timeout=5)
    except HTTPError as exc:
        response = exc
    with response:
        return response.status, json.load(response)


def group(graph, character):
    return next(row for row in graph["junctions"] if row["character_id"] == character)


class StudioFormGraphTests(unittest.TestCase):
    def test_board_attachment_and_mind_are_saved_only_on_the_selected_form(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'forms.sqlite'
            with studio(path) as base:
                _, graph = call(base)
                normal, alternate = group(graph, 'rainee')['forms'][:2]
                port = alternate['port_id']
                # Real PNG, plus ordinary file bytes that must never get an inline preview.
                png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jR9sAAAAASUVORK5CYII=')
                for name, payload, image_only in [('reference.png', png, True), ('note.txt', b'local file', False)]:
                    code, graph = call(base, {'action': 'add_attachment', 'revision': graph['revision'],
                        'character': 'rainee', 'node': port, 'name': name, 'image_only': image_only,
                        'content': base64.b64encode(payload).decode()})
                    self.assertEqual(code, 200, graph)
                image, document = group(graph, 'rainee')['attachments']
                with urlopen(f"{base}/api/form-attachment?id={image['id']}&preview=1") as response:
                    self.assertEqual(response.headers.get_content_type(), 'image/png')
                    self.assertEqual(response.read(), png)
                with self.assertRaises(HTTPError) as err:
                    urlopen(f"{base}/api/form-attachment?id={document['id']}&preview=1")
                self.assertEqual(err.exception.code, 415)
                err.exception.close()

                board = {'notes': [{'id': 'a' * 32, 'text': 'Private drawing reference'}],
                         'positions': {f"file:{image['id']}": {'x': 83, 'y': 91}}}
                edit = {'action': 'save_board', 'revision': graph['revision'], 'character': 'rainee',
                        'port': port, 'board': board}
                code, invalid = call(base, dict(edit, port=normal['port_id']))
                self.assertEqual(code, 400, invalid)
                code, graph = call(base, edit)
                self.assertEqual(code, 200, graph)
                self.assertEqual(call(base, edit)[0], 409)
                code, graph = call(base, {'action': 'create_mind_link', 'revision': graph['revision'],
                    'port': port, 'kind': 'digital_mind', 'label': 'Form rehearsal mind'})
                self.assertEqual(code, 200, graph)
                linked = group(graph, 'rainee')['forms'][1]['link']['node_id']
                _, undone = call(base, {'action': 'undo_graph', 'revision': graph['revision']})
                self.assertEqual(group(undone, 'rainee')['forms'][1]['link'], alternate['link'])
                _, redone = call(base, {'action': 'redo_graph', 'revision': undone['revision']})
                self.assertEqual(group(redone, 'rainee')['forms'][1]['link']['node_id'], linked)

            reopened = FormGraphStore(path, form_targets())
            saved = group(reopened.read(), 'rainee')
            self.assertEqual(saved['boards'], {port: board})
            self.assertEqual(saved['forms'][0]['link'], normal['link'])
            self.assertNotIn('Private drawing reference', repr(reopened.junctions()))

    def test_graph_history_undo_redo_spans_node_changes_and_attachment(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'forms.sqlite'
            with studio(path) as base:
                _,graph=call(base);port=group(graph,'rainee')['forms'][0]['port_id']
                req={'character':'rainee','node':port}
                _,graph=call(base,{'action':'save_node_data','revision':graph['revision'],**req,'content':{'text_fields':{'voice':'First'}}})
                _,graph=call(base,{'action':'add_attachment','revision':graph['revision'],**req,'name':'a.txt','content':base64.b64encode(b'abc').decode()})
                item=group(graph,'rainee')['attachments'][0];self.assertTrue(graph['can_undo_graph'])
                status,graph=call(base,{'action':'undo_graph','revision':graph['revision']});self.assertEqual(status,200)
                self.assertEqual(group(graph,'rainee')['attachments'],[])
                status,graph=call(base,{'action':'undo_graph','revision':graph['revision']});self.assertEqual(status,200)
                self.assertNotIn(port,group(graph,'rainee')['node_data'])
            with studio(path) as base:
                _,graph=call(base);self.assertTrue(graph['can_redo_graph'])
                status,graph=call(base,{'action':'redo_graph','revision':graph['revision']});self.assertEqual(status,200)
                status,graph=call(base,{'action':'redo_graph','revision':graph['revision']});self.assertEqual(status,200)
                self.assertEqual(urlopen(base+'/api/form-attachment?id='+item['id']).read(),b'abc')

    def test_node_attachment_is_separate_recoverable_and_downloadable(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'forms.sqlite'
            with studio(path) as base:
                _,graph=call(base);normal,peter=[f['port_id'] for f in group(graph,'rainee')['forms']]
                add={'action':'add_attachment','revision':graph['revision'],'character':'rainee','node':normal,
                     'name':'Reference.txt','content':base64.b64encode(b'node reference').decode()}
                status,graph=call(base,add);self.assertEqual(status,200)
                item=group(graph,'rainee')['attachments'][0];self.assertEqual(item['node'],normal)
                self.assertEqual(urlopen(base+'/api/form-attachment?id='+item['id']).read(),b'node reference')
                self.assertEqual(call(base,{**add,'revision':graph['revision'],'node':peter,'name':'../unsafe'})[0],400)
                action={'action':'remove_attachment','revision':graph['revision'],'character':'rainee','node':normal,'attachment':item['id']}
                status,graph=call(base,action);self.assertEqual(status,200)
                with self.assertRaises(HTTPError):urlopen(base+'/api/form-attachment?id='+item['id'])
            with studio(path) as base:
                _,graph=call(base);status,graph=call(base,{**action,'action':'restore_attachment','revision':graph['revision']})
                self.assertEqual(status,200);self.assertEqual(urlopen(base+'/api/form-attachment?id='+item['id']).read(),b'node reference')

    def test_nodes_store_nested_data_independently_with_recovery(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'forms.sqlite'
            with studio(path) as base:
                _,graph=call(base); group_r=group(graph,'rainee')
                normal,peter=[f['port_id'] for f in group_r['forms']]
                content={'text_fields':{'voice':'A specific voice'},'custom':{'sources':['one','two'],'parameters':{'a':3}}}
                req={'action':'save_node_data','revision':graph['revision'],'character':'rainee','node':normal,'content':content}
                status,graph=call(base,req);self.assertEqual(status,200)
                self.assertEqual(group(graph,'rainee')['node_data'][normal],content)
                self.assertNotIn(peter,group(graph,'rainee')['node_data'])
                self.assertEqual(call(base,req)[0],409)
                self.assertEqual(call(base,{**req,'revision':graph['revision'],'character':'roger'})[0],400)
                updated={**content,'text_fields':{'voice':'Revised'},'custom':content['custom']}
                status,graph=call(base,{**req,'revision':graph['revision'],'content':updated});self.assertEqual(status,200)
            with studio(path) as base:
                _,graph=call(base);self.assertEqual(group(graph,'rainee')['node_data'][normal],updated)
                status,graph=call(base,{'action':'undo_node_data','revision':graph['revision'],'character':'rainee','node':normal})
                self.assertEqual(status,200);self.assertEqual(group(graph,'rainee')['node_data'][normal],content)
                self.assertTrue(group(graph,'rainee')['node_data_redo'][normal])
                status,graph=call(base,{'action':'redo_node_data','revision':graph['revision'],'character':'rainee','node':normal})
                self.assertEqual(status,200);self.assertEqual(group(graph,'rainee')['node_data'][normal],updated)
                status,graph=call(base,{'action':'undo_node_data','revision':graph['revision'],'character':'rainee','node':normal})
                self.assertEqual(status,200)
                status,graph=call(base,{**req,'revision':graph['revision'],'content':{'text_fields':{'voice':'New branch'}}})
                self.assertEqual(status,200);self.assertFalse(group(graph,'rainee')['node_data_redo'][normal])

    def test_character_node_positions_persist_independently_and_can_be_undone(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'forms.sqlite'
            with studio(path) as base:
                _, graph = call(base)
                rainee = group(graph,'rainee'); francine = group(graph,'francine'); roger = group(graph,'roger')
                self.assertEqual(francine['label'], 'Francine')
                self.assertEqual([f['display_label'] for f in francine['forms']], ['Francine (Normal)', 'Nurse Franny Anderson'])
                self.assertEqual([f['label'] for f in roger['forms']], ['Roger', 'MTV Beach Host', 'Rutgers Royal Persona'])
                rp = rainee['forms'][1]['port_id']; fp = francine['forms'][1]['port_id']; op = roger['forms'][1]['port_id']
                request = {'action':'move_node','revision':0,'character':'rainee','node':rp,'position':{'x':407.5,'y':120}}
                status,graph=call(base,request);self.assertEqual(status,200)
                self.assertEqual(group(graph,'rainee')['positions'][rp],{'x':407.5,'y':120})
                self.assertEqual(call(base,request)[0],409)
                self.assertEqual(call(base,{**request,'revision':graph['revision'],'character':'francine'})[0],400)
                self.assertEqual(call(base,{**request,'revision':graph['revision'],'position':{'x':True,'y':1}})[0],400)
                self.assertEqual(call(base,{**request,'revision':graph['revision'],'node':'data:'+rp})[0],400)
                status,graph=call(base,{'action':'move_node','revision':graph['revision'],'character':'francine','node':fp,'position':{'x':250,'y':55}})
                self.assertEqual(status,200)
                status,graph=call(base,{'action':'move_node','revision':graph['revision'],'character':'roger','node':op,'position':{'x':99,'y':80}})
                self.assertEqual(status,200)
                self.assertEqual(group(graph,'rainee')['positions'][rp]['x'],407.5)
                status,graph=call(base,{'action':'move_node','revision':graph['revision'],'character':'roger','node':roger['junction_id'],'position':{'x':20,'y':30}})
                self.assertEqual(status,200)
            with studio(path) as base:
                _,graph=call(base)
                self.assertEqual(group(graph,'roger')['positions'][op],{'x':99,'y':80})
                self.assertEqual(group(graph,'francine')['positions'][fp],{'x':250,'y':55})
                status,graph=call(base,{'action':'undo_position','revision':graph['revision'],'character':'francine'})
                self.assertEqual(status,200)
                self.assertNotIn(fp,group(graph,'francine')['positions'])
                self.assertEqual(group(graph,'rainee')['positions'][rp]['x'],407.5)
                self.assertEqual(call(base,{'action':'undo_position','revision':graph['revision'],'character':'francine'})[0],400)
                status,graph=call(base,{'action':'redo_position','revision':graph['revision'],'character':'francine'})
                self.assertEqual(status,200);self.assertEqual(group(graph,'francine')['positions'][fp],{'x':250,'y':55})

    def test_graph_backed_character_block_through_studio(self):
        from story_graph.episode_timeline import TimelineStore
        from prose_engine.notebook import NotebookStore
        with TemporaryDirectory() as directory:
            root = Path(directory)
            timeline = TimelineStore(root/'timeline.sqlite')
            timeline.create_episode('example','Example','main',1)
            timeline.save('example',0,script='Original.',source_name='fixture')
            state = NotebookStore(timeline).open('example')
            with studio(root/'forms.sqlite') as base:
                status, graph = call(base, {'action':'add_character','revision':0,'label':'Fixture Character'})
                self.assertEqual(status,200)
                character = next(g['character_id'] for g in graph['junctions'] if g['forms'][0]['label']=='Fixture Character')
                def append(speaker):
                    body = {'action':'append-block','episode':'example','revision':state['revision'],
                            'timeline_revision':state['timeline_revision'],'kind':'character','speaker':speaker}
                    request = Request(base+'/api/notebook',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Origin':base})
                    try: response = urlopen(request,timeout=5)
                    except HTTPError as exc: response = exc
                    with response: return response.status, json.load(response)
                self.assertEqual(append('unknown-character')[0],400)
                status, result = append(character)
                self.assertEqual(status,200)
                self.assertEqual(result['blocks'][-1]['speaker'], character)
            self.assertEqual(NotebookStore(timeline).existing('example')['blocks'][-1]['speaker'],character)

    def test_character_and_reference_images_are_bound_to_forms(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'forms.sqlite'
            with studio(path) as base:
                _, graph = call(base)
                rainee = group(graph, 'rainee')['forms']
                self.assertEqual(group(graph, 'rainee')['label'], 'Rainee')
                self.assertEqual(rainee[0]['display_label'], '2 Broke Girls Max Rainee (Normal)')
                self.assertEqual([f['id'] for f in rainee], ['rainee', 'peter_griffin_celestial_variant'])
                self.assertNotEqual(rainee[0]['port_id'], rainee[1]['port_id'])
                self.assertEqual(rainee[0]['image'], '/images/image6.jpeg')
                self.assertEqual(rainee[1]['image'], '/images/image11.png')
                status, graph = call(base, {'action':'add_character', 'revision':graph['revision'], 'label':'New Character'})
                self.assertEqual(status, 200)
                new = next(g for g in graph['junctions'] if g['forms'][0]['label']=='New Character')
                port = new['forms'][0]['port_id']
                self.assertEqual(call(base, {'action':'add_character','revision':graph['revision'],'label':'new character'})[0],400)
                self.assertEqual(call(base, {'action':'set_image','revision':graph['revision'],'port':port,'image':'data:image/png;base64,@@'})[0],400)
                png = 'data:image/png;base64,' + base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode('ascii')
                status, graph = call(base, {'action':'set_image','revision':graph['revision'],'port':port,'image':png})
                self.assertEqual(status,200)
                self.assertEqual(group(graph,new['character_id'])['forms'][0]['image'],png)
                self.assertEqual(call(base, {'action':'set_image','revision':0,'port':port,'image':png})[0],409)
            reloaded=FormGraphStore(path,form_targets()).read()
            self.assertEqual(group(reloaded,new['character_id'])['forms'][0]['image'],png)
            with studio(path) as base:
                status, restored = call(base, {'action':'undo_image','revision':reloaded['revision'],'port':port})
                self.assertEqual(status,200)
                self.assertIsNone(group(restored,new['character_id'])['forms'][0]['image'])

    def test_independent_ports_survive_restart_and_stale_tab_cannot_overwrite(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "forms.sqlite"
            with studio(path) as base:
                status, graph = call(base)
                self.assertEqual(status, 200)
                self.assertEqual(len(graph["junctions"]), 5)
                self.assertEqual(len(graph["beats"]), 20)
                mind = next(n["id"] for n in graph["nodes"] if n["kind"] == "digital_mind")
                normal, peter = [form["port_id"] for form in group(graph, "rainee")["forms"]]
                status, graph = call(base, {"action": "add_node", "revision": 0, "kind": "super_character",
                                            "label": "Test super node"})
                self.assertEqual(status, 200)
                super_node = next(n["id"] for n in graph["nodes"] if n["kind"] == "super_character")
                for port, node in ((normal, mind), (peter, super_node)):
                    status, graph = call(base, {"action": "set_link", "revision": graph["revision"],
                                                "port": port, "node_id": node})
                    self.assertEqual(status, 200)
                self.assertEqual(call(base, {"action": "set_link", "revision": 0,
                                             "port": peter, "node_id": None})[0], 409)
                self.assertEqual(call(base, {"action": "set_link", "revision": graph["revision"],
                                             "port": peter, "node_id": "unknown"})[0], 400)
                self.assertEqual(call(base, {"action": "set_link", "revision": graph["revision"],
                                             "port": peter, "node_id": None},
                                      origin="https://example.invalid")[0], 403)
            with studio(path) as base:
                _, graph = call(base)
                self.assertEqual([f["link"]["node_id"] for f in group(graph, "rainee")["forms"]],
                                 [mind, super_node])
                packets = run_foxy_mo2(FormGraphStore(path, form_targets()).junctions())
                self.assertEqual([f["link"]["node_id"] for f in packets[0].form_context["rainee"]["forms"]],
                                 [mind])
                self.assertEqual([f["link"]["node_id"] for f in packets[12].form_context["rainee"]["forms"]],
                                 [mind, super_node])
                status, graph = call(base, {"action": "set_link", "revision": graph["revision"],
                                            "port": peter, "node_id": None})
                self.assertEqual(status, 200)
                first, second = group(graph, "rainee")["forms"]
                self.assertEqual(first["link"]["node_id"], mind)
                self.assertIsNone(second["link"])

    def test_user_named_stages_append_before_final_and_stay_out_of_story(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "forms.sqlite"
            with studio(path) as base:
                _, graph = call(base)
                for name in ("Synthetic stage A", "Synthetic stage B"):
                    status, graph = call(base, {"action": "add_stella_stage", "revision": graph["revision"],
                                                "label": name})
                    self.assertEqual(status, 200)
                forms = group(graph, "stella")["forms"]
                self.assertEqual([f["kind"] for f in forms], ["base", "stage", "stage", "transformation"])
                self.assertEqual([f["after"] for f in forms[1:]], [f["id"] for f in forms[:-1]])
                self.assertTrue(all(f["port_id"] not in beat["forms"]
                                    for f in forms[1:] for beat in graph["beats"]))
                graph = FormGraphStore(path, form_targets()).read()
                self.assertEqual(group(graph, "stella")["forms"], forms)

    def test_character_graph_overview_and_three_field_cards_and_js_syntax(self):
        import re
        import shutil
        import subprocess
        import tempfile
        self.assertIn('id="characterGraphOverview"', HTML_TEMPLATE)
        self.assertIn('All characters (overview)', HTML_TEMPLATE)
        self.assertIn('character-graph-roster', HTML_TEMPLATE)
        self.assertIn('Scoped Generation Context:', HTML_TEMPLATE)
        self.assertIn('Structured profile fields', HTML_TEMPLATE)
        self.assertIn('Ports & connections', HTML_TEMPLATE)
        self.assertIn("[['personality','Personality'],['voice','Voice'],['notes','Notes']]", HTML_TEMPLATE)
        scripts = re.findall(r'<script>(.*?)</script>', HTML_TEMPLATE, re.S)
        self.assertTrue(scripts)
        node = shutil.which('node')
        if node:
            with tempfile.TemporaryDirectory() as directory:
                for idx, script in enumerate(scripts):
                    js_path = Path(directory) / f'studio_{idx}.js'
                    js_path.write_text(script, encoding='utf-8')
                    subprocess.run([node, '--check', str(js_path)], check=True)
