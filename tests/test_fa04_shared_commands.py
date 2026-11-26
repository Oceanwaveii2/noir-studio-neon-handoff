"""Cross-client Timeline contract: replay, stale revisions and preserved data."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import base64
import unittest

from prose_engine.episode_commands import EpisodeCommands
from story_graph.episode_timeline import TimelineStore


class SharedTimelineTests(unittest.TestCase):
    def setUp(self):
        root = TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.path = Path(root.name)/'test.sqlite'
        self.store = TimelineStore(self.path)
        self.store.create_episode('one','One','main',10)
        self.store.create_episode('two','Two','main',20)
        self.api = EpisodeCommands(self.store)
        identity = self.store.scope()
        self.scope = {'project':identity['project_id'],'universe':identity['universe_id']}

    def catalog(self):
        return self.api.execute('timeline.catalog', self.scope)

    def move_request(self):
        return {**self.scope,'episode':'two','branch':'main','episode_revision':0,'after':'start',
                'expected_revision':self.catalog()['history']['revision'],'request_id':'original-move'}

    def order(self):
        return [row['id'] for row in self.catalog()['episodes']]

    def test_replayed_move_and_undo_read_the_current_tip_after_reopen(self):
        request = self.move_request()
        moved = self.api.execute('timeline.move',request)
        self.assertEqual(self.order(), ['two','one'])
        self.assertEqual(moved['status'],'APPLIED')
        undo_request = {**self.scope,'expected_revision':moved['history']['revision'],'request_id':'shared-undo'}
        undone = self.api.execute('timeline.undo',undo_request)
        self.assertEqual(self.order(), ['one','two'])
        self.api = EpisodeCommands(TimelineStore(self.path))
        current = self.catalog()
        replay = self.api.execute('timeline.move',request)
        self.assertEqual((replay['status'],replay['receipt'],replay['state']),
                         ('REPLAYED',moved['receipt'],current))
        self.assertEqual(self.api.execute('timeline.undo',undo_request)['receipt'],undone['receipt'])
        self.assertEqual(self.order(),['one','two'])
        self.assertTrue(current['history']['can_redo'])
        with self.assertRaisesRegex(ValueError,'different timeline change'):
            self.api.execute('timeline.move',{**request,'after':'end'})
        with self.assertRaisesRegex(ValueError,'Project does not match'):
            self.api.execute('timeline.move',{**request,'project':'someone-else'})
        self.api.execute('timeline.redo',{**self.scope,'expected_revision':current['history']['revision']})
        self.assertEqual(self.order(),['two','one'])

    def test_simultaneous_moves_use_the_same_stale_order_guard(self):
        request = self.move_request()
        ready = Barrier(2)

        def worker(req):
            store = TimelineStore(self.path)
            ready.wait(timeout=5)
            try:
                return EpisodeCommands(store).execute('timeline.move',req)['status']
            except ValueError as exc:
                return str(exc)

        competitor = {**request,'request_id':'second-move','episode':'one','after':'end'}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker,(request,competitor)))
        self.assertCountEqual(results, ['APPLIED','Timeline changed elsewhere. Refresh and try again.'])
        state = self.catalog()
        self.assertEqual(state['history']['revision'],request['expected_revision']+1)
        self.assertTrue(all(row['head']==0 for row in state['episodes']))

    def test_cover_and_removal_keep_history_and_script_separate(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest('Optional native cover decoder is unavailable')
        binary = BytesIO()
        Image.new('RGB',(15,12),'red').save(binary,format='PNG')
        cover = 'data:image/png;base64,'+base64.b64encode(binary.getvalue()).decode('ascii')
        req = {**self.scope,'expected_revision':self.catalog()['history']['revision'],
               'episode':'one','branch':'main','episode_revision':0}
        with self.assertRaisesRegex(ValueError,'different branch'):
            self.api.execute('timeline.archive',{**req,'branch':'different'})
        with self.assertRaisesRegex(ValueError,'not a complete'):
            self.api.execute('timeline.cover.set',{**req,'cover_version':None,'cover':'data:image/png;base64,iVBORw0KGgo='})
        opened = self.api.execute('timeline.cover.set',{**req,'cover_version':None,'cover':cover})
        self.assertEqual(self.store.get_episode('one')['cover'],cover)
        self.api.execute('timeline.archive',{**req,'expected_revision':opened['history']['revision']})
        self.assertEqual(self.order(),['two'])
        restored = self.api.execute('timeline.undo',{**self.scope,'expected_revision':self.catalog()['history']['revision']})
        self.assertEqual(self.store.get_episode('one')['cover'],cover)
        self.api.execute('timeline.undo',{**self.scope,'expected_revision':restored['history']['revision']})
        replay = self.api.execute('timeline.cover.set',{**req,'cover_version':None,'cover':cover})
        self.assertEqual(replay['status'],'REPLAYED')
        self.assertIsNone(self.store.get_episode('one')['cover'])
        self.assertEqual(self.store.get_episode('one')['head'],0)
