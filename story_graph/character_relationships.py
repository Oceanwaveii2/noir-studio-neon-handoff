"""Project the existing spouse relationship onto the forms active at a writing beat."""
from functools import lru_cache

from .ontology import OntologyGraph, RelationshipType
from .typed_laws import validate_world_claim
from .universe_scope import checked_id
from .world_laws import check_laws


@lru_cache(maxsize=1)
def _spouse_pairs():
    return tuple((edge.subject_id, edge.target_id)
                 for edge in OntologyGraph.create_canonical_foxy_mo2().kinship_relations
                 if edge.relation_type == RelationshipType.MARRIED_LESBIAN_COUPLE)


def override_records(value):
    """Validate author cues saved on a form port. Their scope is exact."""
    if not isinstance(value, list) or len(value) > 32:
        raise ValueError('Relationship overrides need a list of at most 32 cues')
    result = []
    seen = set()
    for cue in value:
        if not isinstance(cue, dict) or set(cue) != {'target', 'episode', 'branch', 'beat', 'guidance'}:
            raise ValueError('Each relationship cue needs a target, episode, branch, beat and guidance')
        target, episode, branch = (checked_id(cue[key], key.title()) for key in ('target', 'episode', 'branch'))
        beat = cue['beat']
        if type(beat) is not int or beat < 0:
            checked_id(beat, 'Replay or bridge beat')
        guidance = cue['guidance']
        if (not isinstance(guidance, str) or not 1 <= len(guidance.strip()) <= 300
                or '\n' in guidance or '\r' in guidance):
            raise ValueError('Relationship guidance needs one line of at most 300 characters')
        key = (target, episode, branch, beat)
        if key in seen:
            raise ValueError('One relationship cue can own each target and beat on a form')
        seen.add(key)
        result.append({**cue, 'guidance': guidance.strip()})
    return tuple(result)


def project(active_forms, junctions, *, kind, episode, branch, beat, laws=(), hidden=()):
    withheld = [phrase.strip().casefold() for phrase in hidden if isinstance(phrase, str) and len(phrase.strip()) >= 8]
    # Include inactive forms from the graph even on replay turns, which do not
    # have the ordinary writer's hidden-information list.
    for character in active_forms:
        group = junctions.get(character)
        if group:
            withheld.extend(form.label.casefold() for form in group.forms
                            if form.kind != 'base' and form.id not in active_forms[character] and len(form.label) >= 8)
    result = []
    for subject in active_forms:
        group = junctions.get(subject)
        for edge in group.relationship_edges if group else ():
            sender, receiver = edge['from'], edge['to']
            cue = edge['bridging_direction']
            if edge.get('retired') or (edge['episode'], edge['branch']) != (episode, branch):
                continue
            if sender['form'] not in active_forms[subject] or receiver['form'] not in active_forms.get(receiver['character'], ()):
                continue
            if check_laws(cue, laws) or any(value in cue.casefold() for value in withheld):
                continue
            result.append(edge)
    for subject, target in _spouse_pairs() if kind == 'afm-starters' else ():
        if not active_forms.get(subject) or not active_forms.get(target):
            continue
        source = 'foxy-mo2-ontology:kinship:' + subject + ':' + target
        claim = {'kind': 'world_fact', 'subject': subject, 'predicate': 'spouse',
                 'value': target, 'assertion': 'fact', 'source_id': source}
        if any(finding['status'] == 'conflict' for finding in validate_world_claim(claim, laws, 0)):
            continue
        group = junctions.get(subject)
        for form in active_forms[subject]:
            cues = group.relationship_overrides.get(form, ()) if group else ()
            cue = next((item for item in cues if (item['target'], item['episode'], item['branch'], item['beat'])
                        == (target, episode, branch, beat)), None)
            cue_blocked = cue and (check_laws(cue['guidance'], laws)
                                   or any(value in cue['guidance'].casefold() for value in withheld))
            for target_form in active_forms[target]:
                edge = {'from': {'character': subject, 'form': form},
                        'to': {'character': target, 'form': target_form}, 'kind': 'spouse', 'source': source}
                if cue_blocked:
                    edge['withheld_override'] = {'port': f'{group.id}:form:{form}', 'reason': 'law-or-beat-scope'}
                elif cue:
                    edge['override'] = {**cue, 'port': f'{group.id}:form:{form}'}
                result.append(edge)
    return tuple(result)


def form_name(endpoint, labels):
    character, form = endpoint['character'], endpoint['form']
    return labels.get(form, character.capitalize() if character == form else form)


def writer_context(edges, labels, *, include_overrides=True):
    spouses = [edge for edge in edges if edge['kind'] == 'spouse']
    if not spouses:
        return ''
    lines = ['\nDIRECTED SPOUSE RELATIONSHIPS (when both forms are present):',
             'Each listed form carries the relationship of its shared character identity.']
    for edge in spouses:
        subject = form_name(edge['from'], labels)
        target = form_name(edge['to'], labels)
        lines.append(f'- {subject} → {target} carries the {edge["from"]["character"]}–{edge["to"]["character"]} spouse relationship.')
        if include_overrides and 'override' in edge:
            lines.append(override_line(edge, labels))
    return '\n'.join(lines) + '\n'


def override_line(edge, labels):
    subject = form_name(edge['from'], labels)
    target = form_name(edge['to'], labels)
    return f'Local direction for this beat only ({subject} → {target}): {edge["override"]["guidance"]}'
