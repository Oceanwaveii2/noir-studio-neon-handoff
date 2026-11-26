"""Conservative, source-linked constraints for an already selected story scope.

These checks assess explicit structured claims; they do not infer a complete
semantic interpretation of free text or turn character beliefs into canon.
"""
from __future__ import annotations

KINDS = {
    'identity', 'parentage', 'relationship', 'transformation', 'chronology', 'location', 'knowledge',
    'physiological_emission', 'sensory_propagation',
}
FIELDS = {'kind', 'subject', 'predicate', 'allowed_values', 'source_id', 'authority',
          'branch', 'valid_from', 'valid_until', 'exceptions'}


def afm_parentage_constraints():
    base={'kind':'parentage','subject':'haley','source_id':'author-context:haley-parentage',
          'authority':'author','branch':'*','valid_from':None,'valid_until':None,'exceptions':[]}
    return [{**base,'predicate':'father','allowed_values':[]},
            {**base,'predicate':'mother','allowed_values':['francine','rainee']}]


def validate_constraint(item):
    if not isinstance(item, dict) or set(item) != FIELDS or item['kind'] not in KINDS:
        raise ValueError('Invalid typed world-law constraint')
    for key in ('subject', 'predicate', 'source_id', 'authority', 'branch'):
        if not isinstance(item[key], str) or not item[key].strip() or len(item[key]) > 200:
            raise ValueError('Typed constraints require subject, predicate, source, authority and branch')
    for key in ('allowed_values', 'exceptions'):
        if not isinstance(item[key], list) or len(item[key]) > 100 or any(not isinstance(v,str) or not v.strip() or len(v)>200 for v in item[key]):
            raise ValueError('Typed constraint values and exceptions must be nonempty strings')
    for key in ('valid_from', 'valid_until'):
        v=item[key]
        if v is not None and (not isinstance(v,list) or len(v)!=2 or any(type(n) is not int or n < 0 for n in v)):
            raise ValueError('Constraint bounds require [episode position, beat]')
    if item['valid_from'] is not None and item['valid_until'] is not None and item['valid_from'] > item['valid_until']:
        raise ValueError('Constraint interval ends before it begins')


def branch_points(connection, episode, beat):
    ep=connection.execute('SELECT branch,position FROM episodes WHERE id=?',(episode,)).fetchone()
    if not ep: raise ValueError('Unknown episode')
    branch=ep['branch']; points={branch:(ep['position'],beat)}
    while True:
        row=connection.execute('SELECT parent,fork_episode,fork_beat FROM branches WHERE id=?',(branch,)).fetchone()
        if row is None: raise ValueError('Unknown branch')
        if row['parent'] is None: break
        parent=row['parent']
        if parent in points: raise ValueError('Cyclic branch ancestry')
        fork=connection.execute('SELECT branch,position FROM episodes WHERE id=?',(row['fork_episode'],)).fetchone()
        if fork is None or fork['branch']!=parent: raise ValueError('Invalid branch fork')
        points[parent]=(fork['position'],row['fork_beat']);branch=parent
    return points


def active_laws(laws, points, current_branch):
    """Keep ancestor rules only when valid at the actual fork point."""
    result=[]
    for law in laws:
        if not law['enabled']: continue
        if law.get('matcher')=='haley_parentage' and 'constraints' not in law:
            law={**law,'constraints':afm_parentage_constraints()}
        if 'constraints' not in law:
            if law.get('matcher')=='typed': raise ValueError('Typed law is missing its constraints')
            result.append(law); continue
        if not isinstance(law['constraints'],list) or not law['constraints']:
            raise ValueError('Typed law is missing its constraints')
        active=[]
        for constraint in law['constraints']:
            validate_constraint(constraint)
            branch=constraint['branch']
            point=points.get(current_branch) if branch=='*' else points.get(branch)
            if point is None: continue
            if constraint['valid_from'] is not None and point < tuple(constraint['valid_from']): continue
            if constraint['valid_until'] is not None and point > tuple(constraint['valid_until']): continue
            active.append(constraint)
        if active:
            result.append({**law,'constraints':active})
    return result


def validate_world_claim(claim, laws, revision):
    required={'kind','subject','predicate','value','assertion','source_id'}
    if not isinstance(claim,dict) or set(claim)!=required or claim['kind']!='world_fact':
        raise ValueError('World facts require subject, predicate, value, assertion and source_id')
    if any(not isinstance(claim[k],str) or not claim[k].strip() for k in required):
        raise ValueError('World fact fields must be nonempty text')
    if claim['assertion'] not in ('fact','belief','source_quote','unknown'):
        raise ValueError('Invalid claim assertion type')
    if claim['assertion']!='fact':
        return [{'status':'uncertain','reason':'This is a belief, quoted source or uncertain claim, not an established world fact.',
                 'claim_source':claim['source_id'],'law_revision':revision}]
    matched=[]
    for law in laws:
        for rule in law.get('constraints',[]):
            if rule['subject'].casefold()!=claim['subject'].casefold() or rule['predicate'].casefold()!=claim['predicate'].casefold(): continue
            permitted={s.casefold() for s in rule['allowed_values']+rule['exceptions']}
            if claim['value'].casefold()=='none' and not permitted:
                matched.append({'status':'supported','rule_id':law['id'],'rule_source':rule['source_id'],
                                'claim_source':claim['source_id'],'law_revision':revision})
                continue
            if claim['value'].casefold() not in permitted:
                matched.append({'status':'conflict','rule_id':law['id'],'constraint_kind':rule['kind'],
                    'rule_source':rule['source_id'],'authority':rule['authority'],
                    'claim_source':claim['source_id'],'law_revision':revision,
                    'reason':f"{claim['subject']} has an unsupported {claim['predicate']}: {claim['value']}"})
            else:
                matched.append({'status':'supported','rule_id':law['id'],'rule_source':rule['source_id'],
                                'claim_source':claim['source_id'],'law_revision':revision})
    return matched or [{'status':'uncertain','reason':'No applicable structured rule supports or rejects this claim.',
                        'claim_source':claim['source_id'],'law_revision':revision}]


def filter_laws_by_active_cast(laws, active_cast=(), *, include_global=True):
    """Keep dense World Laws fast and focused by selecting only rules matching the active cast/entities."""
    cast = {str(c).strip().casefold() for c in (active_cast or ()) if str(c).strip()}
    if not cast:
        return list(laws)
    selected = []
    for law in laws:
        if not law.get('enabled', True):
            continue
        constraints = law.get('constraints') or ()
        if constraints:
            if any(str(rule.get('subject', '')).casefold() in cast for rule in constraints):
                selected.append(law)
                continue
        text = f"{law.get('name', '')} {law.get('statement', '')}".casefold()
        if any(actor in text for actor in cast) or (include_global and law.get('scope') == 'global'):
            selected.append(law)
    return selected
