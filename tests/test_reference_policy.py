import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from prose_engine.influence import Influence
from prose_engine.reference_policy import ReferencePolicy, eligible_index, legacy_identities, restricted_drive, resolve_historical_rank_id, prompt_purposes
from prose_engine.vector_store import chunk_books, VectorSemanticDrive
from prose_engine.embedding_store import EmbeddingIndex
from prose_engine.voice.luar import LuarDrive, LuarIndex
from prose_engine.voice.retrieve import StyleDrive, StyleIndex


class ReferencePolicyTests(unittest.TestCase):
    def setUp(self):
        self.texts = ['allowed marker', 'off marker', 'unclassified marker']
        self.meta = [{'book': x} for x in ('allowed', 'off', 'unknown')]
        self.policy = ReferencePolicy({
            'allowed': {'enabled': True, 'permissions': ['rank_local', 'prompt', 'remote_transfer']},
            'off': {'enabled': True, 'permissions': ['rank_local', 'prompt', 'remote_transfer']}})
        self.influence = Influence({'off': 0})

    def test_authorization_and_influence_exclude_before_ranking(self):
        source = LuarIndex(np.eye(3), self.texts, self.meta)
        view = eligible_index(source, self.policy, ('rank_local','prompt','remote_transfer'), self.influence)
        self.assertEqual(view.texts, ['allowed marker'])
        self.assertEqual(len(source.texts), 3)
        self.assertEqual(view.vectors.shape, (1, 3))
        self.assertIsNone(eligible_index(source, ReferencePolicy({}), ('rank_local',)))
        self.assertIsNone(eligible_index(source, self.policy, ('export',)))

    def test_policy_missing_and_invalid_are_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(ReferencePolicy.load(d).status, 'unconfigured')
            Path(d,'reference_policy.json').write_text('{bad', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                ReferencePolicy.load(d)

    def test_remote_transfer_and_story_scope_are_separate(self):
        local = ReferencePolicy({'allowed': {'enabled': True, 'permissions': ['rank_local', 'prompt']}})
        self.assertTrue(local.allows({'book':'allowed'}, prompt_purposes('local')))
        self.assertFalse(local.allows({'book':'allowed'}, prompt_purposes('codex-session')))
        self.assertFalse(local.allows({'book':'allowed','episode':'future'}, ('rank_local',)))

    def test_luar_and_style_return_only_eligible_and_keep_id_when_rank_changes(self):
        encoder = SimpleNamespace(encode=lambda _: np.array([[1.,0.,0.]]))
        luar = LuarDrive(LuarIndex(np.eye(3), self.texts, self.meta), encoder=encoder)
        style = StyleDrive(StyleIndex(np.eye(3), self.texts, self.meta, encode=lambda _: np.array([1.,0.,0.])))
        for drive in (luar, style):
            bound = restricted_drive(drive, self.policy, ('rank_local','prompt','remote_transfer'), self.influence)
            hits = bound.retrieve_passages('test','query',max_results=3,influence=self.influence)
            self.assertEqual([h.text for h in hits], ['allowed marker'])
            self.assertTrue(hits[0].passage_id.startswith('legacy:'))

    def test_all_three_backends_select_same_sources_before_ranking(self):
        from prose_engine.reference_service import prepare_retrieval
        model = SimpleNamespace(encode=lambda texts, **kw: np.array([[1.,1.,1.]], dtype='float32'))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            policy={"schema_version":1,"sources":self.policy.sources}
            (root/"reference_policy.json").write_text(json.dumps(policy),encoding='utf-8')
            (root/"influence.json").write_text(json.dumps({"books":{"off":0}}),encoding='utf-8')
            for name in ("vector_index.joblib","luar_index.joblib","style_index.joblib"):
                (root/name).write_bytes(b"synthetic")
            topic=EmbeddingIndex(self.texts,self.meta,np.eye(3,dtype='float32'),_model=model)
            luar=LuarIndex(np.eye(3),self.texts,self.meta)
            style=StyleIndex(np.eye(3),self.texts,self.meta,encode=lambda _:np.array([1.,1.,1.]))
            encoder=SimpleNamespace(encode=lambda _:np.array([[1.,1.,1.]],dtype='float32'))
            with patch('prose_engine.embedding_store.load_index',return_value=topic), \
                 patch('prose_engine.voice.luar.LuarIndex.load',return_value=luar), \
                 patch('prose_engine.voice.retrieve.StyleIndex.load',return_value=style), \
                 patch('prose_engine.voice.luar.LuarEncoder',return_value=encoder):
                for backend in ('topic','luar','style'):
                    with self.subTest(backend=backend):
                        setup=prepare_retrieval(root,backend,'codex-session')
                        self.assertEqual(setup.state,'ready')
                        self.assertEqual(setup.drive.index.texts,['allowed marker'])
                        hits=setup.drive.retrieve_passages('test','query',max_results=3,influence=setup.influence)
                        self.assertEqual([hit.text for hit in hits],['allowed marker'])

    def test_legacy_duplicate_ids_are_position_based_not_rank_based(self):
        src=LuarIndex(np.eye(3), ['same','same','other'], [{'book':'x'}]*3)
        a=legacy_identities(src)
        b=legacy_identities(src)
        ids=[m['passage_id'] for m in a.meta]
        self.assertEqual(ids,[m['passage_id'] for m in b.meta])
        self.assertEqual(len(set(ids)),3)
        self.assertEqual(resolve_historical_rank_id('x-0')['status'],'unresolved')
        receipt={'passage_id':'x-0','book':'x','text':'same'}
        self.assertEqual(resolve_historical_rank_id('x-0',receipt,src)['status'],'ambiguous')
        receipt['anchor']=a.meta[1]['anchor']
        mapped=resolve_historical_rank_id('x-0',receipt,src)
        self.assertEqual(mapped['status'],'mapped')
        self.assertEqual(mapped['passage_id'],ids[1])

    def test_same_passage_has_same_id_when_query_changes_its_rank(self):
        src=LuarIndex(np.eye(3), ['first','second','third'], [{'book':'x'}]*3)
        vectors={'a':np.array([[1.,.5,0.]]),'b':np.array([[.5,1.,0.]])}
        drive=LuarDrive(src,encoder=SimpleNamespace(encode=lambda items:vectors[items[0]]))
        first={p.text:p.passage_id for p in drive.retrieve_passages('test','a',max_results=3)}
        second={p.text:p.passage_id for p in drive.retrieve_passages('test','b',max_results=3)}
        self.assertEqual(first,second)

    def test_new_chunk_ids_include_source_revision_and_position(self):
        source=SimpleNamespace(slug='fixture',title='Fixture',text='one')
        sentences=[' '.join(['word']*30)+'.']*2
        with patch('prose_engine.vector_store.D.split_into_sentences', return_value=sentences):
            one=chunk_books([source],target_words=25)
            two=chunk_books([source],target_words=25)
            source.text='changed'
            revised=chunk_books([source],target_words=25)
        self.assertEqual(one[0]['passage_id'],two[0]['passage_id'])
        self.assertNotEqual(one[0]['passage_id'],one[1]['passage_id'])
        self.assertNotEqual(one[0]['passage_id'],revised[0]['passage_id'])

    def test_new_provenance_survives_index_save_and_load(self):
        meta=[{'book':'fiction','source_id':'fiction','source_revision':'rev1',
               'passage_id':'passage:abc','anchor':{'chunk_ordinal':0},
               'chunker':'sentence-words-v1','embedding_model':'synthetic',
               'embedding_revision':'unversioned'}]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'synthetic.joblib'
            EmbeddingIndex(['original'],meta,np.ones((1,2),dtype='float32'),model_name='synthetic').save(path)
            loaded=EmbeddingIndex.load(path)
            self.assertEqual(loaded.meta,meta)
            self.assertEqual(legacy_identities(loaded).meta[0]['passage_id'],'passage:abc')

    def test_variant_generator_sends_only_configured_sources(self):
        from prose_engine.cli import build_parser, cmd_generate_variants
        model = SimpleNamespace(encode=lambda texts, **kw: np.array([[1.,1.,1.]], dtype='float32'))
        index = EmbeddingIndex(self.texts,self.meta,np.eye(3,dtype='float32'),_model=model)
        captured=[]
        provider=SimpleNamespace(generate_rewrite=lambda request,prompt: captured.append(prompt) or 'A fixture response.')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'vector_index.joblib').write_bytes(b'fixture')
            (root/'reference_policy.json').write_text(json.dumps({'schema_version':1,'sources':self.policy.sources}),encoding='utf-8')
            (root/'influence.json').write_text(json.dumps({'books':{'off':0}}),encoding='utf-8')
            scene=root/'scene.txt'
            scene.write_text('The character slowly walked across the large room and wondered what might happen. '*3,encoding='utf-8')
            args=build_parser().parse_args(['generate-variants','--file',str(scene),'--out',str(root/'out.json'),
                '--provider','mock','--books',d,'--allow-book-references','--strategies','action','--count','1'])
            with patch('prose_engine.cli.load_index',return_value=index), patch('prose_engine.cli.create_prose_provider',return_value=provider), patch('prose_engine.cli.ProseDiagnosticsAnalyzer.analyze',return_value=SimpleNamespace(warnings=['fixture'])):
                cmd_generate_variants(args)
            self.assertEqual(len(captured),1)
            self.assertIn('allowed marker',captured[0])
            self.assertNotIn('off marker',captured[0])
            self.assertNotIn('unclassified marker',captured[0])


if __name__ == '__main__':
    unittest.main()
