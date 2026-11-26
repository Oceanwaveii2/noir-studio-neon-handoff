import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from story_graph.episode_timeline import TimelineStore

class ScopedCliTests(unittest.TestCase):
    def test_export_and_retrieval_exclude_future(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'timeline.sqlite'; s=TimelineStore(path);s.add_starter_cards()
            s.save('spring-break',0,script='Quiet scene.',source_name='fixture')
            s.add_event('later','tapped-out',1,'A future glitter incident.',status='approved',permitted=True,source_id='test',reviewer='test')
            base=[sys.executable,'-B','-m','prose_engine','scoped']
            tail=['--timeline',str(path),'--episode','spring-break','--beat','1','--revision','1','--start','0','--end','12']
            p=subprocess.run(base+['export']+tail,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(p.returncode,0,p.stderr);self.assertNotIn('glitter',p.stdout);self.assertEqual(json.loads(p.stdout)['scope']['target'],'Quiet scene.')
            p=subprocess.run(base+['export']+tail+['--protected-ranges','[[0,5]]'],capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertEqual(json.loads(p.stdout)['scope']['protected_ranges'],[[0,5]])
            p=subprocess.run(base+['retrieve']+tail+['--query','glitter'],capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(json.loads(p.stdout)['results'],[])
            p=subprocess.run(base+['export']+tail+['--spring-source',str(path)],capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertNotEqual(p.returncode,0)
