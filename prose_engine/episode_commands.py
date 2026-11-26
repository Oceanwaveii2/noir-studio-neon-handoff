"""Common episode commands for Studio, timeline Workbench and the CLI."""
from __future__ import annotations

from story_graph.director import plan
from story_graph.universe_scope import verify_scope
from .edit_receipts import EditReceipt, ensure
from .notebook import DraftStore, NotebookStore, joined
from .timeline_commands import execute as execute_timeline, revision as _revision
from .writing_runs import WritingRuns


class EpisodeCommands:
    def __init__(self,timeline,*,junctions=None,form_graph=None,books_root=None,provider_factory=None,
                 provider_resolver=None,schedule=None,legacy_source=None):
        self.timeline = timeline
        self.junctions = junctions
        self.form_graph = form_graph
        self.books_root = books_root
        self.provider_factory = provider_factory
        self.provider_resolver = provider_resolver
        self.schedule = schedule
        self.legacy_source = legacy_source

    def execute(self,action,request):
        if not isinstance(action,str) or not isinstance(request,dict):
            raise ValueError('Episode command needs an action and an object')
        with self.timeline._connect() as c:
            identity = verify_scope(c,project_id=request.get('project'),universe_id=request.get('universe'))
        if action.startswith('history.'):
            from .project_history import execute
            return execute(self.timeline, action, request, form_graph=self.form_graph, junctions=self.junctions)
        if action == 'intake.preview':
            from .intake import preview
            return preview(request)
        if action in ('intake.receipt','intake.source'):
            from .intake import receipt, source
            return (receipt if action=='intake.receipt' else source)(self.timeline,request)
        if action in ('intake.create','episode.create'):
            from .intake import create
            junctions = self.form_graph.read()['junctions'] if self.form_graph and identity['kind']=='afm-starters' else ()
            result = create(self.timeline, request, from_document=action=='intake.create', junctions=junctions)
            return {**result, 'state':execute_timeline(self.timeline,'timeline.catalog',request),
                    'notice':'Episode already saved.' if result['status']=='REPLAYED' else 'Episode added.'}
        if action == 'intake.plan':
            from .gemini_driver import plan_episode_from_intake
            return plan_episode_from_intake(
                self.timeline,
                self.form_graph,
                request,
                books_root=self.books_root,
            )
        if action == 'intake.launch':
            from .gemini_driver import drive_episode_from_intake
            return drive_episode_from_intake(
                self.timeline,
                self.form_graph,
                request,
                provider_factory=self.provider_factory,
                max_calls=int(request.get('max_calls', 2)),
                books_root=self.books_root,
            )
        if action == 'intake.history':
            from .gemini_driver import get_intake_director_history
            return get_intake_director_history(self.timeline, request['episode'])
        if action == 'episode.prepare':
            from .cook import prepare_episode
            return prepare_episode(self.timeline, request, form_store=self.form_graph)
        if action == 'episode.preparation.open':
            from .cook import current_preparation
            episode = request['episode']
            with self.timeline._connect() as c:
                c.execute('BEGIN')
                current = self.timeline._require_active(c, episode)
                if request.get('branch', current['branch']) != current['branch']:
                    raise ValueError('The saved episode belongs to a different branch')
                return {'receipt':current_preparation(c, episode, current['head']), 'provider_calls':0}
        if action == 'director.open':
            return plan(self.timeline,request)
        if action == 'fx06.open':
            return self._fx06_open(request)
        if action == 'scene.timeline.open':
            from .story_timeline import open_track
            return open_track(self.timeline, request)
        if action == 'scene.plan.open':
            from .scene_plan import open_plan
            return open_plan(self.timeline, request)
        if action.startswith('scene.plan.inputs.'):
            from .scene_plan_inputs import execute
            return execute(self.timeline, action, request)
        if action == 'mind.inspect':
            from .mind_inspection import inspect
            return inspect(self.timeline, request, junctions=self.junctions)
        if action == 'processing.open':
            from .processing import open_jobs
            return open_jobs(self.timeline, request)
        if action.startswith('scene.media.'):
            from .media_graph import execute
            return execute(self.timeline, action, request)
        if action.startswith('scene.fragment.'):
            from story_graph.scene_fragments import SceneFragmentStore
            return SceneFragmentStore(self.timeline).execute(action,request)
        if action.startswith('scene.override.'):
            from story_graph.scene_override import SceneReplayStore
            result=SceneReplayStore(self.timeline).execute(action,request)
            if action=='scene.override.open':
                from .scene_clips import replay_cues
                if cues:=replay_cues(self.timeline,result['receipt']):
                    result['clip_cues']=cues
            return result
        if action.startswith('scene.minds.'):
            from .replay_minds import execute
            return execute(self.timeline,action,request,junctions=self.junctions,provider_factory=self.provider_factory)
        if action.startswith('scene.clips.'):
            from .scene_clips import execute
            return execute(self.timeline,action,request,junctions=self.junctions,provider_factory=self.provider_factory)
        if action.startswith('scene.branches.'):
            from .branch_continuations import execute
            return execute(self.timeline,action,request,junctions=self.junctions,provider_factory=self.provider_factory,
                           provider_resolver=self.provider_resolver)
        if action.startswith('scene.bridge.'):
            from .scene_bridges import execute
            return execute(self.timeline,action,request,junctions=self.junctions,provider_factory=self.provider_factory,
                           provider_resolver=self.provider_resolver,books_root=self.books_root)
        if action.startswith('scene.exchange.'):
            from .evidence_exchange import execute
            if request.get('action') == action:
                request = {k: v for k, v in request.items() if k != 'action'}
            return execute(self.timeline, action, request, junctions=self.junctions)
        if action.startswith('run.') or action=='director.preview':
            runs = WritingRuns(self.timeline,junctions=self.junctions,books_root=self.books_root,
                               provider_factory=self.provider_factory,provider_resolver=self.provider_resolver,
                               legacy_source=self.legacy_source)
            if action=='run.selection.preview':
                return runs.selection_preview(request)
            if action=='director.preview':
                return runs.preview(request)
            episode = request['episode']
            if action=='run.latest':
                return {'run':runs.latest(episode, request.get('kind'))}
            if action=='run.selection':
                return self._selection(runs, request)
            if action=='run.start':
                state = runs.start(request)
                return self._dispatch(runs,state) if request.get('defer') is not True else state
            ident = request['request_id']
            if action=='run.cancel':
                return runs.cancel(ident,episode)
            if action=='run.status':
                return runs.status(ident,episode)
            if action=='run.resume':
                return self._dispatch(runs,runs.status(ident,episode))
            raise ValueError('Unknown writing run action')
        if action in ('draft.apply','notebook.undo','notebook.redo'):
            return self._edit(action,request)
        if action == 'word_prep.promote':
            from .word_prep import promote
            return promote(self.timeline, request, self.form_graph)
        if action == 'canon.tag.save':
            carrier = request.get('tt_carrier')
            if request.get('mode') == 'time_travel_canon':
                from story_graph.form_graph_store import FormGraphStore
                graph = self.form_graph or FormGraphStore(self.timeline.form_graph_path)
                if not isinstance(carrier, str) or carrier not in graph.junctions():
                    raise ValueError('Choose a saved character as the time-travel carrier')
            tag = self.timeline.save_canon_tag(request['episode'], request['timeline_revision'],
                                               request['canon_revision'], request['mode'], carrier)
            return {'canon_tag': tag}
        if action in ('draft.open','draft.list','draft.compare','draft.favorite','draft.favorite.undo','draft.favorite.redo'):
            return self._read_or_star_draft(action,request)
        if action.startswith('timeline.'):
            return execute_timeline(self.timeline,action,request,junctions=self.junctions)
        if action == 'graph.cook':
            from .graph_cook import cook_graph
            return cook_graph(self.timeline, request)
        if action.startswith('graph.'):
            if self.form_graph is None or identity['kind']!='afm-starters':
                raise ValueError('No shared character graph is connected for this universe')
            if action=='graph.history':
                return self.form_graph.read()
            if action in ('graph.undo','graph.redo'):
                return self.form_graph.change({'action':action[6:]+'_graph','revision':_revision(request,'revision')},
                                              _history_path=self.timeline.path)
        raise ValueError('Unknown episode command')

    def _selection(self, runs, request):
        from .scoped_service import _selection_identity, _selection_replay
        # Requests from before WritingRuns owned selections already have stable draft
        # identities. Reopen them without making another writer attempt.
        previous = {k:v for k,v in request.items() if k not in ('action','defer')}
        previous.setdefault('reference_delivery', 'excerpt')
        identity = _selection_identity(self.timeline, 'generate', previous)
        saved = _selection_replay(self.timeline, identity, previous)
        if saved:
            if saved['status'] != 'PROPOSED':
                original = saved['status']
                saved.update(status='UNKNOWN' if original=='STARTED' else original, draft_id=None,
                             reason='The earlier request has no applicable draft.')
            return saved
        state = runs.start(request, selection=True)
        if request.get('defer') is True:
            return state
        replayed = state['status'] == 'COMPLETED'
        state = self._dispatch(runs, state)
        if self.schedule:
            return state
        if state['status']=='PRESERVED':
            return {k:v for k,v in state.items() if k!='draft_id'}
        if state['status']=='COMPLETED' and state['generation_receipt']:
            draft = DraftStore(NotebookStore(self.timeline)).open(state['episode'],state['branch'],state['draft_id'])
            return {**state, 'run_status':'COMPLETED', 'status':'PROPOSED', 'replayed':replayed, 'text':draft['text'],
                    'writer_receipt':draft['writer_receipt'], 'provider_request_id':draft['provider_request_id'],
                    'attempt_id':draft['attempt_id']}
        return state

    def _fx06_open(self,request):
        from story_graph import fx06_scene as scene
        from .scoped_pipeline import build_packet
        episode=request.get('episode')
        with self.timeline._connect() as c:
            binding=scene.read(c,episode)
        if binding is None:
            raise ValueError('Open the FX06 pilot workspace')
        current=self.timeline.get_episode(episode)
        if request.get('branch') not in (None,scene.BRANCH):
            raise ValueError('FX06 scene must stay on its original branch')
        if request.get('revision') is not None and _revision(request,'revision')!=current['head']:
            raise ValueError('FX06 scene revision is stale')
        graph=self.junctions() if self.junctions else None
        phases=[]
        for item in binding['phases']:
            packet=build_packet(self.timeline,episode,item['beat'],current['head'],item['start'],item['end'],
                                junctions=graph,project_id=scene.PROJECT,universe_id=scene.UNIVERSE,
                                branch=scene.BRANCH)
            phases.append({**item,'text':packet.target,'state':packet.fx06})
        notebook=NotebookStore(self.timeline)
        drafts=DraftStore(notebook)
        roast=next(s for s in phases if s['id']=='roast')
        candidate=next((item for item in drafts.list(episode,scene.BRANCH)
                        if item['status']=='PROPOSED'
                        and item['beat']==roast['beat'] and item['start']==roast['start'] and item['end']==roast['end']),None)
        return {'episode':episode,'branch':scene.BRANCH,'revision':current['head'],'phases':phases,
                'protected_line':scene.PERFUME_LINE,'cutaway':binding['cutaway'],
                'draft':drafts.open(episode,scene.BRANCH,candidate['id']) if candidate else None}

    def _dispatch(self,runs,state):
        if not state['resume_available']:
            return state
        if self.schedule:
            self.schedule(lambda: runs.run(state['id'],state['episode']))
            return state
        return runs.run(state['id'],state['episode'])

    def _read_or_star_draft(self, action, request):
        drafts=DraftStore(NotebookStore(self.timeline))
        episode, branch = request['episode'], request['branch']
        if action=='draft.open':
            return drafts.open(episode,branch,request['draft'])
        if action=='draft.compare':
            return {'diff':drafts.compare(episode,branch,request['first'],request['second'])}
        if action=='draft.list':
            rows = drafts.list(episode,branch)
            if request.get('compact') is True:
                rows = [{k:row.get(k) for k in ('id','status','provider','favorite','created','parent','source_revision')}
                        for row in rows]
            result = {'drafts':rows}
        else:
            expected = request.get('expected_revision')
            if action=='draft.favorite':
                result = drafts.favorite(episode,branch,request['draft'],request.get('value'),
                    expected_favorite=request.get('expected_favorite'),expected_revision=expected)
            else:
                step = drafts.undo_favorite if action.endswith('.undo') else drafts.redo_favorite
                result = step(episode,branch,expected_revision=expected)
        return {**result, 'favorite_history':drafts.favorite_history(episode,branch),
                'timeline_history':self.timeline.history_state()}

    def _edit(self,action,request):
        episode = request['episode']
        notebooks = NotebookStore(self.timeline)
        chosen = {'notebook_revision':_revision(request,'notebook_revision'),
                  'timeline_revision':_revision(request,'timeline_revision')}
        bounds = ('source_start','source_end','candidate_start','candidate_end')
        if action == 'draft.apply':
            chosen.update(draft=request['draft'],branch=request['branch'],**{k:request.get(k) for k in bounds})
        owner = EditReceipt.make(action,episode,chosen,request.get('request_id'))
        with self.timeline._connect() as c:
            ensure(c)

        def describe(replayed):
            # Read the original receipt and the *current* head in one snapshot.
            with self.timeline._connect() as c:
                c.execute('BEGIN')
                receipt = owner.read(c)
                if receipt is None:
                    return None
                ep,rev = notebooks._episode(c,episode)
                current = notebooks._head(c,episode)
                undo,redo = notebooks._history(c,episode,current['revision'])
                state = dict(current, stale=current['timeline_revision'] != ep['head']
                             or joined(current['blocks']) != rev['script'],
                             can_undo=bool(undo),can_redo=bool(redo))
                return {'status':'REPLAYED' if replayed else 'APPLIED',
                        'receipt':receipt,'notebook':state}

        if replay := describe(True):
            return replay
        try:
            args = (chosen['notebook_revision'],chosen['timeline_revision'])
            if action=='draft.apply':
                drafts=DraftStore(notebooks)
                drafts.use(episode,chosen['branch'],chosen['draft'],*args,**{k:chosen[k] for k in bounds},
                           junctions=self.junctions() if self.junctions else None,
                           books_root=self.books_root,receipt=owner)
            else:
                step = notebooks.undo if action=='notebook.undo' else notebooks.redo
                step(episode,*args,receipt=owner)
        except ValueError:
            if replay := describe(True):
                return replay
            raise
        return describe(False)
