"""Local import and recovery tests; no writing provider is needed."""
import base64
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from prose_engine.episode_commands import EpisodeCommands
from prose_engine.notebook import NotebookStore, joined
from story_graph.episode_timeline import TimelineStore


def docx_bytes(text):
    out = BytesIO()
    with ZipFile(out,'w') as z:
        z.writestr('[Content_Types].xml','<Types/>')
        z.writestr('word/document.xml', text)
    return out.getvalue()


DOCX = '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p><w:r><w:t>INT. STUDIO</w:t></w:r></w:p><w:p/>
<w:p><w:r><w:t>Light stays on.</w:t><w:tab/><w:t>Wait.</w:t></w:r></w:p>
</w:body></w:document>'''


class EpisodeIntakeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.timeline = TimelineStore(Path(directory.name)/'episode.sqlite')
        self.timeline.create_episode('past','Past','main',0)
        self.timeline.create_episode('future','Future','main',1)
        self.api = EpisodeCommands(self.timeline,provider_factory=lambda:self.fail('Import must not call a writer'))

    def document(self,raw,name='Stage.docx'):
        return {'name':name,'base64':base64.b64encode(raw).decode()}

    def request(self,doc):
        preview = self.api.execute('intake.preview',{'document':doc})
        self.assertEqual(preview['status'],'READY')
        self.assertEqual([x['id'] for x in self.timeline.cards()],['past','future'])
        return {'document':doc,'file_sha256':preview['source']['sha256'],'text_sha256':preview['source']['text_sha256'],
                'request_id':'prepared-copy','title':'Imported scene','prompt':'Keep this turn.',
                'provider':'codex-session','branch':'main','after':'past'}

    def test_docx_open_positions_matches_preview_and_recovers(self):
        raw = docx_bytes(DOCX)
        request=self.request(self.document(raw))
        result=self.api.execute('intake.create',request)
        episode=result['episode']
        self.assertEqual([x['id'] for x in self.timeline.cards()],['past',episode,'future'])
        state=NotebookStore(self.timeline).existing(episode)
        self.assertEqual(joined(state['blocks']),'INT. STUDIO\n\nLight stays on.\tWait.')
        self.assertEqual(state['default_protection'],100)
        self.assertEqual(result['prompt'],'Keep this turn.')
        self.assertEqual(result['source']['sha256'],sha256(raw).hexdigest())
        with self.timeline._connect() as c:
            self.assertEqual(c.execute('SELECT original FROM episode_intake WHERE episode=?',(episode,)).fetchone()[0],raw)
        reopened=EpisodeCommands(TimelineStore(self.timeline.path))
        before=reopened.execute('timeline.history',{})
        with patch('prose_engine.intake._docx',side_effect=AssertionError('Saved replay must not parse the document again')):
            self.assertEqual(reopened.execute('intake.create',request)['status'],'REPLAYED')
        lookup=reopened.execute('intake.receipt',{'request_id':request['request_id']})
        self.assertEqual((lookup['status'],lookup['receipt']['episode']),('COMMITTED',episode))
        self.assertEqual(reopened.execute('timeline.history',{}),before)
        with self.assertRaisesRegex(ValueError,'different episode request'):
            self.api.execute('intake.create',{**request,'title':'Other'})
        history=self.api.execute('timeline.history',{})
        undo=self.api.execute('timeline.undo',{'expected_revision':history['revision']})
        self.assertEqual([x['id'] for x in self.timeline.cards()],['past','future'])
        self.api.execute('timeline.redo',{'expected_revision':undo['history']['revision']})
        self.assertEqual(self.timeline.get_episode(episode)['script'],joined(state['blocks']))

    def test_mismatched_extraction_and_bad_destination_do_not_create(self):
        request=self.request(self.document(docx_bytes(DOCX)))
        with self.assertRaisesRegex(ValueError,'differs from the preview'):
            self.api.execute('intake.create',{**request,'text_sha256':'stale'})
        with self.assertRaisesRegex(ValueError,'same branch'):
            self.api.execute('intake.create',{**request,'after':'missing'})
        self.assertEqual([x['id'] for x in self.timeline.cards()],['past','future'])
        with self.timeline._connect() as c:
            self.assertIsNone(c.execute("SELECT 1 FROM sqlite_master WHERE name='episode_intake'").fetchone())

    def test_pdf_reports_pages_without_text_instead_of_inventing_words(self):
        try:
            import pymupdf
        except ImportError:
            self.skipTest('Optional PDF reader not installed')
        with pymupdf.open() as source:
            source.new_page().insert_text((72,72),'INT. STUDIO')
            source.new_page()
            raw=source.tobytes()
        result=self.api.execute('intake.preview',{'document':self.document(raw,'Script.pdf')})
        self.assertEqual(result['source']['pages_requiring_ocr'],[2])
        self.assertIn('INT. STUDIO',result['text_preview'])
        request=self.request(self.document(raw,'Script.pdf'))
        with self.assertRaisesRegex(ValueError,'no selectable'):
            self.api.execute('intake.create',request)
        self.assertEqual(self.api.execute('intake.receipt',request)['status'],'NOT_FOUND')
        created=self.api.execute('intake.create',{**request,'accept_partial':True})
        part=self.api.execute('intake.source',{'episode':created['episode'],'branch':'main'})
        self.assertEqual(base64.b64decode(part['base64']),raw)
        self.assertEqual(part['source']['pages_requiring_ocr'],[2])

    def test_plain_text_sources_keep_unicode_and_original_line_endings(self):
        text='INT. STUDIO\r\n\r\nFRANCINE\r\nWait… it’s café time.\t🎬\r\n'
        raw=b'\xef\xbb\xbf'+text.encode('utf-8')
        for ext in ('md','txt','fountain'):
            request_id='plain-'+ext
            document=self.document(raw,'Source.'+ext)
            preview=self.api.execute('intake.preview',{'document':document})
            result=self.api.execute('intake.create',{
                'document':document, 'request_id':request_id,'title':'Text '+ext,
                'file_sha256':preview['source']['sha256'],'text_sha256':preview['source']['text_sha256'],
            })
            episode=result['episode']
            self.assertEqual(self.timeline.get_episode(episode)['script'],text)
            for part,expected in (('original',raw),('transcript',text.encode('utf-8'))):
                ctx={'episode':episode,'branch':'main','part':part,'count':17}
                output=b''
                while len(output)<len(expected):
                    data=self.api.execute('intake.source',{**ctx,'offset':len(output)})
                    self.assertEqual(data['total_bytes'],len(expected))
                    self.assertEqual(data['sha256'],sha256(expected).hexdigest())
                    output+=base64.b64decode(data['base64'])
                    self.assertEqual(len(output),data['next_offset'])
                self.assertEqual(output,expected)
                self.assertEqual(self.api.execute('intake.source',{**ctx,'offset':len(expected)})['base64'],'')
            with self.assertRaisesRegex(ValueError,'branch'):
                self.api.execute('intake.source',{'episode':episode,'branch':'wrong'})
            with self.assertRaisesRegex(ValueError,'Universe does not match'):
                self.api.execute('intake.receipt',{'request_id':request_id,'universe':'wrong'})

    def test_stale_or_ambiguous_sources_cannot_create_a_card(self):
        docx=DOCX.replace('<w:p/>','<w:p><w:ins><w:r><w:t>Tracked line.</w:t></w:r></w:ins></w:p>')
        with self.assertRaisesRegex(ValueError,'tracked or linked'):
            self.api.execute('intake.preview',{'document':self.document(docx_bytes(docx))})
        with self.assertRaisesRegex(ValueError,'UTF-8'):
            self.api.execute('intake.preview',{'document':self.document(b'\xffbroken','Stage.md')})
        req=self.request(self.document(docx_bytes(DOCX)))
        stale=self.timeline.history_state()['revision']-1
        with self.assertRaisesRegex(ValueError,'changed elsewhere'):
            self.api.execute('intake.create',{**req,'expected_revision':stale})
        self.assertEqual(self.api.execute('intake.receipt',req)['status'],'NOT_FOUND')
        self.assertEqual([x['id'] for x in self.timeline.cards()],['past','future'])


if __name__ == '__main__':
    unittest.main()
