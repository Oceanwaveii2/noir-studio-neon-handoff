"""Clip use is scoped by file, period, beat and source revision."""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from prose_engine import scene_clips, scoped_pipeline
from prose_engine.episode_commands import EpisodeCommands
from prose_engine.notebook import NotebookStore
from story_graph.episode_timeline import TimelineStore


class SceneClipTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.store=TimelineStore(Path(temp.name)/'timeline.sqlite',project_id='p',universe_id='u')
        self.store.create_episode('one','One','main',1)
        self.store.create_episode('two','Two','main',2)
        source='INT. KITCHEN – NIGHT\n\nA mug sits on the table.\n'
        self.store.save('one',0,script=source,source_name='clip-fixture')
        self.scope={'project':'p','universe':'u','episode':'one','branch':'main'}
        notebook=NotebookStore(self.store); head=notebook.open('one')
        head=notebook.save('one',head['revision'],head['timeline_revision'],head['blocks'],25,[])
        self.nb=head
        self.calls=[]

        def write(request,prompt):
            self.calls.append((request.request_id,prompt))
            return 'A mug waits on the table.'

        class Writer:
            generate_rewrite=staticmethod(write)

        self.cmd=EpisodeCommands(self.store,provider_factory=Writer)
        graph=self.run_cmd('scene.fragment.import',timeline_revision=head['timeline_revision'],
                           selection={'start':0,'end':len(source)})['fragment']
        self.dest={'fragment':graph['id'],'fragment_revision':graph['revision'],
                   'timeline_revision':head['timeline_revision'],'node':graph['graph']['nodes'][-1]['id']}

    def run_cmd(self,op,**fields):
        return self.cmd.execute(op,self.scope|fields)

    def upload(self,name='review.mp4',data=b'artifact'):
        with patch.object(scene_clips,'_probe',return_value={'duration_ms':7_500,'clock':'clip-relative playback','video_codec':'h264'}):
            return scene_clips.intake(self.store,self.scope|{'name':name},BytesIO(data),len(data))

    def test_upload_round_trip_and_exact_scope(self):
        first=self.upload()
        self.assertEqual(first,self.upload('different-label.mp4'))
        _,file=scene_clips.media(self.store,self.scope|{'id':first['id']})
        self.assertEqual(file.read_bytes(),b'artifact')
        with self.assertRaisesRegex(ValueError,'not available'):
            scene_clips.media(self.store,self.scope|{'id':first['id'],'episode':'two'})
        with self.assertRaisesRegex(ValueError,'filename'):
            self.upload('../source.mp4')
        self.assertEqual(scene_clips.parse_byte_range('bytes=2-4',8),(2,4))
        self.assertEqual(scene_clips.parse_byte_range('bytes=-3',8),(5,7))
        with self.assertRaises(ValueError):
            scene_clips.parse_byte_range('bytes=0-4,5-7',8)

    def test_story_timeline_reopens_only_exact_scoped_clip_pins(self):
        asset = self.upload()
        note = 'Pause, then answer without looking up.'
        fields = self.dest | {'clip': asset['id'], 'purpose': 'performance', 'character': 'Narrator',
                              'note': note, 'start_ms': 1200, 'end_ms': 3400}
        pin = self.run_cmd('scene.clips.attach', **fields)['assignment']
        self.assertEqual(self.run_cmd('scene.clips.attach', **fields)['assignment'], pin)
        args = self.scope | {key: self.dest[key] for key in ('timeline_revision', 'fragment')}
        command = EpisodeCommands(TimelineStore(self.store.path), provider_factory=self.cmd.provider_factory)
        track = command.execute('scene.timeline.open', args)
        beats = [row for scene in track['scenes'] for row in scene['beats']]
        beat, = [row for row in beats if row['clips']]
        self.assertEqual(beat['destination'], pin['destination'])
        start, end = beat['passage']['start'], beat['passage']['end']
        self.assertEqual(beat['passage']['text'], self.store.get_episode('one')['script'][start:end])
        self.assertEqual(beat['clips'][0]['note'], note)
        self.assertEqual(beat['clips'][0]['clip'], asset['id'])
        self.assertEqual(beat['clips'][0]['observation_source'], 'author')
        self.assertEqual(track['provider_calls'], 0)
        with self.assertRaisesRegex(ValueError, 'saved branch'):
            command.execute('scene.timeline.open', args | {'branch': 'other'})
        with self.assertRaisesRegex(ValueError, 'current saved revision'):
            command.execute('scene.timeline.open', args | {'timeline_revision': args['timeline_revision'] + 1})
        self.assertEqual(self.calls, [])

    def test_purpose_and_scope_checks_preserve_current_beat(self):
        asset=self.upload()
        fields=self.dest|{'clip':asset['id'],'purpose':'cutaway','start_ms':1100,'end_ms':3400}
        pin=self.run_cmd('scene.clips.attach',**fields)['assignment']
        self.assertEqual(self.run_cmd('scene.clips.attach',**fields)['assignment'],pin)
        with self.assertRaisesRegex(ValueError,'current cutaway'):
            self.run_cmd('scene.clips.attach',**(fields|{'end_ms':5000}))
        with self.assertRaisesRegex(ValueError,'outside|fit'):
            self.run_cmd('scene.clips.attach',**(fields|{'end_ms':7501}))
        with self.assertRaisesRegex(ValueError,'personality or timing'):
            self.run_cmd('scene.clips.preview',**self.dest)
        self.assertEqual(self.run_cmd('scene.clips.open')['timeline_revision'],self.nb['timeline_revision'])
        self.run_cmd('scene.clips.detach',assignment=pin['id'])
        self.assertEqual(self.run_cmd('scene.clips.open')['assignments'],[])
        self.assertEqual(self.calls,[])

    def test_preview_uses_notes_only_and_a_changed_pin_invalidates_plan(self):
        asset=self.upload('do-not-send-filename.mp4')
        fields=self.dest|{'clip':asset['id'],'purpose':'timing','start_ms':100,'end_ms':2000}
        note='Hold before the reaction.'
        pin=self.run_cmd('scene.clips.attach',**fields,note=note)['assignment']
        with patch.object(scoped_pipeline,'prompt_for',wraps=scoped_pipeline.prompt_for) as make_prompt:
            preview=self.run_cmd('scene.clips.preview',**self.dest)
            make_prompt.assert_called_once()
        prompt=scoped_pipeline.prompt_for(*make_prompt.call_args.args,**make_prompt.call_args.kwargs)
        self.assertEqual(preview['provider_calls'],0)
        self.assertIn(note,prompt)
        self.assertNotIn(asset['name'],prompt)
        self.assertNotIn(asset['content_sha256'],prompt)
        self.run_cmd('scene.clips.detach',assignment=pin['id'])
        self.run_cmd('scene.clips.attach',**fields,note='Let the pause land.')
        with self.assertRaisesRegex(ValueError,'before generating'):
            self.run_cmd('scene.clips.run',**self.dest,plan=preview['plan'])
        self.assertEqual(self.calls,[])
        self.assertEqual(self.store.get_episode('one')['head'],self.nb['timeline_revision'])
