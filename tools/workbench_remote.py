"""Noir Workbench connected view; never imports the engine or opens a workspace."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit

from .noir_client import NoirClient, ServiceError


class ConnectedWorkbench(BaseHTTPRequestHandler):
    def log_message(self, _fmt, *_args):
        pass

    @property
    def origin(self):
        return f'http://127.0.0.1:{self.server.server_port}'

    def reply(self, status, value, *, mime='application/json; charset=utf-8'):
        raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(raw)

    def route(self):
        if self.headers.get('Host') != self.origin.removeprefix('http://'):
            self.reply(403, {'error': 'Use the local Workbench address'})
            return
        parsed = urlsplit(self.path)
        client = self.server.client
        try:
            if self.command == 'GET':
                if parsed.path in ('/', '/workbench_connected.js'):
                    name, mime = ('workbench_connected.html', 'text/html') if parsed.path == '/' else ('workbench_connected.js', 'text/javascript')
                    self.reply(200, (Path(__file__).parent/'assets'/name).read_bytes(), mime=mime+'; charset=utf-8')
                    return
                if parsed.path == '/api/session':
                    remote = client.request('/v1/status')
                    listing = client.request('/v1/episodes')
                    self.reply(200, {'episodes': listing['episodes'], 'service': remote,
                                     'history': listing['history'],
                                     'workbench': {'pid': os.getpid(), 'engine_imported': 'prose_engine' in sys.modules}})
                    return
                if parsed.path == '/api/episode':
                    episode = parse_qs(parsed.query)['episode'][0]
                    self.reply(200, client.request('/v1/open', {'episode': episode}))
                    return
            if self.command == 'POST' and parsed.path in ('/api/preview', '/api/writing', '/api/timeline'):
                if self.headers.get('Origin') != self.origin or self.headers.get_content_type() != 'application/json':
                    self.reply(403, {'error': 'Open this action inside the local Workbench'})
                    return
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 128_000:
                    raise ValueError('Invalid Workbench request size')
                data = json.loads(self.rfile.read(size).decode('utf-8'))
                if parsed.path == '/api/preview':
                    self.reply(200, client.scope('rhythm-preview', **data))
                elif parsed.path == '/api/timeline':
                    action = data.get('action')
                    if action not in ('timeline.undo', 'timeline.redo'):
                        raise ValueError('Choose Timeline Undo or Redo')
                    self.reply(200, client.command(action, **data['request']))
                else:
                    action = data.get('action')
                    if action not in ('run.latest', 'run.status', 'draft.list', 'draft.open', 'draft.compare',
                                      'scene.timeline.open', 'processing.open'):
                        raise ValueError('Use Studio or the service client to start or change a draft')
                    self.reply(200, client.command(action, **data['request']))
                return
            self.reply(404, {'error': 'Unknown Workbench action'})
        except ServiceError as exc:
            self.reply(503, {'error': str(exc)})
        except (OSError, TypeError, ValueError, KeyError):
            self.reply(400, {'error': 'Invalid Workbench request'})

    do_GET = do_POST = route


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service-ticket', required=True, type=Path)
    parser.add_argument('--port', default=8791, type=int)
    args = parser.parse_args(argv)
    with ThreadingHTTPServer(('127.0.0.1', args.port), ConnectedWorkbench) as server:
        server.client = NoirClient(args.service_ticket)
        print(f'Noir Workbench at http://127.0.0.1:{server.server_port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
