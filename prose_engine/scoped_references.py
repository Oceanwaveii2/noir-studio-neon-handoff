"""Policy-bound book references for one already compiled narrative packet."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import random
import re
from statistics import median
from contextlib import nullcontext
import numpy as np

from .reference_policy import ReferencePolicy, prompt_purposes
from .reference_service import _READERS, prepare_retrieval

DEFAULT_BOOKS = Path(__file__).resolve().parents[1] / 'books'
INDEXES = {'topic':'vector_index.joblib','luar':'luar_index.joblib','style':'style_index.joblib'}
HYBRID_BACKENDS = ('style', 'luar', 'topic')
VALID_BACKENDS = (*INDEXES.keys(), 'hybrid')
FUNCTIONS = {'scene':'', 'beauty':'beauty preparation sensory detail anticipation', 'comedy':'comedic timing surprise punchline',
             'tension':'tension suspense anticipation', 'dialogue':'dialogue conversation voice',
             'quiet':'quiet reflective pause', 'transformation':'change physical transformation pacing'}


class ReferenceUnavailable(ValueError):
    def __init__(self,state,message):
        super().__init__(message);self.state=state


_BOILERPLATE_LINE_RE = re.compile(
    r'(?im)^.*(?:'
    r'copyright\s*(?:©|\(c\)|\d{4})|©\s*\d{4}|all\s+rights\s+reserved|'
    r'an\s+imprint\s+of|published\s+by|about\s+the\s+publisher|'
    r'penguin\s+random\s+house|harpercollins|simon\s*&\s*schuster|hachette|macmillan|'
    r'riverhead\s+books|bantam\s+books|vintage\s+books|knopf|'
    r'\bisbn\b|library\s+of\s+congress|printed\s+in\s+the|project\s+gutenberg|'
    r'penguinrandomhouse\.com|other\s+books\s+by\b|credits\s+copyright|'
    r'without\s+limiting\s+the\s+rights\s+under\s+copyright'
    r').*$'
)
_INLINE_COPYRIGHT_RE = re.compile(
    r'(?i)(?:copyright\s*(?:©|\(c\))?\s*\d{4}[^.\n]*\.?|all\s+rights\s+reserved\.?|'
    r'an\s+imprint\s+of\s+[^.\n]*\.?|isbn[\s:-]*[\dxX-]+)'
)


def sanitize_reference_excerpt(text: str) -> str:
    """Strip publisher, imprint, ISBN, Gutenberg, and copyright notices from a craft excerpt."""
    if not isinstance(text, str) or not text:
        return ''
    cleaned_lines = [line for line in text.splitlines() if not _BOILERPLATE_LINE_RE.match(line.strip())]
    cleaned = '\n'.join(cleaned_lines)
    cleaned = _INLINE_COPYRIGHT_RE.sub('', cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
    return cleaned


def _load_obscured_titles(root: Path) -> dict:
    path = root / 'obscured_titles.json'
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        books = data.get('books') if isinstance(data, dict) else None
        return books if isinstance(books, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


OBSCURED_GENRE_SPECS = {
    'curvy_glam_romance': {
        'adjs': ('Silk', 'Velvet', 'Crimson', 'Champagne', 'Satin', 'Amber', 'Blush', 'Honeyed', 'Gilded', 'Rosewater'),
        'nouns': ('Vanity', 'Penthouse', 'Stocking', 'Boudoir', 'Mirror', 'Terrace', 'Lounge', 'Slipper', 'Perfume', 'Suite'),
        'tails': ('Confessions', 'Diary', 'Encounters', 'Desires', 'Curves', 'Whispers'),
        'tags': ['thicc_curvy_descriptors', 'sensory_body_detail', 'glam_confidence'],
        'use': 'High-density curvy/voluptuous body descriptors, warm physical confidence, and shameless sensory texture.',
    },
    'femme_lesbian_heat': {
        'adjs': ('Scarlet', 'Midnight', 'Lace', 'Pearl', 'Sultry', 'Dusk', 'Violet', 'Orchid', 'Plum', 'Ruby'),
        'nouns': ('Cabaret', 'Locket', 'Curtain', 'Lipstick', 'Parlor', 'Balcony', 'Velvet', 'Ribbon', 'Boulevard', 'Suite'),
        'tails': ('Nocturne', 'Rendezvous', 'Affair', 'Letters', 'Temptation', 'Banter'),
        'tags': ['femme_lesbian_heat', 'banter_chemistry', 'physical_posture'],
        'use': 'Femme-on-femme chemistry, sharp banter, physical posture, and tactile erotic heat without dryness.',
    },
    'bizarro_body_comedy': {
        'adjs': ('Feral', 'Mutant', 'Swollen', 'Rubber', 'Bloated', 'Twisted', 'Greasy', 'Sprawling', 'Warped', 'Bizarre'),
        'nouns': ('Treadmill', 'Meatloaf', 'Balloon', 'Basement', 'Vending', 'Blister', 'Sofa', 'Wasteland', 'Bumper', 'Spatula'),
        'tails': ('Mutations', 'Fiasco', 'Overdrive', 'Chronicles', 'Anomaly', 'Carnival'),
        'tags': ['body_transformation', 'absurd_physicality', 'three_beat_scale'],
        'use': 'Flat pulp prose for grotesque body transformations, sudden swelling/morphing mechanics, and deadpan chaos.',
    },
    'fart_gross_out_satire': {
        'adjs': ('Gassy', 'Rumbling', 'Noxious', 'Thunderous', 'Sputtering', 'Colossal', 'Juicy', 'Violent', 'Foul', 'Putrid'),
        'nouns': ('Valve', 'Commode', 'Belly', 'Trousers', 'Breech', 'Codpiece', 'Cushion', 'Bathroom', 'Toilet', 'Bladder'),
        'tails': ('Blast', 'Treatise', 'Tantrums', 'Disasters', 'Symphony', 'Shenanigans'),
        'tags': ['fart_gross_out', 'giant_scale_satire', 'visceral_comedy'],
        'use': 'Sustained flatulence gags, visceral gross-out physicality, and scaling body-function absurdity.',
    },
    'slapstick_farce': {
        'adjs': ('Wobbly', 'Pompous', 'Bumbling', 'Snappy', 'Fizzy', 'Tangled', 'Rowdy', 'Tippled', 'Clumsy', 'Zany'),
        'nouns': ('Banister', 'Monocle', 'Chandelier', 'Teacup', 'Bungalow', 'Umbrella', 'Divan', 'Cocktail', 'Suitcase', 'Foyer'),
        'tails': ('Capers', 'Alibis', 'Blunders', 'Racket', 'Follies', 'Farce', 'Escapades'),
        'tags': ['slapstick_timing', 'comedic_escalation', 'verbal_snap'],
        'use': 'Crisp comedic timing, escalating farce beats, snappy dialogue rebounds, and physical pratfall pacing.',
    },
    'dork_label_humiliation': {
        'adjs': ('Nasal', 'Awkward', 'Braced', 'Checkered', 'Mortified', 'Stammering', 'Sweaty', 'Clueless', 'Flustered', 'Geeky'),
        'nouns': ('Locker', 'Hallway', 'Cafeteria', 'Diary', 'Backpack', 'Glasses', 'Homeroom', 'Bleachers', 'Yearbook', 'Sweater'),
        'tails': ('Demotion', 'Confessions', 'Dossier', 'Meltdown', 'Notes', 'Survival'),
        'tags': ['dork_nerdification_voice', 'label_humiliation_gag', 'queen_bee_banter'],
        'use': 'Label-humiliation timing (name -> mirror -> reaction), dork voice tics, and catty clique hierarchy banter.',
    },
    'marilyn_blonde_voice': {
        'adjs': ('Breathy', 'Giggling', 'Platinum', 'Breezy', 'Dizzy', 'Sugar', 'Dreamy', 'Sparkling', 'Bubbly', 'Glossy'),
        'nouns': ('Diamond', 'Powder-Room', 'Spotlight', 'Vanity', 'Dressing-Room', 'Champagne', 'Puff', 'Robe', 'Stage', 'Cushion'),
        'tails': ('Ellipses', 'Whispers', 'Monologues', 'Interviews', 'Chatter', 'Daydreams'),
        'tags': ['marilyn_blonde_voice', 'breathy_ellipses_cadence', 'sharp_drop_beat'],
        'use': 'Breathy dumb-blonde dialogue cadence with ellipses, dashes, self-interruptions, and a sudden sharp beat.',
    },
    'stripper_mismatch_arc': {
        'adjs': ('Neon', 'Rhinestone', 'Backstage', 'Tinsel', 'Glitter', 'Velvet', 'Satin', 'Dizzy', 'Spotlight', 'Brass'),
        'nouns': ('Catwalk', 'Rail', 'Dressing-Room', 'G-String', 'Club', 'Tip-Jar', 'Spotlight', 'Curtain', 'Heel', 'Booth'),
        'tails': ('Shift', 'Memoir', 'Hustle', 'Routine', 'Confessions', 'Revue'),
        'tags': ['stripper_mismatch_arc', 'costume_crowd_reaction', 'stage_vocabulary'],
        'use': 'Costume-wrong -> mirror -> walk -> crowd reaction beats using club/stage vocabulary and body-vs-mouth mismatch.',
    },
    'noir_mystery_pulp': {
        'adjs': ('Rain-Slicked', 'Smoky', 'Hollow', 'Broken', 'Cold', 'Gritty', 'Crooked', 'Shadowed', 'Ashen', 'Shattered'),
        'nouns': ('Ledger', 'Precinct', 'Sidewalk', 'Ashtray', 'Motel', 'Switchblade', 'Payphone', 'Overcoat', 'Diner', 'Lobby'),
        'tails': ('Files', 'Alibi', 'Blues', 'Testimony', 'Nightshift', 'Reckoning'),
        'tags': ['noir_mystery_pulp', 'punchy_staging', 'hardboiled_contrast'],
        'use': 'Punchy, concrete physical staging and hardboiled contrast to ground wild comedy.',
    },
    'scifi_litrpg_chaos': {
        'adjs': ('Orbital', 'Chrome', 'Static', 'Quantum', 'Synthetic', 'Zero-G', 'Cobalt', 'Vapor', 'Lunar', 'Pixel'),
        'nouns': ('Relay', 'Reactor', 'Signal', 'Horizon', 'Capsule', 'Telemetry', 'Grid', 'Beacon', 'Conduit', 'Circuit'),
        'tails': ('Protocol', 'Logbook', 'Transmission', 'Drift', 'Anomaly', 'Sequence'),
        'tags': ['scifi_litrpg_chaos', 'gadget_ray_escalation', 'system_banter'],
        'use': 'Fast gadget/system escalation, absurd rule-bending, and kinetic action-comedy banter.',
    },
    'literary_satire_classic': {
        'adjs': ('Autumn', 'Glass', 'Gilded', 'Paper', 'Silver', 'Iron', 'Borrowed', 'Narrow', 'Amber', 'Winding'),
        'nouns': ('Notebook', 'Window', 'Staircase', 'Harbor', 'Garden', 'Postcard', 'Kitchen', 'Hallway', 'Porch', 'Bridge'),
        'tails': ('Sketches', 'Satire', 'Portraits', 'Pages', 'Fragments', 'Chronicles'),
        'tags': ['literary_satire_classic', 'sentence_rhythm', 'observational_irony'],
        'use': 'Varied sentence rhythm, crisp observational irony, and character-driven satirical voice.',
    },
}


def classify_book_genre(slug: str, title: str = '', text_sample: str = '') -> str:
    """Classify an ingested book into a craft/prose-usefulness genre bucket."""
    s = f'{slug} {title} {text_sample[:600]}'.lower()
    if any(k in s for k in ('gentlemen_prefer', 'gentlemenprefer', 'marry_brunettes', 'bus_stop', 'marilyn', 'valley_of_the_dolls', 'hollywood_wives', 'sex_and_the_single_girl', 'love_machine', 'divorced_women', 'lorelei')):
        return 'marilyn_blonde_voice'
    if any(k in s for k in ('stripper', 'gypsy_memoirs', 'g_string', 'g-string', 'burlesque')):
        return 'stripper_mismatch_arc'
    if any(k in s for k in ('duff', 'geek_girl', 'how_to_be_popular', 'dork_diaries', 'wimpy_kid', 'queen_bee')):
        return 'dork_label_humiliation'
    if any(k in s for k in ('fart', 'gargantua', 'tristram_shandy', 'captain_underpants', 'day_my_bum', 'gulp_adventures', 'filth_', 'dreamcatcher_', 'choke_', 'dunces')):
        return 'fart_gross_out_satire'
    if any(k in s for k in ('exercise_bike', 'haunted_vagina', 'warrior_wolf', 'thinner', 'big_girl', 'milk_fed', 'lapvona', 'metamorphosis', 'alices_adventures', 'gulliver', 'charlie_and_the_chocolate', 'maskerade', 'third_policeman', 'jekyll', 'frankenstein', 'dracula', 'island_of_doctor_moreau', 'invisible_man', 'apeshit', 'lust_lizard')):
        return 'bizarro_body_comedy'
    if any(k in s for k in ('lesbian', 'fingersmith', 'curious_wine', 'hood', 'written_on_the_body', 'kiss_the_girl', 'well_of_loneliness', 'venus_in_furs')):
        return 'femme_lesbian_heat'
    if any(k in s for k in ('curvy', 'fix_her_up', 'chloe_brown', 'scorpion_s_sweet_venom', 'obscene_madame_d', 'letters_from_a_seducer', 'with_my_dog_eyes', 'fanny_hill', 'fantastic_orgy', 'erotic', 'kama_sutra', 'perfumed_garden', 'casanova', 'romance_of_lust', 'sheik', 'three_weeks', 'luster', 'lyrics_dance_pop', 'iracema', 'his_paradise')):
        return 'curvy_glam_romance'
    if any(k in s for k in ('wodehouse', 'twain', 'jeeves', 'fool', 'monty_python', 'aristophanes', 'moliere', 'importance_of_being_earnest', 'frenzied_fiction', 'three_men', 'diary_of_a_nobody', 'winsome_winnie', 'damsel', 'pickwick', 'candide', 'smollett', 'don_quixote', 'boccaccio', 'satyricon', 'droll_stories', 'me_talk_pretty', 'wow_no_thank_you', 'never_meeting_in_real_life')):
        return 'slapstick_farce'
    if any(k in s for k in ('futuristic_violence', 'dungeon_crawler_carl', 'made_for_love', 'breakfast_of_champions')):
        return 'scifi_litrpg_chaos'
    if any(k in s for k in ('scarlet', 'hound_of_the_baskervilles', 'sign_of_the_four', 'moonstone', 'murders_in_the_rue_morgue', 'armadillo_fists', 'stabbed_me_gently', 'war_slut', 'barbarian_beast')):
        return 'noir_mystery_pulp'
    return 'literary_satire_classic'


def sync_obscured_titles(books_dir: Path, entries: list[dict]) -> dict:
    """Ensure every book entry has a unique genre-matched obscured title and prose-usefulness record."""
    root = Path(books_dir)
    path = root / 'obscured_titles.json'
    existing = _load_obscured_titles(root)
    used_titles = {v.get('obscured_title') for v in existing.values() if isinstance(v, dict) and v.get('obscured_title')}
    used_aliases = {v.get('alias_id') for v in existing.values() if isinstance(v, dict) and v.get('alias_id')}
    type_counts: dict[str, int] = {}
    for v in existing.values():
        if isinstance(v, dict) and v.get('book_type'):
            bt = v['book_type']
            type_counts[bt] = type_counts.get(bt, 0) + 1

    mapping = dict(existing)
    added = 0
    for entry in entries:
        slug = entry.get('slug')
        if not slug or slug in mapping:
            continue
        btype = classify_book_genre(slug, entry.get('title', ''), entry.get('text_sample', ''))
        spec = OBSCURED_GENRE_SPECS[btype]
        seed = int(hashlib.sha256(slug.encode('utf-8')).hexdigest()[:8], 16)
        rng = random.Random(seed)
        title = ''
        for _ in range(500):
            cand = f"{rng.choice(spec['adjs'])} {rng.choice(spec['nouns'])} {rng.choice(spec['tails'])}"
            if cand not in used_titles:
                title = cand
                break
        if not title:
            title = f"{rng.choice(spec['adjs'])} {rng.choice(spec['nouns'])} #{len(mapping) + 1:03d}"
        used_titles.add(title)
        seq = type_counts.get(btype, 0) + 1
        while f'folio_{btype}_{seq:03d}' in used_aliases:
            seq += 1
        type_counts[btype] = seq
        alias_id = f'folio_{btype}_{seq:03d}'
        used_aliases.add(alias_id)
        mapping[slug] = {
            'alias_id': alias_id,
            'obscured_title': title,
            'book_type': btype,
            'craft_tags': list(spec['tags']),
            'prose_usefulness': spec['use'],
        }
        added += 1

    if added or not path.is_file():
        payload = {
            'schema_version': 2,
            'purpose': 'Genre-matched obscured titles, opaque IDs, and prose-usefulness craft index for LLM prompt delivery; keeps books/manifest.json hashes intact.',
            'count': len(mapping),
            'books': mapping,
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
    return {'added': added, 'total': len(mapping), 'path': str(path)}


def _sha(path):
    if not path.is_file(): return 'missing'
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def fingerprint(root,backend):
    if backend == 'hybrid':
        return {'hybrid': {b: fingerprint(root, b) for b in HYBRID_BACKENDS}}
    from .library_indexes import index_path, catalog, encoder_binding
    root=Path(root).resolve()
    return {'policy':_sha(root/'reference_policy.json'),'influence':_sha(root/'influence.json'),
            'quality':_sha(root/'library_quality.json'),
            'index':_sha(index_path(root,backend)), 'catalog':catalog(root)['fingerprint'],
            'release':_sha(root/'library_active.json'), 'encoder':encoder_binding(root,backend),
            'style_model':_sha(index_path(root,backend).parent/'styleprint.json') if backend=='style' else 'not-used'}


def _exclude_known_hidden(drive, hidden):
    """Remove known hidden story phrases from the eligible index before ranking."""
    phrases=tuple(x.strip().casefold() for x in hidden if isinstance(x,str) and len(x.strip())>=8)
    if not phrases: return drive
    index=drive.index
    blocked=re.compile('|'.join(map(re.escape,dict.fromkeys(phrases))))
    keep=[i for i,text in enumerate(index.texts) if not blocked.search(text.casefold())]
    if not keep: return None
    selected=copy.copy(index)
    selected.texts=[index.texts[i] for i in keep]
    selected.meta=[index.meta[i] for i in keep]
    selected.vectors=np.asarray(index.vectors)[keep]
    bound=copy.copy(drive);bound.index=selected
    return bound


def select_references(packet, *, root=DEFAULT_BOOKS, backend='topic', provider, scene_function='scene'):
    if packet.context is None: raise ValueError('A scoped episode is required before book retrieval')
    if scene_function not in FUNCTIONS:
        scene_function = 'scene'
    if backend == 'hybrid':
        return _select_hybrid_references(packet, root=root, provider=provider, scene_function=scene_function)
    if backend not in INDEXES:
        raise ValueError('Invalid book source')
    root=Path(root).expanduser().resolve()
    try:
        if ReferencePolicy.load(root).status=='unconfigured':
            raise ReferenceUnavailable('unconfigured','Configure book source permissions or choose no books.')
        before = fingerprint(root, backend)
    except ReferenceUnavailable:
        raise
    except (OSError, ValueError, KeyError) as exc:
        raise ReferenceUnavailable('unavailable',str(exc)) from exc
    setup=prepare_retrieval(root,backend,provider,verified_basis=before)
    if setup.state!='ready': raise ReferenceUnavailable(setup.state,setup.message)
    if fingerprint(root,backend)!=before: raise ReferenceUnavailable('stale','Book settings or index changed during retrieval setup.')
    query = packet.target + '\n' + FUNCTIONS[scene_function]
    if packet.continuation and packet.continuation['kind'] == 'scene-bridge':
        # The bridge slot is a placeholder. Rank by the stage directions it will contain.
        stages = [frame['stage'] for frame in packet.continuation['program']['frames']]
        query = '\n'.join([FUNCTIONS[scene_function], *stages])
    elif packet.continuation and packet.continuation['kind'] == 'scene-plan':
        stages = [turn['stage'] for turn in packet.continuation['plan']['turns'] if turn['stage']]
        query = '\n'.join([FUNCTIONS[scene_function], *stages])
    pool=_READERS.get()
    try:
        with pool._lock if pool else nullcontext():
            drive=_exclude_known_hidden(setup.drive,packet.hidden_phrases)
            if drive is None: raise ReferenceUnavailable('no_eligible','No references remain after the story-scope check.')
            hits=drive.retrieve_passages('scoped',query,scene_type=scene_function,max_results=6,influence=setup.influence)
    except ReferenceUnavailable:
        raise
    except Exception as exc:
        raise ReferenceUnavailable('unavailable',f'Book retrieval failed ({type(exc).__name__}): {exc}') from exc
    if fingerprint(root,backend)!=before: raise ReferenceUnavailable('stale','Book settings or index changed during retrieval.')
    if not hits: raise ReferenceUnavailable('no_eligible','No eligible passages matched this selection.')
    manifest=root/'manifest.json'
    titles={entry['slug']:entry for entry in json.loads(manifest.read_text(encoding='utf-8')).get('books',[])} if manifest.is_file() else {}
    obscured=_load_obscured_titles(root)
    receipts=[];texts=[];purposes=list(prompt_purposes(provider))
    for rank,hit in enumerate(hits[:6],1):
        text=sanitize_reference_excerpt(hit.text[:1800])
        if not text.strip(): continue
        prov=hit.provenance
        if not isinstance(prov,dict) or not prov.get('source_id') or not hit.passage_id:
            raise ReferenceUnavailable('unavailable','A retrieved passage lacks source identity.')
        raw_source_id=prov['source_id']
        obs=obscured.get(raw_source_id)
        if obs:
            receipt_source_id=obs['alias_id']
            receipt_title=obs['obscured_title']
            receipt_author=''
            receipt_genre=obs.get('book_type','')
            receipt_tags=obs.get('craft_tags',[])
            receipt_use=obs.get('prose_usefulness','')
        elif obscured:
            digest=hashlib.sha256(raw_source_id.encode('utf-8')).hexdigest()[:8]
            receipt_source_id=f'folio_ref_{digest}'
            receipt_title=f'Style Folio #{digest[:4].upper()}'
            receipt_author=''
            receipt_genre=''
            receipt_tags=[]
            receipt_use=''
        else:
            receipt_source_id=raw_source_id
            receipt_title=titles.get(raw_source_id,{}).get('title',raw_source_id)
            receipt_author=titles.get(raw_source_id,{}).get('author','')
            receipt_genre=titles.get(raw_source_id,{}).get('book_type','')
            receipt_tags=[]
            receipt_use=''
        receipts.append({'passage_id':hit.passage_id,'source_id':receipt_source_id,
            'source_title':receipt_title,
            'source_author':receipt_author,
            **({'source_genre': receipt_genre} if receipt_genre else {}),
            **({'craft_tags': receipt_tags} if receipt_tags else {}),
            **({'prose_usefulness': receipt_use} if receipt_use else {}),
            'source_revision':prov.get('source_revision','unknown-legacy'),'anchor':prov.get('anchor'),
            'embedding_backend':prov.get('embedding_backend','unknown-legacy'),
            'embedding_model':prov.get('embedding_model','unknown-legacy'),
            'embedding_revision':prov.get('embedding_revision','unknown-legacy'),
            'index_sha256':before['index'],'policy_sha256':before['policy'],'influence_sha256':before['influence'],
            'catalog_sha256':before['catalog'],'quality_sha256':before['quality'],
            'release_pointer_sha256':before['release'],'encoder_binding_sha256':before['encoder'],
            'excerpt_sha256':hashlib.sha256(text.encode('utf-8')).hexdigest(),
            'excerpt_characters':len(text),'rank':rank,'scene_function':scene_function,
            'selection_reason':'eligible similarity ranking for selected passage and scene function',
            'permitted_purposes':purposes})
        texts.append(text)
    if not texts: raise ReferenceUnavailable('no_eligible','No nonempty eligible passages were returned.')
    if fingerprint(root,backend)!=before: raise ReferenceUnavailable('stale','Book metadata changed while receipts were prepared.')
    return {'texts':tuple(texts),'receipts':receipts,'fingerprint':before,'backend':backend,
            'root':root,'message':setup.message}


SCENE_FUNCTION_CRAFT_TAGS = {
    'comedy': frozenset({'slapstick_timing', 'comedic_escalation', 'verbal_snap', 'fart_gross_out', 'visceral_comedy', 'three_beat_scale'}),
    'beauty': frozenset({'thicc_curvy_descriptors', 'sensory_body_detail', 'glam_confidence', 'femme_lesbian_heat'}),
    'transformation': frozenset({'body_transformation', 'absurd_physicality', 'three_beat_scale', 'dork_nerdification_voice', 'stripper_mismatch_arc'}),
    'dialogue': frozenset({'marilyn_blonde_voice', 'breathy_ellipses_cadence', 'queen_bee_banter', 'banter_chemistry', 'verbal_snap'}),
    'tension': frozenset({'noir_mystery_pulp', 'punchy_staging', 'hardboiled_contrast'}),
    'quiet': frozenset({'literary_satire_classic', 'sentence_rhythm', 'observational_irony'}),
    'scene': frozenset(),
}


def rrf_fuse_hits(backend_bundles: dict, *, scene_function: str = 'scene', k: int = 60, limit: int = 6):
    """Reciprocal Rank Fusion across style/luar/topic backends with craft_tags alignment."""
    target_tags = SCENE_FUNCTION_CRAFT_TAGS.get(scene_function, frozenset())
    pool = {}
    for sub, sub_bundle in backend_bundles.items():
        for rank, (text, rec) in enumerate(zip(sub_bundle['texts'], sub_bundle['receipts']), 1):
            pid = rec.get('passage_id')
            if not pid:
                continue
            contrib = 1.0 / (k + rank)
            entry = pool.get(pid)
            if entry is None:
                tags = set(rec.get('craft_tags') or ())
                tag_bonus = 0.005 * len(tags & target_tags) if target_tags else 0.0
                entry = {
                    'text': text,
                    'rec': dict(rec),
                    'score': tag_bonus,
                    'best_backend': sub,
                    'best_contrib': -1.0,
                    'matched_backends': [],
                    'first_rank': rank,
                }
                pool[pid] = entry
            entry['score'] += contrib
            if sub not in entry['matched_backends']:
                entry['matched_backends'].append(sub)
            if contrib > entry['best_contrib']:
                entry['best_contrib'] = contrib
                entry['best_backend'] = sub

    ranked = sorted(pool.values(), key=lambda e: (-e['score'], e['first_rank'], e['rec']['passage_id']))[:limit]
    texts = []
    receipts = []
    for idx, item in enumerate(ranked, 1):
        texts.append(item['text'])
        receipts.append({
            **item['rec'],
            'rank': idx,
            'hybrid_backend': item['best_backend'],
            'matched_backends': list(item['matched_backends']),
            'rrf_score': round(item['score'], 6),
        })
    return tuple(texts), receipts


def _select_hybrid_references(packet, *, root=DEFAULT_BOOKS, provider, scene_function='scene'):
    """Blend eligible passages from style, luar, and topic indexes via Reciprocal Rank Fusion (RRF)."""
    root = Path(root).expanduser().resolve()
    backend_bundles = {}
    sub_fps = {}
    messages = []
    for sub in HYBRID_BACKENDS:
        try:
            sub_bundle = select_references(packet, root=root, backend=sub, provider=provider, scene_function=scene_function)
        except ReferenceUnavailable:
            continue
        backend_bundles[sub] = sub_bundle
        sub_fps[sub] = sub_bundle['fingerprint']
        messages.append(f"{sub}: {sub_bundle['message']}")
    if not backend_bundles:
        raise ReferenceUnavailable('no_eligible', 'No eligible passages matched across style, LUAR, or topic indexes.')
    texts, receipts = rrf_fuse_hits(backend_bundles, scene_function=scene_function, k=60, limit=6)
    if not texts:
        raise ReferenceUnavailable('no_eligible', 'No eligible passages matched across style, LUAR, or topic indexes.')
    return {
        'texts': tuple(texts),
        'receipts': receipts,
        'fingerprint': {'hybrid': sub_fps},
        'backend': 'hybrid',
        'root': root,
        'message': ' | '.join(messages),
    }


def verify_references(bundle):
    if bundle.get('backend') == 'hybrid':
        sub_fps = (bundle.get('fingerprint') or {}).get('hybrid') or {}
        if not sub_fps:
            raise ReferenceUnavailable('stale', 'Hybrid book binding is missing constituent fingerprints.')
        for sub, expected in sub_fps.items():
            if fingerprint(bundle['root'], sub) != expected:
                raise ReferenceUnavailable('stale', f'Book policy, influence or {sub} index changed; start the operation again.')
        return
    if fingerprint(bundle['root'],bundle['backend']) != bundle['fingerprint']:
        raise ReferenceUnavailable('stale','Book policy, influence or index changed; start the operation again.')


def draft_binding(bundle):
    """Text-free receipt for rechecking the same library when a draft is used."""
    return {'backend':bundle['backend'],
            'root_sha256':hashlib.sha256(str(Path(bundle['root']).resolve()).encode('utf-8')).hexdigest(),
            'fingerprint':dict(bundle['fingerprint'])}


def _is_checksum(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def verify_draft_binding(binding, root=DEFAULT_BOOKS):
    if not isinstance(binding, dict):
        raise ReferenceUnavailable('stale', 'This draft lacks a verifiable book source binding.')
    backend, expected, saved_root = (binding.get(key) for key in ('backend', 'fingerprint', 'root_sha256'))
    if not isinstance(backend, str) or backend not in VALID_BACKENDS or not isinstance(expected, dict) or not _is_checksum(saved_root):
        raise ReferenceUnavailable('stale', 'This draft lacks a verifiable book source binding.')
    root = Path(root).expanduser().resolve()
    if backend == 'hybrid':
        sub_fps = expected.get('hybrid')
        if not isinstance(sub_fps, dict) or not sub_fps:
            raise ReferenceUnavailable('stale', 'This draft lacks a verifiable hybrid book source binding.')
        for sub, sub_expected in sub_fps.items():
            verify_draft_binding({'backend': sub, 'fingerprint': sub_expected, 'root_sha256': saved_root}, root=root)
        return
    root_hash = hashlib.sha256(str(root).encode('utf-8')).hexdigest()
    if saved_root != root_hash:
        required = ['release', 'index', 'catalog', 'encoder', 'policy']
        if backend == 'style':
            required.append('style_model')
        if not all(_is_checksum(expected.get(key)) for key in required):
            raise ReferenceUnavailable('stale', 'A legacy book binding requires the original library directory.')
    try:
        current = fingerprint(root, backend)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ReferenceUnavailable('unavailable', f'The draft’s book library could not be verified. {exc}') from exc
    if current != expected:
        raise ReferenceUnavailable('stale', 'Book library, policy, influence or index changed; create a new draft.')


def cadence_observation(texts):
    """Bounded descriptions of eligible excerpts; these are not quality scores."""
    from .rhythm import rhythm_target
    usable=[text for text in texts if len(text.split())>=20]
    target=rhythm_target(usable)
    if target is None:return None
    return {'sample_count':len(usable),'mean_sentence_words':round(max(0,min(80,target[0])),1),
            'sentence_length_variation':round(max(0,min(80,target[1])),1),
            'interpretation':'descriptive only; not a quality score or mandatory target'}


def craft_observation(texts):
    """Describe reusable rhythm without retaining source wording, roles or events."""
    base = cadence_observation(texts)
    if base is None:
        return None
    lengths, pauses, dialogue = [], 0, 0
    usable = [text for text in texts if len(text.split()) >= 20]
    lines = [line for text in usable for line in text.splitlines() if line.strip()]
    for text in usable:
        pauses += len(re.findall(r'[;:]|—|\.{3}|…', text))
        dialogue += sum(bool(re.search(r'[“”"]', line)) for line in text.splitlines() if line.strip())
        for clause in re.split(r'[.!?;:,—]|\s[-–]\s', text):
            n = len(re.findall(r"\b[\w]+(?:['’][\w]+)?\b", clause))
            if n:
                lengths.append(n)
    clauses = max(1, len(lengths))
    return {**base, 'method':'content-free-cadence-v1',
            'typical_clause_words':min(40, round(median(lengths),1)) if lengths else None,
            'short_clause_share':round(sum(n <= 5 for n in lengths)/clauses, 2),
            'pauses_per_ten_clauses':min(10,round(10*pauses/clauses,1)),
            'quoted_line_share':round(dialogue/max(1,len(lines)),2),
            'transfer':'Borrow spacing, sentence contrast and emphasis only. Keep the manuscript narrator, speaker, order, laws and existing setup or payoff.'}


def beat_craft_cards(packet, observation, bundle):
    """Bind measured craft to the roles of the writable turns in the saved plan."""
    if not observation or not packet.continuation or packet.continuation['kind'] != 'scene-plan':
        return []
    turns = [turn for turn in packet.continuation['plan']['turns'] if turn['stage']]
    sources = [row['passage_id'] for row in bundle['receipts']]
    pacing = {key: observation[key] for key in ('typical_clause_words', 'short_clause_share',
                                                'pauses_per_ten_clauses')}
    sentence_rhythm = {key: observation[key] for key in ('mean_sentence_words', 'sentence_length_variation')}
    cards = []
    for index, turn in enumerate(turns):
        operation = turn['operation']
        following = turns[index + 1]['operation'] if index + 1 < len(turns) else None
        releases = ('release', 'group_release')
        if operation in releases:
            role, direction = 'payoff', 'Give the sound its own clause before the response.'
        elif operation == 'force':
            role, direction = 'reaction', 'Allow a brief reaction after the impact.'
        elif operation in ('split', 'rejoin', 'transform'):
            role, direction = 'transition', 'Make the change readable in one clear action.'
        elif following in releases:
            role, direction = 'setup', 'Leave a little room before the next impact.'
        elif turn['speakers']:
            role, direction = 'exchange', 'Vary short replies with longer ones where the speakers need room.'
        else:
            role, direction = 'continuity', 'Keep the handoff brief and legible.'
        cards.append({'beat': turn['id'], 'pacing': pacing, 'sentence_rhythm': sentence_rhythm,
                      'turn': {'role': role, 'direction': direction},
                      'provenance': {'backend': bundle['backend'], 'passage_ids': sources}})
    return cards
