"""Episode-scoped planning store. This is not yet connected to generation routes."""
from __future__ import annotations
import hashlib
import base64
import binascii
from uuid import uuid4
from contextlib import contextmanager, closing
import json
import sqlite3
from pathlib import Path
from .universe_scope import create_scope, verify_scope
from . import source_timing, transaction_audit

def encode_graph(graph):
    """Validate and serialize the same graph contract for all save paths."""
    if not isinstance(graph,dict) or not isinstance(graph.get('nodes'),list) or not isinstance(graph.get('edges'),list): raise ValueError('Graph requires node and edge lists')
    ids=set()
    for node in graph['nodes']:
        if not isinstance(node,dict) or not isinstance(node.get('id'),str) or not node['id'].strip() or node['id'] in ids:
            raise ValueError('Graph nodes require unique nonempty IDs')
        if 'data' in node and not isinstance(node['data'],dict): raise ValueError('Node data must be an object')
        if 'title' in node and not isinstance(node['title'],str): raise ValueError('Node title must be text')
        ids.add(node['id'])
    for edge in graph['edges']:
        if not isinstance(edge,dict) or edge.get('from') not in ids or edge.get('to') not in ids:
            raise ValueError('Every graph connection must reference existing nodes')
    try: encoded=json.dumps(graph,ensure_ascii=False,allow_nan=False)
    except (TypeError,ValueError) as exc: raise ValueError('Graph must contain valid JSON') from exc
    if len(encoded.encode('utf-8')) > 1_000_000: raise ValueError('Graph exceeds 1 MB')
    return encoded

class TimelineStore:
    def __init__(self, path, *, project_id=None, universe_id=None, form_graph_path=None):
        self.path = str(path)
        if (project_id is None) != (universe_id is None):
            raise ValueError('Specify both project and universe IDs, or neither')
        target = Path(self.path)
        self.form_graph_path = (Path(form_graph_path).resolve() if form_graph_path is not None
                                else target.resolve().with_name('character-forms.sqlite'))
        existing = target.exists()
        if existing:
            # Never add a binding to a legacy user database in place. Inspect it
            # read-only and require the copy-first migration for old stores.
            with closing(sqlite3.connect(target.resolve().as_uri()+'?mode=ro', uri=True, timeout=10)) as db:
                db.row_factory=sqlite3.Row
                scoped=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='project_scope'").fetchone()
                if not scoped:
                    raise ValueError('Legacy timeline is unscoped; migrate a copy before opening it')
                verify_scope(db,project_id=project_id,universe_id=universe_id)
        with self._connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS branches(id TEXT PRIMARY KEY, parent TEXT, fork_episode TEXT, fork_beat INTEGER);
            CREATE TABLE IF NOT EXISTS branch_snapshots(branch TEXT PRIMARY KEY, events TEXT NOT NULL, FOREIGN KEY(branch) REFERENCES branches(id));
            CREATE TABLE IF NOT EXISTS branch_u4_boundaries(branch TEXT PRIMARY KEY REFERENCES branches(id), beat INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS rejoin_reviews(
              event TEXT PRIMARY KEY REFERENCES events(id), source_event TEXT NOT NULL REFERENCES events(id),
              target_episode TEXT NOT NULL REFERENCES episodes(id), reviewer TEXT NOT NULL, source_id TEXT NOT NULL,
              UNIQUE(source_event,target_episode));
            CREATE TABLE IF NOT EXISTS episodes(id TEXT PRIMARY KEY, title TEXT NOT NULL, branch TEXT NOT NULL,
              position INTEGER NOT NULL, cover TEXT, status TEXT NOT NULL DEFAULT 'draft', head INTEGER NOT NULL DEFAULT 0,
              finished_revision INTEGER, UNIQUE(branch, position), FOREIGN KEY(branch) REFERENCES branches(id));
            CREATE TABLE IF NOT EXISTS revisions(episode TEXT NOT NULL, revision INTEGER NOT NULL, graph TEXT NOT NULL,
              script TEXT NOT NULL, source_name TEXT NOT NULL, script_sha256 TEXT NOT NULL,
              PRIMARY KEY(episode,revision), FOREIGN KEY(episode) REFERENCES episodes(id));
            CREATE TABLE IF NOT EXISTS episode_archives(episode TEXT PRIMARY KEY REFERENCES episodes(id),
              previous_status TEXT NOT NULL, head INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS event_form_bindings(event TEXT PRIMARY KEY, character_id TEXT NOT NULL,
              form_id TEXT NOT NULL, action TEXT NOT NULL, FOREIGN KEY(event) REFERENCES events(id));
            CREATE TABLE IF NOT EXISTS event_reviews(event TEXT NOT NULL, reviewer TEXT NOT NULL, source_id TEXT NOT NULL,
              decision TEXT NOT NULL, FOREIGN KEY(event) REFERENCES events(id));
            CREATE TABLE IF NOT EXISTS finish_decisions(episode TEXT NOT NULL, revision INTEGER NOT NULL, reviewer TEXT NOT NULL,
              PRIMARY KEY(episode,revision), FOREIGN KEY(episode) REFERENCES episodes(id));
            CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, episode TEXT NOT NULL, beat INTEGER NOT NULL,
              content TEXT NOT NULL, status TEXT NOT NULL, permitted INTEGER NOT NULL, viewpoint TEXT, source_id TEXT NOT NULL, reviewer TEXT NOT NULL,
              FOREIGN KEY(episode) REFERENCES episodes(id));
            CREATE TABLE IF NOT EXISTS episode_cover_history(
              sequence INTEGER PRIMARY KEY AUTOINCREMENT, episode TEXT NOT NULL REFERENCES episodes(id),
              previous_cover TEXT, new_cover TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS episode_cover_stacks(
              episode TEXT PRIMARY KEY REFERENCES episodes(id), undo_stack TEXT NOT NULL, redo_stack TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS archived_branches(
              id TEXT PRIMARY KEY, parent TEXT, fork_episode TEXT, fork_beat INTEGER,
              events TEXT NOT NULL, beat INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS archived_events(
              id TEXT PRIMARY KEY, episode TEXT NOT NULL, beat INTEGER NOT NULL, content TEXT NOT NULL,
              status TEXT NOT NULL, permitted INTEGER NOT NULL, viewpoint TEXT, source_id TEXT NOT NULL,
              reviewer TEXT NOT NULL, character_id TEXT, form_id TEXT, action TEXT);
            CREATE TABLE IF NOT EXISTS event_form_binding_stacks(
              event TEXT PRIMARY KEY, episode TEXT NOT NULL, undo_stack TEXT NOT NULL, redo_stack TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS archived_rejoins(
              rejoined_event TEXT PRIMARY KEY, source_episode TEXT NOT NULL, source_event TEXT NOT NULL,
              target_episode TEXT NOT NULL REFERENCES episodes(id), target_beat INTEGER NOT NULL,
              reviewer TEXT NOT NULL, source_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS timeline_action_history(
              singleton INTEGER PRIMARY KEY CHECK(singleton=1),
              revision INTEGER NOT NULL DEFAULT 0,
              undo_stack TEXT NOT NULL,
              redo_stack TEXT NOT NULL);
            ''')
            if not c.execute("SELECT 1 FROM branches WHERE id='main'").fetchone():
                c.execute("INSERT OR IGNORE INTO branches(id) VALUES('main')")
            if not existing:
                create_scope(c,project_id,universe_id)
        self._identity = self.scope()

    @staticmethod
    def _action_history_stacks(c):
        row = c.execute(
            'SELECT revision, undo_stack, redo_stack FROM timeline_action_history WHERE singleton=1'
        ).fetchone()
        if row is None:
            return 0, [], []
        return int(row['revision']), json.loads(row['undo_stack']), json.loads(row['redo_stack'])

    @staticmethod
    def _write_action_history(c, revision, undo_stack, redo_stack):
        c.execute(
            'INSERT OR REPLACE INTO timeline_action_history(singleton,revision,undo_stack,redo_stack) VALUES(1,?,?,?)',
            (revision, json.dumps(undo_stack, ensure_ascii=False), json.dumps(redo_stack, ensure_ascii=False)),
        )

    @staticmethod
    def _history_summary(revision, undo_stack, redo_stack):
        return {
            'revision': revision,
            'can_undo': bool(undo_stack),
            'can_redo': bool(redo_stack),
            'undo_count': len(undo_stack),
            'redo_count': len(redo_stack),
            'next_undo_kind': undo_stack[-1].get('kind') if undo_stack else None,
            'next_redo_kind': redo_stack[-1].get('kind') if redo_stack else None,
        }

    def history_state(self):
        """Return persisted global timeline undo/redo stack summary."""
        with self._connect() as c:
            rev, undo_stack, redo_stack = self._action_history_stacks(c)
            return self._history_summary(rev, undo_stack, redo_stack)

    def _push_history_locked(self, c, item):
        rev, undo_stack, _ = self._action_history_stacks(c)
        item = {**item, 'project_history_token': uuid4().hex}
        undo_stack.append(item)
        transaction_audit.record_project_edit(
            c, domain='timeline', target='', operation=item['kind'], token=item['project_history_token'],
            before_patch={'native': item['project_history_token'], 'direction': 'undo'},
            after_patch={'native': item['project_history_token'], 'direction': 'redo'})
        rev += 1
        self._write_action_history(c, rev, undo_stack, [])
        return rev

    @staticmethod
    def _pop_matching(stack, predicate):
        for i in range(len(stack) - 1, -1, -1):
            if predicate(stack[i]):
                return stack.pop(i)
        return None

    def _sync_stack_step_locked(self, c, direction, predicate, fallback_item):
        rev, undo_stack, redo_stack = self._action_history_stacks(c)
        if direction < 0:
            item = self._pop_matching(undo_stack, predicate) or fallback_item
            redo_stack.append(item)
        else:
            item = self._pop_matching(redo_stack, predicate) or fallback_item
            undo_stack.append(item)
        self._sync_project_step(c, item, direction < 0)
        rev += 1
        self._write_action_history(c, rev, undo_stack, redo_stack)

    @staticmethod
    def _sync_project_step(c, item, undo):
        token = item.get('project_history_token')
        transaction_audit.step_project_edit(c, domain='timeline', target='', token=token, next_token=token, undo=undo)

    def _sync_cover_step_locked(self, c, episode, direction, head, previous_cover, target_cover):
        orig_prev = target_cover if direction < 0 else previous_cover
        orig_new = previous_cover if direction < 0 else target_cover
        self._sync_stack_step_locked(
            c,
            direction,
            lambda x: x.get('kind') == 'cover' and x.get('id') == episode
            and x.get('previous_cover') == orig_prev and x.get('cover') == orig_new,
            {'kind': 'cover', 'id': episode, 'head': head, 'previous_cover': orig_prev, 'cover': orig_new},
        )

    def _sync_draft_favorite_step_locked(self, c, episode, branch, draft, direction, previous, value):
        self._sync_stack_step_locked(
            c,
            direction,
            lambda x: x.get('kind') == 'draft_favorite' and x.get('episode') == episode
            and x.get('branch') == branch and x.get('draft') == draft
            and bool(x.get('previous')) == bool(previous) and bool(x.get('value')) == bool(value),
            {'kind': 'draft_favorite', 'episode': episode, 'branch': branch, 'draft': draft,
             'previous': bool(previous), 'value': bool(value)},
        )

    def scope(self):
        with self._connect() as c:
            return verify_scope(c)

    @contextmanager
    def _connect(self):
        c=sqlite3.connect(self.path, timeout=10)
        try:
            c.row_factory=sqlite3.Row
            c.execute('PRAGMA foreign_keys=ON')
            if hasattr(self, '_identity'):
                verify_scope(c, project_id=self._identity['project_id'], universe_id=self._identity['universe_id'])
            with c:
                yield c
        finally:
            c.close()

    @staticmethod
    def _required(value, name):
        if not isinstance(value,str) or not value.strip(): raise ValueError(name+' is required')
        return value.strip()

    def fork(self, branch, parent, episode, beat):
        self._required(branch,'branch')
        if type(beat) is not int or beat < 0: raise ValueError('Invalid fork beat')
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            self._fork_locked(c, branch, parent, episode, beat)

    def _fork_locked(self, c, branch, parent, episode, beat, *, record_history=True):
        self._require_active(c,episode)
        ep=c.execute('SELECT branch FROM episodes WHERE id=?',(episode,)).fetchone()
        if not ep or ep['branch'] != parent: raise ValueError('Fork must refer to an episode on the parent branch')
        snapshot = self._resolve_rows(c, episode, beat)
        c.execute('INSERT INTO branches VALUES(?,?,?,?)',(branch,parent,episode,beat))
        c.execute('INSERT INTO branch_snapshots VALUES(?,?)',(branch,json.dumps(snapshot,ensure_ascii=False)))
        c.execute('INSERT INTO branch_u4_boundaries VALUES(?,?)',(branch,self._u4_boundary(c,episode,beat)))
        c.execute('DELETE FROM archived_branches WHERE id=?',(branch,))
        if record_history:
            self._push_history_locked(c, {'kind': 'fork', 'branch': branch, 'parent': parent, 'episode': episode, 'beat': beat})

    def unfork(self, branch):
        """Undo branch creation when no episodes or child branches depend on it."""
        self._required(branch, 'branch')
        if branch == 'main':
            raise ValueError('Cannot remove main branch')
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            return self._unfork_locked(c, branch)

    def _unfork_locked(self, c, branch, *, record_history=True):
        b = c.execute('SELECT * FROM branches WHERE id=?', (branch,)).fetchone()
        if not b:
            raise ValueError('Unknown branch')
        if c.execute('SELECT 1 FROM episodes WHERE branch=? LIMIT 1', (branch,)).fetchone():
            raise ValueError('Remove or move episodes on this branch before undoing the branch fork')
        if c.execute('SELECT 1 FROM branches WHERE parent=? LIMIT 1', (branch,)).fetchone():
            raise ValueError('Remove child branches before undoing this branch fork')
        snap = c.execute('SELECT events FROM branch_snapshots WHERE branch=?', (branch,)).fetchone()
        u4 = c.execute('SELECT beat FROM branch_u4_boundaries WHERE branch=?', (branch,)).fetchone()
        c.execute(
            'INSERT OR REPLACE INTO archived_branches VALUES(?,?,?,?,?,?)',
            (branch, b['parent'], b['fork_episode'], b['fork_beat'], snap['events'] if snap else '[]', u4['beat'] if u4 else 0),
        )
        c.execute('DELETE FROM branch_u4_boundaries WHERE branch=?', (branch,))
        c.execute('DELETE FROM branch_snapshots WHERE branch=?', (branch,))
        c.execute('DELETE FROM branches WHERE id=?', (branch,))
        info = dict(b)
        if record_history:
            self._push_history_locked(c, {'kind': 'unfork', 'branch': branch, 'parent': info['parent'],
                                          'episode': info['fork_episode'], 'beat': info['fork_beat']})
        return info

    @staticmethod
    def _u4_boundary(c, episode, beat):
        target=c.execute('SELECT branch,position FROM episodes WHERE id=?',(episode,)).fetchone()
        if not target: raise ValueError('Unknown episode')
        spring=c.execute("SELECT status FROM episodes WHERE id='spring-break' AND branch='main'").fetchone()
        if spring and spring['status']=='archived': return 0
        if target['branch'] != 'main':
            row=c.execute('SELECT beat FROM branch_u4_boundaries WHERE branch=?',(target['branch'],)).fetchone()
            return row['beat'] if row else 0
        if episode == 'spring-break': return min(beat,20)
        row=c.execute("SELECT position FROM episodes WHERE id='spring-break' AND branch='main'").fetchone()
        return 20 if row and row['position'] < target['position'] else 0

    def rejoin(self, source_episode, source_event, target_episode, target_beat, reviewer, source_id, permitted, *, rejoined_id=None):
        """Transfer one explicitly reviewed public event to a later beat on the direct parent."""
        reviewer=self._required(reviewer,'Reviewer')
        source_id=self._required(source_id,'Reconciliation source')
        if permitted is not True or type(target_beat) is not int or target_beat < 0:
            raise ValueError('Review and permission are required for a nonnegative target beat')
        if rejoined_id is not None and (not isinstance(rejoined_id, str) or not rejoined_id.startswith('rejoin-')):
            raise ValueError('Invalid rejoined event ID')
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            return self._rejoin_locked(c, source_episode, source_event, target_episode, target_beat,
                                       reviewer, source_id, permitted, rejoined_id=rejoined_id)

    def _rejoin_locked(self, c, source_episode, source_event, target_episode, target_beat, reviewer, source_id, permitted, *, rejoined_id=None, record_history=True):
        self._require_active(c,source_episode);self._require_active(c,target_episode)
        origin=c.execute("""SELECT br.parent, fork.position
            FROM episodes src JOIN branches br ON br.id=src.branch
            JOIN episodes fork ON fork.id=br.fork_episode
            WHERE src.id=?""",(source_episode,)).fetchone()
        target=c.execute('SELECT branch,position,status FROM episodes WHERE id=?',(target_episode,)).fetchone()
        if not origin or not target or target['branch'] != origin['parent'] or target['position'] <= origin['position'] or target['status'] != 'draft':
            raise ValueError('Rejoin into a later draft episode on the direct parent branch')
        event=c.execute("""SELECT ev.*,fb.character_id,fb.form_id,fb.action
          FROM events ev LEFT JOIN event_form_bindings fb ON fb.event=ev.id
          WHERE ev.id=? AND ev.episode=? AND ev.status='approved' AND ev.permitted=1 AND ev.viewpoint IS NULL""",
            (source_event,source_episode)).fetchone()
        if not event or source_event not in self._active_event_ids(c): raise ValueError('Choose an active approved public event from the source episode')
        new_id = rejoined_id or ('rejoin-' + uuid4().hex)
        c.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?)',
            (new_id,target_episode,target_beat,event['content'],'approved',1,None,source_id,reviewer))
        if event['form_id']:
            c.execute('INSERT INTO event_form_bindings VALUES(?,?,?,?)',(new_id,event['character_id'],event['form_id'],event['action']))
        c.execute('INSERT INTO rejoin_reviews VALUES(?,?,?,?,?)',(new_id,source_event,target_episode,reviewer,source_id))
        c.execute('DELETE FROM archived_rejoins WHERE rejoined_event=?', (new_id,))
        if record_history:
            self._push_history_locked(c, {
                'kind': 'rejoin', 'source_episode': source_episode, 'source_event': source_event,
                'target_episode': target_episode, 'target_beat': target_beat,
                'reviewer': reviewer, 'source_id': source_id, 'rejoined_event': new_id,
            })
        return new_id

    def unrejoin(self, target_episode, rejoined_event):
        """Undo a rejoin into a draft target episode when nothing downstream depends on it."""
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            return self._unrejoin_locked(c, target_episode, rejoined_event)

    def _unrejoin_locked(self, c, target_episode, rejoined_event, *, record_history=True):
        target = self._require_active(c, target_episode)
        if target['status'] == 'finished':
            raise ValueError('Reopen a finished episode before undoing a rejoin')
        rr = c.execute(
            'SELECT * FROM rejoin_reviews WHERE event=? AND target_episode=?',
            (rejoined_event, target_episode),
        ).fetchone()
        if not rr:
            raise ValueError('Rejoined event not found in target episode')
        if c.execute('SELECT 1 FROM rejoin_reviews WHERE source_event=?', (rejoined_event,)).fetchone():
            raise ValueError('Undo downstream rejoins before undoing this rejoin')
        for snap in c.execute('SELECT branch, events FROM branch_snapshots').fetchall():
            if any(item.get('id') == rejoined_event for item in json.loads(snap['events'])):
                raise ValueError(f"Branch {snap['branch']} was forked with this rejoined event; undo the branch fork first")
        ev = c.execute('SELECT * FROM events WHERE id=? AND episode=?', (rejoined_event, target_episode)).fetchone()
        src_ev = c.execute('SELECT episode FROM events WHERE id=?', (rr['source_event'],)).fetchone()
        c.execute(
            'INSERT OR REPLACE INTO archived_rejoins VALUES(?,?,?,?,?,?,?)',
            (rejoined_event, src_ev['episode'] if src_ev else '', rr['source_event'], target_episode,
             ev['beat'] if ev else 0, rr['reviewer'], rr['source_id']),
        )
        c.execute('DELETE FROM rejoin_reviews WHERE event=?', (rejoined_event,))
        c.execute('DELETE FROM event_form_bindings WHERE event=?', (rejoined_event,))
        c.execute('DELETE FROM event_reviews WHERE event=?', (rejoined_event,))
        c.execute('DELETE FROM events WHERE id=? AND episode=?', (rejoined_event, target_episode))
        res = {
            'rejoined_event': rejoined_event,
            'source_episode': src_ev['episode'] if src_ev else '',
            'source_event': rr['source_event'],
            'target_episode': target_episode,
            'target_beat': ev['beat'] if ev else 0,
            'reviewer': rr['reviewer'],
            'source_id': rr['source_id'],
        }
        if record_history:
            self._push_history_locked(c, dict(res, kind='unrejoin'))
        return res

    def create_episode(self, episode, title, branch, position, cover=None, *, after=None):
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            self._create_episode_locked(c,episode,title,branch,position,cover,after=after)

    def _create_episode_locked(self, c, episode, title, branch, position, cover=None, *, after=None,
                               script='', source_name=''):
        """Create the card and its first revision inside the caller's transaction."""
        self._required(episode,'episode'); self._required(title,'title')
        if episode in ('spring-break','hot-scoomp','tapped-out'): raise ValueError('Use the starter cards for the fixed story order')
        if type(position) is not int or position < 0: raise ValueError('Invalid position')
        if cover is not None and (not isinstance(cover, str) or len(cover) > 1_400_000): raise ValueError('Invalid cover reference')
        if after is not None and not isinstance(after, str): raise ValueError('Placement target must be text')
        c.execute('INSERT INTO episodes(id,title,branch,position,cover) VALUES(?,?,?,?,?)',(episode,title,branch,position,cover))
        c.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?)',(episode,0,'{"nodes":[],"edges":[]}',script,
                  source_name,hashlib.sha256(script.encode('utf-8')).hexdigest()))
        if after is not None:
            self._move_episode_locked(c, episode, None, after=after, record_history=False, bump_scope=False)
        self._push_history_locked(c, {'kind': 'create', 'id': episode})

    @staticmethod
    def _cover_stacks(c, episode):
        row = c.execute('SELECT undo_stack, redo_stack FROM episode_cover_stacks WHERE episode=?', (episode,)).fetchone()
        if row is not None:
            return json.loads(row['undo_stack']), json.loads(row['redo_stack'])
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='episode_cover_history'").fetchone():
            return [], []
        hist = c.execute(
            'SELECT previous_cover FROM episode_cover_history WHERE episode=? ORDER BY sequence',
            (episode,),
        ).fetchall()
        return [r['previous_cover'] for r in hist], []

    def cover_history_state(self, episode):
        with self._connect() as c:
            self._require_active(c, episode)
            undo_stack, redo_stack = self._cover_stacks(c, episode)
            return {
                'can_undo_cover': bool(undo_stack),
                'can_redo_cover': bool(redo_stack),
                'undo_count': len(undo_stack),
                'redo_count': len(redo_stack),
            }

    @staticmethod
    def _validate_cover(cover):
        if not isinstance(cover, str) or len(cover) > 1_400_000:
            raise ValueError('Choose a PNG, JPEG or WebP image up to 1 MB')
        header, separator, encoded = cover.partition(',')
        if not separator or header not in ('data:image/png;base64', 'data:image/jpeg;base64', 'data:image/webp;base64'):
            raise ValueError('Choose a PNG, JPEG or WebP image')
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError('Invalid cover image') from exc
        signatures = {'data:image/png;base64': raw.startswith(b'\x89PNG\r\n\x1a\n'),
                      'data:image/jpeg;base64': raw.startswith(b'\xff\xd8\xff'),
                      'data:image/webp;base64': raw.startswith(b'RIFF') and raw[8:12] == b'WEBP'}
        if len(raw) > 1_000_000 or not signatures[header]:
            raise ValueError('Choose a valid image up to 1 MB')

    def set_cover(self, episode, expected_revision, expected_cover, cover):
        """Replace artwork without changing the story, retaining the previous image."""
        if type(expected_revision) is not int or (expected_cover is not None and not isinstance(expected_cover, str)):
            raise ValueError('Invalid cover revision')
        self._validate_cover(cover)
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            return self._set_cover_locked(c, episode, expected_revision, expected_cover, cover)

    def _set_cover_locked(self, c, episode, expected_revision, expected_cover, cover):
        row = self._require_active(c,episode)
        if row['head'] != expected_revision or row['cover'] != expected_cover:
            raise ValueError('This episode changed. Refresh and try again.')
        if row['cover'] == cover: return False
        c.execute('''CREATE TABLE IF NOT EXISTS episode_cover_history(
            sequence INTEGER PRIMARY KEY AUTOINCREMENT, episode TEXT NOT NULL REFERENCES episodes(id),
            previous_cover TEXT, new_cover TEXT NOT NULL)''')
        undo_stack, _ = self._cover_stacks(c, episode)
        undo_stack.append(row['cover'])
        c.execute('INSERT INTO episode_cover_history(episode,previous_cover,new_cover) VALUES(?,?,?)',
                  (episode, row['cover'], cover))
        c.execute('INSERT OR REPLACE INTO episode_cover_stacks(episode,undo_stack,redo_stack) VALUES(?,?,?)',
                  (episode, json.dumps(undo_stack), '[]'))
        c.execute('UPDATE episodes SET cover=? WHERE id=?', (cover, episode))
        self._push_history_locked(c, {
            'kind': 'cover', 'id': episode, 'head': row['head'],
            'previous_cover': row['cover'], 'cover': cover,
        })
        return True

    def undo_cover(self, episode, expected_revision=None, expected_cover='__UNSET__'):
        """Restore the previous episode cover without touching story text or graph revisions."""
        return self._step_cover(episode, -1, expected_revision=expected_revision, expected_cover=expected_cover)

    def redo_cover(self, episode, expected_revision=None, expected_cover='__UNSET__'):
        """Reapply an undone episode cover without touching story text or graph revisions."""
        return self._step_cover(episode, 1, expected_revision=expected_revision, expected_cover=expected_cover)

    def _step_cover(self, episode, direction, *, expected_revision=None, expected_cover='__UNSET__'):
        if expected_revision is not None and type(expected_revision) is not int:
            raise ValueError('Invalid cover revision')
        if expected_cover != '__UNSET__' and expected_cover is not None and not isinstance(expected_cover, str):
            raise ValueError('Invalid cover revision')
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            return self._step_cover_locked(
                c, episode, direction, expected_revision=expected_revision,
                expected_cover=expected_cover, sync_history=True,
            )

    def _step_cover_locked(self, c, episode, direction, *, expected_revision=None, expected_cover='__UNSET__', sync_history=True):
        row = self._require_active(c, episode)
        if expected_revision is not None and row['head'] != expected_revision:
            raise ValueError('This episode changed. Refresh and try again.')
        if expected_cover != '__UNSET__' and row['cover'] != expected_cover:
            raise ValueError('This episode changed. Refresh and try again.')
        undo_stack, redo_stack = self._cover_stacks(c, episode)
        if direction < 0:
            if not undo_stack:
                raise ValueError('No previous cover to restore')
            target = undo_stack.pop()
            redo_stack.append(row['cover'])
        else:
            if not redo_stack:
                raise ValueError('No cover change to redo')
            target = redo_stack.pop()
            undo_stack.append(row['cover'])
        c.execute('UPDATE episodes SET cover=? WHERE id=?', (target, episode))
        c.execute('INSERT OR REPLACE INTO episode_cover_stacks(episode,undo_stack,redo_stack) VALUES(?,?,?)',
                  (episode, json.dumps(undo_stack), json.dumps(redo_stack)))
        if sync_history:
            self._sync_cover_step_locked(c, episode, direction, row['head'], row['cover'], target)
        return {
            'episode': episode,
            'head': row['head'],
            'cover': target,
            'previous_cover': row['cover'],
            'can_undo_cover': bool(undo_stack),
            'can_redo_cover': bool(redo_stack),
        }

    def add_starter_cards(self):
        """Create the agreed ordering only in an empty main timeline."""
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute("SELECT 1 FROM episodes WHERE branch='main' LIMIT 1").fetchone():
                raise ValueError('Starter cards require an empty main timeline')
            # Adding these specific cards is the explicit AFM starter action.
            changed=c.execute("UPDATE project_scope SET kind='afm-starters',revision=revision+1 WHERE singleton=1 AND kind='generic'")
            if changed.rowcount and c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='universe_law_head'").fetchone():
                from .world_laws import WorldLawStore, afm_starter_laws
                law=WorldLawStore.in_connection(c)
                if not law['laws']:
                    next_law=law['revision']+1
                    c.execute('INSERT INTO universe_law_revisions VALUES(?,?,?)',
                              (law['universe_id'],next_law,json.dumps(afm_starter_laws(),ensure_ascii=False)))
                    c.execute('UPDATE universe_law_head SET revision=? WHERE universe_id=?',(next_law,law['universe_id']))
            for eid,title,pos in [('spring-break','Spring Break',10),('hot-scoomp','Hot Scoomp',20),('tapped-out','Tapped Out',30)]:
                c.execute('INSERT INTO episodes(id,title,branch,position) VALUES(?,?,?,?)',(eid,title,'main',pos))
                c.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?)',(eid,0,'{"nodes":[],"edges":[]}','', '',hashlib.sha256(b'').hexdigest()))

    def cards(self):
        with self._connect() as c:
            return self._cards_in_conn(c)

    def _cards_in_conn(self, c):
        items = []
        for r in c.execute("SELECT * FROM episodes WHERE status != 'archived' ORDER BY branch,position,id").fetchall():
            item = dict(r)
            undo_stack, redo_stack = self._cover_stacks(c, r['id'])
            item['can_undo_cover'] = bool(undo_stack)
            item['can_redo_cover'] = bool(redo_stack)
            items.append(item)
        return items

    def archived_cards(self):
        with self._connect() as c:
            return [dict(r) for r in c.execute("SELECT * FROM episodes WHERE status = 'archived' ORDER BY branch,position")]

    @staticmethod
    def _require_active(c, episode):
        row=c.execute('SELECT * FROM episodes WHERE id=?',(episode,)).fetchone()
        if not row or row['status']=='archived': raise ValueError('Episode is unavailable or removed from the timeline')
        return row

    def set_archived(self, episode, expected_revision, archive):
        """Remove or restore an episode without deleting its saved content."""
        if type(expected_revision) is not int or type(archive) is not bool:
            raise ValueError('Expected episode revision and action are required')
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            self._set_archived_locked(c, episode, expected_revision, archive)

    def _set_archived_locked(self, c, episode, expected_revision, archive, *, record_history=True):
        row = c.execute('SELECT * FROM episodes WHERE id=?', (episode,)).fetchone()
        if not row or (expected_revision is not None and row['head'] != expected_revision):
            raise ValueError('Episode changed; refresh and try again')
        if archive:
            if row['status'] == 'archived':
                raise ValueError('Episode is already removed')
            c.execute('INSERT INTO episode_archives VALUES(?,?,?)', (episode, row['status'], row['head']))
            c.execute("UPDATE episodes SET status='archived' WHERE id=?", (episode,))
        else:
            old = c.execute('SELECT * FROM episode_archives WHERE episode=?', (episode,)).fetchone()
            if row['status'] != 'archived' or not old or old['head'] != row['head']:
                raise ValueError('Episode cannot be restored because it changed')
            c.execute('UPDATE episodes SET status=? WHERE id=?', (old['previous_status'], episode))
            c.execute('DELETE FROM episode_archives WHERE episode=?', (episode,))
        c.execute('UPDATE project_scope SET revision=revision+1 WHERE singleton=1')
        if record_history:
            self._push_history_locked(c, {'kind': 'remove' if archive else 'restore', 'id': episode})

    def move_episode(self, episode, expected_revision, *, after=None, direction=None, position=None):
        """Reorder an active episode within its branch after validating order invariants."""
        self._required(episode, 'episode')
        if type(expected_revision) is not int:
            raise ValueError('Expected episode revision is required')
        mode_count = sum(x is not None for x in (after, direction, position))
        if mode_count != 1:
            raise ValueError('Specify one placement target, direction, or position')
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            return self._move_episode_locked(
                c, episode, expected_revision, after=after, direction=direction, position=position
            )

    def _plan_move(self, c, episode, expected_revision, *, after=None, direction=None, position=None):
        if sum(value is not None for value in (after, direction, position)) != 1:
            raise ValueError('Specify one placement target, direction, or position')
        row = self._require_active(c, episode)
        if expected_revision is not None and row['head'] != expected_revision:
            raise ValueError('Episode changed; refresh and try again')
        branch = row['branch']
        all_rows = c.execute(
            'SELECT id, position, status FROM episodes WHERE branch=? ORDER BY position, id',
            (branch,),
        ).fetchall()
        active_rows = [r for r in all_rows if r['status'] != 'archived']
        active_ids = [r['id'] for r in active_rows]
        idx = active_ids.index(episode)
        previous_after = 'start' if idx == 0 else active_ids[idx - 1]
        if direction is not None:
            if direction == 'earlier':
                if idx == 0:
                    raise ValueError('Episode is already first on this branch')
                ordered = list(active_ids)
                ordered[idx - 1], ordered[idx] = ordered[idx], ordered[idx - 1]
            elif direction == 'later':
                if idx == len(active_ids) - 1:
                    raise ValueError('Episode is already last on this branch')
                ordered = list(active_ids)
                ordered[idx], ordered[idx + 1] = ordered[idx + 1], ordered[idx]
            else:
                raise ValueError("Direction must be 'earlier' or 'later'")
        elif after is not None:
            if not isinstance(after, str):
                raise ValueError('Placement target must be text')
            remaining = [eid for eid in active_ids if eid != episode]
            if after in ('start', 'first', ''):
                ordered = [episode] + remaining
            elif after == 'end':
                ordered = remaining + [episode]
            else:
                if after == episode or after not in remaining:
                    raise ValueError('Choose another active episode on the same branch')
                target_idx = remaining.index(after)
                ordered = remaining[:target_idx + 1] + [episode] + remaining[target_idx + 1:]
        else:
            if type(position) is not int or position < 0:
                raise ValueError('Invalid position')
            ranked = sorted(
                ((r['position'] if r['id'] != episode else position, 0 if r['id'] == episode else 1, r['id'])
                 for r in active_rows)
            )
            ordered = [item[2] for item in ranked]

        starters = [eid for eid in ordered if eid in ('spring-break', 'hot-scoomp', 'tapped-out')]
        expected_starters = [eid for eid in ('spring-break', 'hot-scoomp', 'tapped-out') if eid in starters]
        locks = []
        if starters != expected_starters:
            locks.append('Starter episodes must remain in the fixed story order')

        rejoin_rows = c.execute(
            """SELECT DISTINCT rr.target_episode, br.fork_episode
               FROM rejoin_reviews rr
               JOIN events ev ON ev.id = rr.source_event
               JOIN episodes src ON src.id = ev.episode
               JOIN branches br ON br.id = src.branch
               WHERE br.parent = ?""",
            (branch,),
        ).fetchall()
        for rrow in rejoin_rows:
            target_ep, fork_ep = rrow['target_episode'], rrow['fork_episode']
            if target_ep in ordered and fork_ep in ordered:
                if ordered.index(target_ep) <= ordered.index(fork_ep):
                    locks.append('Rejoin target episode must remain after its branch fork episode')
        return row, all_rows, active_ids, ordered, previous_after, locks

    def _move_episode_locked(self, c, episode, expected_revision, *, after=None, direction=None, position=None,
                             record_history=True, bump_scope=True):
        row, all_rows, active_ids, ordered, previous_after, locks = self._plan_move(
            c, episode, expected_revision, after=after, direction=direction, position=position)
        if locks:
            raise ValueError(locks[0])
        branch = row['branch']

        if position is not None and after is None and direction is None:
            used = {r['position'] for r in all_rows if r['id'] != episode}
            if ordered == active_ids and row['position'] == position:
                return [dict(r) for r in c.execute("SELECT * FROM episodes WHERE status != 'archived' ORDER BY branch,position")]
            if position not in used:
                c.execute('UPDATE episodes SET position=? WHERE id=?', (position, episode))
                after_active = [r['id'] for r in c.execute(
                    "SELECT id FROM episodes WHERE branch=? AND status != 'archived' ORDER BY position",
                    (branch,),
                ).fetchall()]
                if after_active == ordered:
                    if bump_scope:
                        c.execute('UPDATE project_scope SET revision=revision+1 WHERE singleton=1')
                    if record_history:
                        self._push_history_locked(c, {
                            'kind': 'move', 'id': episode, 'head': row['head'], 'branch': branch,
                            'previous_position': row['position'], 'position': position,
                        })
                    return [dict(r) for r in c.execute("SELECT * FROM episodes WHERE status != 'archived' ORDER BY branch,position")]

        if ordered == active_ids:
            return [dict(r) for r in c.execute("SELECT * FROM episodes WHERE status != 'archived' ORDER BY branch,position")]

        active_iter = iter(ordered)
        full_order = [next(active_iter) if r['status'] != 'archived' else r['id'] for r in all_rows]
        c.execute('UPDATE episodes SET position = -position - 1000000 WHERE branch=?', (branch,))
        for pos_index, eid in enumerate(full_order, start=1):
            c.execute('UPDATE episodes SET position=? WHERE id=?', (pos_index * 10, eid))
        if bump_scope:
            c.execute('UPDATE project_scope SET revision=revision+1 WHERE singleton=1')
        new_idx = ordered.index(episode)
        new_after = 'start' if new_idx == 0 else ordered[new_idx - 1]
        if record_history:
            self._push_history_locked(c, {
                'kind': 'move', 'id': episode, 'head': row['head'], 'branch': branch,
                'previous_after': previous_after, 'after': new_after,
            })
        return [dict(r) for r in c.execute("SELECT * FROM episodes WHERE status != 'archived' ORDER BY branch,position")]

    def timeline_impact(self, c, action, episode, expected_revision, placement):
        """Describe current ordering and the authored links affected by a command."""
        row = self._require_active(c, episode)
        if row['head'] != expected_revision:
            raise ValueError('Episode changed; refresh and try again')
        branch = row['branch']
        before = [item['id'] for item in c.execute(
            "SELECT id FROM episodes WHERE branch=? AND status!='archived' ORDER BY position", (branch,))]
        hard_locks = []
        if action == 'timeline.move':
            _, _, _, after, _, hard_locks = self._plan_move(c, episode, expected_revision, **placement)
        elif action == 'timeline.archive':
            after = [ident for ident in before if ident != episode]
        else:
            after = before
        flags = []
        if before != after:
            old, new = ({ident: i for i, ident in enumerate(order)} for order in (before, after))
            retired = {flag['id'] for flags in self.repair_flags(c).values() for flag in flags}
            for graph_row in c.execute("""SELECT ep.id,r.graph FROM episodes ep JOIN revisions r
                ON r.episode=ep.id AND r.revision=ep.head WHERE ep.branch=? AND ep.status!='archived'
                ORDER BY ep.id""", (branch,)):
                graph = json.loads(graph_row['graph'])
                endpoints = {node['id']: (node.get('data') or {}).get('episode_id', node['id'])
                             for node in graph['nodes']}
                declared = graph.get('timeline_edges', [])
                for edge in (declared if isinstance(declared, list) else []) + graph['edges']:
                    if not isinstance(edge, dict) or not all(isinstance(edge.get(side), str) for side in ('from', 'to')):
                        continue
                    kind = str(edge.get('kind') or edge.get('type') or (edge.get('data') or {}).get('kind') or '').upper()
                    if kind not in ('ENABLES', 'REQUIRES', 'TEMPORAL_LOCK', 'FORKS'):
                        continue
                    source = endpoints.get(edge.get('from'), edge.get('from'))
                    target = endpoints.get(edge.get('to'), edge.get('to'))
                    if not isinstance(source, str) or not isinstance(target, str):
                        continue
                    if source not in old or target not in old or old[source] >= old[target]:
                        continue
                    if source in new and target in new and new[source] < new[target]:
                        continue
                    flag = {'owner': graph_row['id'], 'from': source, 'to': target, 'kind': kind}
                    flag['id'] = hashlib.sha256(json.dumps(flag, sort_keys=True).encode()).hexdigest()
                    if flag['id'] not in retired and flag not in flags:
                        flags.append(flag)
        forks = [dict(item) for item in c.execute(
            'SELECT id, parent, fork_episode FROM branches WHERE fork_episode=? ORDER BY id', (episode,))
        ] if action != 'timeline.rename' else []
        if action == 'timeline.archive':
            for fork in forks:
                flag = {'id': 'fork:' + fork['id'], 'owner': episode, 'from': episode,
                        'to': fork['id'], 'kind': 'FORKS'}
                if not any(flag['id'] == item['id'] for item in self.repair_flags(c).get(episode, [])):
                    flags.append(flag)
        changed_prefix = set(before[:before.index(episode)])
        if episode in after:
            changed_prefix.symmetric_difference_update(after[:after.index(episode)])
        elif after != before:
            changed_prefix = set(before[before.index(episode):])
        memory = []
        if before != after:
            counts = c.execute("""SELECT e.episode,COUNT(*) AS facts FROM events e
                JOIN episodes ep ON ep.id=e.episode WHERE ep.branch=? AND e.status='approved' AND e.permitted=1
                GROUP BY e.episode ORDER BY e.episode""", (branch,))
            memory = [dict(item) for item in counts if item['episode'] in changed_prefix | {episode}]
        return {'title': row['title'], 'before': before, 'after': after, 'hard_locks': hard_locks,
                'temporal_locks': [item for item in flags if item['kind'] == 'TEMPORAL_LOCK'],
                'broken_edges': flags, 'memory_flags': memory, 'affected_branches': forks}

    @staticmethod
    def repair_flags(c):
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='timeline_disconnected_flags'").fetchone():
            return {}
        repairs = {}
        for row in c.execute('SELECT payload FROM timeline_disconnected_flags WHERE disconnected=1 ORDER BY id'):
            flag = json.loads(row['payload'])
            for ident in dict.fromkeys((flag['owner'], flag['from'], flag['to'])):
                repairs.setdefault(ident, []).append(flag)
        return repairs

    @staticmethod
    def _set_disconnected_flags(c, flags, *, disconnected):
        c.execute('''CREATE TABLE IF NOT EXISTS timeline_disconnected_flags(
            id TEXT PRIMARY KEY,payload TEXT NOT NULL,disconnected INTEGER NOT NULL)''')
        for flag in flags:
            c.execute('''INSERT INTO timeline_disconnected_flags VALUES(?,?,?) ON CONFLICT(id)
                DO UPDATE SET disconnected=excluded.disconnected''',
                      (flag['id'], json.dumps(flag, ensure_ascii=False), int(disconnected)))

    @staticmethod
    def _canon_tag(c, episode, head):
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='episode_canon_revisions'").fetchone():
            row = c.execute("""SELECT revision,timeline_revision,mode,tt_carrier FROM episode_canon_revisions
                WHERE episode=? AND timeline_revision<=? ORDER BY revision DESC LIMIT 1""", (episode, head)).fetchone()
            if row:
                return dict(row)
        return {'revision': 0, 'timeline_revision': head, 'mode': 'canon', 'tt_carrier': None}

    def save_canon_tag(self, episode, expected_head, expected_revision, mode, carrier):
        from .universe_scope import checked_id

        if mode not in ('canon', 'non_canon', 'alternate_canon', 'time_travel_canon'):
            raise ValueError('Choose a supported canon mode')
        carrier = checked_id(carrier, 'Time-travel carrier') if mode == 'time_travel_canon' else None
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = self._require_active(c, episode)
            current = self._canon_tag(c, episode, row['head'])
            if type(expected_head) is not int or type(expected_revision) is not int or row['head'] != expected_head:
                raise ValueError('Episode changed; reload its canon tag')
            if current['mode'] == mode and current['tt_carrier'] == carrier:
                return current
            if current['revision'] != expected_revision:
                raise ValueError('Canon tag changed; reload the saved revision')
            c.execute('''CREATE TABLE IF NOT EXISTS episode_canon_revisions(
                episode TEXT NOT NULL,revision INTEGER NOT NULL,timeline_revision INTEGER NOT NULL,
                mode TEXT NOT NULL,tt_carrier TEXT,PRIMARY KEY(episode,revision))''')
            c.execute('INSERT INTO episode_canon_revisions VALUES(?,?,?,?,?)',
                      (episode, expected_revision + 1, expected_head, mode, carrier))
            return self._canon_tag(c, episode, expected_head)

    def get_episode(self, episode):
        with self._connect() as c:
            ep=self._require_active(c,episode)
            rev=c.execute('SELECT * FROM revisions WHERE episode=? AND revision=?',(episode,ep['head'])).fetchone()
            undo_stack, redo_stack = self._cover_stacks(c, episode)
            return {
                **dict(ep),
                'graph': json.loads(rev['graph']),
                'script': rev['script'],
                'source_name': rev['source_name'],
                'script_sha256': rev['script_sha256'],
                'can_undo_cover': bool(undo_stack),
                'can_redo_cover': bool(redo_stack),
                'canon_tag': self._canon_tag(c, episode, ep['head']),
                'timeline_repair': self.repair_flags(c).get(episode, []),
            }

    def save(self, episode, expected_revision, graph=None, script=None, source_name=None, *,
             reject_notebook_script=True, preserve_notebook=False):
        """Save graph/import data; notebook-protected text uses the notebook service.

        The former opt-out parameter is retained for callers compiled against the
        old signature, but cannot disable the protection boundary.
        """
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            ep=c.execute('SELECT * FROM episodes WHERE id=?',(episode,)).fetchone()
            if not ep: raise ValueError('Unknown episode')
            if ep['status'] != 'draft': raise ValueError('Reopen a finished episode before editing')
            if type(expected_revision) is not int or ep['head'] != expected_revision: raise ValueError('Stale revision')
            old=c.execute('SELECT * FROM revisions WHERE episode=? AND revision=?',(episode,expected_revision)).fetchone()
            if script is not None and (script!=old['script'] or source_name!=old['source_name']):
                exists=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='notebook_heads'").fetchone()
                if exists and c.execute('SELECT 1 FROM notebook_heads WHERE episode=?',(episode,)).fetchone():
                    raise ValueError('This episode has notebook protection; save its text and source in the composer')
            if graph is None: graph=json.loads(old['graph'])
            encoded_graph=encode_graph(graph)
            if script is None: script=old['script']; source_name=old['source_name']
            if not isinstance(script,str) or not isinstance(source_name,str): raise ValueError('Script and source name must be text')
            if len(script.encode('utf-8')) > 5_000_000: raise ValueError('Script exceeds 5 MB')
            digest=hashlib.sha256(script.encode('utf-8')).hexdigest()
            rev=expected_revision+1
            c.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?)',(episode,rev,encoded_graph,script,source_name,digest))
            c.execute('UPDATE episodes SET head=? WHERE id=?',(rev,episode))
            if encoded_graph != old['graph'] and (script, source_name) == (old['script'], old['source_name']):
                if preserve_notebook:
                    self._carry_notebook_graph_basis(c, episode, expected_revision, rev)
                transaction_audit.record_project_edit(
                    c, domain='graph', target=episode, operation='save_graph', token=rev,
                    before_patch={'revision': expected_revision}, after_patch={'revision': rev})
            return rev

    def _replay_graph_revision(self, c, episode, before, after):
        ep = self._require_active(c, episode)
        if ep['status'] != 'draft':
            raise ValueError('Reopen the episode before changing its graph.')
        def saved(revision):
            return c.execute('SELECT * FROM revisions WHERE episode=? AND revision=?', (episode, revision)).fetchone()
        head, source, dest = saved(ep['head']), saved(before), saved(after)
        if source is None or dest is None or any(head[key] != source[key] for key in ('graph', 'script', 'source_name')):
            raise ValueError('The episode graph changed outside project history.')
        new_head = ep['head'] + 1
        c.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?)',
                  (episode, new_head, dest['graph'], head['script'], head['source_name'], head['script_sha256']))
        c.execute('UPDATE episodes SET head=? WHERE id=?', (new_head, episode))
        self._carry_notebook_graph_basis(c, episode, ep['head'], new_head)

    @staticmethod
    def _carry_notebook_graph_basis(c, episode, previous, current):
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='notebook_heads'").fetchone():
            return
        row = c.execute('''SELECT r.revision,r.payload FROM notebook_heads h
            JOIN notebook_revisions r ON r.episode=h.episode AND r.revision=h.head
            WHERE h.episode=? AND r.timeline_revision=?''', (episode, previous)).fetchone()
        if row is None:
            return
        revision = row['revision'] + 1
        c.execute('INSERT INTO notebook_revisions VALUES(?,?,?,?)', (episode, revision, current, row['payload']))
        c.execute('UPDATE notebook_heads SET head=? WHERE episode=?', (revision, episode))
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='notebook_history'").fetchone():
            return
        stacks = c.execute('SELECT undo_stack,redo_stack FROM notebook_history WHERE episode=? AND basis_revision=?',
                           (episode, row['revision'])).fetchone()
        earlier, later = stacks if stacks else (json.dumps(list(range(max(0, row['revision'] - 1000), row['revision']))), '[]')
        c.execute('INSERT OR REPLACE INTO notebook_history VALUES(?,?,?,?)', (episode, revision, earlier, later))

    def finish(self, episode, expected_revision, reviewer):
        self._required(reviewer, 'reviewer')
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            self._finish_locked(c, episode, expected_revision, reviewer)

    def _finish_locked(self, c, episode, expected_revision, reviewer, *, record_history=True):
        if self._prerequisites_in_conn(c, episode):
            raise ValueError('Unmet continuity prerequisite')
        result = c.execute(
            "UPDATE episodes SET status='finished',finished_revision=head WHERE id=? AND head=? AND status='draft'",
            (episode, expected_revision),
        )
        if result.rowcount != 1:
            raise ValueError('Unknown, stale or already finished episode')
        rev_name = reviewer.strip()
        c.execute('INSERT OR REPLACE INTO finish_decisions VALUES(?,?,?)', (episode, expected_revision, rev_name))
        if record_history:
            self._push_history_locked(c, {'kind': 'finish', 'id': episode, 'head': expected_revision, 'reviewer': rev_name})

    def reopen(self, episode, expected_revision=None):
        if expected_revision is not None and type(expected_revision) is not int:
            raise ValueError('Invalid episode revision')
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            return self._reopen_locked(c, episode, expected_revision=expected_revision)

    def _reopen_locked(self, c, episode, expected_revision=None, *, record_history=True):
        row = self._require_active(c, episode)
        if expected_revision is not None and row['head'] != expected_revision:
            raise ValueError('Episode changed; refresh and try again')
        result = c.execute("UPDATE episodes SET status='draft' WHERE id=? AND status='finished'", (episode,))
        if result.rowcount != 1:
            raise ValueError('Episode is not finished')
        dec = c.execute('SELECT reviewer FROM finish_decisions WHERE episode=? ORDER BY revision DESC LIMIT 1', (episode,)).fetchone()
        last_reviewer = dec['reviewer'] if dec else 'Author'
        if record_history:
            self._push_history_locked(c, {'kind': 'reopen', 'id': episode, 'head': row['head'], 'reviewer': last_reviewer})
        return {'episode': episode, 'head': row['head'], 'last_reviewer': last_reviewer}

    def add_event(self, event, episode, beat, content, *, status='draft', permitted=False, viewpoint=None, source_id='', reviewer=''):
        self._required(event, 'event'); self._required(content, 'content')
        if type(beat) is not int or beat < 0 or status not in ('draft', 'approved') or type(permitted) is not bool:
            raise ValueError('Invalid event')
        if status == 'approved' and (not source_id.strip() or not reviewer.strip()):
            raise ValueError('Approved events require source identity and reviewer')
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            self._add_event_locked(
                c, event, episode, beat, content, status=status, permitted=permitted,
                viewpoint=viewpoint, source_id=source_id, reviewer=reviewer,
            )

    def _add_event_locked(self, c, event, episode, beat, content, *, status='draft', permitted=False,
                          viewpoint=None, source_id='', reviewer='', record_history=True):
        self._require_active(c, episode)
        c.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?)',
                  (event, episode, beat, content, status, int(permitted), viewpoint, source_id, reviewer))
        c.execute('DELETE FROM archived_events WHERE id=?', (event,))
        if record_history:
            self._push_history_locked(c, {'kind': 'add_event', 'episode': episode, 'event': event})

    def unadd_event(self, episode, event):
        """Remove a draft event cleanly while preserving it for redo."""
        self._required(event, 'event')
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            return self._unadd_event_locked(c, episode, event)

    def _unadd_event_locked(self, c, episode, event, *, record_history=True):
        ep = self._require_active(c, episode)
        if ep['status'] == 'finished':
            raise ValueError('Reopen a finished episode before removing events')
        ev = c.execute('SELECT * FROM events WHERE id=? AND episode=?', (event, episode)).fetchone()
        if not ev:
            raise ValueError('Event does not exist in this episode')
        if ev['status'] != 'draft':
            raise ValueError('Unapprove the event before removing it')
        if c.execute('SELECT 1 FROM rejoin_reviews WHERE event=? OR source_event=?', (event, event)).fetchone():
            raise ValueError('Undo the rejoin before removing this event')
        fb = c.execute('SELECT * FROM event_form_bindings WHERE event=?', (event,)).fetchone()
        c.execute(
            'INSERT OR REPLACE INTO archived_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (ev['id'], ev['episode'], ev['beat'], ev['content'], ev['status'], ev['permitted'],
             ev['viewpoint'], ev['source_id'], ev['reviewer'],
             fb['character_id'] if fb else None, fb['form_id'] if fb else None, fb['action'] if fb else None),
        )
        c.execute('DELETE FROM event_form_bindings WHERE event=?', (event,))
        c.execute('DELETE FROM event_reviews WHERE event=?', (event,))
        c.execute('DELETE FROM events WHERE id=? AND episode=?', (event, episode))
        if record_history:
            self._push_history_locked(c, {'kind': 'remove_event', 'episode': episode, 'event': event})
        return dict(ev)

    def restore_event(self, episode, event, junctions=None):
        """Redo an undone event addition while preserving its content and optional form binding."""
        self._required(event, 'event')
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            return self._restore_event_locked(c, episode, event, junctions=junctions)

    def _restore_event_locked(self, c, episode, event, junctions=None, *, record_history=True):
        ep = self._require_active(c, episode)
        if ep['status'] == 'finished':
            raise ValueError('Reopen a finished episode before restoring events')
        arc = c.execute('SELECT * FROM archived_events WHERE id=? AND episode=?', (event, episode)).fetchone()
        if not arc:
            raise ValueError('Archived event not found')
        c.execute(
            'INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?)',
            (arc['id'], arc['episode'], arc['beat'], arc['content'], 'draft', 0,
             arc['viewpoint'], arc['source_id'], arc['reviewer']),
        )
        if arc['character_id'] and arc['form_id'] and arc['action']:
            if junctions is not None:
                if arc['character_id'] not in junctions or arc['form_id'] not in {f.id for f in junctions[arc['character_id']].forms}:
                    raise ValueError('Choose an existing character and form')
            c.execute('INSERT OR REPLACE INTO event_form_bindings VALUES(?,?,?,?)',
                      (arc['id'], arc['character_id'], arc['form_id'], arc['action']))
        c.execute('DELETE FROM archived_events WHERE id=?', (event,))
        if record_history:
            self._push_history_locked(c, {'kind': 'restore_event', 'episode': episode, 'event': event})
        return dict(arc)

    def bind_form_event(self, episode, event, character_id, form_id, action, junctions):
        if character_id not in junctions or form_id not in {f.id for f in junctions[character_id].forms}:
            raise ValueError('Choose an existing character and form')
        if action not in ('available', 'active'):
            raise ValueError('Choose an available or active form transition')
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            self._bind_form_event_locked(c, episode, event, character_id, form_id, action)

    def _bind_form_event_locked(self, c, episode, event, character_id, form_id, action, *, record_history=True):
        from . import fx06_scene
        if (form_id in fx06_scene.CAST or (episode == fx06_scene.EPISODE and character_id == 'rainee')):
            if fx06_scene.read(c):
                raise ValueError('FX06 form changes are controlled by its authored scene, not ordinary form events')
        self._require_active(c, episode)
        row = c.execute('SELECT status FROM events WHERE id=? AND episode=?', (event, episode)).fetchone()
        if not row or row['status'] != 'draft':
            raise ValueError('Only a draft event in this episode can be bound')
        prev = c.execute('SELECT * FROM event_form_bindings WHERE event=?', (event,)).fetchone()
        st = c.execute('SELECT undo_stack FROM event_form_binding_stacks WHERE event=?', (event,)).fetchone()
        undo_stack = json.loads(st['undo_stack']) if st else []
        undo_stack.append({'character_id': prev['character_id'], 'form_id': prev['form_id'], 'action': prev['action']} if prev else None)
        c.execute('INSERT OR REPLACE INTO event_form_bindings VALUES(?,?,?,?)', (event, character_id, form_id, action))
        c.execute('INSERT OR REPLACE INTO event_form_binding_stacks VALUES(?,?,?,?)',
                  (event, episode, json.dumps(undo_stack), '[]'))
        if record_history:
            self._push_history_locked(c, {'kind': 'bind_form', 'episode': episode, 'event': event})

    def unbind_form_event(self, episode, event):
        """Undo a draft event form binding back to its previous binding or unbound."""
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            return self._unbind_form_event_locked(c, episode, event)

    def _unbind_form_event_locked(self, c, episode, event, *, record_history=True):
        self._require_active(c, episode)
        row = c.execute('SELECT status FROM events WHERE id=? AND episode=?', (event, episode)).fetchone()
        if not row or row['status'] != 'draft':
            raise ValueError('Only a draft event in this episode can be unbound')
        cur = c.execute('SELECT * FROM event_form_bindings WHERE event=?', (event,)).fetchone()
        st = c.execute('SELECT undo_stack, redo_stack FROM event_form_binding_stacks WHERE event=?', (event,)).fetchone()
        undo_stack = json.loads(st['undo_stack']) if st else []
        redo_stack = json.loads(st['redo_stack']) if st else []
        if cur is None and not undo_stack:
            raise ValueError('Event has no form binding to undo')
        target = undo_stack.pop() if undo_stack else None
        redo_stack.append({'character_id': cur['character_id'], 'form_id': cur['form_id'], 'action': cur['action']} if cur else None)
        if target is None:
            c.execute('DELETE FROM event_form_bindings WHERE event=?', (event,))
        else:
            c.execute('INSERT OR REPLACE INTO event_form_bindings VALUES(?,?,?,?)',
                      (event, target['character_id'], target['form_id'], target['action']))
        c.execute('INSERT OR REPLACE INTO event_form_binding_stacks VALUES(?,?,?,?)',
                  (event, episode, json.dumps(undo_stack), json.dumps(redo_stack)))
        if record_history:
            self._push_history_locked(c, {'kind': 'unbind_form', 'episode': episode, 'event': event})
        return {'event': event, 'episode': episode, 'binding': target,
                'can_undo_binding': bool(undo_stack), 'can_redo_binding': bool(redo_stack)}

    def redo_form_event(self, episode, event, junctions=None):
        """Reapply an undone draft event form binding change."""
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            return self._redo_form_event_locked(c, episode, event, junctions=junctions)

    def _redo_form_event_locked(self, c, episode, event, junctions=None, *, record_history=True):
        self._require_active(c, episode)
        row = c.execute('SELECT status FROM events WHERE id=? AND episode=?', (event, episode)).fetchone()
        if not row or row['status'] != 'draft':
            raise ValueError('Only a draft event in this episode can be bound')
        st = c.execute('SELECT undo_stack, redo_stack FROM event_form_binding_stacks WHERE event=?', (event,)).fetchone()
        undo_stack = json.loads(st['undo_stack']) if st else []
        redo_stack = json.loads(st['redo_stack']) if st else []
        if not redo_stack:
            raise ValueError('No form binding change to redo')
        cur = c.execute('SELECT * FROM event_form_bindings WHERE event=?', (event,)).fetchone()
        target = redo_stack.pop()
        undo_stack.append({'character_id': cur['character_id'], 'form_id': cur['form_id'], 'action': cur['action']} if cur else None)
        if target is None:
            c.execute('DELETE FROM event_form_bindings WHERE event=?', (event,))
        else:
            if junctions is not None:
                if target['character_id'] not in junctions or target['form_id'] not in {f.id for f in junctions[target['character_id']].forms}:
                    raise ValueError('Choose an existing character and form')
            c.execute('INSERT OR REPLACE INTO event_form_bindings VALUES(?,?,?,?)',
                      (event, target['character_id'], target['form_id'], target['action']))
        c.execute('INSERT OR REPLACE INTO event_form_binding_stacks VALUES(?,?,?,?)',
                  (event, episode, json.dumps(undo_stack), json.dumps(redo_stack)))
        if record_history:
            self._push_history_locked(c, {'kind': 'bind_form', 'episode': episode, 'event': event})
        return {'event': event, 'episode': episode, 'binding': target,
                'can_undo_binding': bool(undo_stack), 'can_redo_binding': bool(redo_stack)}

    def review_event(self, episode, event, reviewer, source_id, permitted):
        self._required(reviewer, 'reviewer'); self._required(source_id, 'source')
        if permitted is not True:
            raise ValueError('Explicit permission is required')
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            self._review_event_locked(c, episode, event, reviewer, source_id, permitted)

    def _review_event_locked(self, c, episode, event, reviewer, source_id, permitted, *, record_history=True):
        self._required(reviewer, 'reviewer'); self._required(source_id, 'source')
        if permitted is not True:
            raise ValueError('Explicit permission is required')
        self._require_active(c, episode)
        rev_name, src_name = reviewer.strip(), source_id.strip()
        result = c.execute(
            "UPDATE events SET status='approved',permitted=1,reviewer=?,source_id=? WHERE id=? AND episode=? AND status='draft'",
            (rev_name, src_name, event, episode),
        )
        if result.rowcount != 1:
            raise ValueError('Event does not exist or has already been reviewed')
        c.execute('INSERT INTO event_reviews VALUES(?,?,?,?)', (event, rev_name, src_name, 'approved'))
        if record_history:
            self._push_history_locked(c, {
                'kind': 'review_event', 'episode': episode, 'event': event,
                'reviewer': rev_name, 'source_id': src_name,
            })

    def unreview_event(self, episode, event, reviewer='Author'):
        """Revert an approved event back to draft when no downstream dependency locks it."""
        self._required(reviewer, 'reviewer')
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            return self._unreview_event_locked(c, episode, event, reviewer=reviewer)

    def _unreview_event_locked(self, c, episode, event, reviewer='Author', *, record_history=True):
        ep = self._require_active(c, episode)
        if ep['status'] == 'finished':
            raise ValueError('Reopen a finished episode before unapproving events')
        ev = c.execute('SELECT * FROM events WHERE id=? AND episode=?', (event, episode)).fetchone()
        if not ev or ev['status'] != 'approved':
            raise ValueError('Event is not currently approved')
        if c.execute('SELECT 1 FROM rejoin_reviews WHERE event=?', (event,)).fetchone():
            raise ValueError('Rejoined events must be undone with unrejoin')
        if c.execute('SELECT 1 FROM rejoin_reviews WHERE source_event=?', (event,)).fetchone():
            raise ValueError('Undo the parent rejoin before unapproving this event')
        if episode == 'hot-scoomp' and event == 'haley-awakening':
            tapped = c.execute("SELECT status FROM episodes WHERE id='tapped-out'").fetchone()
            if tapped and tapped['status'] == 'finished':
                raise ValueError('Reopen Tapped Out before unapproving its prerequisite event')
        for snap in c.execute('SELECT branch, events FROM branch_snapshots').fetchall():
            if any(item.get('id') == event for item in json.loads(snap['events'])):
                raise ValueError(f"Branch {snap['branch']} was forked with this approved event; undo the branch fork first")
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='passage_anchor_revisions'").fetchone():
            anchor_rows = c.execute('''SELECT r.payload FROM passage_anchor_revisions r
                JOIN (SELECT id,MAX(revision) revision FROM passage_anchor_revisions WHERE episode=? GROUP BY id) h
                ON r.id=h.id AND r.revision=h.revision''', (episode,)).fetchall()
            for ar in anchor_rows:
                payload = json.loads(ar['payload'])
                if payload.get('action') == 'bind' and payload.get('event') == event:
                    raise ValueError('Unbind passage beat anchors referencing this event before unapproving it')
        c.execute("UPDATE events SET status='draft',permitted=0,reviewer='',source_id='' WHERE id=? AND episode=?", (event, episode))
        c.execute('INSERT INTO event_reviews VALUES(?,?,?,?)', (event, reviewer.strip(), ev['source_id'], 'unapproved'))
        prev_reviewer = ev['reviewer'] or reviewer.strip()
        if record_history:
            self._push_history_locked(c, {
                'kind': 'unreview_event', 'episode': episode, 'event': event,
                'reviewer': prev_reviewer, 'source_id': ev['source_id'],
            })
        return {'episode': episode, 'event': event, 'status': 'draft',
                'previous_reviewer': ev['reviewer'], 'previous_source_id': ev['source_id']}

    def undo_history(self, expected_revision=None, *, junctions=None, on_draft_favorite=None):
        """Undo the most recent timeline action from the SQLite history stack."""
        return self._step_history(-1, expected_revision=expected_revision, junctions=junctions, on_draft_favorite=on_draft_favorite)

    def redo_history(self, expected_revision=None, *, junctions=None, on_draft_favorite=None):
        """Redo the most recently undone timeline action from the SQLite history stack."""
        return self._step_history(1, expected_revision=expected_revision, junctions=junctions, on_draft_favorite=on_draft_favorite)

    def _step_history(self, direction, *, expected_revision=None, junctions=None, on_draft_favorite=None):
        if expected_revision is not None and type(expected_revision) is not int:
            raise ValueError('Invalid timeline history revision')
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            return self._step_history_locked(c, direction, expected_revision=expected_revision,
                                             junctions=junctions, on_draft_favorite=on_draft_favorite)

    def _step_history_locked(self, c, direction, *, expected_revision=None, junctions=None, on_draft_favorite=None):
        undo = direction < 0
        rev, undo_stack, redo_stack = self._action_history_stacks(c)
        if expected_revision is not None and rev != expected_revision:
            raise ValueError('Timeline changed elsewhere. Refresh and try again.')
        source = undo_stack if undo else redo_stack
        dest = redo_stack if undo else undo_stack
        if not source:
            raise ValueError('Nothing to undo on the timeline' if undo else 'Nothing to redo on the timeline')
        item = source.pop()
        episode_id, notice = self._apply_history_item_locked(
            c, item, undo=undo, junctions=junctions, on_draft_favorite=on_draft_favorite
        )
        dest.append(item)
        self._sync_project_step(c, item, undo)
        rev += 1
        self._write_action_history(c, rev, undo_stack, redo_stack)
        return {
            'action': 'undo' if undo else 'redo',
            'item': item,
            'kind': item.get('kind'),
            'episode_id': episode_id,
            'notice': notice,
            'history': self._history_summary(rev, undo_stack, redo_stack),
        }

    def _apply_history_item_locked(self, c, item, *, undo, junctions=None, on_draft_favorite=None):
        kind = item.get('kind')
        if item.get('disconnected_flags'):
            self._set_disconnected_flags(c, item['disconnected_flags'], disconnected=not undo)
        if kind == 'rename':
            title = item['previous_title'] if undo else item['title']
            c.execute('UPDATE episodes SET title=? WHERE id=?', (title, item['id']))
            return item['id'], 'Episode title restored.' if undo else 'Episode title reapplied.'
        if kind == 'move':
            if undo:
                kw = {'after': item['previous_after']} if 'previous_after' in item else {'position': item['previous_position']}
                notice = 'Episode order restored.'
            else:
                kw = {'after': item['after']} if 'after' in item else {'position': item['position']}
                notice = 'Episode move reapplied.'
            self._move_episode_locked(c, item['id'], None, **kw, record_history=False)
            return item['id'], notice
        if kind == 'cover':
            expected_cover = item['cover'] if undo else item['previous_cover']
            self._step_cover_locked(c, item['id'], -1 if undo else 1, expected_cover=expected_cover, sync_history=False)
            return item['id'], 'Previous cover restored.' if undo else 'Cover reapplied.'
        if kind in ('create', 'restore', 'remove'):
            archive = undo if kind in ('create', 'restore') else not undo
            self._set_archived_locked(c, item['id'], None, archive, record_history=False)
            notice = 'Episode removed; its events are excluded until restored.' if archive else 'Episode restored.'
            return item['id'], notice
        if kind in ('fork', 'unfork'):
            do_unfork = undo if kind == 'fork' else not undo
            if do_unfork:
                self._unfork_locked(c, item['branch'], record_history=False)
                return None, 'Branch fork undone.' if kind == 'fork' else 'Branch removal reapplied.'
            self._fork_locked(c, item['branch'], item['parent'], item['episode'], item['beat'], record_history=False)
            return item.get('episode'), 'Branch restored.'
        if kind in ('finish', 'reopen'):
            do_reopen = undo if kind == 'finish' else not undo
            if do_reopen:
                self._reopen_locked(c, item['id'], expected_revision=item['head'], record_history=False)
                return item['id'], 'Episode reopened as draft.'
            self._finish_locked(c, item['id'], item['head'], item.get('reviewer') or 'Author', record_history=False)
            return item['id'], 'Reviewed revision pinned.'
        if kind == 'draft_favorite':
            if on_draft_favorite is None:
                raise ValueError('Draft favorite handler is required to step draft favorite history')
            on_draft_favorite(c, item, undo=undo)
            return item['episode'], 'Draft favorite undone.' if undo else 'Draft favorite redone.'
        return self._apply_event_history_item_locked(c, item, undo=undo, junctions=junctions)

    def _apply_event_history_item_locked(self, c, item, *, undo, junctions=None):
        kind = item.get('kind')
        if kind in ('add_event', 'remove_event', 'restore_event'):
            do_remove = undo if kind in ('add_event', 'restore_event') else not undo
            if do_remove:
                self._unadd_event_locked(c, item['episode'], item['event'], record_history=False)
                return item['episode'], 'Draft event removed.'
            self._restore_event_locked(c, item['episode'], item['event'], junctions=junctions, record_history=False)
            return item['episode'], 'Draft event restored.'
        if kind in ('bind_form', 'unbind_form'):
            do_unbind = undo if kind == 'bind_form' else not undo
            if do_unbind:
                self._unbind_form_event_locked(c, item['episode'], item['event'], record_history=False)
                return item['episode'], 'Form binding undone.'
            self._redo_form_event_locked(c, item['episode'], item['event'], junctions=junctions, record_history=False)
            return item['episode'], 'Form binding reapplied.'
        if kind in ('review_event', 'unreview_event'):
            do_unapprove = undo if kind == 'review_event' else not undo
            if do_unapprove:
                self._unreview_event_locked(c, item['episode'], item['event'], reviewer=item.get('reviewer') or 'Author', record_history=False)
                return item['episode'], 'Event approval undone.'
            self._review_event_locked(c, item['episode'], item['event'], item.get('reviewer') or 'Author',
                                      item.get('source_id', ''), True, record_history=False)
            return item['episode'], 'Event approved.'
        if kind in ('rejoin', 'unrejoin'):
            do_unrejoin = undo if kind == 'rejoin' else not undo
            if do_unrejoin:
                self._unrejoin_locked(c, item['target_episode'], item['rejoined_event'], record_history=False)
                return item['target_episode'], 'Rejoin undone.'
            self._rejoin_locked(
                c, item['source_episode'], item['source_event'], item['target_episode'], item['target_beat'],
                item.get('reviewer') or 'Author', item['source_id'], True,
                rejoined_id=item['rejoined_event'], record_history=False,
            )
            return item['target_episode'], 'Rejoin reapplied.'
        raise ValueError(f'Unknown timeline history entry: {kind}')

    def episode_events(self, episode):
        with self._connect() as c:
            self._require_active(c,episode)
            rows = c.execute('''SELECT ev.*, fb.character_id AS form_character, fb.form_id, fb.action AS form_action,
                CASE WHEN rr.event IS NOT NULL THEN 1 ELSE 0 END AS rejoined,
                rr.source_event AS rejoined_from_event
                FROM events ev
                LEFT JOIN event_form_bindings fb ON fb.event = ev.id
                LEFT JOIN rejoin_reviews rr ON rr.event = ev.id
                WHERE ev.episode=? ORDER BY ev.beat,ev.id''', (episode,)).fetchall()
            result = []
            managed = episode == source_timing.EPISODE and source_timing.managed(c)
            attestation = source_timing.approved(c) if managed else None
            for r in rows:
                d = dict(r)
                d['rejoined'] = bool(d.get('rejoined'))
                if managed and d['id'] == source_timing.EVENT:
                    if attestation:
                        d = source_timing.project_event(d, attestation)
                    else:
                        d['timing_status'] = 'source-timing-unavailable'
                result.append(d)
            return sorted(result, key=lambda event: (event['beat'], event['id']))

    def branches(self):
        with self._connect() as c:
            return [dict(row) for row in c.execute('SELECT * FROM branches ORDER BY id')]

    @staticmethod
    def _active_event_ids(c):
        # A rejoined event is also inactive if any event in its source chain
        # belongs to a removed episode. UNION makes cyclic corrupt chains finite.
        return {row['id'] for row in c.execute("""WITH RECURSIVE inactive(id) AS (
            SELECT ev.id FROM events ev JOIN episodes ep ON ep.id=ev.episode WHERE ep.status='archived'
            UNION SELECT rr.event FROM rejoin_reviews rr JOIN inactive i ON rr.source_event=i.id
          ) SELECT id FROM events WHERE id NOT IN (SELECT id FROM inactive)""")}

    def _resolve_rows(self, c, episode, beat, *, source_span=None):
        target=self._require_active(c,episode)
        active_events=self._active_event_ids(c)
        branch=target['branch']
        b=c.execute('SELECT * FROM branches WHERE id=?',(branch,)).fetchone()
        if not b: raise ValueError('Unknown branch')
        inherited=[]
        if b['parent'] is not None:
            snapshot=c.execute('SELECT events FROM branch_snapshots WHERE branch=?',(branch,)).fetchone()
            if not snapshot: raise ValueError('Branch has no verified fork snapshot')
            inherited=[event for event in json.loads(snapshot['events']) if event.get('id') in active_events]
        source_episode = episode == source_timing.EPISODE and source_timing.managed(c)
        rows=c.execute("""SELECT ev.*,ep.position,fb.character_id AS form_character,fb.form_id,fb.action AS form_action
          FROM events ev JOIN episodes ep ON ep.id=ev.episode
          LEFT JOIN event_form_bindings fb ON fb.event=ev.id
          WHERE ep.status != 'archived' AND ep.branch=? AND
          (ep.position < ? OR (ep.position=? AND (ev.beat<=? OR (? AND ev.id=?))))
          AND ev.status='approved' AND ev.permitted=1 ORDER BY ep.position,ev.beat,ev.id""",
          (branch,target['position'],target['position'],beat,source_episode,source_timing.EVENT)).fetchall()
        own = [dict(row) for row in rows if row['id'] in active_events]
        def is_awakening(event):
            return event['id'] == source_timing.EVENT and event['episode'] == source_timing.EPISODE
        if any(map(is_awakening, inherited + own)) and source_timing.managed(c):
            receipt = source_timing.approved(c)
            # A pre-attestation branch snapshot cannot grandfather in beat zero.
            inherited = [ev for ev in inherited if not is_awakening(ev)
                         or (receipt and ev.get('source_timing') == receipt)]
            if episode == source_timing.EPISODE and source_span is not None:
                cut = source_timing.cut_for(*source_span)
                if cut is None or cut.beat < source_timing.AWAKENING_BEAT:
                    receipt = None
            own = [source_timing.project_event(ev, receipt) if is_awakening(ev) else ev
                   for ev in own if not is_awakening(ev) or (receipt and
                       (episode != source_timing.EPISODE or beat >= source_timing.AWAKENING_BEAT))]
            own.sort(key=lambda ev: (ev['position'], ev['beat'], ev['id']))
        return inherited + own

    def resolve(self, episode, beat, viewpoint=None):
        if type(beat) is not int or beat < 0: raise ValueError('Invalid beat')
        with self._connect() as c:
            return [x for x in self._resolve_rows(c,episode,beat) if source_timing.visible_to(x,viewpoint)]

    def prerequisites(self, episode):
        with self._connect() as c:
            return self._prerequisites_in_conn(c, episode)

    def _prerequisites_in_conn(self, c, episode):
        ep = c.execute('SELECT * FROM episodes WHERE id=?', (episode,)).fetchone()
        if not ep:
            raise ValueError('Unknown episode')
        if episode != 'tapped-out':
            return []
        eligible = self._resolve_rows(c, episode, 0)
        if any(e['id'] == 'haley-awakening' and e['episode'] == 'hot-scoomp' and e['viewpoint'] is None
               and (not e.get('form_id') or (e.get('form_character'), e['form_id'], e.get('form_action')) == ('haley', 'awakened_haley_fox', 'active'))
               for e in eligible):
            return []
        return ['Hot Scoomp: Haley awakening must be approved and active first.']
