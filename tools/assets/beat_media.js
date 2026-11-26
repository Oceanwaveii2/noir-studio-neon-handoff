import { NoirApi } from './v2/api.js';

const at = (id) => document.getElementById(id);
const query = new URLSearchParams(location.search);
const episode = query.get('episode');
const types = {
  document: ['reference'], image: ['appearance', 'reference'],
  audio: ['performance', 'timing', 'reference'], video: ['cutaway', 'performance', 'timing', 'reference'],
};
const purposes = {
  reference: 'Reference', appearance: 'Appearance', performance: 'Performance',
  timing: 'Timing', cutaway: 'Audience cutaway',
};
const mode = query.has('form') ? 'form' : query.has('scene') ? 'scene' : 'beat';
const destination = mode === 'form' ? { character: query.get('character'), form: query.get('form') }
  : { timeline_revision: Number(query.get('timeline_revision')),
    [mode]: query.get(mode), [mode === 'scene' ? 'scene_sha256' : 'passage_sha256']:
      query.get(mode === 'scene' ? 'scene_sha256' : 'passage_sha256') };
if (query.has('fragment')) destination.fragment = query.get('fragment');
const story = new URLSearchParams(mode === 'form' ? { episode, view: 'graph' }
  : { episode, view: 'timeline', track: 'story', 'story-beat': destination.beat || query.get('return-beat') || '' });
if (destination.fragment) story.set('story-fragment', destination.fragment);
at('story').href = `/v2?${story}`;
if (mode === 'form') at('story').textContent = '← Character Graph';
at('upload-status').textContent = `Opening the saved ${mode}…`;
at('no-pins').textContent = `No media linked to this ${mode}.`;
at('activity').href = `/processing?${new URLSearchParams({ episode })}`;

let scope;
let library;
let choice;
let readSelector;
let loading = false;
let selectedPreview = 0;
let directionTargets = [];
let directionPending = false;

const command = (name, rest = {}) => NoirApi.episodeCommand({ action: `scene.media.${name}`, ...scope, ...rest });
const seconds = (ms) => (ms / 1000).toFixed(3);

function selectOptions(select, placeholder, values, current) {
  select.replaceChildren(new Option(placeholder, ''), ...values.map(([id, name]) => new Option(name, id)));
  select.value = current || '';
  select.disabled = !values.length;
}

function describe(selector) {
  if (selector.kind === 'text') return `Characters ${selector.start}–${selector.end}`;
  if (selector.kind === 'region') {
    return `${selector.width / 100}% × ${selector.height / 100}% at (${selector.x / 100}%, ${selector.y / 100}%)`;
  }
  return `${seconds(selector.start)}–${seconds(selector.end)} s`;
}

function segmentTitle(segment) {
  return `${library.assets.find((source) => source.id === segment.asset)?.name || 'Source'} · ${purposes[segment.purpose]} · ${describe(segment.selector)}`;
}

async function loadLibrary() {
  library = await command('open', destination);
  selectOptions(at('source'), 'Choose an original', library.assets.map((item) => [item.id, item.name]), choice?.asset.id);
  selectOptions(at('segments'), 'Choose a saved segment',
    library.segments.map((item) => [item.id, segmentTitle(item)]), choice?.segment?.id);
  const pinned = library.pins.map((item) => library.segments.find((segment) => segment.id === item.segment)).filter(Boolean);
  at('no-pins').hidden = Boolean(pinned.length);
  at('pins').replaceChildren(...pinned.map((item) => {
    const link = document.createElement('button');
    link.type = 'button';
    link.textContent = segmentTitle(item);
    link.onclick = () => void choose(item.asset, item.id);
    const entry = document.createElement('li');
    entry.append(link);
    return entry;
  }));
  at('beat-title').textContent = library.target.label;
}

async function loadDirectionTargets() {
  if (mode === 'beat') {
    directionTargets = [{ label: library.target.label, fields: destination }];
    return;
  }
  const body = { ...scope, timeline_revision: library.timeline_revision };
  if (destination.fragment) body.fragment = destination.fragment;
  const track = await NoirApi.episodeCommand({ ...body, action: 'scene.timeline.open' });
  directionTargets = track.scenes.filter((scene) => mode !== 'scene' || scene.id === library.target.scene)
    .flatMap((scene) => scene.beats.filter((beat) => !['frozen', 'retained'].includes(beat.kind)).map((beat) => ({
      label: `${scene.title} · ${beat.label}`,
      fields: { timeline_revision: track.timeline_revision, beat: beat.id, passage_sha256: beat.passage.sha256,
        ...(track.fragment ? { fragment: track.fragment } : {}) },
    })));
  if (mode === 'form' && track.bridge_state === 'planned') {
    const draft = await NoirApi.episodeCommand({ action: 'scene.bridge.preview', ...track.scope, bridge: track.bridge.bridge });
    for (const scene of draft.scope.continuation.program.scenes) {
      for (const beat of scene.beats) {
        directionTargets.push({ label: `Planned · ${beat.id.replaceAll('-', ' ')}`,
          fields: { timeline_revision: track.timeline_revision, bridge: track.bridge.bridge, beat: beat.id } });
      }
    }
  }
  at('direction-target').replaceChildren(...directionTargets.map((item, index) => new Option(item.label, index)));
}

function currentDirection() {
  const target = directionTargets[mode === 'beat' ? 0 : at('direction-target').selectedIndex];
  const pin = library?.pins.find((item) => item.segment === choice?.segment?.id);
  const current = library?.overrides?.find((item) => item.pin === pin?.id
    && item.target.beat === target?.fields.beat && item.target.timeline_revision === target?.fields.timeline_revision
    && item.target.bridge?.bridge === target?.fields.bridge);
  return { pin, target, current };
}

function updateDirection() {
  const { pin, target, current } = currentDirection();
  const purpose = choice?.segment?.purpose;
  at('direction-panel').hidden = !(pin && target && ['timing', 'performance', 'appearance'].includes(purpose));
  at('direction-target-field').hidden = mode === 'beat';
  at('direction').value = current?.direction || '';
  at('direction').placeholder = purpose === 'appearance' ? 'Use the outfit for Nurse Franny'
    : purpose === 'performance' ? 'Use the speaker’s delivery for Rainee 2' : 'Borrow the longest pause before the reply';
  at('clear-direction').hidden = !current;
  const pause = current?.evidence?.quiet_interval;
  at('direction-status').textContent = current
    ? ['Saved', current.actor?.label || 'Whole beat', pause ? `${pause.duration_ms} ms source pause` : 'Saved source observation'].join(' · ')
    : '';
}

async function changeDirection(clear = false) {
  const { pin, target, current } = currentDirection();
  if (!pin || !target || directionPending) return;
  directionPending = true;
  at('set-direction').disabled = at('clear-direction').disabled = true;
  at('direction-status').textContent = 'Checking the exact beat and source…';
  try {
    if (clear) await command('override.clear', { override: current.id });
    else {
      const direction = { pin: pin.id, destination: target.fields, direction: at('direction').value };
      const preview = await command('override.preview', direction);
      if (preview.status !== 'READY') throw new Error(preview.reason);
      const result = await command('override.apply', { ...direction, plan: preview.override.id, previous: preview.previous });
      if (result.status !== 'SAVED') throw new Error(result.reason);
    }
    await loadLibrary();
    updateDirection();
    if (clear) at('direction-status').textContent = 'Direction cleared. The source is still linked here.';
  } catch (error) { at('direction-status').textContent = error.message; }
  finally { at('set-direction').disabled = at('clear-direction').disabled = directionPending = false; }
}

function field(label, value, min, max, step) {
  const block = document.createElement('label');
  block.className = 'field';
  block.textContent = label;
  const input = document.createElement('input');
  input.type = 'number';
  input.min = min;
  input.max = max;
  input.step = step;
  input.value = value;
  input.required = true;
  block.append(input);
  at('selector').append(block);
  return input;
}

function previewButton(label, fn) {
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = label;
  button.onclick = fn;
  at('preview').append(button);
  return button;
}

function textPreview(source, text, saved) {
  const preview = document.createElement('textarea');
  preview.readOnly = true;
  preview.ariaLabel = 'Extracted text';
  // Textarea normalizes CRLF. Translate its selection back to source offsets.
  preview.value = text;
  at('preview').append(preview);
  const sourcePoints = [...text];
  const sourceOffsets = [0];
  for (let i = 0; i < sourcePoints.length; i += 1) {
    const point = sourcePoints[i];
    if (point === '\r' && sourcePoints[i + 1] === '\n') i += 1;
    for (let offset = 1; offset <= point.length; offset += 1) sourceOffsets.push(i + 1);
  }
  if (saved) {
    preview.value = sourcePoints.slice(saved.start, saved.end).join('');
    return;
  }
  const size = source.analysis.characters;
  const start = field('Start character', 0, 0, size - 1, 1);
  const end = field('End character', Math.min(400, size), 1, size, 1);
  previewButton('Use selected text', () => {
    if (preview.selectionStart === preview.selectionEnd) {
      at('status').textContent = 'Select a passage in the source text.';
      return;
    }
    start.value = sourceOffsets[preview.selectionStart];
    end.value = sourceOffsets[preview.selectionEnd];
    at('status').textContent = '';
  });
  readSelector = () => ({ start: start.valueAsNumber, end: end.valueAsNumber });
}

function imagePreview(asset, url, saved) {
  const region = document.createElement('div');
  region.className = 'image-region';
  const image = new Image();
  image.alt = asset.name;
  image.src = url;
  const outline = document.createElement('span');
  region.append(image, outline);
  at('preview').append(region);
  const keys = ['x', 'y', 'width', 'height'];
  const labels = ['Left %', 'Top %', 'Width %', 'Height %'];
  const initial = [0, 0, 100, 100];
  const inputs = saved ? [] : labels.map((label, index) => field(label, initial[index], index < 2 ? 0 : 0.01, 100, 0.01));
  readSelector = () => Object.fromEntries(keys.map((key, i) => [key, Math.round(inputs[i].valueAsNumber * 100)]));
  function update() {
    const box = saved || readSelector();
    outline.hidden = !(box.x + box.width <= 10000 && box.y + box.height <= 10000);
    for (const [index, property] of ['left', 'top', 'width', 'height'].entries()) {
      outline.style[property] = `${box[keys[index]] / 100}%`;
    }
  }
  inputs.forEach((input) => input.addEventListener('input', update));
  update();
}

function timedPreview(asset, url, saved) {
  const player = document.createElement(asset.kind);
  player.src = url;
  player.preload = 'metadata';
  player.playsInline = true;
  player.ariaLabel = asset.name;
  at('preview').append(player);
  const limit = asset.analysis.duration_ms;
  if (!saved) {
    const start = field('Start seconds', 0, 0, seconds(limit - 1), .001);
    const end = field('End seconds', seconds(Math.min(limit, 3000)), .001, seconds(limit), .001);
    readSelector = () => ({ start: Math.round(start.valueAsNumber * 1000), end: Math.round(end.valueAsNumber * 1000) });
  }
  let playUntil;
  let frame;
  const button = previewButton('Play range', async () => {
    if (!player.paused) { player.pause(); return; }
    const range = saved || readSelector();
    if (!(range.start >= 0 && range.start < range.end && range.end <= limit)) {
      at('status').textContent = 'Choose a range within the source.';
      return;
    }
    try {
      playUntil = range.end / 1000;
      player.currentTime = range.start / 1000;
      await player.play();
      cancelAnimationFrame(frame);
      button.textContent = 'Pause';
      frame = requestAnimationFrame(watch);
    } catch (_) { at('status').textContent = 'This range could not be played.'; }
  });
  function watch() {
    if (!player.isConnected) { player.pause(); return; }
    if (player.paused) return;
    if (player.currentTime >= playUntil) {
      player.pause();
      player.currentTime = playUntil;
    } else frame = requestAnimationFrame(watch);
  }
  player.addEventListener('pause', () => { cancelAnimationFrame(frame); button.textContent = 'Play range'; });
  player.addEventListener('timeupdate', () => {
    if (player.currentTime >= playUntil && !player.paused) { player.pause(); player.currentTime = playUntil; }
  });
  player.addEventListener('error', () => { button.disabled = true; at('status').textContent = 'This original could not be played.'; });
}

async function choose(assetId, segmentId = '') {
  const attempt = ++selectedPreview;
  at('preview').querySelector('audio, video')?.pause();
  at('preview').replaceChildren();
  at('selector').replaceChildren();
  at('attachment').hidden = true;
  at('status').textContent = '';
  at('source').value = assetId;
  at('segments').value = segmentId;
  choice = null;
  updateDirection();
  readSelector = null;
  if (!assetId) return;
  try {
    const { asset, text } = await command('source', { asset: assetId });
    if (attempt !== selectedPreview) return;
    const segment = library.segments.find((item) => item.id === segmentId);
    const saved = segment?.selector;
    const params = new URLSearchParams({ ...scope, id: assetId });
    const url = `/api/beat-media/original?${params}`;
    at('original').href = `${url}&download=1`;
    at('original').title = `SHA-256 ${asset.sha256}`;
    if (asset.kind === 'document') textPreview(asset, text, saved);
    else if (asset.kind === 'image') imagePreview(asset, url, saved);
    else timedPreview(asset, url, saved);
    at('selection').textContent = segment
      ? [describe(saved), purposes[segment.purpose], segment.observation].filter(Boolean).join(' · ')
      : '';
    at('purpose-field').hidden = at('observation-field').hidden = Boolean(segment);
    at('purpose').replaceChildren(...types[asset.kind].map((item) => new Option(purposes[item], item)));
    at('observation').value = '';
    at('attach').textContent = segment ? 'Attach saved segment' : `Attach to ${mode}`;
    choice = { asset, segment };
    updateDirection();
    at('attachment').hidden = false;
  } catch (error) {
    if (attempt === selectedPreview) at('status').textContent = error.message;
  }
}

async function upload(files) {
  if (!library || loading || !files.length) return;
  loading = true;
  at('files').disabled = at('import').disabled = true;
  const errors = [];
  const imported = [];
  for (const file of files) {
    at('upload-status').textContent = `Importing ${file.name}…`;
    try {
      const params = new URLSearchParams({ ...scope, name: file.name });
      const request = await fetch(`/api/beat-media/upload?${params}`, { method: 'POST', body: file,
        headers: { 'Content-Type': 'application/octet-stream' } });
      const result = await request.json();
      if (!request.ok) throw new Error(result.error || 'Import failed.');
      imported.push(result.asset);
    } catch (error) { errors.push(`${file.name} · ${error.message}`); }
  }
  try {
    await loadLibrary();
    if (imported.length) await choose(imported[0].id);
  } catch (error) { errors.push(error.message); }
  at('upload-status').textContent = [imported.length ? `${imported.length} imported.` : '', ...errors].filter(Boolean).join(' ');
  at('files').value = '';
  at('files').disabled = at('import').disabled = false;
  loading = false;
}

at('source').onchange = (event) => void choose(event.target.value);
at('direction-target').onchange = updateDirection;
at('direction-form').onsubmit = (event) => { event.preventDefault(); void changeDirection(); };
at('clear-direction').onclick = () => void changeDirection(true);
at('segments').onchange = (event) => {
  const item = library?.segments.find((segment) => segment.id === event.target.value);
  void choose(item?.asset || choice?.asset.id || '', item?.id);
};
at('upload').onsubmit = (event) => { event.preventDefault(); void upload([...at('files').files]); };
at('drop').ondragover = (event) => { event.preventDefault(); at('drop').dataset.drag = ''; };
at('drop').ondragleave = () => { delete at('drop').dataset.drag; };
at('drop').ondrop = (event) => {
  event.preventDefault();
  delete at('drop').dataset.drag;
  void upload([...event.dataTransfer.files]);
};
at('attachment').onsubmit = async (event) => {
  event.preventDefault();
  if (!choice || at('attach').disabled) return;
  const input = choice.segment ? { segment: choice.segment.id } : {
    asset: choice.asset.id, selector: readSelector(), purpose: at('purpose').value, observation: at('observation').value,
  };
  at('attach').disabled = true;
  try {
    const result = await command('attach', { ...destination, ...input });
    await loadLibrary();
    await choose(result.segment.asset, result.segment.id);
    at('status').textContent = `Saved on this ${mode}.`;
  } catch (error) { at('status').textContent = error.message; }
  finally { at('attach').disabled = false; }
};

async function start() {
  try {
    if (!episode || !destination[mode]) throw new Error('Open media from a saved scene, beat or form board.');
    const state = await NoirApi.getEpisodeState(episode);
    scope = { project: state.scope.project_id, universe: state.scope.universe_id, episode, branch: state.episode.branch };
    at('scope').textContent = `${state.episode.title} · ${scope.branch}`
      + (mode === 'form' ? ' · Form board' : ` · r${destination.timeline_revision}`);
    await loadLibrary();
    await loadDirectionTargets().catch((error) => { at('direction-status').textContent = error.message; });
    at('files').disabled = at('import').disabled = false;
    at('upload-status').textContent = 'Document, image, WAV, MP4 or WebM';
    const saved = library.segments.find((item) => item.id === query.get('segment'));
    if (saved) await choose(saved.asset, saved.id);
  } catch (error) { at('upload-status').textContent = error.message; }
}

void start();
