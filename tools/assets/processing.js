import { NoirApi } from './v2/api.js';

const at = (id) => document.getElementById(id);
const query = new URLSearchParams(location.search);
const episode = query.get('episode');
const statuses = {
  QUEUED: 'Queued', RUNNING: 'Running', COMPLETED: 'Completed', SKIPPED: 'Skipped',
  FAILED: 'Failed', UNKNOWN: 'Interrupted',
  CANCELLED: 'Cancelled', STALE: 'Source changed', PARTIAL: 'Partial',
};
let scope;
let selectedJob = query.get('job') || '';
let selectedStep = '';
let previous = '';
let jobs = [];

const story = new URLSearchParams({ episode, view: 'timeline', track: 'story' });
for (const key of ['story-fragment', 'story-beat']) if (query.has(key)) story.set(key, query.get(key));
at('story').href = `/v2?${story}`;

function make(tag, content, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = content;
  return node;
}

function timeText(ms) {
  if (ms === null) return '';
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function stateText(state) {
  if (at('connection').textContent !== state) at('connection').textContent = state;
}

function showDetails(step) {
  at('step-title').textContent = step?.label || 'Step details';
  at('step-status').textContent = step
    ? [statuses[step.status], timeText(step.elapsed_ms), step.error || step.reason].filter(Boolean).join(' · ')
    : 'Select a step to see its receipt.';
  const sections = [];
  for (const [name, value] of [['Input', step?.inputs], ['Output', step?.outputs]]) {
    if (!value || !Object.keys(value).length) continue;
    const section = make('section', '');
    section.append(make('h3', name), make('pre', JSON.stringify(value, null, 2)));
    sections.push(section);
  }
  at('details').replaceChildren(...sections);
}

function render() {
  const current = jobs.find((job) => job.id === selectedJob) || jobs[0];
  const focus = document.activeElement?.dataset.focus;
  const graph = at('graph');
  const offset = graph.scrollLeft;
  const picks = [make('button', 'Follow latest', 'job-choice')];
  picks[0].dataset.focus = 'latest';
  picks[0].ariaPressed = String(!selectedJob);
  picks[0].onclick = () => { selectedJob = ''; selectedStep = ''; render(); };
  for (const job of jobs) {
    const button = make('button', '', 'job-choice');
    button.dataset.focus = job.id;
    button.ariaPressed = String(selectedJob === job.id);
    button.append(make('strong', job.title), make('span', statuses[job.status]),
      make('small', new Date(job.created_at * 1000).toLocaleTimeString()));
    button.onclick = () => { selectedJob = job.id; selectedStep = ''; render(); };
    picks.push(button);
  }
  at('jobs').replaceChildren(...(jobs.length ? picks : [make('p', 'No jobs yet.', 'hint')]));
  at('job-title').textContent = current?.title || 'Job stages';
  at('graph-empty').hidden = Boolean(current);
  const badge = at('job-state');
  badge.hidden = !current;
  badge.textContent = current ? `${statuses[current.status]} · ${timeText(current.elapsed_ms)}` : '';
  if (current?.error) badge.title = current.error;
  else badge.removeAttribute('title');
  badge.dataset.state = current?.status || '';
  const active = current?.steps.find((step) => step.id === selectedStep)
    || current?.steps.find((step) => step.status === 'RUNNING' || step.status === 'FAILED' || step.status === 'UNKNOWN')
    || current?.steps.find((step) => step.status === 'COMPLETED') || current?.steps[0];
  const stages = new Map();
  for (const step of current?.steps || []) {
    if (!stages.has(step.stage)) {
      const group = make('li', '', 'stage');
      group.append(make('h3', step.stage));
      stages.set(step.stage, group);
    }
    const button = make('button', '', 'step');
    button.dataset.state = step.status;
    button.dataset.focus = `step-${step.id}`;
    button.ariaPressed = String(active === step);
    const status = make('span', '', 'step-status');
    if (step.status === 'RUNNING') {
      const spinner = make('i', '', 'spinner');
      spinner.ariaHidden = 'true';
      status.append(spinner);
    }
    const message = make('span', [statuses[step.status], timeText(step.elapsed_ms)].filter(Boolean).join(' · '));
    message.dataset.elapsed = step.id;
    status.append(message);
    button.append(make('strong', step.label), status);
    button.onclick = () => { selectedStep = step.id; render(); };
    stages.get(step.stage).append(button);
  }
  graph.replaceChildren(...stages.values());
  graph.scrollLeft = offset;
  showDetails(active);
  if (focus) document.querySelector(`[data-focus="${CSS.escape(focus)}"]`)?.focus({ preventScroll: true });
}

function refreshTimes() {
  const job = jobs.find((item) => item.id === selectedJob) || jobs[0];
  if (!job || (job.status !== 'RUNNING' && job.status !== 'QUEUED')) return;
  at('job-state').textContent = `${statuses[job.status]} · ${timeText(job.elapsed_ms)}`;
  const running = job.steps.find((step) => step.status === 'RUNNING');
  if (!running) return;
  at('graph').querySelector(`[data-elapsed="${CSS.escape(running.id)}"]`).textContent =
    `Running · ${timeText(running.elapsed_ms)}`;
  if (!selectedStep || selectedStep === running.id) at('step-status').textContent = `Running · ${timeText(running.elapsed_ms)}`;
}

async function refresh() {
  try {
    const response = await NoirApi.episodeCommand({ action: 'processing.open', ...scope });
    jobs = response.jobs;
    if (selectedJob && !jobs.some((job) => job.id === selectedJob)) {
      const saved = await NoirApi.episodeCommand({ action: 'processing.open', ...scope, job: selectedJob });
      jobs = [...saved.jobs, ...jobs];
    }
    const next = JSON.stringify(jobs, (key, value) => key === 'elapsed_ms' ? undefined : value);
    if (previous !== next) { previous = next; render(); }
    else refreshTimes();
    stateText('Live');
  } catch (error) {
    stateText(`Connection interrupted · ${error.message}`);
    // Keep the last receipts readable, with no assumption that work is still running.
    for (const spinner of document.querySelectorAll('.spinner')) spinner.remove();
    previous = '';
  } finally {
    setTimeout(refresh, 550);
  }
}

async function start() {
  try {
    if (!episode) throw new Error('Open Processing from an episode’s Story Beats.');
    const state = await NoirApi.getEpisodeState(episode);
    scope = { project: state.scope.project_id, universe: state.scope.universe_id, episode, branch: state.episode.branch };
    at('scope').textContent = `${state.episode.title} · ${scope.branch}`;
    await refresh();
  } catch (error) {
    stateText(error.message);
  }
}

void start();
