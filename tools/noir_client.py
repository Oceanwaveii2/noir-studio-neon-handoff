"""Standard-library client for the authenticated local Noir v1 service."""
from __future__ import annotations

from http.client import HTTPException
import json
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

_POST_LIMIT = {'/v1/cover':1_400_000, '/v1/intake':4*((32*1024*1024+2)//3)+1_405_000}

class ServiceError(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


class NoirClient:
    def __init__(self, ticket):
        self.ticket = Path(ticket)
        self.opener = build_opener(ProxyHandler({}), _NoRedirect())

    def request(self, route, data=None):
        if route not in {'/v1/status', '/v1/episodes', '/v1/open', '/v1/command', '/v1/cover', '/v1/intake', '/v1/scope'}:
            raise ValueError('Use a known local Noir v1 route')
        try:
            if self.ticket.stat().st_size > 4_096:
                raise ValueError('Invalid Noir connection ticket')
            settings = json.loads(self.ticket.read_text(encoding='utf-8'))
            base_url = settings['url']
            base = urlsplit(base_url)
            token = settings['token']
            if (settings['protocol'] != 1 or not base.port or base_url != f'http://127.0.0.1:{base.port}'
                    or not re.fullmatch(r'[A-Za-z0-9_-]{32,100}', token)):
                raise ValueError('Invalid Noir v1 connection ticket')
            headers = {'Authorization': 'Bearer '+token, 'Accept': 'application/json'}
            raw = None if data is None else json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
            if raw is not None:
                if len(raw) > _POST_LIMIT.get(route,128_000):
                    raise ValueError('Noir request exceeds its size limit')
                headers['Content-Type'] = 'application/json'
            with self.opener.open(Request(base_url+route, data=raw, headers=headers), timeout=115) as response:
                if response.headers.get_content_type() != 'application/json':
                    raise ValueError('Invalid Noir service response')
                result = response.read(24_000_001)
                if len(result) > 24_000_000:
                    raise ValueError('Noir service result exceeds its size limit')
                return json.loads(result)
        except HTTPError as exc:
            try:
                message = json.loads(exc.read(8_192)).get('error')
            except (ValueError, AttributeError):
                message = None
            raise ServiceError(message or f'Noir service rejected the request ({exc.code})') from exc
        except (OSError, URLError, HTTPException) as exc:
            raise ServiceError('Noir service is unavailable. Reconnect using the same ticket.') from exc
        except (KeyError, ValueError, TypeError) as exc:
            raise ServiceError(str(exc)) from exc

    def command(self, action, **request):
        route='/v1/command'
        if action=='timeline.cover.set':
            route='/v1/cover'
        elif action.startswith('intake.') or (action=='episode.create' and request.get('cover')):
            route='/v1/intake'
        return self.request(route,{'action': action, 'request': request})

    def scope(self, action, **request):
        return self.request('/v1/scope', {'action': action, 'request': request})
