"""Episode notebook, masks and draft records, stored beside timeline revisions.

Offsets are Python Unicode code points in the exact concatenation of block text.
This service never calls a model.  Existing episode scripts and their revisions
remain the authority and are changed only by a checked, transactional edit.
"""
from __future__ import annotations

from contextlib import nullcontext
import copy
import difflib
import hashlib
import json
import re
import unicodedata
from uuid import uuid4

from story_graph import transaction_audit


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def timeline_token(connection):
    """Conservatively invalidate drafts if timeline facts or ordering change."""
    tables = ('project_scope', 'branches', 'branch_snapshots', 'branch_u4_boundaries', 'episodes',
              'events', 'event_form_bindings', 'universe_law_head', 'universe_law_revisions')
    data = []
    for table in tables:
        data.append([table, [list(row) for row in connection.execute(f'SELECT * FROM {table} ORDER BY rowid')]])
    for table in ('imported_editions','imported_episode_sources'):
        if connection.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone():
            data.append([table,[list(row) for row in connection.execute(f'SELECT * FROM {table} ORDER BY rowid')]])
    from story_graph.character_profiles import snapshot
    _, profile_token=snapshot(connection)
    if profile_token!='none': data.append(['character_profile_token',profile_token])
    return digest(json.dumps(data, ensure_ascii=False, separators=(',', ':')))


def joined(blocks):
    return ''.join(block['text'] for block in blocks)


def _id():
    return uuid4().hex


def _value(value):
    if type(value) is not int or not 1 <= value <= 100:
        raise ValueError('Protection must be an integer from 1 to 100; zero is not supported')
    return value


_BLANK_LINE_RE = re.compile(r'((?:\r\n|\r(?!\n)|\n)(?:[ \t]*(?:\r\n|\r(?!\n)|\n))+)')
_SEPARATOR_RE = re.compile(r'^(?:\*{3,}|-{3,}|_{3,}|\*\s+\*\s+\*)$')
_SCENE_HEADING_RE = re.compile(
    r'^(?:#{1,6}\s+\S|(?:#{1,6}\s*)?(?:\*\*)?(?:INT\.|EXT\.|INT\/EXT\.|I\/E\.|SCENE\s+\d+\b|CHAPTER\s+\d+\b|PROLOGUE\b|EPILOGUE\b|ACT\s+[IVX\d]+\b))',
    re.IGNORECASE,
)
_CUE_RE = re.compile(r"^([A-Z][A-Z0-9 .’'\-]{1,38})\s*:\s*")
_FOUNTAIN_RE = re.compile(r"^([A-Z][A-Z0-9 .’'\-]{1,38})\s*\r?\n(?=\S)")
_ATTRIB_RE = re.compile(
    r'^[“"][^”"\r\n]+[”"]\s*,?\s+([^\W\d_][\w’\'\-]*(?:\s+[^\W\d_][\w’\'\-]*)?)\s+'
    r'(?:said|asked|replied|answered|whispered|shouted|called|muttered|declared|gasped|yelled|announced|exclaimed)\b'
)


def _split_chunks(text):
    # Preserve every separator, including CRLF, as part of the enclosing chunk.
    # A CRLF is one line ending; do not backtrack and count its two code
    # points as a blank line when deriving block boundaries.
    parts = _BLANK_LINE_RE.split(text)
    chunks = [parts[i] + (parts[i + 1] if i + 1 < len(parts) else '')
              for i in range(0, len(parts), 2)]
    return [part for part in chunks if part] or ['']


def _trailing_blank_line(text):
    return bool(re.search(r'(?:\r\n|\r(?!\n)|\n)(?:[ \t]*(?:\r\n|\r(?!\n)|\n))+\Z', text))


def _is_separator(text):
    return bool(_SEPARATOR_RE.match((text or '').strip()))


def _is_scene_heading(text, kind=None):
    if kind == 'scene-heading':
        return True
    source = (text or '').strip()
    return bool(source and _SCENE_HEADING_RE.match(source))


def _infer_label(text):
    source = (text or '').strip()
    if not source:
        return ('Narrator', 'narrator')
    if re.match(r'^(?:#{1,6}\s*)?(?:\*\*)?(?:INT\.|EXT\.|INT/EXT\.|I/E\.|SCENE\s+\d+\b)', source, re.IGNORECASE):
        return ('Scene', 'narrator')
    cue = _CUE_RE.match(source)
    if cue:
        return (cue.group(1).strip(), 'character')
    fountain = _FOUNTAIN_RE.match(source)
    if fountain:
        return (fountain.group(1).strip(), 'character')
    attrib = _ATTRIB_RE.match(source)
    if attrib and attrib.group(1)[:1].isupper():
        return (attrib.group(1), 'character')
    if source.startswith(('“', '"')):
        return ('Dialogue', 'character')
    return ('Narrator', 'narrator')


def _effective_group_key(block, index):
    text = block.get('text', '')
    kind = block.get('kind')
    if _is_separator(text):
        return (f'separator:{index}', False)
    if _is_scene_heading(text, kind):
        return (f'scene-heading:{index}', False)
    if kind and kind != 'unresolved':
        if kind == 'character':
            speaker = block.get('speaker')
            if speaker:
                form = block.get('form') or ''
                return (f'character:{speaker}::{form}', True)
            return (f'character-anon:{index}', False)
        if kind == 'narrator':
            return ('narrator', True)
        return (f'{kind}:{index}', False)
    label, inferred_kind = _infer_label(text)
    if inferred_kind == 'character':
        if label == 'Dialogue':
            return (f'dialogue:{index}', False)
        return (f'inferred-character:{label.lower()}', True)
    return ('narrator', True)


def _group_spans(blocks):
    runs = []
    offset = 0
    for index, block in enumerate(blocks):
        key, can_group = _effective_group_key(block, index)
        text = block.get('text', '')
        length = len(text)
        if runs and runs[-1]['can_group'] and can_group and runs[-1]['key'] == key and _trailing_blank_line(runs[-1]['blocks'][-1]['text']):
            runs[-1]['blocks'].append(block)
            runs[-1]['end'] = offset + length
        else:
            runs.append({'key': key, 'can_group': can_group, 'blocks': [block], 'start': offset, 'end': offset + length})
        offset += length
    return runs


def _blocks(text, source_name, timeline_revision):
    chunks = _split_chunks(text)
    offset = 0
    blocks = []
    for part in chunks:
        blocks.append({'id': _id(), 'kind': 'unresolved', 'speaker': None,
                       'form': None, 'text': part,
                       'source': {'name': source_name, 'timeline_revision': timeline_revision,
                                  'start': offset, 'end': offset + len(part),
                                  'sha256': digest(part)}})
        offset += len(part)
    return blocks


def _valid_blocks(blocks):
    if not isinstance(blocks, list) or not blocks:
        raise ValueError('Notebook needs at least one block')
    ids = set()
    for block in blocks:
        if not isinstance(block, dict) or not isinstance(block.get('id'), str) or not block['id'] or block['id'] in ids:
            raise ValueError('Blocks require unique IDs')
        ids.add(block['id'])
        if block.get('kind') not in ('unresolved', 'narrator', 'character', 'scene-heading', 'stage-direction'):
            raise ValueError('Unknown block kind')
        if not isinstance(block.get('text'), str):
            raise ValueError('Block text must be text')
        for field in ('speaker', 'form'):
            if block.get(field) is not None and (not isinstance(block[field], str) or not block[field].strip()):
                raise ValueError('Speaker and form must be IDs or null')
        if block.get('kind') != 'character' and (block.get('speaker') or block.get('form')):
            raise ValueError('Only character blocks may have speaker or form bindings')
        if block.get('form') and not block.get('speaker'):
            raise ValueError('A form requires a speaker')
        if block.get('source') is not None and not isinstance(block['source'], dict):
            raise ValueError('Invalid source anchor')
        cue = block.get('cue_prefix')
        if cue is not None and (not isinstance(cue, str) or not 1 <= len(cue) <= 128
                                or len(cue.splitlines()) != 1 or cue.strip() != cue):
            raise ValueError('Invalid speaker cue')
        label = block.get('cue_label')
        if label is not None and (not isinstance(label, str) or not 1 <= len(label) <= 45
                                  or not label.isprintable() or label.strip() != label):
            raise ValueError('Invalid speaker cue label')


def _place_speaker_cues(blocks, cues):
    """Move exact prefixes into the visual header without changing any block text."""
    rows = {item['block']: item for item in cues}
    if len(rows) != len(cues):
        raise ValueError('Speaker cue blocks must be unique')
    result = []
    for block in blocks:
        target = rows.pop(block['id'], None)
        if target is None:
            result.append(block)
            continue
        prefix, speaker, form = (target[k] for k in ('prefix', 'speaker', 'form'))
        text = block['text']
        if (block['kind'] not in ('character', 'narrator', 'unresolved')
                or block.get('speaker') not in (None, speaker)
                or block.get('form') not in (None, form)
                or digest(text) != target['block_sha256']
                or not isinstance(prefix, str) or not text.startswith(prefix)
                or not text[len(prefix):].strip() or not _safe_boundary(text, len(prefix))):
            raise ValueError('Speaker cue no longer matches the source block')
        result.append(dict(block, kind='character', speaker=speaker, form=form, cue_prefix=prefix))
    if rows:
        raise ValueError('A speaker cue source block was not found')
    _valid_blocks(result)
    return result


def _valid_masks(text, masks):
    if not isinstance(masks, list):
        raise ValueError('Masks must be a list')
    seen = set()
    for mask in masks:
        if not isinstance(mask, dict) or not isinstance(mask.get('id'), str) or not mask['id'] or mask['id'] in seen:
            raise ValueError('Masks need unique IDs')
        seen.add(mask['id'])
        a, b = mask.get('start'), mask.get('end')
        if type(a) is not int or type(b) is not int or not 0 <= a < b <= len(text):
            raise ValueError('Mask range is outside this document')
        _value(mask.get('value'))
        if mask.get('sha256') != digest(text[a:b]):
            raise ValueError('Stale mask anchor')
        if type(mask.get('hard', False)) is not bool or (mask.get('hard') and mask['value'] != 100):
            raise ValueError('A hard lock must be 100 percent')


def _safe_boundary(text, position):
    """Conservatively reject common multi-code-point character splits.

    Browser selection also uses Intl.Segmenter; this standard-library check is
    intentionally not a complete implementation of Unicode grapheme rules.
    """
    if position in (0,len(text)):return True
    left,right=text[position-1],text[position]
    if left=='\r' and right=='\n':return False
    if unicodedata.category(right).startswith('M') or right=='\u200d' or left=='\u200d':return False
    code=ord(right)
    if 0x1f3fb<=code<=0x1f3ff or 0xe0020<=code<=0xe007f:return False
    if 0x1f1e6<=ord(left)<=0x1f1ff and 0x1f1e6<=code<=0x1f1ff:return False
    return True


def resolve(text, default, masks):
    """Resolve masks over the default. Overlaps use the highest mask value."""
    _value(default)
    _valid_masks(text, masks)
    bounds = sorted({0, len(text), *(m['start'] for m in masks), *(m['end'] for m in masks)})
    out = []
    for a, b in zip(bounds, bounds[1:]):
        if a == b:
            continue
        selected = [m for m in masks if m['start'] < b and a < m['end']]
        value = max((m['value'] for m in selected), default=default)
        hard = any(m.get('hard', False) for m in selected)
        item = {'start': a, 'end': b, 'value': value, 'hard': hard}
        if out and out[-1]['end'] == a and out[-1]['value'] == value and out[-1]['hard'] == hard:
            out[-1]['end'] = b
        else:
            out.append(item)
    return out


def remap_masks(old, new, masks, edit=None):
    """Move unchanged anchored spans; fail closed if any selected span changed."""
    _valid_masks(old, masks)
    if not masks:
        return []
    if old == new:
        return [dict(mask) for mask in masks]
    start, end = edit if edit is not None else (0, len(old))
    new_end = end + len(new) - len(old)
    if not (0 <= start <= end <= len(old) and start <= new_end <= len(new)
            and old[:start] == new[:start] and old[end:] == new[new_end:]):
        raise ValueError('Edit does not match its authorized source occurrence')
    before, after = old[start:end], new[start:new_end]
    matches = None
    result = []
    for mask in masks:
        a, b = mask['start'], mask['end']
        if b <= start:
            dest = a
        elif a >= end:
            dest = a + new_end - end
        else:
            if start == end:
                raise ValueError('Insertion splits a protected or masked range')
            left, right = max(a, start), min(b, end)
            overlap = old[left:right]
            if before.count(overlap) > 1 and after.count(overlap) < before.count(overlap):
                raise ValueError('Edit ambiguously removes a protected occurrence; select the editable range')
            if matches is None:
                matches = difflib.SequenceMatcher(a=before, b=after, autojunk=False).get_matching_blocks()
            match = next((m for m in matches if m.a <= left-start and right-start <= m.a+m.size), None)
            if match is None:
                raise ValueError('Edit touches a protected or masked range; adjust the mask first')
            dest = a + match.b - match.a
        item = dict(mask, start=dest, end=dest+b-a)
        if ((a < start < b and dest != a) or (a < end < b and item['end'] != b + new_end - end)
                or new[dest:item['end']] != old[a:b]):
            raise ValueError('Edit splits or changes a protected or masked range')
        result.append(item)
    return result


def _replace_blocks(blocks, start, end, replacement):
    blocks = copy.deepcopy(blocks)
    old = joined(blocks)
    new = old[:start] + replacement + old[end:]
    if new == old:
        return blocks
    boundaries=[]
    position=0
    for block in blocks[:-1]:
        position += len(block['text']);boundaries.append(position)
    if any(start < boundary < end for boundary in boundaries):
        # A rewrite spanning identities must not silently put dialogue into a
        # narrator block. Preserve each boundary only if unchanged text maps it
        # to exactly one location; otherwise the author needs a narrower edit.
        matches=difflib.SequenceMatcher(a=old,b=new,autojunk=False).get_matching_blocks()
        mapped=[]
        for boundary in boundaries:
            if boundary <= start: candidates={boundary}
            elif boundary >= end: candidates={boundary+len(replacement)-(end-start)}
            else:
                candidates=set()
                for part in matches:
                    if not part.size or not part.a < boundary < part.a+part.size:
                        continue
                    anchor=old[part.a:part.a+part.size]
                    if old.find(anchor)==old.rfind(anchor) and new.find(anchor)==new.rfind(anchor):
                        candidates.add(part.b+boundary-part.a)
            if len(candidates)!=1:
                raise ValueError('Cannot safely preserve block identities across this edit; use a narrower selection')
            mapped.append(next(iter(candidates)))
        if mapped != sorted(mapped) or any(x<0 or x>len(new) for x in mapped):
            raise ValueError('Cannot safely preserve block order across this edit')
        positions=[0,*mapped,len(new)]
        for i,block in enumerate(blocks):block['text']=new[positions[i]:positions[i+1]]
        return blocks
    offset = 0
    inserted = False
    for index,block in enumerate(blocks):
        text = block['text']; stop = offset + len(text)
        if not inserted and (offset <= start < stop or (index==len(blocks)-1 and start==stop)):
            block['text'] = text[:start-offset] + replacement + text[min(len(text), max(0, end-offset)):]
            inserted = True
        elif inserted and offset < end and stop > start:
            block['text'] = text[min(len(text), max(0, end-offset)):]
        offset = stop
    if not inserted:
        raise ValueError('Edit cannot be located in blocks')
    return blocks


def _derived_kind_for_text(template, text):
    kind = template.get('kind', 'narrator')
    if _is_separator(text):
        return (kind if kind in ('narrator', 'unresolved') else 'narrator', None, None)
    if _is_scene_heading(text):
        return ('scene-heading', None, None)
    if kind == 'character' and template.get('speaker'):
        return ('character', template.get('speaker'), template.get('form'))
    if kind in ('narrator', 'unresolved', 'scene-heading', 'stage-direction', 'character'):
        _, inferred_kind = _infer_label(text)
        if inferred_kind == 'character':
            return ('unresolved', None, None)
        return ('narrator' if kind in ('scene-heading', 'stage-direction', 'character') or _is_separator(template.get('text', '')) else kind, None, None)
    return (kind, template.get('speaker'), template.get('form'))


def _reconstruct_homogeneous_group(subblocks, new_group_text):
    old_chunks = [b['text'] for b in subblocks]
    new_chunks = _split_chunks(new_group_text)
    opcodes = difflib.SequenceMatcher(a=old_chunks, b=new_chunks, autojunk=False).get_opcodes()
    result = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == 'equal':
            for i in range(i1, i2):
                result.append(copy.deepcopy(subblocks[i]))
        elif tag == 'replace':
            old_slice = subblocks[i1:i2]
            base = old_slice[0]
            base_sources = [copy.deepcopy(b['source']) for b in old_slice if b.get('source') is not None]
            if len(old_slice) == 1 and (j2 - j1) == 1:
                item = copy.deepcopy(base)
                item['text'] = new_chunks[j1]
                result.append(item)
            else:
                for offset_idx, chunk_text in enumerate(new_chunks[j1:j2]):
                    if offset_idx == 0:
                        item = copy.deepcopy(base)
                        item['text'] = chunk_text
                        if len(old_slice) > 1:
                            item['source'] = {'merged_sources': base_sources} if base_sources else None
                        result.append(item)
                    else:
                        kind, speaker, form = _derived_kind_for_text(base, chunk_text)
                        derived_source = {'split_from': copy.deepcopy(base['source'])} if base.get('source') is not None else None
                        result.append({'id': _id(), 'kind': kind, 'speaker': speaker, 'form': form,
                                       'text': chunk_text, 'source': derived_source})
        elif tag == 'insert':
            ref = subblocks[min(i1, len(subblocks) - 1)]
            for chunk_text in new_chunks[j1:j2]:
                kind, speaker, form = _derived_kind_for_text(ref, chunk_text)
                result.append({'id': _id(), 'kind': kind, 'speaker': speaker, 'form': form,
                               'text': chunk_text, 'source': None})
    if not result:
        item = copy.deepcopy(subblocks[0])
        item['text'] = new_group_text
        result.append(item)
    changed = len(result) != len(subblocks) or any(
        r['id'] != o['id'] or r.get('source') != o.get('source') for r, o in zip(result, subblocks)
    )
    return result, changed


def _replace_blocks_in_document(blocks, old_text, new_text):
    if new_text == old_text:
        return copy.deepcopy(blocks), False
    runs = _group_spans(blocks)
    opcodes = difflib.SequenceMatcher(a=old_text, b=new_text, autojunk=False).get_opcodes()
    non_equal = [op for op in opcodes if op[0] != 'equal']
    boundaries = [r['end'] for r in runs[:-1]]
    if any(a < boundary < b for _, a, b, _, _ in non_equal for boundary in boundaries):
        updated = copy.deepcopy(blocks)
        for tag, a, b, x, y in reversed(opcodes):
            if tag != 'equal':
                updated = _replace_blocks(updated, a, b, new_text[x:y])
        return updated, False
    boundary_left = {r['end']: idx for idx, r in enumerate(runs[:-1])}
    run_ops = [[] for _ in runs]
    for tag, a, b, x, y in non_equal:
        if a < b:
            target = next((idx for idx, r in enumerate(runs) if r['start'] <= a and b <= r['end']), None)
        elif a == len(old_text):
            target = len(runs) - 1
        elif a in boundary_left:
            left_idx = boundary_left[a]
            inserted = new_text[x:y]
            target = left_idx if (runs[left_idx]['can_group'] and _trailing_blank_line(inserted)) else left_idx + 1
        else:
            target = next((idx for idx, r in enumerate(runs) if r['start'] <= a < r['end']), None)
        if target is None:
            updated = copy.deepcopy(blocks)
            for t, a0, b0, x0, y0 in reversed(opcodes):
                if t != 'equal':
                    updated = _replace_blocks(updated, a0, b0, new_text[x0:y0])
            return updated, False
        run_ops[target].append((tag, a, b, x, y))
    new_group_texts = []
    for idx, r in enumerate(runs):
        cursor = r['start']
        pieces = []
        for _, a, b, x, y in run_ops[idx]:
            pieces.append(old_text[cursor:a])
            pieces.append(new_text[x:y])
            cursor = b
        pieces.append(old_text[cursor:r['end']])
        new_group_texts.append(''.join(pieces))
    for idx, r in enumerate(runs[:-1]):
        old_g = old_text[r['start']:r['end']]
        if _trailing_blank_line(old_g) and not _trailing_blank_line(new_group_texts[idx]):
            raise ValueError('Cannot safely preserve block identities across this edit; use a narrower selection')
    out_blocks = []
    trusted_structure = False
    for idx, r in enumerate(runs):
        old_g = old_text[r['start']:r['end']]
        new_g = new_group_texts[idx]
        if new_g == old_g:
            out_blocks.extend(copy.deepcopy(r['blocks']))
            continue
        subblocks = copy.deepcopy(r['blocks'])
        new_chunks = _split_chunks(new_g)
        if len(new_chunks) == len(subblocks) and all(len(_split_chunks(b['text'])) == 1 for b in subblocks):
            local_ops = [(tag, a - r['start'], b - r['start'], x, y) for tag, a, b, x, y in run_ops[idx]]
            try:
                candidate = copy.deepcopy(subblocks)
                for _, la, lb, x, y in reversed(local_ops):
                    candidate = _replace_blocks(candidate, la, lb, new_text[x:y])
                if joined(candidate) == new_g and all(len(_split_chunks(b['text'])) == 1 for b in candidate):
                    out_blocks.extend(candidate)
                    continue
            except ValueError:
                pass
        if r['can_group'] or len(new_chunks) > 1:
            rebuilt, changed = _reconstruct_homogeneous_group(subblocks, new_g)
            out_blocks.extend(rebuilt)
            trusted_structure = trusted_structure or changed
        else:
            for _, la, lb, x, y in reversed([(tag, a - r['start'], b - r['start'], x, y) for tag, a, b, x, y in run_ops[idx]]):
                subblocks = _replace_blocks(subblocks, la, lb, new_text[x:y])
            out_blocks.extend(subblocks)
    return out_blocks, trusted_structure


def _remap_with_stale(old, new, masks, stale, edit=None):
    current, stale = [], list(stale)
    for mask in masks:
        try:
            current.extend(remap_masks(old, new, [mask], edit))
        except ValueError:
            if mask['value'] == 100 or mask.get('hard'):
                raise
            stale.append({**mask, 'reason':'Text changed; select a new range to reactivate'})
    return current, stale


def _replace_planned_blocks(blocks, start, end, planned):
    """Keep the original blocks outside the replacement and type the new cues from its plan."""
    before, after = [], []
    position = 0
    for block in blocks:
        text = block['text']
        limit = position + len(text)
        if limit <= start:
            before.append(block)
        elif position >= end:
            after.append(block)
        else:
            if position < start:
                before.append(dict(block, text=text[:start-position]))
            if limit > end:
                part = dict(block, text=text[end-position:])
                if position < start:
                    part.update(id=_id(), source=None)
                after.append(part)
        position = limit
    return before + [dict(block, id=_id(), source=None) for block in planned] + after


def _text_edit_steps(text, edits):
    # Work from the end so each saved source offset still refers to the original passage.
    for start, end, replacement in reversed(edits):
        if text[start:end] != replacement:
            updated = text[:start] + replacement + text[end:]
            yield text, updated, (start, end, replacement)
            text = updated


class NotebookStore:
    def __init__(self, timeline):
        self.timeline = timeline
        with timeline._connect() as c:
            c.executescript('''
              CREATE TABLE IF NOT EXISTS notebook_heads(episode TEXT PRIMARY KEY REFERENCES episodes(id), head INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS notebook_revisions(episode TEXT NOT NULL REFERENCES episodes(id), revision INTEGER NOT NULL,
                timeline_revision INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(episode,revision));
              CREATE TABLE IF NOT EXISTS episode_drafts(id TEXT PRIMARY KEY, episode TEXT NOT NULL REFERENCES episodes(id),
                branch TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL, favorite INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS notebook_history(episode TEXT PRIMARY KEY REFERENCES episodes(id),
                basis_revision INTEGER NOT NULL, undo_stack TEXT NOT NULL, redo_stack TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS draft_favorite_history(episode TEXT NOT NULL REFERENCES episodes(id),
                branch TEXT NOT NULL, revision INTEGER NOT NULL, undo_stack TEXT NOT NULL, redo_stack TEXT NOT NULL,
                PRIMARY KEY(episode,branch));
            ''')

    @staticmethod
    def _history(c, episode, expected):
        row=c.execute('SELECT * FROM notebook_history WHERE episode=?',(episode,)).fetchone()
        if row is None or row['basis_revision']!=expected:
            return list(range(max(0,expected-1000),expected)),[]
        return json.loads(row['undo_stack']),json.loads(row['redo_stack'])

    @staticmethod
    def _episode(c, episode):
        ep = c.execute('SELECT * FROM episodes WHERE id=?', (episode,)).fetchone()
        if not ep or ep['status']=='archived':
            raise ValueError('Episode is unavailable or removed from the timeline')
        rev = c.execute('SELECT * FROM revisions WHERE episode=? AND revision=?', (episode, ep['head'])).fetchone()
        if rev is None:
            raise ValueError('Episode revision is missing')
        return ep, rev

    @staticmethod
    def _head(c, episode):
        row = c.execute('SELECT r.* FROM notebook_heads h JOIN notebook_revisions r ON r.episode=h.episode AND r.revision=h.head WHERE h.episode=?', (episode,)).fetchone()
        if row is None:
            return None
        result = json.loads(row['payload'])
        result.update(revision=row['revision'], timeline_revision=row['timeline_revision'])
        return result

    def open(self, episode):
        with self.timeline._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            ep, rev = self._episode(c, episode)
            head = self._head(c, episode)
            if head is None:
                state = {'schema_version': 1, 'episode': episode, 'branch': ep['branch'],
                         'default_protection': 100, 'blocks': _blocks(rev['script'], rev['source_name'], ep['head']),
                         'masks': []}
                c.execute('INSERT INTO notebook_heads VALUES(?,0)', (episode,))
                c.execute('INSERT INTO notebook_revisions VALUES(?,?,?,?)', (episode, 0, ep['head'], json.dumps(state, ensure_ascii=False)))
                head = dict(state, revision=0, timeline_revision=ep['head'])
            head['stale'] = head['timeline_revision'] != ep['head'] or joined(head['blocks']) != rev['script']
            return head

    def prepare_structure(self, episode, timeline_revision, project_blocks, publish, *, viewpoint=None, expected=None):
        """Derive notebook labels and timing together without changing manuscript text."""
        from story_graph.beat_map import map_episode

        with self.timeline._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            ep, rev = self._episode(c, episode)
            old = self._head(c, episode)
            text = rev['script']
            if ep['status'] != 'draft' or type(timeline_revision) is not int or ep['head'] != timeline_revision:
                raise ValueError('Episode changed or finished; reopen the saved draft before preparing it')
            if expected is not None and (type(expected) is not int or not old or old['revision'] != expected):
                raise ValueError('Notebook changed; reopen the saved draft before preparing it')
            if digest(text) != rev['script_sha256']:
                raise ValueError('Episode text does not match its saved fingerprint')
            if old is not None and (old['timeline_revision'] != timeline_revision or joined(old['blocks']) != text):
                raise ValueError('Notebook and episode revisions differ; resolve the saved versions before preparing')
            if old is None:
                state = {'schema_version': 1, 'episode': episode, 'branch': ep['branch'],
                         'default_protection': 100, 'blocks': _blocks(text, rev['source_name'], timeline_revision),
                         'masks': []}
            else:
                state = {key: value for key, value in old.items() if key not in ('revision', 'timeline_revision')}
            before = state['blocks']
            after = project_blocks(c, state, old['revision'] if old else None)
            _valid_blocks(after)
            _valid_masks(text, state['masks'])
            if joined(after) != text:
                raise ValueError('Preparation would change the exact saved text')
            state['blocks'] = after
            if old is None:
                next_revision = 0
                c.execute('INSERT INTO notebook_heads VALUES(?,0)', (episode,))
            else:
                next_revision = old['revision'] + int(after != before)
            if old is None or after != before:
                c.execute('INSERT INTO notebook_revisions VALUES(?,?,?,?)',
                          (episode, next_revision, timeline_revision, json.dumps(state, ensure_ascii=False)))
                if old is not None:
                    undo, _ = self._history(c, episode, old['revision'])
                    c.execute('UPDATE notebook_heads SET head=? WHERE episode=?', (next_revision, episode))
                    c.execute('INSERT OR REPLACE INTO notebook_history VALUES(?,?,?,?)',
                              (episode, next_revision, json.dumps([*undo, old['revision']]), '[]'))
                    transaction_audit.record_project_edit(
                        c, domain='notebook', target=episode, operation='prepare_structure', token=old['revision'],
                        before_patch={'notebook_revision': old['revision'], 'timeline_revision': timeline_revision},
                        after_patch={'notebook_revision': next_revision, 'timeline_revision': timeline_revision})
            # Map in this transaction so failures also roll back a prepared notebook.
            mapping = map_episode(self.timeline, episode, timeline_revision, viewpoint=viewpoint, _connection=c)
            prepared = dict(state, revision=next_revision, timeline_revision=timeline_revision, stale=False)
            receipt = publish(c, prepared, mapping)
            return prepared, mapping, len(before), receipt

    def reconcile_copy(self, episode, *, preference, timeline_head, notebook_head, episode_sha, notebook_sha):
        """Append matching forward revisions for an explicitly chosen recovery copy."""
        return self.reconcile_versions(episode, preference=preference, timeline_head=timeline_head,
                                       notebook_head=notebook_head, episode_sha=episode_sha,
                                       notebook_sha=notebook_sha)

    def reconcile_versions(self, episode, *, preference, timeline_head, notebook_head, episode_sha,
                           notebook_sha, speaker_cues=()):
        """Carry the chosen saved text forward and optionally stage an undoable layout."""
        if preference not in ('episode', 'notebook'):
            raise ValueError('Choose which saved text to carry forward')
        with self.timeline._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            ep, rev = self._episode(c, episode)
            old = self._head(c, episode)
            if (ep['status'] != 'draft' or ep['head'] != timeline_head or old is None
                    or old['revision'] != notebook_head):
                raise ValueError('The inspected draft revisions are no longer current')
            episode_text, notebook_text = rev['script'], joined(old['blocks'])
            if digest(episode_text) != episode_sha or rev['script_sha256'] != episode_sha or digest(notebook_text) != notebook_sha:
                raise ValueError('The inspected text does not match the saved fingerprints')
            if episode_text == notebook_text and old['timeline_revision'] == timeline_head:
                raise ValueError('The episode and notebook already match')
            if old.get('stale_masks'):
                raise ValueError('Review unresolved mask anchors before reconciling these versions')

            selected = notebook_text if preference == 'notebook' else episode_text
            frozen = [dict(id=str(i), start=r['start'], end=r['end'], value=100,
                           sha256=digest(notebook_text[r['start']:r['end']]))
                      for i, r in enumerate(resolve(notebook_text, old['default_protection'], old['masks']))
                      if r['value'] == 100]
            remap_masks(notebook_text, selected, frozen)
            masks = remap_masks(notebook_text, selected, old['masks'])
            blocks = old['blocks']
            if selected != notebook_text:
                for row in c.execute('SELECT payload FROM notebook_revisions WHERE episode=? ORDER BY revision DESC', (episode,)):
                    prior = json.loads(row['payload'])['blocks']
                    if joined(prior) == selected:
                        blocks = prior
                        break
                else:
                    blocks = _blocks(selected, rev['source_name'], timeline_head)
            _valid_blocks(blocks)
            _valid_masks(selected, masks)
            if joined(blocks) != selected or len(selected.encode('utf-8')) > 5_000_000:
                raise ValueError('The selected version could not be projected losslessly')
            layout = _place_speaker_cues(blocks, speaker_cues) if speaker_cues else blocks
            if joined(layout) != selected:
                raise ValueError('Speaker layout must preserve exact saved text')
            next_timeline, next_notebook = timeline_head + 1, notebook_head + 1
            source = rev['source_name'] if preference == 'episode' else f'notebook:{episode}@{notebook_head}'
            result = {'schema_version': 1, 'episode': episode, 'branch': ep['branch'],
                      'default_protection': old['default_protection'], 'blocks': blocks, 'masks': masks,
                      'stale_masks': [], 'reconciliation': {'episode_revision': timeline_head,
                      'episode_sha256': episode_sha, 'notebook_revision': notebook_head,
                      'notebook_sha256': notebook_sha, 'preference': preference}}
            c.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?)',
                      (episode, next_timeline, rev['graph'], selected, source, digest(selected)))
            c.execute('INSERT INTO notebook_revisions VALUES(?,?,?,?)',
                      (episode, next_notebook, next_timeline, json.dumps(result, ensure_ascii=False)))
            c.execute('UPDATE episodes SET head=? WHERE id=?', (next_timeline, episode))
            undo = []
            if layout != blocks:
                # Ordinary Undo switches off the visual layout while preserving the reconciled text.
                undo.append(next_notebook)
                next_notebook += 1
                result['blocks'] = layout
                c.execute('INSERT INTO notebook_revisions VALUES(?,?,?,?)',
                          (episode, next_notebook, next_timeline, json.dumps(result, ensure_ascii=False)))
            c.execute('UPDATE notebook_heads SET head=? WHERE episode=?', (next_notebook, episode))
            c.execute('INSERT OR REPLACE INTO notebook_history VALUES(?,?,?,?)',
                      (episode, next_notebook, json.dumps(undo), '[]'))
            return dict(result, revision=next_notebook, timeline_revision=next_timeline, stale=False)

    def save(self, episode, expected, timeline_revision, blocks, default_protection, masks, *, _guard_token=None, _rhythm_guard=None, _reference_guard=None, _scope_guard=None, _stale_masks=None, _trusted_structure=False, _graph=None, _history_action=None, _history_target=None, _receipt=None, _edits=None, _connection=None):
        _valid_blocks(blocks)
        _value(default_protection)
        text = joined(blocks)
        if len(text.encode('utf-8')) > 5_000_000:raise ValueError('Script exceeds 5 MB')
        from story_graph.episode_timeline import encode_graph
        encoded_graph=None if _graph is None else encode_graph(_graph)
        _valid_masks(text, masks)
        with (nullcontext(_connection) if _connection is not None else self.timeline._connect()) as c:
            if _connection is None:
                c.execute('BEGIN IMMEDIATE')
            if _receipt is not None:
                _receipt.check_new(c)
            ep, old_rev = self._episode(c, episode)
            old = self._head(c, episode)
            if old is None or type(expected) is not int or old['revision'] != expected:
                raise ValueError('Stale notebook revision')
            undo_stack,redo_stack=self._history(c,episode,expected)
            if _history_action in ('undo','redo'):
                stack=undo_stack if _history_action=='undo' else redo_stack
                if not stack or stack[-1]!=_history_target: raise ValueError('Notebook history changed; reload and try again')
            if _guard_token is not None and timeline_token(c) != _guard_token:
                raise ValueError('Timeline facts changed; draft must be checked again')
            if _scope_guard is not None:
                _scope_guard(c)
            if _rhythm_guard is not None:
                from story_graph.beat_rhythm import read as read_beat_rhythm
                beat,token=_rhythm_guard
                if read_beat_rhythm(c,episode,beat)['token']!=token:
                    raise ValueError('Beat direction changed; draft must be checked again')
            if ep['status'] != 'draft' or type(timeline_revision) is not int or ep['head'] != timeline_revision or old['timeline_revision'] != ep['head']:
                raise ValueError('Stale or finished episode revision')
            old_text = joined(old['blocks'])
            if old_text != old_rev['script']:
                raise ValueError('Notebook and episode text differ')
            steps = None if _edits is None else list(_text_edit_steps(old_text, _edits))
            if steps is not None and (steps[-1][1] if steps else old_text) != text:
                raise ValueError('Edit does not match its authorized source occurrence')

            def remap(anchors):
                if steps is None:
                    return remap_masks(old_text, text, anchors)
                for before, after, (a, b, _) in steps:
                    anchors = remap_masks(before, after, anchors, (a, b))
                return anchors

            prior_masks={m['id']:m for m in old['masks']}
            for mask in masks:
                prior=prior_masks.get(mask['id'])
                if prior is None or (prior['start'],prior['end'])!=(mask['start'],mask['end']):
                    if not _safe_boundary(text,mask['start']) or not _safe_boundary(text,mask['end']):
                        raise ValueError('Mask must start and end between complete characters')
            if not _trusted_structure:
                original_sources = {b['id']: b.get('source') for b in old['blocks']}
                for block in blocks:
                    if block['id'] in original_sources and block.get('source') != original_sources[block['id']]:
                        raise ValueError('Existing source anchors cannot be rewritten')
                    if block['id'] not in original_sources and block.get('source') is not None:
                        raise ValueError('New blocks cannot invent source anchors')
            # Hard locks can never be deleted, softened, moved to different text or
            # altered through this API. Their exact reanchoring is checked below.
            hard = [m for m in old['masks'] if m.get('hard')]
            # Undo and redo recover the exact positions recorded in a verified history revision.
            if _history_action:
                saved = c.execute('SELECT payload FROM notebook_revisions WHERE episode=? AND revision=?',
                                  (episode, _history_target)).fetchone()
                target = json.loads(saved['payload'])
                if target['masks'] != masks or joined(target['blocks']) != text:
                    raise ValueError('History target differs from the saved mask occurrences')
                historical = {m['id']:m for m in masks}
                mapped_hard = []
                for m in hard:
                    found = historical.get(m['id'])
                    if not found or not found.get('hard') or found['sha256'] != m['sha256']:
                        raise ValueError('Existing hard lock cannot be removed or weakened')
            else:
                mapped_hard = remap(hard)
            by_id = {m['id']: m for m in masks}
            if any(by_id.get(m['id']) != m for m in mapped_hard):
                raise ValueError('Existing hard lock cannot be removed or weakened')
            if not _history_action:
                tracked_soft = [m for m in old['masks'] if m['id'] in by_id and not m.get('hard')]
                for mapped in remap(tracked_soft):
                    current = by_id[mapped['id']]
                    if (current['start'], current['end'], current['sha256']) != (mapped['start'], mapped['end'], mapped['sha256']):
                        raise ValueError('An existing mask cannot be moved to different text')
            if _reference_guard is not None:
                _reference_guard()
            next_timeline = ep['head']
            graph_changed=encoded_graph is not None and json.loads(old_rev['graph'])!=_graph
            if text != old_text and _history_action is None:
                # Frozen effective ranges must survive exactly and in order.
                frozen = [dict(id=str(i), start=r['start'], end=r['end'], value=100,
                               hard=False, sha256=digest(old_text[r['start']:r['end']]))
                          for i, r in enumerate(resolve(old_text, old['default_protection'], old['masks'])) if r['value'] == 100]
                remap(frozen)
            if text != old_text or graph_changed:
                next_timeline += 1
                c.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?)',
                          (episode, next_timeline, encoded_graph if graph_changed else old_rev['graph'], text, old_rev['source_name'], digest(text)))
                c.execute('UPDATE episodes SET head=? WHERE id=?', (next_timeline, episode))
            state = {'schema_version': 1, 'episode': episode, 'branch': ep['branch'],
                     'default_protection': default_protection, 'blocks': blocks, 'masks': masks,
                     'stale_masks': old.get('stale_masks', []) if _stale_masks is None else _stale_masks}
            next_revision = expected + 1
            c.execute('INSERT INTO notebook_revisions VALUES(?,?,?,?)', (episode, next_revision, next_timeline, json.dumps(state, ensure_ascii=False)))
            c.execute('UPDATE notebook_heads SET head=? WHERE episode=?', (next_revision, episode))
            if _history_action=='undo': undo_stack.pop();redo_stack.append(expected)
            elif _history_action=='redo': redo_stack.pop();undo_stack.append(expected)
            else: undo_stack.append(expected);redo_stack=[]
            c.execute('INSERT OR REPLACE INTO notebook_history VALUES(?,?,?,?)',
                      (episode,next_revision,json.dumps(undo_stack),json.dumps(redo_stack)))
            if _history_action:
                transaction_audit.step_project_edit(
                    c, domain='notebook', target=episode, token=_history_target,
                    next_token=expected, undo=_history_action == 'undo')
            else:
                transaction_audit.record_project_edit(
                    c, domain='notebook', target=episode, operation='save', token=expected,
                    before_patch={'notebook_revision': expected, 'timeline_revision': timeline_revision},
                    after_patch={'notebook_revision': next_revision, 'timeline_revision': next_timeline})
            if _receipt is not None:
                _receipt.record(c,next_revision,next_timeline)
            return dict(state, revision=next_revision, timeline_revision=next_timeline, stale=False)

    def edit_text(self, episode, expected, timeline_revision, start, end, replacement, *, guard_token=None, rhythm_guard=None, reference_guard=None, scope_guard=None, receipt=None, edits=None, planned_blocks=None):
        state = self.open(episode)
        old = joined(state['blocks'])
        if type(start) is not int or type(end) is not int or not 0 <= start <= end <= len(old) or not isinstance(replacement, str):
            raise ValueError('Invalid text edit')
        edits = ((start, end, replacement),) if edits is None else tuple(edits)
        if planned_blocks is not None and edits != ((start, end, replacement),):
            raise ValueError('A planned scene needs one complete replacement')
        previous_end = start
        for a, b, part in edits:
            if type(a) is not int or type(b) is not int or not previous_end <= a <= b <= end or not isinstance(part, str):
                raise ValueError('Invalid component text edit')
            previous_end = b
        blocks, masks, stale_masks = state['blocks'], state['masks'], state.get('stale_masks', [])
        for before, after, (a, b, part) in _text_edit_steps(old, edits):
            masks, stale_masks = _remap_with_stale(before, after, masks, stale_masks, (a, b))
            blocks = (_replace_planned_blocks(blocks, a, b, planned_blocks) if planned_blocks is not None
                      else _replace_blocks(blocks, a, b, part))
        if joined(blocks) != old[:start] + replacement + old[end:]:
            raise ValueError('Component edits do not match the validated draft')
        return self.save(episode, expected, timeline_revision, blocks, state['default_protection'], masks,
                         _guard_token=guard_token, _rhythm_guard=rhythm_guard, _reference_guard=reference_guard,
                         _scope_guard=scope_guard, _stale_masks=stale_masks, _receipt=receipt, _edits=edits)

    def speaker_options(self, episode, block_id):
        from story_graph.source_imports import snapshot as source_snapshot, binding, source_junctions
        state=self.existing(episode)
        if state is None or state['stale']:raise ValueError('Open the current notebook')
        item=next((b for b in state['blocks'] if b['id']==block_id),None)
        if item is None:raise ValueError('Block not found')
        start=0
        for b in state['blocks']:
            if b['id']==block_id:break
            start+=len(b['text'])
        with self.timeline._connect() as c:
            ep,rev=self._episode(c,episode);found=binding(c,episode)
            if found is None:raise ValueError('This block has no imported character graph')
            scope=source_snapshot(c,episode,ep['head'],rev['script'],digest(rev['graph']),start,start+len(item['text']))
            groups=source_junctions(found[1]);active={p['character_id']:p['active_form'] for p in scope['characters']}
            options=[{'character':None,'form':None,'label':'Narrator / no character binding'}]
            for cid,group in sorted(groups.items()):
                ident=active.get(cid,cid)
                # Only base and as-of active source form, never future planning forms.
                for f in group.forms:
                    if f.id in (cid,ident):options.append({'character':cid,'form':f.id,'label':group.forms[0].label+(' · '+f.label if f.id!=cid else '')})
        return {'revision':state['revision'],'timeline_revision':state['timeline_revision'],'options':options}

    def bind_speaker(self, episode, expected, timeline_revision, block_id, character, form):
        if isinstance(block_id, str):
            raw_ids = [block_id]
        elif isinstance(block_id, list) and block_id and all(isinstance(bid, str) and bid for bid in block_id):
            raw_ids = list(dict.fromkeys(block_id))
        else:
            raise ValueError('Block not found')
        options=self.speaker_options(episode,raw_ids[0])
        if not any((o['character'],o['form'])==(character,form) for o in options['options']):
            raise ValueError('Choose a source-backed base or currently available form')
        state=self.existing(episode)
        if state['revision']!=expected or state['timeline_revision']!=timeline_revision:raise ValueError('Stale speaker binding')
        by_id = {b['id']: b for b in state['blocks']}
        if any(bid not in by_id for bid in raw_ids):
            raise ValueError('Block not found')
        if len(raw_ids) > 1:
            spans = _group_spans(state['blocks'])
            target_span = next((r for r in spans if any(b['id'] == raw_ids[0] for b in r['blocks'])), None)
            span_ids = {b['id'] for b in target_span['blocks']} if target_span else set()
            if not set(raw_ids).issubset(span_ids):
                raise ValueError('Bind speaker across blocks in the same group or pick one block at a time')
        blocks=copy.deepcopy(state['blocks'])
        target_set = set(raw_ids)
        for item in blocks:
            if item['id'] in target_set:
                item.update(kind='character' if character else 'narrator',speaker=character,form=form,
                            binding_evidence={'status':'author-correction','previous':item.get('binding_evidence')})
        return self.save(episode,expected,timeline_revision,blocks,state['default_protection'],state['masks'])

    def append_block(self, episode, expected, timeline_revision, kind, speaker=None, *, junctions=None):
        """Append an explicitly typed, recoverable writing block."""
        if kind not in ('narrator', 'character'):
            raise ValueError('Choose a narrator or character block')
        if kind == 'character':
            if not isinstance(speaker, str) or not isinstance(junctions, dict) or speaker not in junctions:
                raise ValueError('Create or choose a character graph first')
        elif speaker is not None:
            raise ValueError('Narrator blocks do not have a character')
        state=self.existing(episode)
        if state is None or state['stale'] or state['revision']!=expected or state['timeline_revision']!=timeline_revision:
            raise ValueError('Notebook changed; reload before adding a block')
        blocks=copy.deepcopy(state['blocks'])
        text=joined(blocks)
        if not blocks[-1]['text']:
            blocks[-1].update(kind=kind,speaker=speaker,form=None)
        else:
            if not text.endswith(('\n\n','\r\n\r\n','\r\r')):
                blocks[-1]['text'] += '\r\n\r\n' if '\r\n' in text else '\n\n'
            blocks.append({'id':_id(),'kind':kind,'speaker':speaker,'form':None,'text':'','source':None})
        return self.save(episode,expected,timeline_revision,blocks,state['default_protection'],state['masks'],
                         _stale_masks=state.get('stale_masks', []))

    def save_document(self, episode, expected, timeline_revision, text, graph):
        """Atomically save a whole editor document and graph through mask guards."""
        if not isinstance(text,str):raise ValueError('Script must be text')
        state=self.existing(episode)
        if state is None or state['stale'] or state['revision']!=expected or state['timeline_revision']!=timeline_revision:
            raise ValueError('Notebook protection is stale; reload or synchronize before saving')
        old=joined(state['blocks'])
        masks,stale=_remap_with_stale(old,text,state['masks'],state.get('stale_masks',[]))
        blocks,trusted_structure=_replace_blocks_in_document(state['blocks'],old,text)
        if joined(blocks)!=text:raise ValueError('Cannot safely map this edit to notebook blocks')
        return self.save(episode,expected,timeline_revision,blocks,state['default_protection'],masks,
                         _stale_masks=stale,_trusted_structure=trusted_structure,_graph=graph)

    def _history_step(self, episode, expected, timeline_revision, action, receipt=None, *, connection=None,
                      graph_revision=None):
        with (nullcontext(connection) if connection is not None else self.timeline._connect()) as c:
            self._episode(c,episode)
            head=self._head(c,episode)
            if head is None or type(expected) is not int or head['revision']!=expected:
                raise ValueError('Stale notebook revision')
            undo,redo=self._history(c,episode,expected);stack=undo if action=='undo' else redo
            if not stack: raise ValueError('No notebook change to '+action)
            target=stack[-1]
            old = c.execute('SELECT payload,timeline_revision FROM notebook_revisions WHERE episode=? AND revision=?', (episode,target)).fetchone()
            graph = c.execute('SELECT graph FROM revisions WHERE episode=? AND revision=?',
                              (episode, old['timeline_revision'] if graph_revision is None else graph_revision)).fetchone() if old else None
        if old is None:
            raise ValueError('No earlier notebook revision')
        if graph is None:raise ValueError('Notebook graph revision is missing')
        state = json.loads(old['payload'])
        return self.save(episode, expected, timeline_revision, state['blocks'], state['default_protection'], state['masks'],
                         _trusted_structure=True, _stale_masks=state.get('stale_masks', []),_graph=json.loads(graph['graph']),
                         _history_action=action,_history_target=target,_receipt=receipt,_connection=connection)

    def undo(self, episode, expected, timeline_revision, *, receipt=None):
        return self._history_step(episode,expected,timeline_revision,'undo',receipt)

    def redo(self, episode, expected, timeline_revision, *, receipt=None):
        return self._history_step(episode,expected,timeline_revision,'redo',receipt)

    def dismiss_stale_mask(self, episode, expected, timeline_revision, ident):
        """Remove one explicitly selected inactive soft mask in a new revision."""
        state=self.existing(episode)
        if state is None or state['stale'] or state['revision']!=expected:
            raise ValueError('Open the current notebook before clearing a stale mask')
        stale=state.get('stale_masks',[])
        matches=[m for m in stale if m.get('id')==ident]
        if len(matches)!=1:raise ValueError('Stale mask not found or ambiguous')
        if matches[0].get('hard') or matches[0].get('value')==100:
            raise ValueError('An exact or hard lock cannot be dismissed as a stale mask')
        return self.save(episode,expected,timeline_revision,state['blocks'],state['default_protection'],state['masks'],
                         _stale_masks=[m for m in stale if m.get('id')!=ident])

    def existing(self, episode):
        """Read an already initialized notebook without creating one."""
        with self.timeline._connect() as c:
            return self.existing_in_connection(c, episode)

    @classmethod
    def existing_in_connection(cls, c, episode):
        ep, rev = cls._episode(c, episode)
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='notebook_heads'").fetchone():
            return None
        state = cls._head(c, episode)
        if state is not None:
            state['stale'] = state['timeline_revision'] != ep['head'] or joined(state['blocks']) != rev['script']
        return state

    def sync(self, episode, expected, timeline_revision):
        """Reanchor an externally saved script, refusing edits to exact locks."""
        with self.timeline._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            ep, rev = self._episode(c, episode)
            state = self._head(c, episode)
            if state is None or state['revision'] != expected or ep['head'] != timeline_revision:
                raise ValueError('Stale notebook or episode revision')
            old, new = joined(state['blocks']), rev['script']
            frozen = [dict(id=str(i), start=r['start'], end=r['end'], value=100, hard=False,
                           sha256=digest(old[r['start']:r['end']]))
                      for i, r in enumerate(resolve(old, state['default_protection'], state['masks'])) if r['value'] == 100]
            remap_masks(old, new, frozen)
            masks, stale = _remap_with_stale(old, new, state['masks'], state.get('stale_masks', []))
            blocks = copy.deepcopy(state['blocks'])
            for tag, a, b, x, y in reversed(difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes()):
                if tag != 'equal':
                    blocks = _replace_blocks(blocks, a, b, new[x:y])
            if joined(blocks) != new:
                raise ValueError('Cannot safely map this external edit to notebook blocks')
            result = {'schema_version':1, 'episode':episode, 'branch':ep['branch'],
                      'default_protection':state['default_protection'], 'blocks':blocks,
                      'masks':masks, 'stale_masks':stale}
            next_revision = expected + 1
            c.execute('INSERT INTO notebook_revisions VALUES(?,?,?,?)',
                      (episode,next_revision,timeline_revision,json.dumps(result,ensure_ascii=False)))
            c.execute('UPDATE notebook_heads SET head=? WHERE episode=?', (next_revision,episode))
            return dict(result, revision=next_revision, timeline_revision=timeline_revision, stale=False)

    def split(self, episode, expected, timeline_revision, block_id, offset):
        state = self.open(episode)
        blocks = copy.deepcopy(state['blocks'])
        index = next((i for i, b in enumerate(blocks) if b['id'] == block_id), None)
        if index is None or type(offset) is not int or not 0 < offset < len(blocks[index]['text']):
            raise ValueError('Invalid block split')
        original = blocks[index]
        second = copy.deepcopy(original)
        second['id'] = _id()
        second['text'] = original['text'][offset:]
        original['text'] = original['text'][:offset]
        # The source anchor continues to identify the original source passage;
        # it is provenance, not an assertion that edited text equals the source.
        blocks.insert(index+1, second)
        return self.save(episode, expected, timeline_revision, blocks, state['default_protection'], state['masks'], _trusted_structure=True)

    def merge(self, episode, expected, timeline_revision, first_id, second_id):
        state = self.open(episode)
        blocks = copy.deepcopy(state['blocks'])
        index = next((i for i, b in enumerate(blocks) if b['id'] == first_id), None)
        if index is None or index+1 >= len(blocks) or blocks[index+1]['id'] != second_id:
            raise ValueError('Merge requires adjacent blocks')
        left, right = blocks[index:index+2]
        if (left['kind'], left['speaker'], left['form']) != (right['kind'], right['speaker'], right['form']):
            raise ValueError('Merge requires matching block kind and bindings')
        left['text'] += right['text']
        left['source'] = {'merged_sources': [left.get('source'), right.get('source')]}
        del blocks[index+1]
        return self.save(episode, expected, timeline_revision, blocks, state['default_protection'], state['masks'], _trusted_structure=True)


class DraftStore:
    """Immutable candidate content plus explicitly mutable favorite/status."""
    def __init__(self, notebook):
        self.notebook = notebook
        self.timeline = notebook.timeline

    def guard_scope(self, c, packet):
        from story_graph.world_laws import WorldLawStore
        from story_graph.universe_scope import verify_scope
        from story_graph.character_profiles import snapshot
        from story_graph.beat_rhythm import read as read_beat_rhythm
        if getattr(packet, 'compositor', None):
            from .cook import guard_render_context
            guard_render_context(self.timeline, c, packet)
        scope = verify_scope(c, project_id=packet.context.project_id, universe_id=packet.context.universe_id)
        if scope['scope_revision'] != packet.context.scope_revision:
            raise ValueError('Project or universe scope changed before generation')
        ep, rev = self.notebook._episode(c, packet.episode)
        if ep['branch'] != packet.branch or ep['head'] != packet.revision:
            raise ValueError('Stale or incorrect draft scope')
        if (digest(rev['graph']) != packet.context.graph_sha256 or
                (rev['script'] and digest(rev['script']) != packet.context.source_sha256)):
            raise ValueError('Source or graph changed before generation')
        notebook = self.notebook._head(c, packet.episode)
        if notebook is not None and (notebook['timeline_revision'] != ep['head'] or joined(notebook['blocks']) != rev['script']):
            raise ValueError('Notebook is stale')
        current_mask_revision = None if notebook is None else notebook['revision']
        if current_mask_revision != packet.protection_revision:
            raise ValueError('Protection changed before generation')
        if WorldLawStore.in_connection(c,project_id=scope['project_id'],universe_id=scope['universe_id'])['revision'] != packet.world_law_revision:
            raise ValueError('World laws changed before generation')
        if snapshot(c)[1] != str(packet.character_store_token).split('+form:', 1)[0]:
            raise ValueError('Character profiles changed before generation')
        if read_beat_rhythm(c,packet.episode,packet.beat)['token'] != packet.beat_rhythm.get('token','none'):
            raise ValueError('Beat direction changed before generation')
        from .scoped_groups import guard
        guard(self.timeline,c,packet.composite or (packet,))
        return scope, notebook

    def start(self, packet, provider, parent=None, *, reference_receipts=None, scene_function='scene',
              reference_features=None, reference_binding=None, request_budget=None, rhythm_guidance=None,
              composite_segments=None, draft_id=None, writing_run=None, proposal=None, write_guard=None):
        if not isinstance(provider, str) or not provider:
            raise ValueError('Provider is required')
        if packet.context is None:
            raise ValueError('A project and universe context is required')
        if proposal is not None and not isinstance(proposal.get('text'), str):
            raise ValueError('A proposal needs text')
        with self.timeline._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if write_guard is not None:
                write_guard(c)
            scope, notebook = self.guard_scope(c, packet)
            if parent is not None:
                p = c.execute('SELECT episode,branch FROM episode_drafts WHERE id=?', (parent,)).fetchone()
                if p is None or p['episode'] != packet.episode or p['branch'] != packet.branch:
                    raise ValueError('Parent draft belongs to a different scope')
            ident = draft_id or _id()
            record = {'id': ident, 'episode': packet.episode, 'branch': packet.branch,
                      'project_id':scope['project_id'], 'universe_id':scope['universe_id'],
                      'context':packet.context.public(),
                      'source_revision': packet.revision, 'graph_revision': packet.revision,
                      'notebook_revision': None if notebook is None else notebook['revision'],
                      'mask_revision': None if notebook is None else notebook['revision'],
                      'world_law_revision': packet.world_law_revision,
                      'rhythm_revision':packet.beat_rhythm.get('revision') or None,
                      'rhythm_token':packet.beat_rhythm.get('token','none'),
                      'rhythm_profile_id':f'{packet.episode}:{packet.beat}' if packet.beat_rhythm.get('status')=='configured' else None,
                      'reference_features':reference_features, 'provider': provider, 'parent': parent,
                      'rhythm_guidance':rhythm_guidance, 'rhythm_evidence':None,
                      'beat': packet.beat, 'viewpoint': packet.viewpoint, 'start': packet.start,
                      'end': packet.end, 'source_sha256': packet.target_sha256,
                      'source_text': packet.target, 'text': None, 'issue': None,
                      'timeline_token': timeline_token(c),
                      'protected_ranges': [[a,b] for a,b,_ in packet.protected],
                      'reference_receipts':reference_receipts or [], 'scene_function':scene_function,
                      'character_store_token':packet.character_store_token,
                      'character_receipts':packet.character_receipts(),
                      'writing_context':packet.public(),
                      'passage_anchor':packet.passage_anchor,
                      'composite_segments':composite_segments,
                      'reference_binding':reference_binding,
                      'request_budget':request_budget or {'max_provider_calls':1,'token_limit':None}}
            if writing_run is not None:
                record['writing_run'] = writing_run
            if proposal is not None:
                record.update(text=proposal['text'], issue=proposal.get('issue'),
                              rhythm_evidence=proposal.get('rhythm_evidence'))
                kind = (record['issue'] or {}).get('kind') if isinstance(record['issue'], dict) else None
                record['origin'] = {'exact-protection':'preserved', 'offline-bridge':'imported',
                                    'beat_group':'assembled'}.get(kind, 'unknown')
                if proposal.get('writer_receipts'):
                    record.update(origin='generated', writer_receipts=proposal['writer_receipts'])
            c.execute('INSERT INTO episode_drafts(id,episode,branch,status,payload) VALUES(?,?,?,?,?)',
                      (ident, packet.episode, packet.branch, 'PROPOSED' if proposal is not None else 'STARTED',
                       json.dumps(record, ensure_ascii=False)))
            return ident

    def provider_ready(self, ident, provider, request_id, prompt_sha256, *, journal_id=None, write_guard=None):
        """Record the actual local request cap and journal lookup before dispatch."""
        cap=getattr(provider,'max_calls',None)
        budget={'max_provider_calls':min(1,cap) if type(cap) is int and cap>=0 else 1,'token_limit':None}
        job=getattr(provider,'job_id',None); scope=getattr(provider,'recovery_scope',None)
        with self.timeline._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if write_guard is not None:
                write_guard(c)
            row=c.execute('SELECT status,payload FROM episode_drafts WHERE id=?',(ident,)).fetchone()
            if row is None or row['status']!='STARTED': raise ValueError('Draft is missing or already finalized')
            data=json.loads(row['payload'])
            data['request_budget'].update(max_provider_calls=budget['max_provider_calls'])
            data['provider_job_id']=job if isinstance(job,str) else None
            data['provider_recovery_scope']=scope if isinstance(scope,str) else None
            if journal_id is not None:
                data['provider_journal_id'] = journal_id
            data['provider_request_id'] = request_id
            data['provider_prompt_sha256'] = prompt_sha256
            c.execute('UPDATE episode_drafts SET payload=? WHERE id=?',(json.dumps(data,ensure_ascii=False),ident))

    def finish(self, ident, status, text=None, issue=None, attempt_id=None, meaning_evidence=None,rhythm_evidence=None,
               *, writer_response_sha256=None, raw_response_sha256=None, write_guard=None, on_saved=None,
               compositor_polish=None):
        if status not in ('PROPOSED', 'BLOCKED', 'FAILED', 'STALE', 'UNKNOWN'):
            raise ValueError('Invalid draft status')
        if status == 'PROPOSED' and not isinstance(text, str):
            raise ValueError('A proposal needs text')
        with self.timeline._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if write_guard is not None:
                write_guard(c)
            row = c.execute('SELECT * FROM episode_drafts WHERE id=?', (ident,)).fetchone()
            if row is None or row['status'] != 'STARTED':
                raise ValueError('Draft is missing or already finalized')
            data = json.loads(row['payload']); data['text'] = text; data['issue'] = issue
            if compositor_polish is not None:
                data['compositor_polish'] = compositor_polish
            data['attempt_id'] = attempt_id if isinstance(attempt_id,str) else None
            if writer_response_sha256 is not None:
                if not data.get('provider_request_id') or not data.get('provider_prompt_sha256'):
                    raise ValueError('Writer response has no dispatched request receipt')
                data['writer_receipt'] = {'request_id':data['provider_request_id'],
                                          'prompt_sha256':data['provider_prompt_sha256'],
                                          'response_sha256':writer_response_sha256,
                                          'attempt_id':data['attempt_id']}
                if raw_response_sha256 is not None:
                    data['writer_receipt']['raw_response_sha256'] = raw_response_sha256
                if status == 'PROPOSED':
                    data['origin'] = 'generated'
            if meaning_evidence is not None: data['meaning_evidence'] = meaning_evidence
            if rhythm_evidence is not None: data['rhythm_evidence'] = rhythm_evidence
            c.execute('UPDATE episode_drafts SET status=?,payload=? WHERE id=?', (status, json.dumps(data, ensure_ascii=False), ident))
            if on_saved is not None:
                on_saved(c, status)

    @staticmethod
    def _favorite_stacks(c, episode, branch):
        row = c.execute(
            'SELECT revision, undo_stack, redo_stack FROM draft_favorite_history WHERE episode=? AND branch=?',
            (episode, branch),
        ).fetchone()
        if row is None:
            return 0, [], []
        return int(row['revision']), json.loads(row['undo_stack']), json.loads(row['redo_stack'])

    def favorite_history(self, episode, branch):
        with self.timeline._connect() as c:
            ep, _ = self.notebook._episode(c, episode)
            if ep['branch'] != branch:
                raise ValueError('Wrong episode branch')
            rev, undo_stack, redo_stack = self._favorite_stacks(c, episode, branch)
            return {
                'favorite_revision': rev,
                'can_undo_favorite': bool(undo_stack),
                'can_redo_favorite': bool(redo_stack),
                'undo_count': len(undo_stack),
                'redo_count': len(redo_stack),
            }

    def open(self, episode, branch, ident):
        with self.timeline._connect() as c:
            saved = self.read_saved(c, episode, branch, ident)
            rev, undo_stack, redo_stack = self._favorite_stacks(c, episode, branch)
            return dict(saved, favorite_revision=rev, can_undo_favorite=bool(undo_stack),
                        can_redo_favorite=bool(redo_stack))

    @staticmethod
    def read_saved(c, episode, branch, ident):
        row = c.execute('SELECT * FROM episode_drafts WHERE id=? AND episode=? AND branch=?', (ident, episode, branch)).fetchone()
        if row is None:
            raise ValueError('Draft not found in this episode and branch')
        data = json.loads(row['payload'])
        data.setdefault('origin', 'imported' if data.get('provider') == 'offline-bridge' else 'unknown')
        return dict(data, status=row['status'], favorite=bool(row['favorite']))

    def list(self, episode, branch):
        with self.timeline._connect() as c:
            ep, _ = self.notebook._episode(c, episode)
            if ep['branch'] != branch:
                raise ValueError('Wrong episode branch')
            rows = c.execute('SELECT id FROM episode_drafts WHERE episode=? AND branch=? ORDER BY rowid', (episode, branch)).fetchall()
        return [self.open(episode, branch, row['id']) for row in rows]

    def favorite(self, episode, branch, ident, value=None, *, expected_favorite=None, expected_revision=None):
        if value is not None and type(value) is not bool:
            raise ValueError('Favorite must be true or false')
        if expected_favorite is not None and type(expected_favorite) is not bool:
            raise ValueError('Expected favorite state must be true or false')
        if expected_revision is not None and type(expected_revision) is not int:
            raise ValueError('Expected favorite revision must be an integer')
        with self.timeline._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            ep, _ = self.notebook._episode(c, episode)
            if ep['branch'] != branch:
                raise ValueError('Wrong episode branch')
            row = c.execute(
                'SELECT favorite FROM episode_drafts WHERE id=? AND episode=? AND branch=?',
                (ident, episode, branch),
            ).fetchone()
            if row is None:
                raise ValueError('Draft not found in this episode and branch')
            current_fav = bool(row['favorite'])
            if expected_favorite is not None and current_fav != expected_favorite:
                raise ValueError('Draft favorite state changed; refresh drafts and try again')
            rev, undo_stack, _ = self._favorite_stacks(c, episode, branch)
            if expected_revision is not None and rev != expected_revision:
                raise ValueError('Draft favorite history changed; refresh drafts and try again')
            target_fav = (not current_fav) if value is None else value
            if target_fav != current_fav:
                c.execute(
                    'UPDATE episode_drafts SET favorite=? WHERE id=? AND episode=? AND branch=?',
                    (int(target_fav), ident, episode, branch),
                )
                undo_stack.append({'draft': ident, 'previous': current_fav, 'value': target_fav})
                rev += 1
                c.execute(
                    'INSERT OR REPLACE INTO draft_favorite_history(episode,branch,revision,undo_stack,redo_stack) VALUES(?,?,?,?,?)',
                    (episode, branch, rev, json.dumps(undo_stack), '[]'),
                )
                self.timeline._push_history_locked(c, {
                    'kind': 'draft_favorite', 'episode': episode, 'branch': branch,
                    'draft': ident, 'previous': current_fav, 'value': target_fav,
                })
        return self.open(episode, branch, ident)

    def undo_favorite(self, episode, branch, *, expected_revision=None):
        return self._step_favorite(episode, branch, -1, expected_revision=expected_revision)

    def redo_favorite(self, episode, branch, *, expected_revision=None):
        return self._step_favorite(episode, branch, 1, expected_revision=expected_revision)

    def _apply_history_favorite_in_conn(self, c, item, *, undo):
        return self._step_favorite_in_conn(
            c, item['episode'], item['branch'], -1 if undo else 1,
            expected_draft=item['draft'], sync_timeline_history=False,
        )

    def _step_favorite(self, episode, branch, direction, *, expected_revision=None):
        if expected_revision is not None and type(expected_revision) is not int:
            raise ValueError('Expected favorite revision must be an integer')
        with self.timeline._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            draft_id = self._step_favorite_in_conn(
                c, episode, branch, direction, expected_revision=expected_revision, sync_timeline_history=True
            )
        return self.open(episode, branch, draft_id)

    def _step_favorite_in_conn(self, c, episode, branch, direction, *, expected_revision=None,
                               expected_draft=None, sync_timeline_history=True):
        ep, _ = self.notebook._episode(c, episode)
        if ep['branch'] != branch:
            raise ValueError('Wrong episode branch')
        rev, undo_stack, redo_stack = self._favorite_stacks(c, episode, branch)
        if expected_revision is not None and rev != expected_revision:
            raise ValueError('Draft favorite history changed; refresh drafts and try again')
        if direction < 0:
            if not undo_stack:
                raise ValueError('No favorite change to undo')
            entry = undo_stack.pop()
            expected_cur, target_val = bool(entry['value']), bool(entry['previous'])
            redo_stack.append(entry)
        else:
            if not redo_stack:
                raise ValueError('No favorite change to redo')
            entry = redo_stack.pop()
            expected_cur, target_val = bool(entry['previous']), bool(entry['value'])
            undo_stack.append(entry)
        if expected_draft is not None and entry['draft'] != expected_draft:
            raise ValueError('Draft favorite state changed; refresh drafts and try again')
        row = c.execute(
            'SELECT favorite FROM episode_drafts WHERE id=? AND episode=? AND branch=?',
            (entry['draft'], episode, branch),
        ).fetchone()
        if row is None:
            raise ValueError('Draft not found in this episode and branch')
        if bool(row['favorite']) != expected_cur:
            raise ValueError('Draft favorite state changed; refresh drafts and try again')
        c.execute(
            'UPDATE episode_drafts SET favorite=? WHERE id=? AND episode=? AND branch=?',
            (int(target_val), entry['draft'], episode, branch),
        )
        rev += 1
        c.execute(
            'INSERT OR REPLACE INTO draft_favorite_history(episode,branch,revision,undo_stack,redo_stack) VALUES(?,?,?,?,?)',
            (episode, branch, rev, json.dumps(undo_stack), json.dumps(redo_stack)),
        )
        if sync_timeline_history:
            self.timeline._sync_draft_favorite_step_locked(
                c, episode, branch, entry['draft'], direction, bool(entry['previous']), bool(entry['value'])
            )
        return entry['draft']

    def compare(self, episode, branch, first, second):
        a = self.open(episode, branch, first); b = self.open(episode, branch, second)
        if a['text'] is None or b['text'] is None:
            raise ValueError('Cannot compare incomplete drafts')
        return ''.join(difflib.unified_diff(a['text'].splitlines(keepends=True), b['text'].splitlines(keepends=True), fromfile=first, tofile=second))

    def use(self, episode, branch, ident, notebook_revision, timeline_revision, *,
            source_start=None, source_end=None, candidate_start=None, candidate_end=None, junctions=None, books_root=None, receipt=None):
        """Apply a full or selected candidate to its exact source revision."""
        from .scoped_pipeline import build_packet, validate_output
        draft = self.open(episode, branch, ident)
        if draft['status'] != 'PROPOSED' or draft['text'] is None:
            raise ValueError('Only a completed proposal can be used')
        if draft['source_revision'] != timeline_revision:
            raise ValueError('Draft source revision is stale')
        scope=self.timeline.scope()
        if draft.get('project_id') != scope['project_id'] or draft.get('universe_id') != scope['universe_id']:
            raise ValueError('Draft has an unknown or different project/universe; retain it for migration')
        state = self.notebook.existing(episode)
        if state is None or state['stale'] or state['revision'] != notebook_revision:
            raise ValueError('Open the current notebook before using a draft')
        if draft['notebook_revision'] != notebook_revision:
            raise ValueError('Draft notebook or mask revision is stale')
        if draft.get('composite_segments'):
            if any(x is not None for x in (source_start,source_end,candidate_start,candidate_end)):
                raise ValueError('Partial composite application is ambiguous; use an individual child draft')
            from .scoped_groups import compose, guard, saved_composite_context_matches
            children=[self.open(episode,branch,s['draft_id']) for s in draft['composite_segments']]
            packet,candidate,segments=compose(self.timeline,children,junctions)
            if (candidate != draft['text'] or segments != draft['composite_segments'] or
                    not saved_composite_context_matches(packet, draft['writing_context'])):
                raise ValueError('Composite draft boundaries or child scope changed')
            reference_guard=None
            if draft.get('reference_receipts'):
                from .scoped_references import DEFAULT_BOOKS, verify_draft_binding
                reference_guard=lambda:verify_draft_binding(draft.get('reference_binding'),books_root or DEFAULT_BOOKS)
                reference_guard()
            edits = [(part['source_start'], part['source_end'], candidate[part['candidate_start']:part['candidate_end']])
                     for part in segments]
            return self.notebook.edit_text(episode,notebook_revision,timeline_revision,packet.start,packet.end,candidate,
                guard_token=draft['timeline_token'],reference_guard=reference_guard,
                scope_guard=lambda c:guard(self.timeline,c,packet.composite),receipt=receipt,edits=edits)
        replay = ((draft.get('writing_context') or {}).get('fx06') or {}).get('replay_minds')
        clips = (draft.get('writing_context') or {}).get('clip_context')
        continuation = (draft.get('writing_context') or {}).get('continuation')
        compositor = (draft.get('writing_context') or {}).get('compositor')
        guard_token = draft['timeline_token']
        if continuation and continuation.get('kind') in ('scene-bridge', 'scene-plan'):
            # Bridges revalidate their source, exact fork, parent, replay and join on
            # every apply. Refresh the race guard before that validation so a saved
            # sibling can proceed after an unrelated branch changes.
            with self.timeline._connect() as c:
                c.execute('BEGIN')
                guard_token = timeline_token(c)
        packet = build_packet(self.timeline, episode, draft['beat'], timeline_revision, draft['start'], draft['end'],
                              draft['viewpoint'], junctions, protected_ranges=draft['protected_ranges'],
                              passage_anchor=draft.get('passage_anchor'),replay_binding=replay['binding'] if replay else None,
                              clip_binding=clips['binding'] if clips else None,
                              continuation_binding=continuation['binding'] if continuation else None,
                              compositor_preparation=compositor['preparation'] if compositor else None, books_root=books_root)
        if packet.compositor != compositor:
            raise ValueError('Cook inputs changed; render again from the current saved context.')
        if continuation and 'turns' in continuation and continuation != packet.continuation:
            raise ValueError('Bridge cast or Mind guidance changed since this proposal')
        if continuation and continuation.get('kind') == 'scene-plan' and continuation != packet.continuation:
            raise ValueError('The scene plan changed since this proposal')
        from .scoped_groups import guard, saved_relationships_match
        if not saved_relationships_match(packet, draft.get('writing_context') or {}):
            raise ValueError('Draft relationship guidance is stale')
        if packet.passage_anchor!=draft.get('passage_anchor'):
            raise ValueError('Draft passage anchor changed')
        if packet.mind_support != (draft.get('writing_context') or {}).get('mind_support'):
            raise ValueError('Draft local character rules are stale')
        from .media_overrides import verify_draft
        verify_draft(packet, draft)
        if packet.context is None or draft.get('context') != packet.context.public():
            raise ValueError('Draft project, law, graph or character-form scope has changed')
        if draft.get('character_store_token','none') != packet.character_store_token:
            raise ValueError('Draft character profiles are stale')
        if draft.get('rhythm_token','none') != packet.beat_rhythm.get('token','none'):
            raise ValueError('Draft beat direction is stale')
        reference_guard=None
        if draft.get('reference_receipts'):
            from .scoped_references import DEFAULT_BOOKS, verify_draft_binding
            reference_guard=lambda:verify_draft_binding(draft.get('reference_binding'),books_root or DEFAULT_BOOKS)
            reference_guard()
        if packet.branch != branch or packet.target_sha256 != draft['source_sha256']:
            raise ValueError('Draft source no longer matches')
        if source_start is None and source_end is None and candidate_start is None and candidate_end is None:
            source_start, source_end = 0, len(packet.target)
            candidate_start, candidate_end = 0, len(draft['text'])
        bounds = (source_start, source_end, candidate_start, candidate_end)
        if (any(type(x) is not int for x in bounds) or not 0 <= source_start <= source_end <= len(packet.target)
                or not 0 <= candidate_start <= candidate_end <= len(draft['text'])):
            raise ValueError('Selection is outside the draft or source')
        replacement = draft['text'][candidate_start:candidate_end]
        candidate = packet.target[:source_start] + replacement + packet.target[source_end:]
        issues = validate_output(packet, candidate, source_edit=(source_start, source_end))
        if issues:
            raise ValueError('; '.join(issues))
        planned_blocks = None
        if continuation and continuation.get('kind') == 'scene-plan':
            if bounds != (0, len(packet.target), 0, len(draft['text'])):
                raise ValueError('Apply the complete scene plan to preserve its beat and speaker bindings')
            from .scene_plan import proposal_lines
            planned_blocks = proposal_lines(packet.continuation, replacement)
        return self.notebook.edit_text(episode, notebook_revision, timeline_revision,
            packet.start + source_start, packet.start + source_end, replacement, guard_token=guard_token,
            rhythm_guard=(packet.beat,packet.beat_rhythm.get('token','none')),reference_guard=reference_guard,
            scope_guard=lambda c:guard(self.timeline,c,(packet,)),receipt=receipt,planned_blocks=planned_blocks)
