"""Scoped access to the same processing receipts used by Studio and automation."""
from contextlib import nullcontext

from story_graph.scene_fragments import SceneFragmentStore
from story_graph.universe_scope import checked_id
from telemetry.processing_jobs import Job, read


COMMANDS = frozenset({'processing.open'})
STEPS = {
    'media-import': (
        ('receive', 'Intake', 'Read and fingerprint file'),
        ('analysis', 'Analysis', 'Extract or probe source'),
        ('save', 'Save', 'Register reusable source'),
    ),
    'media-attach': (
        ('resolve', 'Graph linking', 'Resolve exact destination'),
        ('segment', 'Validation', 'Check segment and purpose'),
        ('save', 'Save', 'Save graph link'),
    ),
    'bridge-save': (
        ('source', 'Intake', 'Check saved bridge'),
        ('context', 'Context', 'Assemble beat and Mind context'),
        ('writer', 'Writing', 'Writer dispatch'),
        ('validate', 'Validation', 'Check supplied draft'),
        ('save', 'Save', 'Commit the proposal'),
    ),
}


def begin(store, request, kind, title, inputs):
    with store._connect() as c:
        scope, _ = SceneFragmentStore._scope(c, request)
    return Job(store._connect, scope, kind, title, STEPS[kind], inputs)


def step(job, ident, inputs=None):
    return job.step(ident, inputs) if job else nullcontext({})


def _compositor(c, scope, head, runs):
    from .cook import current_preparation
    from .scene_plan_inputs import read as attached_inputs

    prepared = current_preparation(c, scope['episode'], head)
    if not prepared:
        return None
    sockets = prepared.get('turn_sockets')
    mounted = attached_inputs(c, scope, sockets['replay_sha256']) if sockets else None
    matched = [row for row in runs if row.get('scene_plan') and
               (row['timeline_revision'], row['notebook_revision']) == (head, prepared['notebook_revision'])]
    rough = next((row for row in matched if not row.get('rough_draft')), None)
    polished = next((row for row in matched if row.get('rough_draft')), None)
    parent = None
    if polished:
        from .notebook import DraftStore
        try:
            saved_parent = DraftStore.read_saved(c, scope['episode'], scope['branch'], polished['rough_draft'])
            if saved_parent['status'] == 'PROPOSED' and saved_parent['notebook_revision'] == prepared['notebook_revision']:
                parent = saved_parent
        except ValueError:
            pass

    def saved(key, label, outputs, status='COMPLETED'):
        return {'id': str(key), 'stage': f'Pass {key}', 'label': label,
                'status': status, 'elapsed_ms': None, 'outputs': outputs}

    def writing(key, label, row):
        if not row:
            return saved(key, label, None, 'QUEUED')
        receipt = {name: row[name] for name in ('run_id', 'draft')}
        return saved(key, label, receipt, row['status']) | {'elapsed_ms': row['elapsed_ms'], 'error': row['error']}

    steps = [
        saved(1, 'Prepare typed text', {'notebook_revision': prepared['notebook_revision']}),
        saved(2, 'Prepare scene graphs and sockets',
              {'preparation': prepared['id'], 'graphs': len(prepared['fragments']), 'sockets': len(prepared['sockets'])}),
        saved(3, 'Bind reviewed scene inputs', {'package_sha256': mounted['package_sha256']} if mounted else None,
              'COMPLETED' if mounted else 'QUEUED' if sockets else 'SKIPPED'),
        saved(4, 'Write and validate the rough scene', {'draft': parent['id']})
        if parent else writing(4, 'Write and validate the rough scene', rough),
        writing(5, 'Polish the saved rough draft', polished),
    ]
    last = polished or rough
    status = last['status'] if last else 'QUEUED'
    if not polished and status == 'COMPLETED':
        status = 'QUEUED'
    return {'id': 'compositor-' + prepared['id'][:24], 'scope': scope, 'kind': 'compositor',
            'title': 'Narrative compositor', 'status': status, 'steps': steps,
            'created_at': last['created_at'] if last else 0, 'elapsed_ms': last['elapsed_ms'] if last else 0,
            'error': last['error'] if last else None}


def open_jobs(store, request):
    from .writing_runs import read_processing
    with store._connect() as c:
        c.execute('BEGIN')
        scope, head = SceneFragmentStore._scope(c, request)
        ident = request.get('job')
        if ident is not None:
            checked_id(ident, 'Processing job')
        runs = read_processing(c, scope)
        jobs = read(c, scope, ident) + [row for row in runs if ident is None or row['id'] == ident]
        jobs.sort(key=lambda job: job['created_at'], reverse=True)
        if (compositor := _compositor(c, scope, head, runs)) and ident in (None, compositor['id']):
            jobs.insert(0, compositor)
        return {'scope': scope, 'jobs': jobs[:40], 'provider_calls': 0}
