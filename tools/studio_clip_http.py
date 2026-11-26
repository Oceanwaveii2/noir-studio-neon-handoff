"""Loopback clip upload and byte-range playback for the Studio HTTP adapter."""
from __future__ import annotations

import sqlite3
from urllib.parse import parse_qs, quote


class ClipHTTPMixin:
    def _clip_query(self, url):
        return {k: v[0] for k,v in parse_qs(url.query).items()}

    def _serve_clip(self, url):
        from prose_engine.scene_clips import media
        if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
            self._form_json(403,{'error':'Open the clip in this Studio window.'}); return
        try:
            asset,path=media(self._timeline_store(),self._clip_query(url))
            file=path.open('rb')
        except (ValueError, OSError, sqlite3.Error):
            self._form_json(404,{'error':'This clip is unavailable in this episode.'}); return
        self._send_media(asset, file)

    def _send_media(self, asset, file, *, download=False):
        from prose_engine.scene_clips import parse_byte_range
        with file:
            total=asset['bytes']
            ranges=self.headers.get_all('Range') or []
            try:
                start,end=parse_byte_range(','.join(ranges) if ranges else None,total)
            except ValueError:
                self.send_response(416); self.send_header('Content-Range',f'bytes */{total}')
                self.send_header('Content-Length','0'); self.end_headers(); return
            count=end-start+1
            self.send_response(206 if ranges else 200)
            if ranges: self.send_header('Content-Range',f'bytes {start}-{end}/{total}')
            self.send_header('Content-Type',asset['mime'])
            if download:
                self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(asset['name'], safe=''))
            self.send_header('Content-Length',str(count))
            self.send_header('Accept-Ranges','bytes')
            self.send_header('Cache-Control','no-store')
            self.send_header('Cross-Origin-Resource-Policy','same-origin')
            self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers()
            try:
                file.seek(start)
                while count:
                    block=file.read(min(count,65536))
                    if not block: break
                    self.wfile.write(block)
                    count-=len(block)
            except (OSError, TimeoutError):
                self.close_connection=True

    def _upload_length(self):
        lengths = self.headers.get_all('Content-Length') or []
        if (len(lengths) != 1 or not lengths[0].strip().isascii() or not lengths[0].strip().isdecimal()
                or len(lengths[0].strip()) > 10 or self.headers.get('Transfer-Encoding') is not None):
            raise ValueError('This upload needs the source file size.')
        self.connection.settimeout(60)
        return int(lengths[0])

    def _upload_clip(self, url):
        from prose_engine.scene_clips import intake
        from story_graph.scene_fragments import SceneFragmentError
        host=f'127.0.0.1:{self.server.server_port}'
        self.close_connection=True
        if self.headers.get('Host')!=host or self.headers.get('Origin')!=f'http://{host}':
            self._form_json(403,{'error':'Open the episode in this Studio window.'}); return
        try:
            asset=intake(self._timeline_store(),self._clip_query(url),self.rfile,self._upload_length())
            self._form_json(201,{'asset':asset,'provider_calls':0})
        except SceneFragmentError as exc:
            self._form_json(400,{'error':str(exc),'code':exc.code})
        except (ValueError, OSError, sqlite3.Error) as exc:
            self._form_json(400,{'error':str(exc) if isinstance(exc,ValueError) else 'Could not save this clip locally.'})
