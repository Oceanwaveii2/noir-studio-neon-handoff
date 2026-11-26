"""Versioned universe-wide laws and conservative deterministic text checks.

Literal checks detect configured phrases, not every possible semantic violation.
They are not a substitute for semantic validation or author review.
"""
from __future__ import annotations
import json
import re
from collections import Counter
from .universe_scope import verify_scope
from .typed_laws import afm_parentage_constraints, validate_constraint


_PARENTAGE = re.compile(
    r"\bHaley[’']s\s+(?:biological\s+)?(?:father|dad|daddy|paternal\s+parent)\b"
    r"|\b(?:father|dad|daddy)\s+of\s+Haley\b"
    r"|\bHaley\s+(?:has|had|knows|met)\s+(?:a\s+|her\s+)?(?:biological\s+)?(?:father|dad|daddy)\b"
    r"|\bHaley\s+(?:looked\s+at|visited|met|called)\s+her\s+(?:biological\s+)?(?:father|dad|daddy)\b",
    re.IGNORECASE)


def afm_starter_laws():
    return [{'id':'haley-parentage', 'name':'Haley’s parentage',
             'statement':'Haley is the child of Francine and Rainee, two women; she has no father in this universe.',
             'enabled':True, 'matcher':'haley_parentage', 'phrases':[], 'constraints':afm_parentage_constraints()}]


def check_laws(text, laws):
    """Return matched law IDs and normalized evidence for explicit text claims."""
    found = []
    for law in laws:
        if not law['enabled']:
            continue
        if law['matcher'] == 'haley_parentage':
            matches = (item['evidence'].casefold() for item in parentage_findings(text,law,0) if item['status']=='conflict')
        else:
            matches = (m.group(0).casefold() for phrase in law['phrases']
                       for m in re.finditer(re.escape(phrase), text, re.IGNORECASE))
        found.extend((law['id'], match) for match in matches)
    return Counter(found)


def parentage_findings(text, law, revision):
    """Classify narrow explicit mentions; quoted/believed claims stay uncertain."""
    findings=[]
    rules=[r for r in law.get('constraints',afm_parentage_constraints())
           if r['subject'].casefold()=='haley' and r['predicate'].casefold()=='father']
    if not rules: return findings
    for match in _PARENTAGE.finditer(text):
        start=max(text.rfind('.',0,match.start()),text.rfind('!',0,match.start()),text.rfind('?',0,match.start()),text.rfind('\n',0,match.start()))+1
        ends=[x for x in (text.find('.',match.end()),text.find('!',match.end()),text.find('?',match.end()),text.find('\n',match.end())) if x>=0]
        end=min(ends) if ends else len(text)
        sentence=text[start:end]; before=text[start:match.start()]; after=text[match.end():end]
        if re.match(r'(?:-in-law\b|\s+figure\b)',after,re.I): continue
        single_quote=bool((re.search(r"(?:^|\s)'[^'\n]*$",before) and "'" in (after+text[end:end+3])) or
                          ('‘' in before and '’' not in before and '’' in (after+text[end:end+3])))
        nonfact=(single_quote or before.count('"') % 2 == 1 or ('“' in before and '”' not in before) or
                 bool(re.search(r'\b(?:believ\w*|thought|thinks?|imagined|claimed|alleged|knew|assumed|wondered|insisted|jok\w*|pretend\w*|rumou?r|in American Dad|source show)\b',sentence,re.I)))
        negated=bool(re.search(r'\b(?:does not exist|doesn.t exist|never existed|is not real|isn.t real|is a myth)\b',after,re.I))
        if negated: continue
        uncertain=nonfact or bool(re.search(r'\b(?:not|never|no)\b',sentence,re.I)) or any(r['allowed_values'] or r['exceptions'] for r in rules)
        findings.append({'status':'uncertain' if uncertain else 'conflict','rule_id':law['id'],
                         'rule_source':rules[0]['source_id'],'law_revision':revision,
                         'evidence':match.group(0),
                         'reason':'Verify whether this is a character belief or source quotation.' if uncertain else 'The statement implies Haley has a father.'})
    return findings


def _validate(laws):
    if not isinstance(laws, list) or len(laws) > 200:
        raise ValueError('World laws must be a list of at most 200 rules')
    ids = set()
    for law in laws:
        if not isinstance(law, dict) or not {'id', 'name', 'statement', 'enabled', 'matcher', 'phrases'} <= set(law) or set(law)-{'id', 'name', 'statement', 'enabled', 'matcher', 'phrases', 'constraints'}:
            raise ValueError('A world law requires its ID, name, statement, enabled flag and matcher')
        if not isinstance(law['id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', law['id']) or law['id'] in ids:
            raise ValueError('World law IDs must be unique and use letters, numbers, hyphen or underscore')
        ids.add(law['id'])
        if not isinstance(law['name'], str) or not law['name'].strip() or len(law['name']) > 120:
            raise ValueError('A world law needs a short name')
        if not isinstance(law['statement'], str) or not law['statement'].strip() or len(law['statement']) > 3000:
            raise ValueError('A world law needs a statement')
        if type(law['enabled']) is not bool or law['matcher'] not in ('literal', 'haley_parentage', 'typed'):
            raise ValueError('Invalid world law matcher or enabled flag')
        if (not isinstance(law['phrases'], list) or len(law['phrases']) > 30 or
            any(not isinstance(p, str) or not p.strip() or len(p) > 200 for p in law['phrases'])):
            raise ValueError('Invalid forbidden phrases')
        if law['matcher'] == 'literal' and not law['phrases']:
            raise ValueError('A literal world law needs at least one forbidden phrase')
        if law['matcher'] == 'typed' and 'constraints' not in law:
            raise ValueError('A typed world law needs constraints')
        if 'constraints' in law:
            if not isinstance(law['constraints'],list) or not 1 <= len(law['constraints']) <= 100:
                raise ValueError('Typed laws require one or more constraints')
            for constraint in law['constraints']: validate_constraint(constraint)


class WorldLawStore:
    def __init__(self, timeline, *, project_id=None, universe_id=None):
        self.timeline = timeline
        with timeline._connect() as c:
            verify_scope(c,project_id=project_id,universe_id=universe_id)
            c.executescript('''
              CREATE TABLE IF NOT EXISTS universe_law_head(universe_id TEXT PRIMARY KEY, revision INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS universe_law_revisions(universe_id TEXT NOT NULL, revision INTEGER NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(universe_id,revision));
              CREATE TABLE IF NOT EXISTS universe_law_history(universe_id TEXT PRIMARY KEY,basis_revision INTEGER NOT NULL,
                undo_stack TEXT NOT NULL,redo_stack TEXT NOT NULL);
            ''')
            c.execute('BEGIN IMMEDIATE')
            self.identity=verify_scope(c,project_id=project_id,universe_id=universe_id)
            universe=self.identity['universe_id']
            if c.execute('SELECT 1 FROM universe_law_head WHERE universe_id=?',(universe,)).fetchone() is None:
                afm = self.identity['kind']=='afm-starters'
                initial = afm_starter_laws() if afm else []
                c.execute('INSERT INTO universe_law_revisions VALUES(?,0,?)', (universe,json.dumps(initial,ensure_ascii=False)))
                c.execute('INSERT INTO universe_law_head VALUES(?,0)', (universe,))

    @staticmethod
    def in_connection(c, *, project_id=None, universe_id=None, allow_uninitialized=False):
        scope=verify_scope(c,project_id=project_id,universe_id=universe_id)
        if allow_uninitialized and not c.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='universe_law_head'").fetchone():
            return {'revision': 0, 'laws': afm_starter_laws() if scope['kind']=='afm-starters' else [],
                    'project_id': scope['project_id'], 'universe_id': scope['universe_id']}
        row = c.execute('''SELECT r.* FROM universe_law_head h JOIN universe_law_revisions r
             ON r.universe_id=h.universe_id AND r.revision=h.revision WHERE h.universe_id=?''',
             (scope['universe_id'],)).fetchone()
        if row is None:
            raise ValueError('World law revision is missing')
        return {'revision':row['revision'], 'laws':json.loads(row['payload']),
                'project_id':scope['project_id'],'universe_id':scope['universe_id']}

    def open(self):
        with self.timeline._connect() as c:
            return self.in_connection(c,project_id=self.identity['project_id'],universe_id=self.identity['universe_id'])

    @staticmethod
    def _history(c, universe, expected):
        row=c.execute('SELECT * FROM universe_law_history WHERE universe_id=?',(universe,)).fetchone()
        if not row or row['basis_revision']!=expected:return list(range(max(0,expected-1000),expected)),[]
        return json.loads(row['undo_stack']),json.loads(row['redo_stack'])

    def save(self, expected_revision, laws, *, _history_action=None, _history_target=None):
        _validate(laws)
        with self.timeline._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            current = self.in_connection(c,project_id=self.identity['project_id'],universe_id=self.identity['universe_id'])
            if type(expected_revision) is not int or current['revision'] != expected_revision:
                raise ValueError('Stale world law revision')
            undo,redo=self._history(c,current['universe_id'],expected_revision)
            if _history_action in ('undo','redo'):
                stack=undo if _history_action=='undo' else redo
                if not stack or stack[-1]!=_history_target:raise ValueError('World law history changed; reload and try again')
            for law in laws:
                for rule in law.get('constraints',[]):
                    if rule['branch']!='*' and c.execute('SELECT 1 FROM branches WHERE id=?',(rule['branch'],)).fetchone() is None:
                        raise ValueError('Typed law names an unknown branch')
            revision = expected_revision + 1
            c.execute('INSERT INTO universe_law_revisions VALUES(?,?,?)', (current['universe_id'],revision,json.dumps(laws,ensure_ascii=False)))
            c.execute('UPDATE universe_law_head SET revision=? WHERE universe_id=?', (revision,current['universe_id']))
            if _history_action=='undo':undo.pop();redo.append(expected_revision)
            elif _history_action=='redo':redo.pop();undo.append(expected_revision)
            else:undo.append(expected_revision);redo=[]
            c.execute('INSERT OR REPLACE INTO universe_law_history VALUES(?,?,?,?)',
                      (current['universe_id'],revision,json.dumps(undo),json.dumps(redo)))
            return {'revision':revision, 'laws':laws,'project_id':current['project_id'],'universe_id':current['universe_id']}

    def _history_step(self, expected_revision, action):
        with self.timeline._connect() as c:
            verify_scope(c,project_id=self.identity['project_id'],universe_id=self.identity['universe_id'])
            current=self.in_connection(c,project_id=self.identity['project_id'],universe_id=self.identity['universe_id'])
            if type(expected_revision) is not int or current['revision']!=expected_revision:raise ValueError('Stale world law revision')
            undo,redo=self._history(c,self.identity['universe_id'],expected_revision);stack=undo if action=='undo' else redo
            if not stack:raise ValueError('No world law change to '+action)
            target=stack[-1]
            row = c.execute('SELECT payload FROM universe_law_revisions WHERE universe_id=? AND revision=?',
                            (self.identity['universe_id'],target)).fetchone()
        if row is None:
            raise ValueError('No previous world law revision')
        return self.save(expected_revision,json.loads(row['payload']),_history_action=action,_history_target=target)

    def undo(self, expected_revision):return self._history_step(expected_revision,'undo')
    def redo(self, expected_revision):return self._history_step(expected_revision,'redo')
