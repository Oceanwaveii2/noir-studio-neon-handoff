"""Host-owned stdio session registration and workspace-wide attempt windows."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory

from .deepseek_session import DeepSeekSessionProvider
from .session_attempts import AttemptJournal, SessionAttemptError

PRIMARY = {'codex-session':'Codex','gemini-session':'Gemini'}
FRIENDLY = {'deepseek-session':'DeepSeek','claude-session':'Claude','grok-session':'Grok'}


def registered(config=None):
    path = config or os.environ.get('NOIR_SESSION_REGISTRY')
    if not path:
        return {}
    configuration=Path(path)
    if configuration.stat().st_size > 64_000:
        raise ValueError('Writer registry is too large')
    data = json.loads(configuration.read_text(encoding='utf-8-sig'))
    if data.get('schema_version') != 1 or not isinstance(data.get('writers'),dict) or len(data['writers']) > 12:
        raise ValueError('Invalid writer registry')
    out={}
    for mode,entry in data['writers'].items():
        if (not re.fullmatch(r'[a-z][a-z0-9-]{0,35}-session',mode) or mode in PRIMARY or not isinstance(entry,dict)):
            raise ValueError('Writer registry contains an invalid or reserved session name')
        argv=entry.get('argv')
        if (not isinstance(argv,list) or not 1 <= len(argv) <= 24 or
                any(not isinstance(arg,str) or not arg or len(arg)>512 or '\0' in arg for arg in argv) or
                not Path(argv[0]).is_absolute()):
            raise ValueError('Registered writer requires an absolute executable and fixed arguments')
        seconds=entry.get('timeout_seconds',90)
        label=entry.get('label',FRIENDLY.get(mode,mode.removesuffix('-session')))
        if type(seconds) is not int or not 1 <= seconds <= 180 or not isinstance(label,str) or not 1<=len(label)<=80 or not label.isprintable():
            raise ValueError('Invalid writer label or timeout')
        out[mode]={'argv':tuple(argv),'timeout_seconds':seconds,'label':label}
    return out


def session_names(config=None):
    return {**PRIMARY,**{name:entry['label'] for name,entry in registered(config).items()}}


def host_adapter(mode, config=None):
    if mode in PRIMARY:
        from .composer_bridge import load_isolated_composer_bridge
        return load_isolated_composer_bridge(mode.removesuffix('-session'))
    entry=registered(config).get(mode)
    if not entry or not Path(entry['argv'][0]).is_file():
        raise SessionAttemptError('The selected host writer is not installed or configured.',state='rejected')

    def send(prompt):
        with TemporaryDirectory(prefix='noir-writer-') as scratch:
            run = subprocess.run(entry['argv'], input=prompt.encode('utf-8'), capture_output=True,
                                 cwd=scratch, timeout=entry['timeout_seconds'],
                                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        response = run.stdout.decode('utf-8')
        if run.returncode or len(response)>1_000_000 or not response.strip():
            raise RuntimeError('The registered writer did not return a usable result.')
        return response
    return send


class WriterWindow:
    def __init__(self, ledger, window, allowed, max_calls, max_prompt_bytes, *, config=None, attach=None):
        self.ledger=Path(ledger)
        self.job='noir-window:'+window
        self.config=config
        self.names=session_names(config)
        self.allowed=frozenset(allowed)
        self.max_calls=max_calls
        self.max_prompt_bytes=max_prompt_bytes
        self.attach=attach or (lambda mode:host_adapter(mode,config))
        if not self.allowed <= self.names.keys() or type(max_calls) is not int or not 0<=max_calls<=32:
            raise ValueError('Choose configured writers with a finite service call limit (0–32)')
        if type(max_prompt_bytes) is not int or not 1<=max_prompt_bytes<=256_000:
            raise ValueError('Set a positive writer prompt byte limit')
        self.journal=AttemptJournal(self.ledger.with_name(self.ledger.name+'.attempts.sqlite'))
        # Empty writer windows must remain empty after restarts, too.
        self.journal.bind_window(self.job,json.dumps([sorted(self.allowed),max_calls,max_prompt_bytes]))

    def connect(self,mode,scope):
        if mode not in self.allowed or self.max_calls==0:
            raise SessionAttemptError('The selected writer is not enabled for this service window.',state='rejected')
        attached=self.attach(mode)
        provider=DeepSeekSessionProvider(session_handler=attached,max_calls=self.max_calls,ledger=self.ledger,
                                         job_id=self.job,recovery_scope=scope,shared_budget=True,
                                         max_prompt_bytes=self.max_prompt_bytes)
        provider.name=provider.model_name=mode
        return provider

    def status(self):
        attempts=[a for a in self.journal.list_attempts() if a['job']==self.job]
        return {'limit':self.max_calls,'used':len(attempts),'max_prompt_bytes':self.max_prompt_bytes,
                'sessions':[{'id':mode,'label':label,'enabled':mode in self.allowed and self.max_calls>0}
                            for mode,label in self.names.items()],
                'uncertain':sum(a['state'] in ('started','remote_unknown','cancel_requested') for a in attempts)}
