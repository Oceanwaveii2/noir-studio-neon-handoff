const el = id => document.getElementById(id);
const [episodes, beats, preview, draft, message, text] = ['episodes','beats','preview','draft','status','text'].map(el);
const [story, processing] = ['story', 'processing'].map(el);
let current, turn = 0;
let storyPoints = null;
let timeline, changing = false;
const api = async (route, body) => {
  const response = await fetch(route, body ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)} : {});
  const result = await response.json();
  if (!response.ok) throw Error(result.error);
  return result;
};
const options = (target, values) => target.replaceChildren(...values.map(([caption,id]) => new Option(caption,id)));
const open = async () => {
  const id = ++turn;
  preview.disabled = draft.disabled = true;
  story.disabled = processing.disabled = true;
  storyPoints = null;
  story.textContent = 'Story Beats';
  el('beat-label').textContent = 'Passage';
  text.textContent = '';
  message.textContent = '';
  try {
    const item = await api(`/api/episode?episode=${encodeURIComponent(episodes.value)}`);
    if (id !== turn) return;
    current = item;
    options(beats, current.map.beats.map((beat,index) => [`${beat.number}. ${beat.text.trim().slice(0,66)}`,index]));
    story.disabled = item.episode.head < 1;
    processing.disabled = false;
    draft.disabled = false;
    show();
  } catch (error) { if (id === turn) message.textContent = error.message; }
};
function show() {
  ++turn;
  if (storyPoints) {
    const point = storyPoints[beats.selectedIndex];
    text.textContent = point?.passage.text || '';
    const cues = point?.clips.map(clip => {
      const range = `${(clip.start_ms / 1000).toFixed(3)}–${(clip.end_ms / 1000).toFixed(3)} s`;
      return `${clip.name} (${range}${clip.clip ? '' : ', unavailable in this copy'})`;
    }) || [];
    message.textContent = point
      ? [point.scene, point.kind === 'frozen' ? 'Frozen passage' : point.label, ...cues].join(' · ')
      : 'No saved story beats.';
    preview.disabled = true;
    return;
  }
  const beat = current?.map.beats[beats.selectedIndex];
  text.textContent = beat?.text || '';
  preview.disabled = !beat;
  message.textContent = '';
}
episodes.addEventListener('change',open);
beats.addEventListener('change',show);
preview.addEventListener('click',async () => {
  const id = ++turn, map = current.map, beat = map.beats[beats.selectedIndex];
  const body = {episode:map.episode,project:map.project_id,universe:map.universe_id,branch:map.branch,
    revision:map.revision,beat:beat.scope_beat,start:beat.start,end:beat.end,provider:'codex-session',references:'style'};
  preview.disabled = true;
  message.textContent = 'Reading cadence from the shared library…';
  try {
    const result = await api('/api/preview',body);
    if (id !== turn) return;
    const count = result.reference_receipts?.length ?? 0;
    message.textContent = count ? `Ready · ${count} source-linked cadence cues` : 'No book cues available for this passage.';
  } catch (error) { if (id === turn) message.textContent = error.message; }
  finally { if (id === turn) preview.disabled = false; }
});
const savedScope = () => ({episode:current.episode.id,branch:current.episode.branch,
  project:current.map.project_id,universe:current.map.universe_id});
story.addEventListener('click', async () => {
  if (storyPoints) { await open(); return; }
  const id = ++turn;
  preview.disabled = true;
  try {
    const result = await api('/api/writing', {action:'scene.timeline.open',
      request:{...savedScope(),timeline_revision:current.episode.head}});
    if (id !== turn) return;
    storyPoints = result.scenes.flatMap(scene => scene.beats.map(beat => ({...beat,scene:scene.title})));
    options(beats, storyPoints.map((beat,index) => [`${beat.scene} · ${beat.label}`,index]));
    story.textContent = 'Notebook passages';
    el('beat-label').textContent = 'Story beat';
    story.disabled = false;
    show();
  } catch(error) {
    if (id === turn) {
      story.disabled = false;
      preview.disabled = beats.selectedIndex < 0;
      message.textContent = error.message;
    }
  }
});
processing.addEventListener('click', async () => {
  const id = ++turn;
  try {
    const result = await api('/api/writing', {action:'processing.open',request:savedScope()});
    if (id !== turn) return;
    const job = result.jobs[0];
    message.textContent = job ? `${job.title} · ${job.status.toLowerCase()} · ${job.id}` : 'No saved jobs in this episode.';
    if (job) text.textContent = job.steps.map(step =>
      `${step.label} · ${step.status.toLowerCase()}${step.elapsed_ms == null ? '' : ` · ${step.elapsed_ms} ms`}`).join('\n');
  } catch(error) { if (id === turn) message.textContent = error.message; }
});
draft.addEventListener('click',async () => {
  const id = ++turn, episode = current.episode.id;
  preview.disabled = Boolean(storyPoints) || beats.selectedIndex < 0;
  message.textContent = 'Opening the latest writing run…';
  try {
    const result = await api('/api/writing',{action:'run.latest',request:{episode}});
    if (id !== turn) return;
    const run = result.run;
    message.textContent = run ? `Latest run: ${run.status.toLowerCase()}` : 'No writing run for this episode yet.';
    if (run?.draft_id) {
      const value = await api('/api/writing',{action:'draft.open',request:{episode,branch:run.branch,draft:run.draft_id}});
      if (id === turn) text.textContent = value.candidate || value.text || '';
    }
  } catch (error) { if (id === turn) message.textContent = error.message; }
});
const timelineNotice = el('timeline-status');
function historyButtons() {
  el('timeline-refresh').disabled = changing;
  el('timeline-undo').disabled = changing || !timeline?.history?.can_undo;
  el('timeline-redo').disabled = changing || !timeline?.history?.can_redo;
}
async function showTimeline(state) {
  timeline = state;
  const selected = episodes.value;
  options(episodes, state.episodes.map(episode => [episode.title, episode.id]));
  if (state.episodes.some(item => item.id === selected)) episodes.value = selected;
  if (episodes.value) await open();
  else {
    ++turn;
    current = null;
    options(beats, []);
    preview.disabled = draft.disabled = story.disabled = processing.disabled = true;
    text.textContent = '';
    message.textContent = 'There are no episodes in this workspace yet.';
  }
}
async function reloadTimeline() {
  const result = await api('/api/session');
  await showTimeline({episodes:result.episodes, history: result.history, workspace:result.service.workspace});
  el('connection').textContent = 'Connected to the local Noir service';
}
async function timelineAction(direction) {
  if (changing || (direction && !timeline)) return;
  changing = true;
  historyButtons();
  let notice = '';
  try {
    if (!direction) {
      await reloadTimeline();
      notice = 'Showing the saved timeline.';
    } else {
      const result = await api('/api/timeline', {action: 'timeline.'+direction, request: {
        expected_revision:timeline.history.revision, project:timeline.workspace.project_id,
        universe:timeline.workspace.universe_id,
      }});
      await showTimeline(result.state);
      notice = result.status === 'REPLAYED' ? 'This change was already saved.' : result.notice;
    }
  } catch (error) {
    notice = error.message;
    if (direction) await reloadTimeline().catch(() => {});
    else el('connection').textContent = error.message;
  } finally {
    changing = false;
    historyButtons();
    timelineNotice.textContent = notice;
  }
}
el('timeline-refresh').addEventListener('click', () => timelineAction());
el('timeline-undo').addEventListener('click', () => timelineAction('undo'));
el('timeline-redo').addEventListener('click', () => timelineAction('redo'));
timelineAction();
