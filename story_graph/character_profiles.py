"""Revisioned, source-backed profile snapshots for connected form ports.

These records are author-provided adapters, not Digital Mind implementations.
No profile or node is created merely by reading or resolving a junction.
"""
from __future__ import annotations
import hashlib
import json
import re

STABLE = {'personality','voice','author_note','behavior'}
DYNAMIC = {'relationship','goal','physical_state','knowledge','objective'}
CATEGORIES = STABLE | DYNAMIC


def _id(value,name):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,160}',value):
        raise ValueError(name+' is invalid')
    return value


def _exists(c):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='character_profile_heads'").fetchone())


def snapshot(c):
    """Read a consistent current snapshot inside the caller's transaction."""
    if not _exists(c): return (), 'none'
    rows=c.execute('''SELECT h.character_id,h.form_id,h.node_id,h.kind,h.revision,r.payload
        FROM character_profile_heads h JOIN character_profile_revisions r
        ON r.character_id=h.character_id AND r.form_id=h.form_id AND r.node_id=h.node_id AND r.revision=h.revision
        ORDER BY h.character_id,h.form_id,h.node_id''').fetchall()
    heads=c.execute('SELECT COUNT(*) FROM character_profile_heads').fetchone()[0]
    if len(rows)!=heads: raise ValueError('Character profile revision is missing')
    if not rows: return (), 'none'
    data=[dict(row) for row in rows]
    token=hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    records=[]
    for row in data:
        fields=json.loads(row['payload']);_validate(c,row['character_id'],fields)
        records.append({**row,'fields':fields})
    return tuple(records), token


def merge_node_profiles(rows, token, junctions):
    """Merge FormGraphStore character/form node data with timeline CharacterProfileStore snapshots."""
    if not junctions:
        return rows, token
    extra = []
    for cid in sorted(junctions):
        group = junctions[cid]
        for row in getattr(group, 'node_profiles', ()):
            extra.append(dict(row))
    if not extra:
        return rows, token
    by_key = {(r['character_id'], r['form_id'], r['node_id']): dict(r) for r in rows}
    for row in extra:
        key = (row['character_id'], row['form_id'], row['node_id'])
        if key in by_key:
            existing = by_key[key]
            seen = {f['id'] for f in existing['fields']}
            combined = list(existing['fields']) + [f for f in row['fields'] if f['id'] not in seen]
            by_key[key] = {**existing, 'fields': combined, 'form_graph_revision': row['revision']}
        else:
            by_key[key] = dict(row)
    merged = tuple(by_key[k] for k in sorted(by_key))
    node_hash = hashlib.sha256(
        json.dumps(extra, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    ).hexdigest()
    return merged, f'{token}+form:{node_hash}'


def _check_port(junctions,character,form,node,kind):
    group=junctions.get(character)
    actual=next((f for f in group.forms if f.id==form),None) if group else None
    if not actual or not actual.link or (actual.link.node_id,actual.link.kind)!=(node,kind):
        raise ValueError('Connect this exact form port before saving profile data')


def _validate(c,character,fields):
    if not isinstance(fields,list) or len(fields)>100: raise ValueError('Profile fields must be a list of at most 100 entries')
    seen=set()
    for field in fields:
        if not isinstance(field,dict) or set(field)!={'id','category','text','source_type','source_id','confidence'}:
            raise ValueError('Profile fields require ID, category, text, source and confidence')
        _id(field['id'],'Field ID');_id(field['source_id'],'Source ID')
        if field['id'] in seen: raise ValueError('Profile field IDs must be unique')
        seen.add(field['id'])
        if field['category'] not in CATEGORIES or field['confidence'] not in ('author','verified','uncertain'):
            raise ValueError('Invalid profile category or confidence')
        if not isinstance(field['text'],str) or not field['text'].strip() or len(field['text'])>2000:
            raise ValueError('Profile field text must be nonempty and at most 2,000 characters')
        if field['source_type']=='universal_author':
            if field['category'] not in STABLE: raise ValueError('Dynamic character fields require a timeline event')
        elif field['source_type']=='event':
            event=c.execute('SELECT status,permitted,viewpoint FROM events WHERE id=?',(field['source_id'],)).fetchone()
            if not event or event['status']!='approved' or not event['permitted']:
                raise ValueError('Profile event source must be approved and permitted')
            if field['category']=='knowledge' and event['viewpoint']!=character:
                raise ValueError('Knowledge needs a private event for that character')
        else: raise ValueError('Choose an author-universal or timeline event source')


class CharacterProfileStore:
    def __init__(self,timeline): self.timeline=timeline

    def open(self,character,form,node):
        for v,n in ((character,'Character ID'),(form,'Form ID'),(node,'Node ID')): _id(v,n)
        with self.timeline._connect() as c:
            rows,_=snapshot(c)
        row=next((r for r in rows if (r['character_id'],r['form_id'],r['node_id'])==(character,form,node)),None)
        if row is None: return {'revision':0,'fields':[],'status':'missing','scope':'authoring'}
        return {k:row[k] for k in ('character_id','form_id','node_id','kind','revision','fields')} | {'status':'author_supplied','scope':'authoring'}

    def save(self,character,form,node,kind,expected_revision,fields,junctions):
        for v,n in ((character,'Character ID'),(form,'Form ID'),(node,'Node ID')): _id(v,n)
        if kind not in ('digital_mind','super_character') or type(expected_revision) is not int or expected_revision<0:
            raise ValueError('Invalid node type or profile revision')
        _check_port(junctions,character,form,node,kind)
        with self.timeline._connect() as c:
            c.execute('BEGIN IMMEDIATE');_validate(c,character,fields)
            c.execute('''CREATE TABLE IF NOT EXISTS character_profile_heads(character_id TEXT NOT NULL,form_id TEXT NOT NULL,
                node_id TEXT NOT NULL,kind TEXT NOT NULL,revision INTEGER NOT NULL,PRIMARY KEY(character_id,form_id,node_id))''')
            c.execute('''CREATE TABLE IF NOT EXISTS character_profile_revisions(character_id TEXT NOT NULL,form_id TEXT NOT NULL,
                node_id TEXT NOT NULL,revision INTEGER NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(character_id,form_id,node_id,revision))''')
            row=c.execute('SELECT kind,revision FROM character_profile_heads WHERE character_id=? AND form_id=? AND node_id=?',(character,form,node)).fetchone()
            if (row['revision'] if row else 0)!=expected_revision: raise ValueError('Stale character profile revision')
            if row and row['kind']!=kind: raise ValueError('Node type does not match its saved profile')
            revision=expected_revision+1
            c.execute('INSERT INTO character_profile_revisions VALUES(?,?,?,?,?)',(character,form,node,revision,json.dumps(fields,ensure_ascii=False)))
            c.execute('INSERT OR REPLACE INTO character_profile_heads VALUES(?,?,?,?,?)',(character,form,node,kind,revision))
        return self.open(character,form,node)

    def undo(self,character,form,node,kind,expected_revision,junctions):
        if type(expected_revision) is not int or expected_revision<1:
            raise ValueError('No prior character profile revision')
        _check_port(junctions,character,form,node,kind)
        with self.timeline._connect() as c:
            if not _exists(c): raise ValueError('No prior character profile revision')
            current=c.execute('SELECT revision FROM character_profile_heads WHERE character_id=? AND form_id=? AND node_id=?',(character,form,node)).fetchone()
            if not current or current['revision']!=expected_revision: raise ValueError('Stale character profile revision')
            row=c.execute('SELECT payload FROM character_profile_revisions WHERE character_id=? AND form_id=? AND node_id=? AND revision=?',
                          (character,form,node,expected_revision-1)).fetchone()
            if expected_revision>1 and not row: raise ValueError('Prior character profile revision is missing')
            fields=json.loads(row['payload']) if row else []
        return self.save(character,form,node,kind,expected_revision,fields,junctions)


def resolve(forms, rows, visible, viewpoint, hidden, laws=()):
    """Project only base + active form, and only provenance visible at this beat."""
    by_key={(r['character_id'],r['form_id'],r['node_id']):r for r in rows}
    visible_events={e['id']:e for e in visible}
    output={};emitted=set();all_values=[]
    for row in rows:
        all_values.extend(f.get('text','') for f in row['fields'] if isinstance(f,dict))
    for cid,group in forms.items():
        available=group['forms'];base=available[0];active=next(f for f in available if f['status']=='active')
        selected=[base] if base['id']==active['id'] else [base,active]
        parts=[]
        for form in selected:
            link=form.get('link')
            row=by_key.get((cid,form['id'],link['node_id'])) if link else by_key.get((cid,form['id'],form.get('port_id')))
            expected_kind=link['kind'] if link else 'form_card'
            part={'form_id':form['id'],'port_id':form['port_id'],
                'status':'unlinked' if (not link and not row) else 'linked_no_profile',
                'node':link or ({'kind':row['kind'],'node_id':row['node_id']} if row else None),
                'revision':None,'fields':[]}
            if row and row['kind']==expected_kind:
                part['status']='author_supplied_snapshot';part['revision']=row['revision']
                for field in row['fields']:
                    if field['source_type']=='event':
                        event=visible_events.get(field['source_id'])
                        if not event or (event.get('viewpoint') is not None and (viewpoint!=cid or event['viewpoint']!=cid)): continue
                        if field['category']=='knowledge' and (viewpoint!=cid or event.get('viewpoint')!=cid): continue
                        source={'type':'event','id':field['source_id'],'evidence_source':event['source_id'],'reviewer':event['reviewer']}
                    else: source={'type':'universal_author','id':field['source_id']}
                    text=field['text']
                    if any(h.strip().casefold() in text.casefold() for h in hidden if isinstance(h,str) and len(h.strip())>=8): continue
                    from .world_laws import check_laws
                    if check_laws(text,laws): continue
                    part['fields'].append({**field,'source':source});emitted.add(text)
            parts.append(part)
        output[cid]={'character_id':cid,'junction_id':group['junction_id'],'active_form':active['id'],
                     'profiles':parts,'status':'incomplete',
                     'data_status':'missing' if any(p['status']!='author_supplied_snapshot' or not p['fields'] for p in parts) else 'author_supplied',
                     'note':'A link or saved snapshot does not verify a working character node.'}
    hidden_values=[v for v in all_values if isinstance(v,str) and v not in emitted and len(v.strip())>=8]
    return output,hidden_values
