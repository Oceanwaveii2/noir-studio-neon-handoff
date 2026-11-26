"""Composite draft validation. No child is checked at another child's cutoff."""
from dataclasses import replace

from .scoped_pipeline import build_packet, validate_output


def saved_relationships_match(packet, saved):
    if 'relationships' in saved:
        return saved['relationships'] == list(packet.relationships)
    # Historical drafts predate the projection of built-in spouse facts onto active forms.
    # An authored cue, including a withheld cue, always requires current guidance.
    return all(set(edge) == {'from', 'to', 'kind', 'source'} and edge['kind'] == 'spouse' and
               edge['source'].startswith('foxy-mo2-ontology:kinship:') for edge in packet.relationships)


def saved_composite_context_matches(packet, saved):
    if not isinstance(saved, dict) or not saved_relationships_match(packet, saved):
        return False
    current = packet.public()
    if 'relationships' not in saved:
        current.pop('relationships', None)
    if packet.composite:
        prior_scopes = saved.get('composite_scopes')
        if not isinstance(prior_scopes, list) or len(prior_scopes) != len(packet.composite):
            return False
        if not all(saved_composite_context_matches(child, scope)
                   for child, scope in zip(packet.composite, prior_scopes)):
            return False
        current['composite_scopes'] = prior_scopes
    return current == saved


def packet_for_draft(store, draft, junctions=None):
    packet = build_packet(store, draft['episode'], draft['beat'], draft['source_revision'],
        draft['start'], draft['end'], draft['viewpoint'], junctions,
        project_id=draft['project_id'], universe_id=draft['universe_id'], branch=draft['branch'],
        protected_ranges=draft['protected_ranges'], passage_anchor=draft.get('passage_anchor'))
    if (draft.get('context') != packet.context.public() or
            draft['source_sha256'] != packet.target_sha256 or
            draft['notebook_revision'] != packet.protection_revision or
            draft.get('character_store_token', 'none') != packet.character_store_token or
            draft.get('rhythm_token', 'none') != packet.beat_rhythm.get('token', 'none') or
            draft.get('passage_anchor') != packet.passage_anchor):
        raise ValueError('Draft source, anchor, protection, character or beat direction is stale')
    if not saved_relationships_match(packet, draft.get('writing_context') or {}):
        raise ValueError('Draft relationship guidance is stale')
    from .media_overrides import verify_draft
    verify_draft(packet, draft)
    return packet


def compose(store, children, junctions=None):
    packets = tuple(packet_for_draft(store, child, junctions) for child in children)
    if not packets or len(packets) > 8:
        raise ValueError('Invalid composite child count')
    first = packets[0]
    if any((p.episode, p.branch, p.revision, p.viewpoint) !=
           (first.episode, first.branch, first.revision, first.viewpoint) for p in packets):
        raise ValueError('Composite children have different episode scopes')
    script = store.get_episode(first.episode)['script']
    cursor = first.start; offset = 0; pieces = []; segments = []
    for child, packet in zip(children, packets):
        if packet.start < cursor or child['status'] != 'PROPOSED' or not isinstance(child['text'], str):
            raise ValueError('Composite children overlap or are incomplete')
        separator = script[cursor:packet.start]
        pieces.append(separator); offset += len(separator)
        segments.append({'draft_id': child['id'], 'source_start': packet.start, 'source_end': packet.end,
                         'candidate_start': offset, 'candidate_end': offset + len(child['text']),
                         'separator': separator})
        pieces.append(child['text']); offset += len(child['text']); cursor = packet.end
    target = script[first.start:packets[-1].end]
    from .notebook import digest
    aggregate = replace(first, target=target, target_sha256=digest(target), end=packets[-1].end,
                        protected=tuple(r for p in packets for r in p.protected),
                        protection_ranges=tuple(r for p in packets for r in p.protection_ranges),
                        passage_anchor=None, composite=packets)
    candidate = ''.join(pieces)
    validate(packets, segments, candidate)
    return aggregate, candidate, segments


def validate(packets, segments, candidate):
    if len(packets) != len(segments):
        raise ValueError('Composite scope is incomplete')
    cursor = 0
    for packet, segment in zip(packets, segments):
        start, end = segment['candidate_start'], segment['candidate_end']
        if (segment['source_start'] != packet.start or segment['source_end'] != packet.end or
                not 0 <= cursor <= start <= end <= len(candidate) or
                candidate[cursor:start] != segment['separator']):
            raise ValueError('Composite boundaries or fixed separators changed')
        problems = validate_output(packet, candidate[start:end])
        if problems:
            raise ValueError('; '.join(problems))
        cursor = end
    if cursor != len(candidate):
        raise ValueError('Composite has unscoped trailing text')


def guard(store, c, packets):
    """Called inside the same BEGIN IMMEDIATE transaction as the edit/draft save."""
    from story_graph.beat_anchors import check
    from story_graph.beat_rhythm import read
    from .media_overrides import guard as guard_media
    for packet in packets:
        guard_media(store, c, packet)
        if getattr(packet, 'compositor', None):
            from .cook import guard_render_context
            guard_render_context(store, c, packet)
        if getattr(packet,'continuation',None):
            from .branch_continuations import guard as guard_continuation
            guard_continuation(store,c,packet)
        if getattr(packet,'fx06',None) and packet.fx06.get('replay_minds'):
            from .replay_minds import guard as guard_replay
            guard_replay(store,c,packet)
        if getattr(packet,'clip_context',None):
            from .scene_clips import guard as guard_clips
            guard_clips(store,c,packet)
        if getattr(packet,'fx06',None) and packet.fx06['active_cast']:
            from .scene_mind_support import guard as guard_mind_rules
            guard_mind_rules(c,packet)
        if read(c, packet.episode, packet.beat)['token'] != packet.beat_rhythm.get('token', 'none'):
            raise ValueError('Beat direction changed; draft must be checked again')
        current = check(store, c, packet.episode, packet.revision, packet.start, packet.end,
                        packet.beat, packet.viewpoint, packet.passage_anchor)
        if current != packet.passage_anchor:
            raise ValueError('Passage anchor changed; draft must be checked again')
