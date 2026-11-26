import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from prose_engine.providers import composer_bridge
from prose_engine.providers.primary_session import create_scoped_provider
from prose_engine.models import ProseRewriteRequest

class IsolationTests(unittest.TestCase):
    def test_gemini_uses_new_session_per_provider(self):
        paths=[]
        class Session:
            def __init__(self,path): paths.append(Path(path)); self.executable='fake'
            def run(self,prompt,label=None): return 'safe'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'composer'; (root/'narrative_composer').mkdir(parents=True)
            (root/'narrative_composer/__init__.py').write_text('',encoding='utf-8')
            config=Path(tmp)/'bridge.json'; config.write_text(json.dumps({'composer_root':str(root)}),encoding='utf-8')
            with patch.object(composer_bridge,'BRIDGE_CONFIG',config), patch.object(composer_bridge.importlib,'import_module',return_value=types.SimpleNamespace(GeminiCliSession=Session)):
                a=composer_bridge.load_isolated_composer_bridge('gemini')
                b=composer_bridge.load_isolated_composer_bridge('gemini')
                self.assertEqual(a('first'),'safe'); self.assertEqual(b('second'),'safe')
        self.assertNotEqual(paths[0],paths[1]); self.assertEqual(paths[0].parent.name,'scoped-sessions')
        self.assertNotEqual(paths[0].name,'gemini-u75-session.json')

    def test_scoped_provider_ignores_custom_handlers_and_is_single_use(self):
        with patch('prose_engine.providers.primary_session.load_isolated_composer_bridge',return_value=lambda _: 'safe') as factory:
            provider=create_scoped_provider('gemini-session')
            self.assertEqual(provider.max_calls,1); factory.assert_called_once_with('gemini')
        with self.assertRaises(ValueError): create_scoped_provider('local')
