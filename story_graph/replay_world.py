"""Candidate scene transitions executed by the normal beat sequencer."""
from __future__ import annotations

from copy import deepcopy

from .epistemic import EpistemicLedger, Fact
from .models import CharacterState, Location, Portal, PortalState, TransactionResult
from .world_state import StoryWorldState


def transform_rules(profile):
    policy=profile.get('branch_rules') or {}
    root=profile['root']
    rules={(root,form):{'node':node,'from_form':None,'needs_reunion':True}
           for form,node in profile['anchors']['transform'].items()}
    rules.update({(r['actor'],r['id']):r for r in policy.get('transforms',())})
    return rules


class SceneReplayWorld(StoryWorldState):
    """A disposable world with one authorized split family, of any admitted size."""

    def __init__(self, profile, reveal_beats):
        super().__init__('Scoped scene replay')
        self.profile = deepcopy(profile)
        self.root = profile['root']
        self.members = {}
        self.used_members = set()
        self.signals = {}
        self.reunions = 0
        self.releases = {}
        self.observations = {}
        self.lines = set()
        self.reactions = []
        self.ledger = EpistemicLedger()
        self.form_reveal_beats = deepcopy(reveal_beats)
        self.transforms = transform_rules(profile)
        policy = profile.get('branch_rules') or {}
        self.reactivation = policy.get('reactivation')
        self.intervention_forms = policy.get('intervention_forms', {})
        self.group_force = policy.get('reactivated_group_force')
        self.reactivated_at = None
        self.group_release = None
        self.split_origin = None
        for loc in profile['locations']:
            self.add_location(Location(loc, loc))
        for p in profile['portals']:
            self.add_portal(Portal(p['id'], p['id'], p['from'], p['to'], PortalState.CLOSED,
                                   allows_scent=p['allows_scent'], scent_permeability=p['permeability'],
                                   allows_sound=p['allows_sound'], allows_traversal=False))
        for person in profile['actors']:
            ident = person['id']
            self.add_character(CharacterState(ident, ident, person['location'], physique={
                'active_avatar': ident,
                'can_self_morph': ident == self.root or any(owner==ident for owner,_ in self.transforms),
                'can_target_morph': False,
            }))
            self.ledger.register_character(ident)

    def active(self, actor):
        return actor in self.characters and (actor != self.root or not self.members)

    @staticmethod
    def _result(txn, reason='', **changes):
        return TransactionResult(not reason, txn.action, txn.actor, txn.target, reason, changes)

    def _handle_scene_release(self, txn):
        if txn.actor != self.root or not self.active(txn.actor):
            return self._result(txn, 'Only the active scoped root can produce this release')
        actor = self.characters[txn.actor]
        emission, force = self.profile['emission'], self.profile['force']
        severity = txn.params['severity']
        scent = (emission['strength'][severity] if emission and actor.active_avatar == emission['form'] else None)
        strong = bool(force and actor.active_avatar == force['form'] and severity == 'severe')
        value = {'location': actor.location, 'form': actor.active_avatar, 'scent': scent, 'force': strong,
                 'tick': self.tick}
        self.releases[txn.beat_id] = value
        return self._result(txn, release=value)

    def _handle_scene_notice(self, txn):
        release_id = txn.params['release']
        event = self.releases.get(release_id)
        if not self.active(txn.actor) or not event or not event['scent']:
            return self._result(txn, 'Observation needs a present observer and an in-scope scent release')
        fact_id = 'scent-' + release_id
        self.ledger.register_fact(Fact(fact_id, event['scent'], origin_tick=event['tick'], is_private=True))
        if not self.ledger.infer_from_sensory(txn.actor, fact_id, event['location'], self, self.tick):
            return self._result(txn, 'The air path does not allow this observer to perceive the scent')
        self.observations[txn.beat_id] = {'actor': txn.actor, 'fact': fact_id}
        return self._result(txn, observation=self.observations[txn.beat_id])

    def _handle_scene_line(self, txn):
        seen = self.observations.get(txn.params['observation'])
        if not self.active(txn.actor) or not seen or seen['actor'] != txn.actor or not self.ledger.knows(txn.actor, seen['fact']):
            return self._result(txn, 'The protected response needs this speaker’s prior observation')
        lock = txn.params['lock']
        self.lines.add(lock)
        return self._result(txn, protected_line={'id': lock, 'sha256': txn.params['sha256']})

    def _handle_scene_split(self, txn):
        root = self.characters[self.root]
        repeat = self.reactivation if txn.params.get('reactivate') else None
        origin = repeat['form'] if repeat else self.root
        if txn.actor != self.root or self.members or root.active_avatar != origin or not root.can_self_morph or root.id == 'haley':
            return self._result(txn, 'Split requires the active authorized form')
        if repeat:
            release_id=repeat['release']
            release=self.releases.get(release_id)
            if (not self.reunions or not release or release['form']!=origin or release['location']!=root.location
                    or not any(r['release']==release_id for r in self.reactions)):
                return self._result(txn,'The active form has not caused this branch’s checked release and reaction')
        protected = self.profile['protected_line']
        payoff = protected['lock'] if protected else None
        if payoff is not None and payoff not in self.lines:
            return self._result(txn, 'The protected response must occur before the split')
        roster = txn.params['members']
        if len(roster)<2 or any(mid in self.characters for mid in roster):
            return self._result(txn, 'The split requires inactive manifestation bodies')
        if ((repeat and set(roster)!=self.used_members)
                or (not repeat and any(mid in self.used_members for mid in roster))):
            return self._result(txn,'Only a checked repeat split can reactivate the same bodies')
        permitted = {row['id']: row['mind'] for row in self.profile['members']}
        if len(set(roster)) != len(roster) or any(mid not in permitted for mid in roster):
            return self._result(txn, 'The requested manifestation is not authorized for this family')
        for mid in roster:
            self.add_character(CharacterState(mid, mid, root.location, clothing=root.clothing, physique={
                'active_avatar': mid, 'can_self_morph': False, 'can_target_morph': False,
            }))
            if repeat:
                self.ledger.reset_character(mid)
            self.ledger.register_character(mid)
        self.members = {mid: permitted[mid] for mid in roster}
        self.used_members.update(roster)
        self.signals.clear()
        self.split_origin = origin if repeat else None
        self.reactivated_at = txn.beat_id if repeat else None
        return self._result(txn, activated=[{'id': mid, 'mind': mind} for mid, mind in self.members.items()])

    def _form_is_active(self, actor, form):
        return self.active(actor) and self.characters[actor].active_avatar == form

    def _handle_scene_intervene(self, txn):
        if txn.actor not in self.profile['interveners'] or not self.active(txn.actor) or not self.members:
            return self._result(txn, 'The rejoin intervention requires an authorized, present actor and an active split')
        if txn.actor in self.intervention_forms and not self._form_is_active(txn.actor, self.intervention_forms[txn.actor]):
            return self._result(txn, 'The authorized intervener must be in the authored form')
        can_hear, clarity = self.can_hear(self.root, self.characters[txn.actor].location)
        if not can_hear or clarity < 0.25:
            return self._result(txn, 'The split family cannot hear this intervention')
        self.signals[txn.beat_id] = txn.actor
        return self._result(txn, intervention=txn.actor)

    def _handle_scene_rejoin(self, txn):
        signal = txn.params['intervention']
        if txn.actor != self.root or not self.members or signal not in self.signals:
            return self._result(txn, 'Reunion requires an active split and its authorized intervention')
        helper = self.signals[signal]
        if helper in self.intervention_forms and not self._form_is_active(helper, self.intervention_forms[helper]):
            return self._result(txn, 'The authorized intervener changed form before the reunion')
        if txn.params.get('pattern_arity', len(self.members)) != len(self.members):
            return self._result(txn, 'The active destination bodies do not fit the borrowed reunion shape')
        retired = list(self.members)
        for member in retired:
            del self.characters[member]
        self.members.clear()
        self.signals.clear()
        self.split_origin = None
        self.reactivated_at = None
        self.reunions += 1
        return self._result(txn, retired=retired, active_form=self.characters[self.root].active_avatar)

    def _handle_scene_transform(self, txn):
        form = txn.params['avatar_id']
        rule=self.transforms.get((txn.actor,form))
        if not rule or not self.active(txn.actor) or self.form_reveal_beats.get(txn.actor,{}).get(form)!=txn.beat_id:
            return self._result(txn, 'The form can only activate at its pinned transformation')
        if rule['needs_reunion'] and not self.reunions:
            return self._result(txn, 'The destination transformation requires reunion first')
        if rule['from_form'] is not None and self.characters[txn.actor].active_avatar!=rule['from_form']:
            return self._result(txn,'The authored predecessor is not active')
        source = rule.get('requires_actor_form')
        if source and not self._form_is_active(source['actor'], source['form']):
            return self._result(txn, 'The transformation’s authored power source is not active')
        return self._handle_morph_self(txn)

    def _handle_scene_group_release(self, txn):
        if (not self.group_force or txn.actor != self.root or not self.members or not self.reactivated_at or
                self.group_release or txn.params['after_reactivation'] != self.reactivated_at):
            return self._result(txn, 'One group release requires the authored repeat split and its active group')
        places = {self.characters[mid].location for mid in self.members}
        if len(places) != 1:
            return self._result(txn, 'The manifestations must be together to produce this group release')
        value = {'location': next(iter(places)), 'form': 'split', 'emitters': list(self.members),
                 'scent': None, 'force': True, 'tick': self.tick}
        self.group_release = txn.beat_id
        self.releases[txn.beat_id] = value
        return self._result(txn, release=value)

    def _handle_scene_force(self, txn):
        event = self.releases.get(txn.params['release'])
        force = self.profile['force']
        if force and event and self.group_release == txn.params['release']:
            if not self.reactivated_at or not self.members or set(event['emitters']) != self.members.keys():
                return self._result(txn, 'Group force requires the same active manifestations')
            force = {'recipient': force['recipient'], 'form': 'split',
                     'visible_from': self.group_force['visible_from'], 'destination': self.group_force['destination']}
        if (not force or not event or not event['force'] or txn.actor != force['recipient']
                or not self.active(txn.actor) or event['form'] != force['form']):
            return self._result(txn, 'The authored reaction needs an authorized force release and its present recipient')
        actor = self.characters[txn.actor]
        if actor.location not in force['visible_from']:
            return self._result(txn, 'The recipient is outside the force reaction’s authored scene positions')
        if any(r['release'] == txn.params['release'] for r in self.reactions):
            return self._result(txn, 'This release already caused its authored reaction')
        change = {'actor': actor.id, 'from': actor.location, 'to': force['destination'],
                  'release': txn.params['release']}
        actor.location = force['destination']
        self.reactions.append(change)
        return self._result(txn, reaction=change)

    def projection(self):
        """Only active characters, facts seen by their recipients, and current form."""
        return {
            'tick': self.tick,
            'root': self.root,
            'root_form': 'split' if self.members else self.characters[self.root].active_avatar,
            'manifestations': [{'id': mid, 'mind': self.members[mid]} for mid in sorted(self.members)],
            'actors': {key: {'location': actor.location, 'form': actor.active_avatar}
                       for key, actor in sorted(self.characters.items()) if self.active(key)},
            'knowledge': {key: sorted(fact.id for fact in self.ledger.get_known_facts(key))
                          for key in sorted(self.characters) if self.active(key)},
            'reunions': self.reunions,
            'reactions': deepcopy(self.reactions),
            **({'split_origin':self.split_origin} if self.split_origin else {}),
        }
