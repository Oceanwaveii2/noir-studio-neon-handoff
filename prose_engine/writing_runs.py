"""Durable, bounded orchestration of the existing scoped writing service."""
from __future__ import annotations

import json
import re
from sqlite3 import OperationalError
import threading
import time
from contextlib import contextmanager
from uuid import uuid4

from story_graph import director
from .beat_workflow import _prepare_group, assemble_group
from .notebook import DraftStore, NotebookStore
from .scoped_service import execute_scoped


LEASE_SECONDS = 45
SELECTION_STAGE_SECONDS = {'context':120, 'writer-1':30, 'write-1':195, 'validate-1':45, 'save':30}
_KEY = re.compile(r'[A-Za-z0-9_.:-]{1,125}\Z')
_REQUEST = ('episode','revision','branch','project','universe','source_sha256','anchor_token',
            'viewpoint','beats','direction','provider','references','reference_delivery','craft_mode','scene_function','plan_id',
            'max_attempts','max_input_bytes','max_output_chars','notebook_revision')
_SELECTION = ('beat', 'start', 'end', 'protected_ranges', 'law_revision', 'passage_anchor',
              'parent_draft', 'scene_plan', 'polish_draft', 'guidance', 'rhythm_plan_id', 'expected_prompt_sha256',
              'compositor_preparation')


def _key(value):
    if not isinstance(value,str) or not _KEY.fullmatch(value):
        raise ValueError('A stable request ID is required')
    return value


def _bound(value, lo, hi, label):
    if type(value) is not int or not lo <= value <= hi:
        raise ValueError(f'{label} must be between {lo} and {hi}')
    return value


def _normalize(request, *, selection=False):
    req = {k: request[k] for k in _REQUEST if k in request}
    if selection:
        req.pop('beats', None)
        req.pop('plan_id', None)
        req.update({k: request[k] for k in _SELECTION if k in request})
    required = ('episode','branch','project','universe') if selection else (
        'episode','branch','project','universe','source_sha256')
    for k in required:
        if not isinstance(req.get(k),str) or not req[k]:
            raise ValueError(f'Saved {k} is required')
    if ((not selection or 'notebook_revision' in req)
            and (type(req.get('notebook_revision')) is not int or req['notebook_revision'] < 0)):
        raise ValueError('The saved protection revision is required')
    req.setdefault('viewpoint', None)
    req.setdefault('direction', '')
    req.setdefault('scene_function', 'scene')
    req.setdefault('provider', 'codex-session')
    req.setdefault('references', 'none')
    req['max_attempts'] = _bound(req.get('max_attempts',1 if selection else 8),0,8,'Writer attempt limit')
    req['max_input_bytes'] = _bound(req.get('max_input_bytes',96_000),1,256_000,'Input byte limit')
    req['max_output_chars'] = _bound(req.get('max_output_chars',8_000),1,20_000,'Per-passage output limit')
    return req


def _prepare(timeline, req, options):
    direction = director.plan(timeline, req, proposal=True)
    if req.get('plan_id') is not None and req['plan_id'] != direction['id']:
        raise ValueError('Director plan changed; reopen the selected beats')
    _, _, jobs, previews, guidance = _prepare_group(timeline, req, director_plan=direction, **options)
    parts = []
    for job, preview in zip(jobs, previews):
        scope = preview['scope']
        if scope['protection_revision'] != req['notebook_revision']:
            raise ValueError('Protection changed; reload the saved episode')
        parts.append({'cutoff':scope['beat'], 'start':scope['start'], 'end':scope['end'],
                      'locked':preview['rhythm_guidance']['fully_locked'],
                      'input_bytes':preview['prompt_bytes'],
                      'scope_receipt':director.fingerprint(scope),
                      'rhythm_plan_id':preview['rhythm_guidance']['id'],
                      'reference_receipt':director.fingerprint(preview['reference_binding'])})
    calls = sum(not part['locked'] for part in parts)
    size = sum(part['input_bytes'] for part in parts)
    if calls > req['max_attempts'] or size > req['max_input_bytes']:
        raise ValueError(f'The selected beats need {calls} writer slots and {size} UTF-8 prompt bytes; '
                         'choose a smaller group or adjust the run limits')
    manifest = {'director':direction, 'parts':parts, 'planned_attempts':calls, 'planned_input_bytes':size}
    return manifest,jobs,previews,guidance


def _draft_id(run, index):
    return director.fingerprint(['noir-writing-run',run,index])[:32]


def _processing_id(run):
    return 'writing-' + _draft_id(run, 'group')


def _output_id(run, kind):
    return _draft_id(run, 0 if kind == 'selection' else 'group')


def _lease_end(row, payload):
    deadline = payload.get('processing', {}).get('deadline_at')
    lease = row['expires']
    return min(lease, deadline) if deadline is not None and lease is not None else lease


def read_processing(c, scope, ident=None, *, now=None):
    """Project the persisted run and its draft receipts without starting or resuming work."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='episode_writing_runs'").fetchone():
        return []
    now = time.time() if now is None else now
    rows = c.execute('SELECT * FROM episode_writing_runs WHERE episode=? AND branch=? ORDER BY rowid DESC',
                     (scope['episode'], scope['branch']))
    jobs = []
    for row in rows:
        run_id = _processing_id(row['id'])
        if ident and ident != run_id:
            continue
        data = json.loads(row['payload'])
        req = data['request']
        if (req['project'], req['universe']) != (scope['project'], scope['universe']):
            continue
        status = WritingRuns._describe(c, row, now=now)
        observed = data.get('processing', {})
        expired = row['state']=='RUNNING' and _lease_end(row, data) < now
        final = row['state'] not in ('QUEUED', 'RUNNING') or expired
        created = observed.get('created_at', row['updated'])
        end = max(created, _lease_end(row, data) if expired else row['updated'] if final else now)
        steps = []

        def add(key, stage, label, fallback='QUEUED', inputs=None, outputs=None):
            step = dict(observed.get('steps', {}).get(key, {}))
            state = step.get('status', fallback)
            if fallback in ('FAILED', 'UNKNOWN') or (state == 'QUEUED' and fallback != 'QUEUED'):
                state = fallback
            if final and state == 'RUNNING':
                state = 'UNKNOWN' if expired or row['state']=='UNKNOWN' else 'FAILED'
            elif final and state == 'QUEUED':
                state = 'SKIPPED'
            step.update(id=key, stage=stage, label=label, status=state)
            started = step.get('started_at')
            step['elapsed_ms'] = max(0, round((step.get('finished_at', end)-started)*1000)) if started is not None else None
            if inputs:
                step['inputs'] = inputs
            if outputs:
                step['outputs'] = outputs
            steps.append(step)

        manifest = data.get('manifest') or {}
        selection = data.get('kind') == 'selection'
        context_state = 'COMPLETED' if any(part['draft_id'] for part in status['parts']) else 'QUEUED'
        add('context', 'Context', 'Compile saved writing scope', context_state,
            {'revision':req['revision'], 'planned_attempts':manifest.get('planned_attempts'),
             'planned_input_bytes':manifest.get('planned_input_bytes')})
        for part in status['parts']:
            index = part['index']
            receipt = {key:part[key] for key in ('draft_id', 'attempt_id', 'provider_request_id') if part[key]}
            part_state = part['status']
            writing = 'SKIPPED' if part['locked'] else 'COMPLETED' if part_state in ('PROPOSED', 'BLOCKED') else 'QUEUED'
            stages = observed.get('steps', {})
            returned = stages.get(f'write-{index}', {}).get('status') == 'COMPLETED'
            if selection:
                add(f'writer-{index}', 'Writer', 'Check writer and attempt journal')
            if not part['locked'] and not returned and (part_state=='UNKNOWN' or
                    (expired and part_state=='STARTED' and f'validate-{index}' not in stages)):
                writing = 'UNKNOWN'
            elif not part['locked'] and part_state == 'FAILED' and (not selection or f'write-{index}' in stages):
                writing = 'FAILED'
            add(f'write-{index}', 'Writing', f'Write passage {index}', writing,
                {'input_bytes':part['input_bytes']} if not part['locked'] else None, receipt)
            validation = {'PROPOSED':'COMPLETED', 'BLOCKED':'FAILED', 'STALE':'FAILED'}.get(part_state, 'QUEUED')
            add(f'validate-{index}', 'Validation', f'Preserve exact passage {index}' if part['locked']
                else f'Validate passage {index}', validation, {'scope_sha256':part['scope_receipt']}, receipt)
        add('save', 'Save', 'Commit the selection draft' if selection else 'Commit the draft group',
            'COMPLETED' if status['draft_id'] else 'QUEUED',
            outputs={'draft_id':status['draft_id']} if status['draft_id'] else None)
        jobs.append({'id':run_id, 'scope':scope, 'kind':'writing-run',
                     'title':'Generate selection' if selection else 'Write selected beats',
                     'run_id':row['id'], 'status':'UNKNOWN' if expired else row['state'], 'created_at':created,
                     'elapsed_ms':max(0, round((end-created)*1000)), 'steps':steps,
                     'error':status['reason'],
                     **({'scene_plan': req['scene_plan'], 'timeline_revision': req['revision'],
                         'notebook_revision': req.get('notebook_revision'), 'draft': status['draft_id'],
                         'rough_draft': req.get('polish_draft')} if req.get('scene_plan') else {}),
                     'resume_available':status['resume_available']})
        if ident or len(jobs) == 40:
            break
    return jobs


class WritingRuns:
    def __init__(self, timeline, *, junctions=None, books_root=None, provider_factory=None, provider_resolver=None,
                 legacy_source=None):
        self.timeline = timeline
        self.options = {'junctions':junctions,'books_root':books_root}
        self.provider_factory = provider_factory
        self.provider_resolver = provider_resolver
        self.legacy_source = legacy_source
        with timeline._connect() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS episode_writing_runs (
                         id TEXT PRIMARY KEY, episode TEXT NOT NULL REFERENCES episodes(id),
                         branch TEXT NOT NULL, request_sha256 TEXT NOT NULL, payload TEXT NOT NULL,
                         state TEXT NOT NULL, owner TEXT, expires REAL, cancelled INTEGER NOT NULL DEFAULT 0,
                         reason TEXT, updated REAL NOT NULL)''')

    def preview(self, request):
        req = _normalize(request)
        manifest,_,_,_ = _prepare(self.timeline,req,self.options)
        return {'status':'PREVIEW', **manifest}

    def _selection_request(self, request):
        ep = self.timeline.get_episode(request['episode'])
        scope = self.timeline.scope()
        req = _normalize({'project':scope['project_id'], 'universe':scope['universe_id'],
                          'branch':ep['branch'], 'beat':0,
                          'reference_delivery':'excerpt', **request}, selection=True)
        if req['branch'] != ep['branch']:
            raise ValueError('Selection belongs to a different episode branch')
        if ('polish_draft' in req or 'guidance' in req) and not req.get('scene_plan'):
            raise ValueError('Polish and comparison guidance require a saved Turn Ledger')
        _bound(req.get('revision'), 0, 2**63-1, 'Selection revision')
        a, b = req.get('start'), req.get('end')
        if type(a) is not int or type(b) is not int or not 0 <= a < b:
            raise ValueError('Select a nonempty passage on the saved episode')
        return req

    def _selection_context(self, request):
        episode = request['episode']
        binding = {key: request[key] for key in ('scene_plan', 'polish_draft', 'guidance') if key in request}
        return {**self.options,
                'legacy_source': (lambda: self.legacy_source(episode)) if self.legacy_source else None,
                'continuation_binding': binding or None,
                'selection_run': True}

    def _selection_preview(self, req):
        from .scoped_references import ReferenceUnavailable
        try:
            preview = execute_scoped(self.timeline, 'rhythm-preview', req, **self._selection_context(req))
        except ReferenceUnavailable as exc:
            raise ReferenceUnavailable(exc.state, f"{req['references']} book guidance: {exc}") from exc
        scope = preview['scope']
        if 'notebook_revision' in req and req['notebook_revision'] != scope['protection_revision']:
            raise ValueError('Selection protection changed; reload the saved episode')
        if 'source_sha256' in req and req['source_sha256'] != scope['context']['source_sha256']:
            raise ValueError('The saved manuscript changed; select the passage again')
        return preview

    def selection_preview(self, request):
        return self._selection_preview(self._selection_request(request))

    def _prepare_selection(self, req):
        preview = self._selection_preview(req)
        locked = preview['rhythm_guidance']['fully_locked']
        prompt_sha = preview['prompt_sha256']
        if req.get('expected_prompt_sha256', prompt_sha) != prompt_sha:
            raise ValueError('The selection preview changed; preview the saved passage again')
        attempts = 0 if locked else 1
        size = preview['prompt_bytes']
        if attempts > req['max_attempts']:
            raise ValueError('Writer attempt budget is zero. No request was sent.')
        if size > req['max_input_bytes']:
            raise ValueError('Writer input exceeds the run’s byte budget. No request was sent.')
        scope = preview['scope']
        return {'director':None, 'planned_attempts':attempts, 'planned_input_bytes':size,
                'scene_plan':req.get('scene_plan'), 'parts':[{
                    'cutoff':scope['beat'], 'start':scope['start'], 'end':scope['end'],
                    'locked':locked, 'input_bytes':size, 'prompt_sha256':prompt_sha,
                    'scope_receipt':director.fingerprint(scope),
                    'rhythm_plan_id':preview['rhythm_guidance']['id'],
                    'reference_receipt':director.fingerprint(preview['reference_binding']),
                }]}, preview

    def _row(self,c,ident,episode):
        row = c.execute('SELECT * FROM episode_writing_runs WHERE id=? AND episode=?',(ident,episode)).fetchone()
        if not row:
            raise ValueError('Writing run not found in this episode')
        return row

    @staticmethod
    def _describe(c,row,*,now=None):
        data = json.loads(row['payload'])
        kind = data.get('kind', 'beats')
        manifest = data.get('manifest') or {}
        output = _output_id(row['id'], kind)
        draft = c.execute('SELECT status,payload FROM episode_drafts WHERE id=?',(output,)).fetchone()
        saved = json.loads(draft['payload']) if draft else {}
        parts=[]
        for index, part in enumerate(manifest.get('parts', [])):
            ident = _draft_id(row['id'],index)
            found = c.execute('SELECT status,payload FROM episode_drafts WHERE id=?',(ident,)).fetchone()
            result = json.loads(found['payload']) if found else {}
            parts.append({**part, 'index':index+1, 'status':found['status'] if found else 'QUEUED',
                          'draft_id':ident if found else None, 'attempt_id':result.get('attempt_id'),
                          'provider_request_id':result.get('provider_request_id')})
        done = sum(part['status']=='PROPOSED' for part in parts)
        receipts = saved.get('writer_receipts') or (
            [saved['writer_receipt']] if kind == 'selection' and saved.get('writer_receipt') else [])
        applicable = draft and draft['status']=='PROPOSED' and row['state']=='COMPLETED'
        processing = data.get('processing', {})
        stage = processing.get('stage', 'accept')
        now = time.time() if now is None else now
        expired = row['state']=='RUNNING' and _lease_end(row, data) < now
        reason = row['reason']
        if expired:
            deadline = processing.get('deadline_at')
            reason = ('The writing stage exceeded its deadline.' if deadline and deadline < now
                      else 'The writing worker stopped reporting.')
        return {'id':row['id'],'episode':row['episode'],'branch':row['branch'],'status':row['state'],
                'kind':kind, 'stage':stage, 'scene_plan':manifest.get('scene_plan'),
                **({'polish_draft': data['request']['polish_draft']}
                   if 'polish_draft' in data.get('request', {}) else {}),
                'cancel_requested':bool(row['cancelled']), 'reason':reason,'updated':row['updated'],
                'resume_available':row['state']=='QUEUED' or expired,
                'draft_id':output if applicable else None,
                'origin':saved.get('origin', 'preserved' if row['state']=='PRESERVED' else 'unknown'),
                'generation_receipt':({'run_id':row['id'], 'draft_id':saved['id'],
                                        'writer_receipts':receipts} if applicable and receipts else None),
                **({'polish': saved['compositor_polish']} if 'compositor_polish' in saved else {}),
                'completed':done,'total':len(parts),'parts':parts,'director':manifest.get('director'),
                'planned_attempts':manifest.get('planned_attempts'),
                'planned_input_bytes':manifest.get('planned_input_bytes')}

    def status(self,ident,episode):
        with self.timeline._connect() as c:
            c.execute('BEGIN')
            return self._describe(c,self._row(c,_key(ident),episode))

    def latest(self,episode,kind=None):
        if kind not in (None, 'selection', 'beats'):
            raise ValueError('Unknown writing run kind')
        with self.timeline._connect() as c:
            c.execute('BEGIN')
            self.timeline._require_active(c,episode)
            row = c.execute("""SELECT * FROM episode_writing_runs WHERE episode=? AND
                             (? IS NULL OR coalesce(json_extract(payload,'$.kind'),'beats')=?)
                             ORDER BY rowid DESC LIMIT 1""", (episode,kind,kind)).fetchone()
            return self._describe(c,row) if row else None

    def start(self,request,*,selection=False):
        ident = _key(request.get('request_id'))
        req = self._selection_request(request) if selection else _normalize(request)
        checksum = director.fingerprint(['selection',req] if selection else req)
        def existing(c):
            row = c.execute('SELECT * FROM episode_writing_runs WHERE id=?',(ident,)).fetchone()
            if row and row['request_sha256'] != checksum:
                raise ValueError('Request ID already belongs to a different writing run')
            return row
        with self.timeline._connect() as c:
            if row := existing(c):
                return self._describe(c,row)
        manifest = None if selection else _prepare(self.timeline,req,self.options)[0]
        # Initialize the draft table before creating any queued work.
        NotebookStore(self.timeline)
        with self.timeline._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if not existing(c):
                other = c.execute("""SELECT id FROM episode_writing_runs WHERE episode=?
                                    AND state IN ('QUEUED','RUNNING') LIMIT 1""",(req['episode'],)).fetchone()
                if other:
                    raise ValueError('This episode already has a writing run. Reopen the saved run first.')
                created = time.time()
                frozen = manifest is not None and not manifest['planned_attempts']
                c.execute("""INSERT INTO episode_writing_runs(id,episode,branch,request_sha256,payload,state,reason,updated)
                             VALUES(?,?,?,?,?,?,?,?)""",(ident,req['episode'],req['branch'],checksum,
                          json.dumps({'request':req,'manifest':manifest,'kind':'selection' if selection else 'beats',
                                      'processing':{'created_at':created,'steps':{}}},ensure_ascii=False),
                          'PRESERVED' if frozen else 'QUEUED',
                          'The selected passages are fully protected.' if frozen else None, created))
            return self._describe(c,self._row(c,ident,req['episode']))

    def cancel(self,ident,episode):
        with self.timeline._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = self._row(c,_key(ident),episode)
            if row['state'] in ('QUEUED','RUNNING'):
                stopped = row['state']=='QUEUED' or _lease_end(row, json.loads(row['payload'])) < time.time()
                c.execute('UPDATE episode_writing_runs SET cancelled=1,state=?,updated=? WHERE id=?',
                          ('CANCELLED' if stopped else 'RUNNING',time.time(),ident))
            return self._describe(c,self._row(c,ident,episode))

    def run(self,ident,episode):
        ident = _key(ident)
        owner = uuid4().hex
        with self.timeline._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = self._row(c,ident,episode)
            saved = json.loads(row['payload'])
            if row['state'] != 'QUEUED' and not (row['state']=='RUNNING' and _lease_end(row,saved) < time.time()):
                return self._describe(c,row)
            saved.get('processing', {}).pop('deadline_at', None)
            c.execute("UPDATE episode_writing_runs SET state='RUNNING',owner=?,expires=?,updated=?,payload=? WHERE id=?",
                      (owner,time.time()+LEASE_SECONDS,time.time(),json.dumps(saved,ensure_ascii=False),ident))
        req, manifest = saved['request'], saved['manifest']
        selection = saved.get('kind') == 'selection'
        stop = threading.Event()

        def heartbeat():
            while not stop.wait(5):
                try:
                    with self.timeline._connect() as c:
                        c.execute("UPDATE episode_writing_runs SET expires=? WHERE id=? AND owner=? AND state='RUNNING'",
                                  (time.time()+LEASE_SECONDS,ident,owner))
                except OperationalError:
                    continue

        def owns_run(c):
            current = self._row(c,ident,episode)
            if (current['owner'] != owner or current['state'] != 'RUNNING'
                    or _lease_end(current, json.loads(current['payload'])) < time.time()):
                raise ValueError('Another worker now owns this writing run')
            return current

        def guard(c):
            current = owns_run(c)
            if current['cancelled']:
                raise ValueError('Writing run cancelled')
            return current

        def before_dispatch():
            with self.timeline._connect() as c:
                guard(c)

        def observe(key, state, reason=None):
            try:
                with self.timeline._connect() as c:
                    c.execute('BEGIN IMMEDIATE')
                    current = self._row(c, ident, episode)
                    if current['owner'] != owner:
                        if state == 'RUNNING':
                            raise ValueError('Another worker now owns this writing run')
                        return
                    if state == 'RUNNING' and (current['state'] != 'RUNNING' or (selection and current['cancelled'])):
                        raise ValueError('Writing run stopped')
                    payload = json.loads(current['payload'])
                    if _lease_end(current, payload) < time.time():
                        if state == 'RUNNING':
                            raise ValueError('The writing stage exceeded its deadline')
                        return
                    progress = payload.setdefault('processing', {'created_at':row['updated'], 'steps':{}})
                    step = progress['steps'].setdefault(key, {})
                    stamp = time.time()
                    if state == 'RUNNING':
                        step.clear()
                        step['started_at'] = stamp
                        progress['stage'] = key
                        if selection:
                            progress['deadline_at'] = stamp + SELECTION_STAGE_SECONDS[key]
                    else:
                        step['finished_at'] = stamp
                        progress.pop('deadline_at', None)
                    step['status'] = state
                    if reason:
                        step['reason'] = reason
                    c.execute('UPDATE episode_writing_runs SET payload=?,updated=? WHERE id=?',
                              (json.dumps(payload, ensure_ascii=False), stamp, ident))
            except OperationalError:
                if selection and state == 'RUNNING':
                    raise
                return

        @contextmanager
        def watch(key):
            observe(key, 'RUNNING')
            try:
                yield
            except Exception as exc:
                observe(key, 'FAILED', str(exc)[:500])
                raise
            else:
                observe(key, 'COMPLETED')

        def terminal(c, state, reason=None):
            c.execute('UPDATE episode_writing_runs SET state=?,reason=?,owner=NULL,expires=NULL,updated=? WHERE id=?',
                      (state,reason,time.time(),ident))

        def finish(state, reason=None):
            with self.timeline._connect() as c:
                c.execute('BEGIN IMMEDIATE')
                current = self._row(c,ident,episode)
                if (current['owner'] == owner and current['state']=='RUNNING'
                        and _lease_end(current, json.loads(current['payload'])) >= time.time()):
                    if current['cancelled'] and state not in ('COMPLETED','UNKNOWN'):
                        state,reason = 'CANCELLED','Writing run stopped.'
                    terminal(c, state, reason)
                return self._describe(c,self._row(c,ident,episode))

        def read_draft(draft_id):
            with self.timeline._connect() as c:
                found = c.execute('SELECT status,payload FROM episode_drafts WHERE id=? AND episode=? AND branch=?',
                                  (draft_id,episode,req['branch'])).fetchone()
                return {**json.loads(found['payload']), 'status':found['status']} if found else {}

        def part_options(draft_id, index, preview, plan_part, existing):
            return {'draft_id':draft_id,'receipt':{'id':ident,'kind':'selection' if selection else 'passage','index':index},
                    'write_guard':guard,'finish_guard':guard if selection else owns_run,
                    'before_dispatch':before_dispatch,'existing_draft':existing or None,
                    'progress':lambda stage: watch(stage if stage=='save' else f'{stage}-{index}'),
                    'expected_scope':preview['scope'],
                    'limits':{'input_bytes':plan_part['input_bytes'],'output_chars':req['max_output_chars']}}

        def writer_for_run():
            return (lambda: self.provider_resolver(req['provider'], episode)) if self.provider_resolver else self.provider_factory

        def save_selection(c, status):
            if status != 'PROPOSED':
                return
            current = owns_run(c)
            payload = json.loads(current['payload'])
            progress = payload['processing']
            progress.pop('deadline_at', None)
            progress['stage'] = 'save'
            progress['steps'].setdefault('save', {}).update(status='COMPLETED', finished_at=time.time())
            c.execute('UPDATE episode_writing_runs SET payload=? WHERE id=?',
                      (json.dumps(payload, ensure_ascii=False),ident))
            terminal(c, 'COMPLETED')

        def write_selection():
            child = _output_id(ident, 'selection')
            before_dispatch()
            try:
                with watch('context'):
                    prepared, preview = self._prepare_selection(req)
                    if manifest is not None and manifest != prepared:
                        raise ValueError('The saved selection context changed; preview again')
                    with self.timeline._connect() as c:
                        c.execute('BEGIN IMMEDIATE')
                        payload = json.loads(guard(c)['payload'])
                        payload['manifest'] = prepared
                        c.execute('UPDATE episode_writing_runs SET payload=? WHERE id=?',
                                  (json.dumps(payload,ensure_ascii=False),ident))
            except (ValueError, OSError) as exc:
                return finish('STALE' if manifest is not None else 'BLOCKED', str(exc)[:500])
            if not prepared['planned_attempts']:
                return finish('PRESERVED', 'The selected text is fully protected.')
            prior = read_draft(child)
            if prior and prior['status'] != 'STARTED':
                return finish(prior['status'] if prior['status'] != 'PROPOSED' else 'COMPLETED')
            part = part_options(child, 1, preview, prepared['parts'][0], prior)
            part.update(selection=True, prompt_sha256=preview['prompt_sha256'], on_saved=save_selection)
            try:
                result = execute_scoped(self.timeline, 'generate',
                            {**req, 'rhythm_plan_id':preview['rhythm_guidance']['id']},
                            **self._selection_context(req), provider_factory=writer_for_run(), run_part=part)
            except Exception as exc:
                draft = read_draft(child)
                status = draft.get('status', 'BLOCKED')
                if status == 'STARTED':
                    status = 'UNKNOWN' if draft.get('provider_request_id') else 'BLOCKED'
                return finish(status, str(exc)[:500])
            if result['status'] == 'PROPOSED':
                return self.status(ident, episode)
            return finish('BLOCKED', ' '.join(result.get('issues') or ['The writer did not produce an applicable draft.'])[:500])

        thread = threading.Thread(target=heartbeat,daemon=True)
        thread.start()
        try:
            if selection:
                return write_selection()
            whole_id = _draft_id(ident,'group')
            if read_draft(whole_id).get('status')=='PROPOSED':
                return finish('COMPLETED')
            if not manifest['planned_attempts']:
                return finish('PRESERVED', 'The selected passages are fully protected.')
            # An uncertain send stays charged. An interrupted worker can resume
            # from a verified response in the original journal.
            if any(read_draft(_draft_id(ident,i)).get('status') == 'UNKNOWN' for i in range(len(req['beats']))):
                return finish('UNKNOWN','A previous writer request may have landed. No request was repeated.')
            before_dispatch()
            try:
                with watch('context'):
                    current,jobs,previews,guidance = _prepare(self.timeline,req,self.options)
                    if director.fingerprint(current) != director.fingerprint(manifest):
                        raise ValueError('The saved scene, protection, or writing context changed')
            except (ValueError, OSError) as exc:
                return finish('STALE',str(exc))
            results=[]
            writer = writer_for_run()
            for i,(job,preview) in enumerate(zip(jobs,previews)):
                before_dispatch()
                child = _draft_id(ident,i)
                prior = read_draft(child)
                status = prior.get('status')
                if status in (None, 'STARTED'):
                    part = part_options(child, i+1, preview, manifest['parts'][i], prior)
                    try:
                        execute_scoped(self.timeline,'generate',
                            {**job,'rhythm_plan_id':preview['rhythm_guidance']['id']}, **self.options,
                            provider_factory=writer,
                            director_controls=manifest['director']['choices'][i]['controls'],
                            rhythm_position={'index':i+1,'count':len(jobs)},run_part=part)
                    except Exception as exc:
                        status = read_draft(child).get('status')
                        return finish('UNKNOWN' if status in ('UNKNOWN','STARTED') else
                                      'STALE' if status=='STALE' else 'PARTIAL', str(exc)[:500])
                    status = read_draft(child).get('status')
                if status != 'PROPOSED':
                    return finish('STALE' if status=='STALE' else 'PARTIAL','A passage did not produce an applicable draft')
                results.append({'beat':req['beats'][i],'draft_id':child,'status':'PROPOSED'})
            before_dispatch()
            with watch('save'):
                assemble_group(self.timeline,req,results,guidance,**self.options,draft_id=whole_id,
                               writing_run={'id':ident,'kind':'group','director':manifest['director'],
                                            'budget':{'attempts':manifest['planned_attempts'],
                                                      'input_bytes':manifest['planned_input_bytes']}},
                               write_guard=guard)
            return finish('COMPLETED')
        except Exception as exc:
            return finish('PARTIAL',str(exc)[:500])
        finally:
            stop.set()
