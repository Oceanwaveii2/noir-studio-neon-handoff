/* Noir Fiction Studio v2 — Typed REST API Client */

function request(url, options = {}) {
  return fetch(url, options);
}

function httpError(response, message) {
  const error = new Error(message || 'Request failed (' + response.status + ')');
  error.status = response.status;
  return error;
}

async function requestJson(url, options = {}) {
  const response = await request(url, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
  const text = await response.text();
  let data = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch (_) {
      if (!response.ok) throw httpError(response);
      throw new Error(`Invalid JSON from ${url} (${response.status})`);
    }
  }
  if (!response.ok) {
    throw httpError(response, data.error);
  }
  if (options.method === 'POST' && typeof options.body === 'string') {
    const { action } = JSON.parse(options.body);
    const historyWrite = {
      '/api/form-graph': true,
      '/api/timeline': !['open', 'events'].includes(action),
      '/api/notebook': !['open', 'current', 'speakers', 'speaker_options'].includes(action),
      '/api/beat-rhythm': ['structure_save', 'save', 'undo', 'redo'].includes(action),
      '/api/word-prep': true,
      '/api/episode-command': /^(?:timeline\.(move|rename|cover\.set|archive|restore|undo|redo)|draft\.(apply|favorite.*)|notebook\.(undo|redo)|graph\.(undo|redo)|episode\.create|intake\.create|word_prep\.promote)$/.test(action),
    }[url];
    if (historyWrite) window.dispatchEvent(new Event('noir:history-changed'));
  }
  return data;
}

export const NoirApi = {
  getSampleProjects() {
    return requestJson('/api/sample-projects');
  },

  uploadBeatMedia(scope, file) {
    const query = new URLSearchParams({ ...scope, name: file.name });
    return requestJson('/api/beat-media/upload?' + query, {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: file,
    });
  },

  getAudioManifest() {
    return requestJson('/assets/audio/audio_manifest.json');
  },

  async getAudioBytes(url) {
    const response = await request(url);
    if (!response.ok) throw httpError(response);
    return response.arrayBuffer();
  },

  getLottieAsset(name) {
    return requestJson('/assets/vfx/lottie/' + encodeURIComponent(name) + '.json');
  },

  getTimeline() {
    return requestJson('/api/timeline');
  },

  getEpisodeState(episode) {
    const query = new URLSearchParams({ episode });
    return requestJson(`/api/state?${query}`);
  },

  getEpisodeContext(episode, beat = 0, viewpoint = '') {
    const query = new URLSearchParams({ episode, beat: String(beat) });
    if (viewpoint) query.set('viewpoint', viewpoint);
    return requestJson(`/api/episode-context?${query}`);
  },

  notebookAction(payload) {
    return requestJson('/api/notebook', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  timelineAction(payload) {
    return requestJson('/api/timeline', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  draftsAction(payload) {
    return requestJson('/api/drafts', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  getFormGraph(episode) {
    const query = new URLSearchParams();
    if (episode) query.set('episode', episode);
    return requestJson(`/api/form-graph?${query}`);
  },

  formGraphAction(payload) {
    return requestJson('/api/form-graph', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  characterProfileAction(payload) {
    return requestJson('/api/character-profiles', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  getBeatMap(episode, revision, viewpoint = '') {
    const query = new URLSearchParams({ episode, revision: String(revision) });
    if (viewpoint) query.set('viewpoint', viewpoint);
    return requestJson(`/api/beat-map?${query}`);
  },

  beatAnchorsAction(payload) {
    return requestJson('/api/beat-anchors', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  beatRhythmAction(payload) {
    return requestJson('/api/beat-rhythm', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  beatGroupAction(payload) {
    return requestJson('/api/beat-group', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  episodeCommand(payload) {
    return requestJson('/api/episode-command', { method: 'POST', body: JSON.stringify(payload) });
  },

  promoteWordPrep(payload) {
    return requestJson('/api/word-prep', { method: 'POST', body: JSON.stringify(payload) });
  },

  intake(payload, signal) {
    return requestJson('/api/intake', { method: 'POST', body: JSON.stringify(payload), signal });
  },

  getBookPolicy() {
    return requestJson('/api/book-policy');
  },

  saveBookPolicy(payload) {
    return requestJson('/api/book-policy', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  getBookStatus(backend = 'none', provider = 'codex-session') {
    const query = new URLSearchParams({ backend, provider });
    return requestJson(`/api/book-status?${query}`);
  },

  getWriters() { return requestJson('/api/writers'); },

  scopedAction(payload) {
    return requestJson('/api/scoped', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  worldLawsAction(payload) {
    return requestJson('/api/world-laws', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  canonDiff(payload) {
    return requestJson('/api/canon-diff', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  canonProposals(payload) {
    return requestJson('/api/canon-proposals', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  slotInfill(payload) {
    return requestJson('/api/slot-infill', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  craftBrief(payload) {
    return requestJson('/api/craft-brief', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  cookEpisode(episode, viewpoint, timelineRevision, notebookRevision) {
    return requestJson('/api/cook', {
      method: 'POST',
      body: JSON.stringify({ episode, viewpoint, timeline_revision: timelineRevision, notebook_revision: notebookRevision }),
    });
  },

  getCookStatus(jobId) {
    const query = new URLSearchParams({ job_id: jobId });
    return requestJson(`/api/cook/status?${query}`);
  },
};
