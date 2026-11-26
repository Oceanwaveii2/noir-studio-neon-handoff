"""An episode-scoped timing library and typed rules on the three existing Rainee Minds."""
from __future__ import annotations

import re

from story_graph import fx06_scene, scene_fragments as f
from story_graph.scene_override import _unpack


LIBRARY = 'fx06-fart-media'
KIND = 'performance-timing'
ADMITTED = {'direct_emitter','dialogue_report'}
CATEGORIES = ADMITTED | {'emitter_candidate','device_reference'}


def read(c,scope):
    row = (c.execute('SELECT * FROM scene_mind_support WHERE episode=?',(scope['episode'],)).fetchone()
           if f._has(c,'scene_mind_support') else None)
    if row and (body:=_unpack(row))['scope']==scope:
        return body | {'sha256':row['sha256']}
    return None


def install(store,request,recipe,media):
    """Pin an authored package to the actual Mind IDs and verified local clip receipts."""
    from .replay_minds import _basis, _registered
    with store._connect() as c:
        c.execute('BEGIN IMMEDIATE')
        scope,head=f.SceneFragmentStore._scope(c,request)
        comparison,_=_registered(c,scope)
        verified,_=_basis(store,c,scope,head,comparison['basis']['replay'])
        if verified!=comparison['basis']:
            raise ValueError('The active Mind links no longer match the saved split replay')
        return save_library(c, store, scope, recipe, media, verified['cast'])


def save_library(c, store, scope, recipe, media, verified_cast):
    """Save the scoped library against Mind links already checked by the caller."""
    from .scene_clips import _get, _asset_path
    f._object(recipe,('schema_version','rules'))
    if recipe['schema_version']!=1 or not isinstance(recipe['rules'],list):
        raise ValueError('Choose a version 1 character-rule package')
    cast = {actor['form_id']: actor for actor in verified_cast}
    rules = {}
    for rule in recipe['rules']:
        f._object(rule,('form','trigger','scent','perfume','source_url'))
        form, trigger = rule['form'], rule['trigger']
        if form not in cast or form in rules or trigger!='personal_gas_release':
            raise ValueError('Each signature must target one of the three original Minds')
        scent = f._label(rule['scent'],40).strip()
        perfume = f._label(rule['perfume'],95).strip()
        if not re.fullmatch(r'[a-z]+(?: [a-z]+){0,2}',scent) or not f._label(rule['source_url'],512).startswith('https://'):
            raise ValueError('Use a short scent cue and a reference URL')
        rules[form] = rule | {'scent':scent,'perfume':perfume,'mind':cast[form]['node_id'],
                              'speaker':cast[form]['speaker']}
    if set(rules)!=set(cast) or len({rule['scent'] for rule in rules.values()})!=3:
        raise ValueError('Provide one distinct scent for each Mind')
    if not isinstance(media,list) or not 1<=len(media)<=30:
        raise ValueError('Choose the bounded timing library')
    items = []
    seen = set()
    for item in media:
        f._object(item,('clip','source','title','category','content_sha256','source_range_ms','note'))
        asset = _get(c,'scene_clip_assets',scope,item['clip'])
        _asset_path(store,asset)
        bounds = item['source_range_ms']
        if (item['category'] not in CATEGORIES or item['source'] in seen
                or f._sha(item['content_sha256'])!=asset['content_sha256']
                or not isinstance(bounds,list) or len(bounds)!=2
                or any(type(value) is not int for value in bounds) or not 0<=bounds[0]<bounds[1]):
            raise ValueError('The timing clip does not match its source record')
        f._label(item['source'],120)
        f._label(item['title'],160)
        f._label(item['note'],380)
        seen.add(item['source'])
        items.append(item | {'writing_eligible':item['category'] in ADMITTED})
    body = {'schema_version':1,'scope':scope,'activation':'rainee-split-active',
            'library':{'id':LIBRARY,'title':'Fart Media','kind':KIND,'items':items},
            'links':[{'mind':a['node_id'],'form':a['form_id'],'to':LIBRARY,'use':KIND} for a in cast.values()],
            'rules':[rules[form] for form in cast]}
    raw = f.encoded(body)
    c.execute('''CREATE TABLE IF NOT EXISTS scene_mind_support (
        episode TEXT PRIMARY KEY REFERENCES episodes(id), payload TEXT NOT NULL, sha256 TEXT NOT NULL)''')
    previous = c.execute('SELECT * FROM scene_mind_support WHERE episode=?',(scope['episode'],)).fetchone()
    if previous and _unpack(previous)!=body:
        raise ValueError('A different Mind package is already saved in this copy')
    if not previous:
        c.execute('INSERT INTO scene_mind_support VALUES(?,?,?)',(scope['episode'],raw,f.digest(raw)))
    return body | {'sha256':f.digest(raw)}


def allowed_use(c,scope,clip,purpose):
    """Mark the indexed show examples as timing or audition only."""
    body=read(c,scope)
    if not body:
        return True
    items=[item for item in body['library']['items'] if item['clip']==clip]
    return not items or (purpose=='timing' and any(i['writing_eligible'] for i in items))


def project(c,scope,root_form,cast):
    """Previewing a board never changes the set of Minds active at the beat."""
    if root_form!='split' or not cast:
        return None
    body=read(c,scope)
    if body is None:
        return None
    active={(actor['form_id'],actor['node_id']) for actor in cast}
    rules=[r for r in body['rules'] if (r['form'],r['mind']) in active]
    if not rules:
        return None
    return {'package_sha256':body['sha256'],'rules':rules}


def writer_context(context,exercise=False):
    if not context:
        return ''
    cues={rule['speaker']:rule['scent'] for rule in context['rules']}
    direction=('For this explicit signature test, give each actor a brief personal gas release in their own Action line. '
               'Write their assigned cue word or phrase in that line. You may put the sound and the cue in one short observation. '
               if exercise else 'If an active actor personally passes gas, use that actor’s assigned scent in their action. '
               'Do not make an actor pass gas just to mention the scent. ')
    return ('\nLOCAL CHARACTER RULES (active forms only; world laws and frozen text take priority):\n'
            'These are their individual scents on a new release, not the pre-existing floral smell and not perfume bottles. '
            'Scent cues by speaker: '+f.encoded(cues)+'. '+direction+
            'Keep each release distinct. Do not name brands or give these scents to an inactive form.\nEND LOCAL CHARACTER RULES\n')


_RELEASE=re.compile(r'\b(?:fart(?:s|ed|ing)?|pfft+|toot(?:s|ed)?|(?:pass(?:es|ed)?|releases?|lets? out) gas)\b',re.I)
_SCENT_SOUND=r'\b(?:a|one) (?:(?:quick|little|soft|brief|small) )?(?:squeak|puff) (?:brings|carries|releases) (?:a hint of )?'


def validate_output(context,text,*,exercise=False):
    """Check explicit cues in FX06's defined action lines, not arbitrary semantic paraphrases."""
    if not context or fx06_scene.validate_turns(text):
        return []
    lines=[line.strip().casefold() for line in text.splitlines() if line.strip()]
    by_speaker={r['speaker']:r for r in context['rules']}
    issues=[]
    for i,speaker in enumerate(fx06_scene.SPEAKERS):
        rule=by_speaker.get(speaker)
        if rule is None:
            continue
        action=lines[2*i+1]
        cue=re.escape(rule['scent'])
        # An indirect sound alone is ambiguous. In the explicit assay accept it
        # only when it directly produces the selected signature in that action.
        release=_RELEASE.search(action) or (exercise and re.search(_SCENT_SOUND+cue+r'(?!\w)',action))
        if not exercise and not _RELEASE.search(action):
            continue
        def cue_present(value):
            return re.search(r'(?<!\w)'+re.escape(value)+r'(?!\w)',action)
        if ((exercise and not release) or not cue_present(rule['scent']) or
                any(cue_present(r['scent']) for r in context['rules'] if r!=rule)):
            issues.append(f'{speaker} must use their own {rule["scent"]} scent on a personal release')
    return issues


def guard(c,packet):
    context=packet.context
    scope={'project':context.project_id,'universe':context.universe_id,'scope_revision':context.scope_revision,
           'episode':packet.episode,'branch':packet.branch}
    now=project(c,scope,packet.fx06['root_form'],packet.fx06['active_cast'])
    if now!=packet.mind_support:
        raise ValueError('The local character rules changed; rebuild this draft')
