"""Versioned local Noir service for an explicitly selected workspace."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import hmac
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
from secrets import token_urlsafe
import sqlite3
from urllib.parse import parse_qsl, urlsplit
from uuid import uuid4

from story_graph.beat_map import map_episode
from story_graph.episode_timeline import TimelineStore
from story_graph.form_graph_store import FormGraphStore
from story_graph.source_imports import junctions
from story_graph.universe_scope import checked_id
from .episode_commands import EpisodeCommands
from .evidence_exchange import COMMANDS as EXCHANGE_COMMANDS
from .notebook import NotebookStore
from .providers.session_registry import WriterWindow
from .reference_service import ReferenceReaders
from .scoped_pipeline import recovery_scope
from .scoped_service import execute_scoped
from .timeline_commands import ACTIONS as TIMELINE_COMMANDS, EPISODE_FIELDS
from .branch_continuations import COMMANDS as BRANCH_COMMANDS
from .scene_bridges import COMMANDS as BRIDGE_COMMANDS
from .scene_plan_inputs import COMMANDS as PLAN_INPUT_COMMANDS
from .story_timeline import COMMAND as STORY_TIMELINE_COMMAND
from .mind_inspection import COMMAND as MIND_INSPECTION_COMMAND
from .processing import COMMANDS as PROCESSING_COMMANDS
from .media_graph import COMMANDS as MEDIA_COMMANDS
from story_graph.scene_fragments import COMMANDS as FRAGMENT_COMMANDS

API_VERSION = 1
MAX_REQUEST = 128_000
MAX_RESPONSE = 24_000_000
MAX_COVER_REQUEST = 1_400_000
MAX_EXCHANGE_REQUEST = 16_000
INTAKE_COMMANDS = frozenset({'intake.preview','intake.create','intake.receipt','intake.source'})
COMMANDS = frozenset({
    'director.open', 'director.preview', 'run.start', 'run.selection', 'run.selection.preview',
    'run.latest', 'run.status', 'run.resume', 'run.cancel',
    'episode.create', 'episode.prepare', 'episode.preparation.open', 'draft.open', 'draft.list', 'draft.compare', 'draft.apply',
    'notebook.undo', 'notebook.redo', 'graph.history', 'graph.undo', 'graph.redo', 'graph.cook',
    STORY_TIMELINE_COMMAND, MIND_INSPECTION_COMMAND, 'scene.plan.open',
}) | TIMELINE_COMMANDS | INTAKE_COMMANDS | BRANCH_COMMANDS | BRIDGE_COMMANDS | PROCESSING_COMMANDS | MEDIA_COMMANDS | FRAGMENT_COMMANDS | PLAN_INPUT_COMMANDS
SCOPED = frozenset({'context', 'export', 'retrieve', 'validate', 'rhythm-preview'})


class NoirService:
    def __init__(self, timeline, books, writer, *, forms=None, exchange_result=None):
        self.timeline = timeline
        self.books = Path(books).resolve(strict=True)
        if not self.books.is_dir():
            raise ValueError('Choose an existing book library directory')
        self.writer = writer
        self.instance = uuid4().hex
        self.readers = ReferenceReaders()
        self.workers = ThreadPoolExecutor(max_workers=1, thread_name_prefix='noir-writing')
        if forms is not None:
            self.timeline.form_graph_path = Path(forms).resolve()
        self.exchange_result = checked_id(exchange_result, 'Exchange branch result') if exchange_result else None

    def _form_store(self):
        if self.timeline.scope()['kind'] != 'afm-starters':
            return None
        with self.timeline._connect() as db:
            external = junctions(db, {})
        forms = self.timeline.form_graph_path
        return FormGraphStore(forms if forms.is_file() else None, imported=external)

    def _junctions(self):
        store = self._form_store()
        return store.junctions() if store is not None else {}

    def _writer_for(self, mode, episode):
        return self.writer.connect(mode, recovery_scope(self.timeline, episode))

    def _schedule(self, operation):
        def work():
            with self.readers.activate():
                operation()
        self.workers.submit(work)

    def close(self):
        self.workers.shutdown(wait=True)

    def dispatch(self, method, path, request=None):
        with self.readers.activate():
            return self._dispatch(method, path, request)

    def _dispatch(self, method, path, request):
        if (method, path) == ('GET', '/v1/status'):
            return {'protocol': API_VERSION, 'instance': self.instance, 'pid': os.getpid(),
                    'workspace': self.timeline.scope(), 'readers': self.readers.metrics(),
                    'writer': self.writer.status()}
        if (method, path) == ('GET', '/v1/episodes'):
            return EpisodeCommands(self.timeline).execute('timeline.catalog', {})
        if method != 'POST' or path not in ('/v1/open', '/v1/command', '/v1/cover', '/v1/intake', '/v1/scope', '/v1/exchange'):
            raise LookupError('Unknown service route or version')
        if not isinstance(request, dict):
            raise ValueError('Send a JSON object')
        if path == '/v1/open':
            episode = self.timeline.get_episode(request['episode'])
            source = map_episode(self.timeline, episode['id'], episode['head'], viewpoint=request.get('viewpoint'))
            notebook = NotebookStore(self.timeline).existing(episode['id'])
            if notebook and notebook['timeline_revision'] != episode['head']:
                notebook = {**notebook, 'stale': True}
            return {'episode': {key: episode[key] for key in EPISODE_FIELDS}, 'map': source, 'notebook': notebook}
        action = request.get('action')
        payload = request.get('request')
        if not isinstance(action, str) or not isinstance(payload, dict):
            raise ValueError('Send an action and a request object')
        if path == '/v1/exchange':
            if (not self.exchange_result or action not in EXCHANGE_COMMANDS or
                    payload.get('result') != self.exchange_result):
                raise LookupError('This ticket can only exchange evidence for its saved branch result')
            return EpisodeCommands(self.timeline, junctions=self._junctions).execute(action, payload)
        if path == '/v1/scope':
            if action not in SCOPED:
                raise LookupError('Unknown scoped service action')
            payload = {'reference_delivery': 'excerpt', **payload}
            binding = {'scene_plan':payload['scene_plan']} if 'scene_plan' in payload else None
            return execute_scoped(self.timeline, action, payload, junctions=self._junctions, books_root=self.books,
                                  continuation_binding=binding)
        if action not in COMMANDS:
            raise LookupError('Unknown episode service action')
        if (path == '/v1/cover') != (action == 'timeline.cover.set'):
            raise ValueError('Use the cover command on its image upload route')
        if ((path=='/v1/intake' and action not in INTAKE_COMMANDS|{'episode.create'})
                or (action in INTAKE_COMMANDS and path!='/v1/intake')):
            raise ValueError('Use the source intake route for document commands')
        if action in ('director.preview', 'run.start'):
            payload = {'reference_delivery': 'excerpt', **payload}
        if action == 'run.start':
            mode = payload.get('provider')
            if not isinstance(mode, str) or mode not in self.writer.allowed or self.writer.max_calls == 0:
                raise ValueError('The selected writer is not enabled in this window')
            for name, ceiling in (('max_attempts', self.writer.max_calls),
                                  ('max_input_bytes', self.writer.max_prompt_bytes)):
                value = payload.get(name)
                if type(value) is not int or not 0 < value <= ceiling:
                    raise ValueError(f'Choose {name} from 1 to {ceiling} for this service window')
        return EpisodeCommands(self.timeline, junctions=self._junctions, form_graph=self._form_store()
                               if (action.startswith('graph.') and action != 'graph.cook') or
                               action in ('episode.create','intake.create') else None, books_root=self.books,
                               provider_resolver=self._writer_for, schedule=self._schedule).execute(action, payload)


def workspace_key(timeline):
    scope = timeline.scope()
    bits = [os.path.normcase(str(Path(timeline.path).resolve())), scope['project_id'], scope['universe_id']]
    return sha256('\0'.join(bits).encode('utf-8')).hexdigest()


def open_ticket(path, port, workspace):
    """Create once or reopen the same connection; a lost ledger fails closed."""
    path = Path(path)
    url = f'http://127.0.0.1:{port}'
    if path.is_file():
        ticket = json.loads(path.read_text(encoding='utf-8'))
        if (ticket.get('protocol') != API_VERSION or ticket.get('workspace') != workspace or ticket.get('url') != url
                or not re.fullmatch(r'[A-Za-z0-9_-]{32,100}', ticket.get('token', ''))
                or not re.fullmatch(r'[0-9a-f]{32}', ticket.get('window', ''))):
            raise ValueError('Connection ticket belongs to a different service, port or workspace')
        if not path.with_suffix('.usage.jsonl.attempts.sqlite').is_file():
            raise ValueError('The saved service attempt ledger is missing; restore it before reconnecting')
        return ticket
    return {'protocol': API_VERSION, 'url': url, 'workspace': workspace, 'token': token_urlsafe(32), 'window': uuid4().hex}


def write_ticket(path, ticket):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        json.dump(ticket, handle)


def open_exchange_ticket(path, connection, result):
    expected = {k: connection[k] for k in ('protocol', 'url', 'workspace')}
    expected |= {'kind': 'scene-exchange', 'result': checked_id(result, 'Exchange branch result')}
    if path.is_file():
        ticket = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(ticket, dict) or set(ticket) != set(expected) | {'token'} or
                any(ticket[k] != v for k, v in expected.items()) or
                not isinstance(ticket['token'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,100}', ticket['token'])):
            raise ValueError('Exchange ticket belongs to a different service, workspace or branch result')
        return ticket
    return expected | {'token': token_urlsafe(32)}


class ServiceHTTP(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, service, token, *, exchange_token=None):
        super().__init__(('127.0.0.1', port), ServiceHandler)
        self.service = service
        self.token = token
        self.exchange_token = exchange_token


class ServiceHandler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(15)
        super().setup()

    def log_message(self, _fmt, *_args):
        pass  # No passage text, authentication headers or request data in access logs.

    def _reply(self, status, data):
        raw = json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(raw) > MAX_RESPONSE:
            status, raw = HTTPStatus.REQUEST_ENTITY_TOO_LARGE, b'{"error":"Service result exceeded its size limit"}'
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _clip(self, query):
        from .scene_clips import media, parse_byte_range
        pairs = parse_qsl(query, strict_parsing=True, max_num_fields=6)
        request = dict(pairs)
        keys = {'project','universe','episode','branch','id','sha256'}
        if len(pairs) != len(keys) or request.keys() != keys:
            raise ValueError('Open a saved clip from its story beat')
        asset, path = media(self.server.service.timeline, request)
        if asset['content_sha256'] != request['sha256']:
            raise ValueError('The clip edition changed; reopen Story Beats')
        total = asset['bytes']
        ranges = self.headers.get_all('Range') or []
        try:
            start, end = parse_byte_range(','.join(ranges) if ranges else None, total)
        except ValueError:
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header('Content-Range', f'bytes */{total}')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        with path.open('rb') as file:
            file.seek(start)
            remaining = end-start+1
            self.send_response(HTTPStatus.PARTIAL_CONTENT if ranges else HTTPStatus.OK)
            self.send_header('Content-Length', str(remaining))
            if ranges:
                self.send_header('Content-Range', f'bytes {start}-{end}/{total}')
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Type', asset['mime'])
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            while remaining:
                data = file.read(min(remaining, 65_536))
                if not data:
                    return
                self.wfile.write(data)
                remaining -= len(data)

    def _serve(self):
        try:
            bearer = self.headers.get('Authorization', '').encode('latin-1')
            token = self.server.exchange_token if self.path == '/v1/exchange' else self.server.token
            if (self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}'
                    or self.headers.get('Origin') is not None or not token
                    or not hmac.compare_digest(bearer, ('Bearer '+token).encode('ascii'))):
                self._reply(HTTPStatus.FORBIDDEN, {'error': 'A local service connection ticket is required'})
                return
            if self.command == 'GET' and self.path.startswith('/v1/clip?'):
                self._clip(urlsplit(self.path).query)
                return
            payload = None
            if self.command == 'POST':
                length = int(self.headers.get('Content-Length', '0'))
                if self.path == '/v1/intake':
                    from .intake import MAX_REQUEST as limit
                elif self.path == '/v1/exchange':
                    limit = MAX_EXCHANGE_REQUEST
                else:
                    limit = MAX_COVER_REQUEST if self.path == '/v1/cover' else MAX_REQUEST
                if (not 0 < length <= limit or self.headers.get_content_type() != 'application/json'
                        or self.headers.get('Transfer-Encoding') is not None):
                    raise ValueError('Send bounded application/json')
                payload = json.loads(self.rfile.read(length).decode('utf-8'))
            self._reply(HTTPStatus.OK, self.server.service.dispatch(self.command, self.path, payload))
        except (ValueError, KeyError, TypeError) as exc:
            self._reply(HTTPStatus.BAD_REQUEST, {'error': str(exc)[:500]})
        except LookupError as exc:
            self._reply(HTTPStatus.NOT_FOUND, {'error': str(exc)})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        except (OSError, sqlite3.Error):
            self._reply(HTTPStatus.SERVICE_UNAVAILABLE, {'error': 'The local workspace is unavailable'})

    do_GET = do_POST = _serve


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeline', required=True, type=Path, help='Existing, scoped timeline database')
    parser.add_argument('--books', required=True, type=Path, help='Local book library directory')
    parser.add_argument('--ticket', required=True, type=Path, help='Private connection ticket, outside source control')
    parser.add_argument('--forms', type=Path, help='Optional existing character form database')
    parser.add_argument('--exchange-ticket', type=Path, help='Private evidence-only connection ticket for another local app')
    parser.add_argument('--exchange-result', help='One registered saved branch result for the exchange ticket')
    parser.add_argument('--port', type=int, default=8790)
    parser.add_argument('--allow-writer', action='append', default=[])
    parser.add_argument('--max-attempts', type=int, default=0)
    parser.add_argument('--max-prompt-bytes', type=int, default=28_000)
    args = parser.parse_args(argv)
    if not args.timeline.is_file() or not 1 <= args.port <= 65535:
        parser.error('Choose an existing timeline and a valid local port')
    if args.forms is not None and not args.forms.is_file():
        parser.error('Explicit character form database does not exist')
    if bool(args.allow_writer) != bool(args.max_attempts):
        parser.error('Enable writers with an explicit positive attempt limit, or leave them disabled')
    if bool(args.exchange_ticket) != bool(args.exchange_result) or (
            args.exchange_ticket and args.exchange_ticket.resolve() == args.ticket.resolve()):
        parser.error('Set an exchange result and a separate exchange ticket together')
    try:
        timeline = TimelineStore(args.timeline.resolve())
        ticket = open_ticket(args.ticket, args.port, workspace_key(timeline))
        exchange = open_exchange_ticket(args.exchange_ticket, ticket, args.exchange_result) if args.exchange_ticket else {}
        if exchange.get('token') == ticket['token']:
            raise ValueError('The evidence and workspace tokens must be different')
        ledger = args.ticket.with_suffix('.usage.jsonl')
        writer = WriterWindow(ledger, ticket['window'], args.allow_writer, args.max_attempts, args.max_prompt_bytes)
        service = NoirService(timeline, args.books, writer, forms=args.forms, exchange_result=args.exchange_result)
        try:
            with ServiceHTTP(args.port, service, ticket['token'], exchange_token=exchange.get('token')) as server:
                if not args.ticket.is_file():
                    write_ticket(args.ticket, ticket)
                if exchange and not args.exchange_ticket.is_file():
                    write_ticket(args.exchange_ticket, exchange)
                print(f'Noir service v{API_VERSION} at {ticket["url"]}', flush=True)
                server.serve_forever()
        finally:
            service.close()
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(2, f'Service unavailable: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
