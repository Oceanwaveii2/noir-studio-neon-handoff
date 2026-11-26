import { escapeHtml as h } from './compose.js';

const PURPOSE = {
  structure: 'Structure reference',
  cutaway: 'Audience cutaway',
  personality: 'Personality',
  performance: 'Performance',
  timing: 'Timing',
};
const FORMS = {
  peter_griffin_celestial_variant: 'Rainee Peter',
  nurse_pamela_franny_anderson: 'Nurse Franny',
};

function time(ms) {
  return `${Math.floor(ms / 60000)}:${((ms % 60000) / 1000).toFixed(3).padStart(6, '0')}`;
}

function sceneTitle(title) {
  const text = title.replace(/^SCENE \d+:\s*/i, '');
  return text === text.toUpperCase() ? text.toLowerCase().replace(/(^|\s)\p{L}/gu, (ch) => ch.toUpperCase()) : text;
}

function label(beat) {
  return beat.kind === 'frozen' ? 'Haley’s frozen line' : beat.label;
}

function storyRows(story) {
  return (story?.scenes || []).flatMap((scene) => scene.beats.map((beat) => ({ ...beat, scene })));
}

function currentBeat(state, rows) {
  return rows.find((beat) => beat.id === state.storyCursor) || rows[0];
}

function clipDestination(story, beat) {
  if (!beat.destination) return '';
  const query = new URLSearchParams({
    episode: story.scope.episode,
    fragment: beat.destination.fragment,
    fragment_revision: beat.destination.fragment_revision,
    timeline_revision: story.timeline_revision,
    beat: beat.destination.node,
    'return-beat': beat.id,
  });
  if (beat.replay) {
    query.set('receipt', beat.replay);
    query.set('event', beat.id);
  }
  return `/scene-clips?${query}`;
}

function mediaDestination(story, beat, segment, scene = false) {
  const target = scene ? { scene: beat.scene.id, scene_sha256: beat.scene.passages_sha256, 'return-beat': beat.id }
    : { beat: beat.id, passage_sha256: beat.passage.sha256 };
  const query = new URLSearchParams({ episode: story.scope.episode, timeline_revision: story.timeline_revision, ...target });
  if (story.fragment) query.set('fragment', story.fragment);
  if (segment) query.set('segment', segment);
  return `/beat-media?${query}`;
}

export function renderStoryTimeline(state) {
  const story = state.storyTimeline;
  const rows = storyRows(story);
  const beat = currentBeat(state, rows);
  const mindQuery = story && beat ? new URLSearchParams({ episode: story.scope.episode, turn: beat.id }) : null;
  if (story?.fragment && mindQuery) mindQuery.set('fragment', story.fragment);
  const index = rows.indexOf(beat);
  const clip = beat?.clips.find((item) => item.id === state.storyClip) || beat?.clips[0];
  const episode = state.episodeState?.episode;
  const graphs = `/scene-fragments?${new URLSearchParams({ episode: state.episodeId })}`;
  const activity = new URLSearchParams({ episode: state.episodeId });
  if (story?.fragment) activity.set('story-fragment', story.fragment);
  if (beat) activity.set('story-beat', beat.id);
  const attach = beat ? clipDestination(story, beat) : '';
  const media = clip?.clip ? `/api/scene-clips/media?${new URLSearchParams({ ...story.scope, id: clip.clip })}` : '';
  const title = episode?.title || 'Story timeline';
  return `<div class="v2-tl-shell v2-story-shell">
    <header class="v2-tl-toolbar">
      <div class="v2-tl-title-group"><h1>${h(title)}</h1><span>Story beats${story ? ` · r${story.timeline_revision}` : ''}</span></div>
      <div class="v2-tl-actions">
        <button type="button" class="v2-tl-btn" id="v2EpisodeCards">Episode cards</button>
        ${episode ? `<a class="v2-tl-btn" href="${h(graphs)}">Scene graphs</a>` : ''}
        ${episode ? `<a class="v2-tl-btn" href="/processing?${h(activity)}">Processing graph</a>` : ''}
      </div>
    </header>
    ${story?.fragments?.length > 1 ? `<label class="v2-story-fragment">Scene graph <select id="v2StoryFragment">
      <option value="">Choose a scene</option>
      ${story.fragments.map((item) => `<option value="${h(item.id)}" ${story.fragment === item.id ? 'selected' : ''}>${h(item.title)}</option>`).join('')}
    </select></label>` : ''}
    ${story?.bridge_state === 'planned' ? '<p class="v2-story-message">The saved bridge is awaiting application. Its written beats appear after the draft is applied.</p>' : ''}
    ${state.storyError ? `<p class="v2-story-message" role="alert">${h(state.storyError)} <button id="v2StoryRefresh" class="v2-tl-btn">Reload</button></p>` : ''}
    ${!beat ? `<p class="v2-story-message" role="status">${state.storyError ? 'Story beats are unavailable for this saved revision.'
      : !story && (state.busy || episode?.head) ? 'Opening the saved story…' : 'Choose or import a saved scene graph to show its beats.'}</p>`
      : `<section class="v2-story-track" aria-label="Story timeline">
      <nav class="v2-story-chapters" aria-label="Scene stops">
        ${story.scenes.filter((scene) => scene.beats.length).map((scene) => `<button type="button" class="v2-tl-btn"
          data-story-stop="${h(scene.beats[0].id)}" ${beat.scene.id === scene.id ? 'aria-current="step"' : ''}>${h(sceneTitle(scene.title))}</button>`).join('')}
      </nav>
      <div id="v2StoryLane" class="v2-story-lane" aria-label="Beat strip">
        ${story.scenes.map((scene) => `<section class="v2-story-scene" aria-label="${h(scene.title)}">
          <h2>${h(sceneTitle(scene.title))}</h2>
          <div class="v2-story-beats">${scene.beats.map((item) => `<button type="button" class="v2-story-beat"
            data-story-beat="${h(item.id)}" data-kind="${h(item.kind)}" ${item.id === beat.id ? 'aria-current="step"' : ''}>
            <strong>${h(label(item))}</strong>
            ${item.clips.length ? `<span class="v2-story-pin">${item.clips.length} ${item.clips.length === 1 ? 'clip' : 'clips'}</span>`
              : item.kind === 'frozen' ? '<span>Frozen · 100%</span>' : item.kind === 'retained' ? '<span>Source rejoin</span>' : ''}
            ${item.media?.length ? `<span class="v2-story-pin">${item.media.length} ${item.media.length === 1 ? 'media link' : 'media links'}</span>` : ''}
          </button>`).join('')}</div>
        </section>`).join('')}
      </div>
      <footer class="v2-story-controls">
        <button type="button" class="v2-tl-btn" data-story-stop="${h(rows[index - 1]?.id)}" ${index === 0 ? 'disabled' : ''}>← Previous beat</button>
        <span aria-live="polite">Beat ${index + 1} of ${rows.length}</span>
        <button type="button" class="v2-tl-btn" data-story-stop="${h(rows[index + 1]?.id)}" ${index + 1 === rows.length ? 'disabled' : ''}>Next beat →</button>
      </footer>
    </section>
    <article class="v2-story-detail" aria-label="Selected beat">
      <div class="v2-story-text">
        <p class="v2-story-context">${h(sceneTitle(beat.scene.title))}${beat.kind === 'frozen' ? ' · Frozen passage'
          : beat.kind === 'retained' ? ` · Kept from source r${story.retained.revision}` : ''}</p>
        <h2>${h(label(beat))}</h2>
        <blockquote>${h(beat.passage.text)}</blockquote>
        <div class="v2-tl-actions">
          <button type="button" class="v2-tl-btn v2-tl-btn-primary" id="v2StoryCompose">Open passage in Compose</button>
          <a class="v2-tl-btn" href="/mind-inspector?${h(mindQuery.toString())}">Inspect Minds</a>
          ${attach ? `<a class="v2-tl-btn" href="${h(attach)}">Attach a clip</a>` : ''}
          <a class="v2-tl-btn" href="${h(mediaDestination(story, beat))}">Beat media</a>
          <a class="v2-tl-btn" href="${h(mediaDestination(story, beat, null, true))}">Scene media</a>
        </div>
        ${beat.media?.length ? `<ul class="v2-story-cast" aria-label="Media on this beat">
          ${beat.media.map(({ asset, segment }) => `<li><a href="${h(mediaDestination(story, beat, segment.id))}">${h(asset.name)}</a> · ${h(segment.purpose)}</li>`).join('')}
        </ul>` : ''}
        ${beat.scene.media?.length ? `<ul class="v2-story-cast" aria-label="Media on this scene">
          ${beat.scene.media.map(({ asset, segment }) => `<li><a href="${h(mediaDestination(story, beat, segment.id, true))}">${h(asset.name)}</a> · ${h(segment.purpose)}</li>`).join('')}
        </ul>` : ''}
        ${Object.keys(beat.actors || {}).length ? `<details class="v2-story-cast"><summary>Active cast</summary>
          <ul>${Object.values(beat.actors).map((actor) => `<li>${h(FORMS[actor.form] || actor.form.replace(/[-_]/g, ' '))} · ${h(actor.location)}</li>`).join('')}</ul></details>` : ''}
      </div>
      ${clip ? `<aside class="v2-story-media" aria-label="Pinned media">
        ${beat.clips.length > 1 ? `<label>Source clip <select id="v2StoryClipSelect">${beat.clips.map((item) => `<option value="${h(item.id)}"
          ${clip.id === item.id ? 'selected' : ''}>${h(PURPOSE[item.purpose])} · ${h(item.name)}</option>`).join('')}</select></label>` : ''}
        <p class="v2-story-context">${h(PURPOSE[clip.purpose])}</p><h3>${h(clip.name)}</h3>
        <p class="v2-story-clip-range">${time(clip.start_ms)} – ${time(clip.end_ms)}
          ${clip.purpose === 'structure' ? ` · ${clip.operator === 'invert_merge' ? 'Reverse the merge' : 'Reuse the merge'}` : ''}</p>
        ${clip.note ? `<p>${h(clip.note)}</p>` : ''}
        ${media ? `<video id="v2StoryVideo" preload="metadata" playsinline src="${h(media)}" aria-label="${h(clip.name)}"></video>
          <button type="button" class="v2-tl-btn" id="v2StoryPlay">Play pinned range</button><span id="v2StoryMediaStatus" role="status"></span>`
          : '<p role="status">Media unavailable in this copy.</p>'}
      </aside>` : ''}
    </article>
    ${story.drafts?.length ? `<details class="v2-story-variants"><summary>Saved bridge drafts (${story.drafts.length})</summary>
      ${story.drafts.map((draft, i) => `<button type="button" class="v2-tl-btn" data-story-draft="${h(draft.id)}">
        Draft ${i + 1} · ${h(draft.in_manuscript ? 'In manuscript' : draft.status.toLowerCase())}</button>`).join('')}</details>` : ''}`}
  </div>`;
}

export function bindStoryTimeline({ state, onEpisodeCards, onPick, onClip, onOpen, onReload, onDraft }) {
  document.getElementById('v2EpisodeCards')?.addEventListener('click', onEpisodeCards);
  document.getElementById('v2StoryRefresh')?.addEventListener('click', () => onReload());
  document.getElementById('v2StoryFragment')?.addEventListener('change', (event) => onReload(event.target.value));
  document.querySelectorAll('[data-story-stop],[data-story-beat]').forEach((button) => {
    button.addEventListener('click', () => onPick(button.dataset.storyStop || button.dataset.storyBeat));
  });
  document.querySelectorAll('[data-story-draft]').forEach((button) => {
    button.addEventListener('click', () => onDraft(button.dataset.storyDraft));
  });
  const beat = currentBeat(state, storyRows(state.storyTimeline));
  if (!beat) return;
  document.getElementById('v2StoryCompose')?.addEventListener('click', () => onOpen(beat));
  document.getElementById('v2StoryClipSelect')?.addEventListener('change', (event) => onClip(event.target.value));
  const lane = document.getElementById('v2StoryLane');
  const card = lane.querySelector('[aria-current="step"]');
  if (card) requestAnimationFrame(() => {
    if (!card.isConnected) return;
    const left = card.getBoundingClientRect().left - lane.getBoundingClientRect().left + lane.scrollLeft;
    if (left < lane.scrollLeft || left + card.offsetWidth > lane.scrollLeft + lane.clientWidth) {
      lane.scrollLeft = Math.max(0, left - lane.clientWidth * 0.18);
    }
  });
  const clip = beat.clips.find((item) => item.id === state.storyClip) || beat.clips[0];
  const video = document.getElementById('v2StoryVideo');
  if (!video || !clip) return;
  const button = document.getElementById('v2StoryPlay');
  const status = document.getElementById('v2StoryMediaStatus');
  const start = clip.start_ms / 1000;
  const end = clip.end_ms / 1000;
  video.addEventListener('error', () => {
    button.disabled = true;
    status.textContent = 'This clip could not be opened.';
  });
  video.addEventListener('loadedmetadata', () => { video.currentTime = start; }, { once: true });
  let animation = 0;
  function stopAtEnd() {
    if (!video.isConnected || video.paused) return;
    if (video.currentTime >= end) {
      video.pause();
      video.currentTime = end;
      status.textContent = 'Pinned range played';
    } else animation = requestAnimationFrame(stopAtEnd);
  }
  video.addEventListener('pause', () => {
    cancelAnimationFrame(animation);
    button.textContent = 'Play pinned range';
  });
  button.addEventListener('click', async () => {
    if (!video.paused) { video.pause(); return; }
    status.textContent = '';
    try {
      video.currentTime = start;
      await video.play();
      button.textContent = 'Pause';
      animation = requestAnimationFrame(stopAtEnd);
    } catch (_) { status.textContent = 'This clip could not be played.'; }
  });
}
