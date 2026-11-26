"""Loopback upload and playback of original Story Beats media."""
import sqlite3
from pathlib import Path

from prose_engine import media_graph
from story_graph.scene_fragments import SceneFragmentError
from tools.studio_clip_http import ClipHTTPMixin


TOOLS = Path(__file__).resolve().parent
PAGES = {'/processing': 'processing_page.html', '/beat-media': 'beat_media_page.html'}
ASSETS = {'/assets/processing.css': 'text/css', '/assets/processing.js': 'application/javascript',
          '/assets/beat_media.js': 'application/javascript'}


class MediaHTTPMixin(ClipHTTPMixin):
    def _media_get(self, url):
        if url.path == '/api/scene-clips/media':
            self._serve_clip(url)
            return True
        if url.path == '/api/beat-media/original':
            self._serve_beat_media(url)
            return True
        if url.path in PAGES:
            try:
                query = self._clip_query(url)
                self._timeline_store().get_episode(query.get('episode'))
                body = (TOOLS / PAGES[url.path]).read_bytes()
            except (ValueError, sqlite3.Error, OSError):
                self._form_json(404, {'error': 'Open a saved episode to inspect its processing or media.'})
                return True
            content_type = 'text/html'
        elif url.path in ASSETS:
            body = (TOOLS / 'assets' / Path(url.path).name).read_bytes()
            content_type = ASSETS[url.path]
        else:
            return False
        self.send_response(200)
        self.send_header('Content-Type', content_type + '; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(body)
        return True

    def _media_post(self, url):
        if url.path == '/api/beat-media/upload':
            self._upload_beat_media(url)
        elif url.path == '/api/scene-clips/upload':
            self._upload_clip(url)
        else:
            return False
        return True

    def _serve_beat_media(self, url):
        if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
            self._form_json(403, {'error': 'Open the media in this Studio window.'})
            return
        query = self._clip_query(url)
        try:
            asset, path = media_graph.original(self._timeline_store(), query)
            file = path.open('rb')
        except (ValueError, OSError, sqlite3.Error):
            self._form_json(404, {'error': 'The original is unavailable in this episode.'})
            return
        self._send_media(asset, file, download=asset['kind'] == 'document' or query.get('download') == '1')

    def _upload_beat_media(self, url):
        host = f'127.0.0.1:{self.server.server_port}'
        self.close_connection = True
        if self.headers.get('Host') != host or self.headers.get('Origin') != f'http://{host}':
            self._form_json(403, {'error': 'Open the episode in this Studio window.'})
            return
        try:
            result = media_graph.upload(self._timeline_store(), self._clip_query(url), self.rfile, self._upload_length())
            self._form_json(201, result)
        except SceneFragmentError as exc:
            self._form_json(400, {'error': str(exc), 'code': exc.code})
        except (ValueError, OSError, sqlite3.Error) as exc:
            self._form_json(400, {'error': str(exc) if isinstance(exc, ValueError) else 'Could not save the source locally.'})
