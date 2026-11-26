import base64
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from story_graph.episode_timeline import TimelineStore
from tools.studio_ui import StudioRequestHandler


PNG = 'data:image/png;base64,' + base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode()
PNG2 = 'data:image/png;base64,' + base64.b64encode(b'\x89PNG\r\n\x1a\nother').decode()


class CoverChangeTests(unittest.TestCase):
    def test_cover_history_and_stale_updates_preserve_story(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TimelineStore(Path(tmp) / 'timeline.sqlite')
            store.create_episode('ep', 'Story', 'main', 10)
            store.save('ep', 0, graph={'nodes': [], 'edges': []}, script='Existing text', source_name='fixture')
            before = store.get_episode('ep')
            self.assertTrue(store.set_cover('ep', 1, None, PNG))
            self.assertFalse(store.set_cover('ep', 1, PNG, PNG))
            with self.assertRaisesRegex(ValueError, 'changed'):
                store.set_cover('ep', 1, None, PNG2)
            with self.assertRaisesRegex(ValueError, 'changed'):
                store.set_cover('ep', 0, PNG, PNG2)
            with self.assertRaises(ValueError):
                store.set_cover('ep', 1, PNG, 'data:image/png;base64,bm90IGFuIGltYWdl')
            self.assertTrue(store.set_cover('ep', 1, PNG, PNG2))
            after = store.get_episode('ep')
            for key in ('script', 'graph', 'head', 'branch', 'position'):
                self.assertEqual(before[key], after[key])
            self.assertEqual(after['cover'], PNG2)
            with store._connect() as db:
                history = list(db.execute('SELECT previous_cover,new_cover FROM episode_cover_history ORDER BY sequence'))
            self.assertEqual([tuple(row) for row in history], [(None, PNG), (PNG, PNG2)])

    def test_undo_and_redo_cover_preserve_story_and_history_via_store_and_http(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / 'timeline.sqlite'
            store = TimelineStore(db_path)
            store.create_episode('ep', 'Story', 'main', 10)
            store.save('ep', 0, graph={'nodes': [{'id': 'n1'}], 'edges': []}, script='Preserved text', source_name='fixture')
            store.set_cover('ep', 1, None, PNG)
            store.set_cover('ep', 1, PNG, PNG2)

            state = store.cover_history_state('ep')
            self.assertEqual((state['can_undo_cover'], state['can_redo_cover']), (True, False))

            with self.assertRaisesRegex(ValueError, 'changed'):
                store.undo_cover('ep', 0, PNG2)
            with self.assertRaisesRegex(ValueError, 'changed'):
                store.undo_cover('ep', 1, PNG)

            first = store.undo_cover('ep', 1, PNG2)
            self.assertEqual(first['cover'], PNG)
            self.assertTrue(first['can_undo_cover'] and first['can_redo_cover'])
            second = store.undo_cover('ep', 1, PNG)
            self.assertIsNone(second['cover'])
            self.assertFalse(second['can_undo_cover'])
            self.assertTrue(second['can_redo_cover'])
            with self.assertRaisesRegex(ValueError, 'No previous cover'):
                store.undo_cover('ep', 1, None)

            reapplied = store.redo_cover('ep', 1, None)
            self.assertEqual(reapplied['cover'], PNG)
            with store._connect() as db:
                history = list(db.execute('SELECT previous_cover,new_cover FROM episode_cover_history ORDER BY sequence'))
            self.assertEqual([tuple(row) for row in history], [(None, PNG), (PNG, PNG2)])

            server = ThreadingHTTPServer(('127.0.0.1', 0), StudioRequestHandler)
            server.timeline_path = db_path
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_address[1]}'

            def post(data):
                req = urllib.request.Request(
                    f'{base}/api/timeline',
                    data=json.dumps(data).encode('utf-8'),
                    headers={'Content-Type': 'application/json', 'Origin': base},
                    method='POST',
                )
                with urllib.request.urlopen(req) as resp:
                    return json.load(resp)

            try:
                html = urllib.request.urlopen(f'{base}/timeline').read().decode('utf-8')
                self.assertIn('undoCoverBtn', html)
                self.assertIn('redoCoverBtn', html)
                res = post({'action': 'redo_cover', 'id': 'ep', 'expected_revision': 1, 'expected_cover': PNG})
                self.assertEqual(res['cover'], PNG2)
                self.assertEqual(res['episode']['script'], 'Preserved text')
                res2 = post({'action': 'undo_cover', 'id': 'ep', 'expected_revision': 1, 'expected_cover': PNG2})
                self.assertEqual(res2['cover'], PNG)
                self.assertTrue(res2['episode']['can_redo_cover'])
                with self.assertRaises(urllib.error.HTTPError) as err:
                    post({'action': 'redo_cover', 'id': 'ep', 'expected_revision': 1, 'expected_cover': PNG2})
                self.assertEqual(err.exception.code, 400)
            finally:
                server.shutdown(); server.server_close(); thread.join()

    def test_cover_route_requires_same_origin(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = ThreadingHTTPServer(('127.0.0.1', 0), StudioRequestHandler)
            server.timeline_path = Path(tmp) / 'timeline.sqlite'
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            url = 'http://127.0.0.1:' + str(server.server_port)
            def post(data, origin):
                request = urllib.request.Request(url + '/api/timeline', data=json.dumps(data).encode(),
                                                 headers={'Content-Type': 'application/json', 'Origin': origin})
                with urllib.request.urlopen(request) as response: return json.load(response)
            try:
                post({'action': 'create', 'id': 'ep', 'title': 'Story', 'branch': 'main', 'position': 10}, url)
                change = {'action': 'set_cover', 'id': 'ep', 'expected_revision': 0, 'expected_cover': None, 'cover': PNG}
                with self.assertRaises(urllib.error.HTTPError) as error: post(change, 'http://invalid.example')
                self.assertEqual(error.exception.code, 403)
                self.assertTrue(post(change, url)['changed'])
                self.assertEqual(post({'action': 'open', 'id': 'ep'}, url)['episode']['cover'], PNG)
            finally:
                server.shutdown(); server.server_close(); thread.join()


class EpisodeReorderTests(unittest.TestCase):
    def test_move_episode_reorders_checks_revision_and_preserves_archived_slots(self):
        from pathlib import Path
        import tempfile
        from story_graph.episode_timeline import TimelineStore

        with tempfile.TemporaryDirectory() as tmp:
            store = TimelineStore(Path(tmp) / 'timeline.sqlite')
            store.create_episode('ep-a', 'Episode A', 'main', 10)
            store.create_episode('ep-b', 'Episode B', 'main', 20)
            store.create_episode('ep-c', 'Episode C', 'main', 30)

            with self.assertRaisesRegex(ValueError, 'Episode changed'):
                store.move_episode('ep-c', 99, direction='earlier')

            store.set_archived('ep-b', store.get_episode('ep-b')['head'], True)
            rev0 = store.scope()['scope_revision']
            cards = store.move_episode('ep-c', store.get_episode('ep-c')['head'], direction='earlier')
            self.assertEqual([c['id'] for c in cards if c['branch'] == 'main'], ['ep-c', 'ep-a'])
            self.assertGreater(store.scope()['scope_revision'], rev0)

            arch_b = next(c for c in store.archived_cards() if c['id'] == 'ep-b')
            store.set_archived('ep-b', arch_b['head'], False)
            restored = store.cards()
            self.assertEqual([c['id'] for c in restored if c['branch'] == 'main'], ['ep-c', 'ep-b', 'ep-a'])

            cards = store.move_episode('ep-b', store.get_episode('ep-b')['head'], after='start')
            self.assertEqual([c['id'] for c in cards if c['branch'] == 'main'], ['ep-b', 'ep-c', 'ep-a'])
            cards = store.move_episode('ep-b', store.get_episode('ep-b')['head'], after='end')
            self.assertEqual([c['id'] for c in cards if c['branch'] == 'main'], ['ep-c', 'ep-a', 'ep-b'])
            cards = store.move_episode('ep-c', store.get_episode('ep-c')['head'], after='ep-a')
            self.assertEqual([c['id'] for c in cards if c['branch'] == 'main'], ['ep-a', 'ep-c', 'ep-b'])
            cards = store.move_episode('ep-b', store.get_episode('ep-b')['head'], position=0)
            self.assertEqual([c['id'] for c in cards if c['branch'] == 'main'], ['ep-b', 'ep-a', 'ep-c'])

    def test_move_episode_protects_afm_starters_and_rejoin_target_order(self):
        from pathlib import Path
        import tempfile
        from story_graph.episode_timeline import TimelineStore

        with tempfile.TemporaryDirectory() as tmp:
            store = TimelineStore(Path(tmp) / 'timeline.sqlite')
            store.add_starter_cards()
            store.create_episode('ep-extra', 'Extra', 'main', 25)
            with self.assertRaisesRegex(ValueError, 'fixed story order'):
                store.move_episode('spring-break', store.get_episode('spring-break')['head'], after='hot-scoomp')
            cards = store.move_episode('ep-extra', store.get_episode('ep-extra')['head'], after='start')
            self.assertEqual([c['id'] for c in cards if c['branch'] == 'main'][:2], ['ep-extra', 'spring-break'])

        with tempfile.TemporaryDirectory() as tmp:
            store = TimelineStore(Path(tmp) / 'timeline.sqlite')
            store.create_episode('ep-fork', 'Fork Ep', 'main', 10)
            store.create_episode('ep-target', 'Target Ep', 'main', 20)
            store.fork('side', 'main', 'ep-fork', 0)
            store.create_episode('ep-side', 'Side Ep', 'side', 10)
            store.add_event('ev-side', 'ep-side', 0, 'Side discovery', status='approved', permitted=True, source_id='src-1', reviewer='ed')
            store.rejoin('ep-side', 'ev-side', 'ep-target', 0, 'ed', 'src-1', True)
            with self.assertRaisesRegex(ValueError, 'Rejoin target episode'):
                store.move_episode('ep-target', store.get_episode('ep-target')['head'], after='start')

    def test_timeline_http_move_and_page_controls(self):
        from http.server import ThreadingHTTPServer
        import json
        from pathlib import Path
        import tempfile
        import threading
        import urllib.error
        import urllib.request
        from story_graph.episode_timeline import TimelineStore
        from tools.studio_ui import StudioRequestHandler

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / 'timeline.sqlite'
            store = TimelineStore(db_path)
            store.create_episode('ep-a', 'Episode A', 'main', 10)
            store.create_episode('ep-b', 'Episode B', 'main', 20)
            store.create_episode('ep-c', 'Episode C', 'main', 30)
            ep_c_head = store.get_episode('ep-c')['head']

            server = ThreadingHTTPServer(('127.0.0.1', 0), StudioRequestHandler)
            server.timeline_path = db_path
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f'http://127.0.0.1:{server.server_address[1]}'
                html = urllib.request.urlopen(f'{base}/timeline').read().decode('utf-8')
                for marker in ('moveEpisodeAfter', 'moveEpisodeApply', 'moveEpisodeEarlier', 'moveEpisodeLater', 'applyTimelineHistory'):
                    self.assertIn(marker, html)
                html_classic = urllib.request.urlopen(f'{base}/timeline?theme=classic').read().decode('utf-8')
                self.assertIn('URLSearchParams', html_classic)

                req = urllib.request.Request(
                    f'{base}/api/timeline',
                    data=json.dumps({'action': 'move', 'id': 'ep-c', 'expected_revision': ep_c_head, 'after': 'start'}).encode('utf-8'),
                    headers={'Content-Type': 'application/json', 'Origin': base},
                    method='POST',
                )
                body = json.loads(urllib.request.urlopen(req).read().decode('utf-8'))
                self.assertEqual([c['id'] for c in body['cards'] if c['branch'] == 'main'], ['ep-c', 'ep-a', 'ep-b'])
                self.assertEqual(body['episode']['id'], 'ep-c')
                self.assertIn('scope_revision', body['scope'])

                bad_req = urllib.request.Request(
                    f'{base}/api/timeline',
                    data=json.dumps({'action': 'move', 'id': 'ep-c', 'expected_revision': 99, 'after': 'end'}).encode('utf-8'),
                    headers={'Content-Type': 'application/json', 'Origin': base},
                    method='POST',
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(bad_req)
                self.assertEqual(ctx.exception.code, 400)
            finally:
                server.shutdown(); server.server_close(); thread.join()

    def test_timeline_page_sqlite_history_atomic_create_after_and_cover_sync(self):
        import base64
        from http.server import ThreadingHTTPServer
        import json
        from pathlib import Path
        import tempfile
        import threading
        import urllib.request
        from story_graph.episode_timeline import TimelineStore
        from tools.studio_ui import StudioRequestHandler

        cover1 = 'data:image/png;base64,' + base64.b64encode(b'\x89PNG\r\n\x1a\ncov1').decode()
        cover2 = 'data:image/png;base64,' + base64.b64encode(b'\x89PNG\r\n\x1a\ncov2').decode()

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / 'timeline.sqlite'
            store = TimelineStore(db_path)
            store.create_episode('ep-a', 'Episode A', 'main', 10)
            store.create_episode('ep-b', 'Episode B', 'main', 11)

            server = ThreadingHTTPServer(('127.0.0.1', 0), StudioRequestHandler)
            server.timeline_path = db_path
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_address[1]}'

            def post(payload):
                req = urllib.request.Request(
                    f'{base}/api/timeline',
                    data=json.dumps(payload).encode('utf-8'),
                    headers={'Content-Type': 'application/json', 'Origin': base},
                    method='POST',
                )
                with urllib.request.urlopen(req) as resp:
                    return json.loads(resp.read().decode('utf-8'))

            try:
                html = urllib.request.urlopen(f'{base}/timeline').read().decode('utf-8')
                for marker in ('applyTimelineHistory', 'undo_history', 'redo_history'):
                    self.assertIn(marker, html)
                self.assertNotIn('noir-timeline-history', html)

                before_state = json.loads(urllib.request.urlopen(f'{base}/api/timeline').read().decode('utf-8'))['history']
                created = post({
                    'action': 'create', 'id': 'ep-gap', 'title': 'Gap Episode',
                    'branch': 'main', 'position': 99, 'after': 'ep-a',
                })
                self.assertEqual(created['history']['undo_count'], before_state['undo_count'] + 1)
                self.assertEqual(created['history']['next_undo_kind'], 'create')

                cards = json.loads(urllib.request.urlopen(f'{base}/api/timeline').read().decode('utf-8'))['cards']
                self.assertEqual([c['id'] for c in cards if c['branch'] == 'main'], ['ep-a', 'ep-gap', 'ep-b'])

                undone = post({'action': 'undo_history', 'expected_revision': created['history']['revision']})
                self.assertEqual(undone['kind'], 'create')
                self.assertEqual([c['id'] for c in undone['cards'] if c['branch'] == 'main'], ['ep-a', 'ep-b'])

                redone = post({'action': 'redo_history', 'expected_revision': undone['history']['revision']})
                self.assertEqual(redone['kind'], 'create')
                self.assertEqual([c['id'] for c in redone['cards'] if c['branch'] == 'main'], ['ep-a', 'ep-gap', 'ep-b'])

                c1 = post({
                    'action': 'set_cover', 'id': 'ep-a', 'expected_revision': 0,
                    'expected_cover': None, 'cover': cover1,
                })
                c2 = post({
                    'action': 'set_cover', 'id': 'ep-a', 'expected_revision': 0,
                    'expected_cover': cover1, 'cover': cover2,
                })
                self.assertEqual(c2['history']['next_undo_kind'], 'cover')

                uc = post({'action': 'undo_cover', 'id': 'ep-a'})
                self.assertEqual(uc['episode']['cover'], cover1)
                self.assertEqual(uc['history']['next_redo_kind'], 'cover')

                rc = post({'action': 'redo_cover', 'id': 'ep-a'})
                self.assertEqual(rc['episode']['cover'], cover2)
                self.assertEqual(rc['history']['next_undo_kind'], 'cover')

                with TimelineStore(db_path)._connect() as conn:
                    cover_rows = conn.execute("SELECT COUNT(*) FROM episode_cover_history WHERE episode='ep-a'").fetchone()[0]
                self.assertEqual(cover_rows, 2)
            finally:
                server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__': unittest.main()
