const state = {
  csvPath: '',
  stories: [],
  selectedStory: null,
  storyDetail: null,
  storyScopeDefaults: {
    lob_scope: { mode: 'all', values: [] },
    stage_scope: { mode: 'all', values: [] },
  },
  storyScopeAuto: true,
  currentIntents: [],
  flowType: 'unordered',
  authorName: 'CASForge',
  feature: null,
  quality: {},
  unresolvedSteps: [],
  omittedItems: [],
  coverageGaps: [],
  page: 'intake',
  remapIndex: null,
  synthesisTimer: null,
  directFlowType: 'unordered',
};

// LOBs, stages, and families are loaded from /api/config (driven by config/domain_knowledge.json).
// Edit that file to add new options — no code change needed here.
let FAMILY_ORDER = [];
let LOB_PRESETS = [];
let STAGE_PRESETS = [];

async function loadConfig() {
  try {
    const res = await fetch('/api/config');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const cfg = await res.json();
    LOB_PRESETS = cfg.lobs || [];
    STAGE_PRESETS = cfg.stages || [];
    FAMILY_ORDER = cfg.families || [];
  } catch (e) {
    console.warn('Could not load /api/config:', e);
    LOB_PRESETS = ['All LOBs'];
    STAGE_PRESETS = ['All Stages'];
    FAMILY_ORDER = [];
  }
}
const SYNTHESIS_LINES = [
  'Reading Jira logic... Who wrote this? Interesting choice.',
  'Scanning Llama repository... Found some gems.',
  'Orchestrating test steps... Harmonizing logic.',
  'Are there comments? Checking for hidden traps...',
  'Finalizing the Blueprint...'
];

const storyListEl = document.getElementById('story-list');
const storyInsightEl = document.getElementById('story-insight');
const intakeMetricsEl = document.getElementById('intake-metrics');
const coverageGridEl = document.getElementById('coverage-grid');
const intentGalleryEl = document.getElementById('intent-gallery');
const featureEditorEl = document.getElementById('feature-editor');
const unresolvedListEl = document.getElementById('unresolved-list');
const artifactOverviewEl = document.getElementById('artifact-overview');
const synthesisModalEl = document.getElementById('synthesis-modal');
const remapModalEl = document.getElementById('remap-modal');

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function uniq(values) {
  const out = [];
  const seen = new Set();
  for (const raw of values || []) {
    const value = String(raw || '').trim();
    if (!value) continue;
    const key = value.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(value);
  }
  return out;
}

function parseCsvValues(raw) {
  return uniq(String(raw || '').split(',').map(item => item.trim()));
}

function normalizeScope(scope) {
  if (!scope || typeof scope !== 'object') return { mode: 'all', values: [] };
  const values = uniq(scope.values || []);
  return scope.mode === 'specific' && values.length
    ? { mode: 'specific', values }
    : { mode: 'all', values: [] };
}

function emptyStoryScopeDefaults() {
  return {
    lob_scope: { mode: 'all', values: [] },
    stage_scope: { mode: 'all', values: [] },
  };
}

function storyScopePayload() {
  return state.storyScopeAuto ? null : state.storyScopeDefaults;
}

function displayStoryScope(kind) {
  if (state.storyScopeAuto) return 'Auto (story inferred)';
  const key = kind === 'lob' ? 'lob_scope' : 'stage_scope';
  return scopeLabel(state.storyScopeDefaults[key], kind);
}

function allLabel(kind) {
  return kind === 'lob' ? 'All LOBs' : 'All Stages';
}

function scopeLabel(scope, kind) {
  const normalized = normalizeScope(scope);
  return normalized.mode === 'all' ? allLabel(kind) : normalized.values.join(', ');
}

function isScopeSelected(scope, label, kind) {
  const normalized = normalizeScope(scope);
  if (label === allLabel(kind)) return normalized.mode === 'all';
  return normalized.mode === 'specific' && normalized.values.some(value => value.toLowerCase() === label.toLowerCase());
}

function toggleScopeValue(scope, label, kind) {
  if (label === allLabel(kind)) return { mode: 'all', values: [] };
  const normalized = normalizeScope(scope);
  const values = normalized.mode === 'specific' ? [...normalized.values] : [];
  const idx = values.findIndex(item => item.toLowerCase() === label.toLowerCase());
  if (idx >= 0) values.splice(idx, 1);
  else values.push(label);
  return values.length ? { mode: 'specific', values: uniq(values) } : { mode: 'all', values: [] };
}

function normalizeIntentItem(item, idx) {
  if (typeof item === 'string') {
    return {
      id: `intent_${String(idx + 1).padStart(3, '0')}`,
      text: item,
      family: 'positive',
      inherit_story_scope: true,
      lob_scope: null,
      stage_scope: null,
      action_target: null,
      screen_hint: null,
      expected_outcome: null,
    };
  }
  return {
    id: item.id || `intent_${String(idx + 1).padStart(3, '0')}`,
    text: item.text || '',
    family: item.family || 'positive',
    inherit_story_scope: item.inherit_story_scope !== false,
    lob_scope: item.lob_scope || null,
    stage_scope: item.stage_scope || null,
    action_target: item.action_target || null,
    screen_hint: item.screen_hint || null,
    expected_outcome: item.expected_outcome || null,
  };
}

function getEffectiveIntentScope(intent) {
  if (!intent || intent.inherit_story_scope !== false) {
    return {
      lob_scope: normalizeScope(state.storyScopeDefaults.lob_scope),
      stage_scope: normalizeScope(state.storyScopeDefaults.stage_scope),
    };
  }
  return {
    lob_scope: normalizeScope(intent.lob_scope),
    stage_scope: normalizeScope(intent.stage_scope),
  };
}

function setStatus(id, message, kind = '') {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = message || '';
  el.className = `status-line${kind ? ` ${kind}` : ''}`;
}

function setPage(name) {
  state.page = name;
  document.querySelectorAll('.page').forEach((page) => {
    page.classList.toggle('active', page.id === `page-${name}`);
  });
  document.querySelectorAll('[data-progress-pill]').forEach((pill) => {
    const phase = pill.dataset.progressPill;
    pill.classList.toggle('active', phase === name);
    pill.classList.toggle('done', (phase === 'intake' && name !== 'intake') || (phase === 'refine' && name === 'artifact'));
  });
}

function renderScopeCloud(targetId, scope, presets, kind, onClick) {
  const target = document.getElementById(targetId);
  target.innerHTML = presets.map((label) => `
    <button class="chip ${isScopeSelected(scope, label, kind) ? 'active' : ''}" type="button" data-chip="${escapeHtml(label)}">${escapeHtml(label)}</button>
  `).join('');
  target.querySelectorAll('[data-chip]').forEach((btn) => btn.addEventListener('click', () => onClick(btn.dataset.chip)));
}

function renderStoryList() {
  document.getElementById('story-count').textContent = `${state.stories.length} loaded`;
  if (!state.stories.length) {
    storyListEl.innerHTML = '<div class="card-copy">Load a CSV and the queue will appear here.</div>';
    return;
  }
  storyListEl.innerHTML = state.stories.map((story) => `
    <button class="story-tile ${state.selectedStory && state.selectedStory.key === story.key ? 'active' : ''}" type="button" data-story-key="${escapeHtml(story.key)}">
      <div class="story-meta">
        <span class="story-key">${escapeHtml(story.key)}</span>
        <span class="story-type">${escapeHtml(story.type)}</span>
      </div>
      <div class="story-summary">${escapeHtml(story.summary)}</div>
    </button>
  `).join('');
  storyListEl.querySelectorAll('[data-story-key]').forEach((btn) => btn.addEventListener('click', () => selectStory(btn.dataset.storyKey)));
}

function renderStoryInsight() {
  const detail = state.storyDetail;
  document.getElementById('selected-story-key').textContent = detail ? detail.issue_key : 'No story';
  if (!detail) {
    storyInsightEl.innerHTML = '<div class="card-copy">Pick a story from the queue to inspect the summary, description, impacted areas, and acceptance context before extraction.</div>';
    return;
  }
  storyInsightEl.innerHTML = `
    <div class="insight-field"><strong>Summary</strong><div>${escapeHtml(detail.summary)}</div></div>
    <div class="insight-field"><strong>Description</strong><div>${escapeHtml(detail.description || detail.story_description || 'No description supplied.')}</div></div>
    <div class="insight-field"><strong>Impacted Areas</strong><div>${escapeHtml(detail.impacted_areas || 'Not specified')}</div></div>
    <div class="insight-field"><strong>Acceptance Criteria</strong><div>${escapeHtml(detail.acceptance_criteria || 'No acceptance criteria supplied.')}</div></div>
    ${detail.new_process ? `<div class="insight-field"><strong>System Process</strong><div>${escapeHtml(detail.new_process)}</div></div>` : ''}
    ${detail.supplemental_comments ? `<div class="insight-field"><strong>Comments</strong><div>${escapeHtml(detail.supplemental_comments)}</div></div>` : ''}
  `;
}

function renderIntakeMetrics() {
  const metrics = [
    ['Selected story', state.storyDetail ? state.storyDetail.issue_key : 'Not chosen'],
    ['LOB scope', displayStoryScope('lob')],
    ['Stage scope', displayStoryScope('stage')],
  ];
  intakeMetricsEl.innerHTML = metrics.map(([label, value]) => `
    <div class="metric-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>
  `).join('');
}

function renderIntake() {
  renderStoryList();
  renderStoryInsight();
  renderIntakeMetrics();
  renderScopeCloud('lob-chip-cloud', state.storyScopeDefaults.lob_scope, LOB_PRESETS, 'lob', (label) => {
    state.storyScopeAuto = false;
    state.storyScopeDefaults.lob_scope = toggleScopeValue(state.storyScopeDefaults.lob_scope, label, 'lob');
    renderIntake();
  });
  renderScopeCloud('stage-chip-cloud', state.storyScopeDefaults.stage_scope, STAGE_PRESETS, 'stage', (label) => {
    state.storyScopeAuto = false;
    state.storyScopeDefaults.stage_scope = toggleScopeValue(state.storyScopeDefaults.stage_scope, label, 'stage');
    renderIntake();
  });
  document.getElementById('author-name').value = state.authorName;
  document.getElementById('flow-ordered').classList.toggle('active', state.flowType === 'ordered');
  document.getElementById('flow-unordered').classList.toggle('active', state.flowType === 'unordered');
  document.getElementById('ignite-btn').disabled = !(state.storyDetail && state.flowType);
  wireEdgeLighting();
}

function familyCounts() {
  const counts = Object.fromEntries(FAMILY_ORDER.map((family) => [family, 0]));
  state.currentIntents.forEach((intent) => {
    counts[intent.family] = (counts[intent.family] || 0) + 1;
  });
  return counts;
}

function renderCoverage() {
  const counts = familyCounts();
  coverageGridEl.innerHTML = FAMILY_ORDER.map((family) => `
    <div class="coverage-chip">
      <strong>${counts[family] || 0}</strong>
      <span>${escapeHtml(family.replace(/_/g, ' '))}</span>
    </div>
  `).join('');
}

function renderRefinementHeader() {
  document.getElementById('refine-story-title').textContent = state.storyDetail ? state.storyDetail.summary : 'No story selected';
  document.getElementById('refine-story-key').textContent = state.storyDetail ? state.storyDetail.issue_key : '-';
  document.getElementById('refine-story-summary').textContent = state.storyDetail ? (state.storyDetail.new_process || state.storyDetail.description || 'Story loaded.') : 'Extract intents from the intake page to populate the gallery.';
  const scopeNotes = [
    `Story LOB: ${displayStoryScope('lob')}`,
    `Story Stage: ${displayStoryScope('stage')}`,
    `Flow: ${state.flowType}`,
  ];
  document.getElementById('refine-story-scope').innerHTML = scopeNotes.map((note) => `<span class="meta-tag">${escapeHtml(note)}</span>`).join('');
}
function renderIntentGallery() {
  const cards = state.currentIntents.map((intent, idx) => {
    const effectiveScope = getEffectiveIntentScope(intent);
    const hints = [
      intent.action_target ? `Target: ${intent.action_target}` : '',
      intent.screen_hint ? `Screen: ${intent.screen_hint}` : '',
      intent.expected_outcome ? `Outcome: ${intent.expected_outcome}` : '',
    ].filter(Boolean);
    const scopeText = intent.inherit_story_scope !== false
      ? `Inherited scope - ${scopeLabel(effectiveScope.lob_scope, 'lob')} / ${scopeLabel(effectiveScope.stage_scope, 'stage')}`
      : `Override scope - ${scopeLabel(effectiveScope.lob_scope, 'lob')} / ${scopeLabel(effectiveScope.stage_scope, 'stage')}`;
    return `
      <article class="intent-card glass-card" data-edge-light>
        <div class="intent-head">
          <span class="family-badge ${escapeHtml(intent.family)}">${escapeHtml(intent.family.replace(/_/g, ' '))}</span>
          <span class="intent-id mono">${escapeHtml(intent.id)}</span>
        </div>
        <textarea class="intent-input" data-intent-text="${idx}" spellcheck="false">${escapeHtml(intent.text)}</textarea>
        <div class="meta-cloud">
          ${(hints.length ? hints : ['Hints improve retrieval steering when the story is sparse.']).map((hint) => `<span class="meta-tag">${escapeHtml(hint)}</span>`).join('')}
        </div>
        <div class="scope-note">${escapeHtml(scopeText)}</div>
        <div class="intent-actions">
          <div class="button-row">
            <button class="btn btn-secondary btn-small" type="button" data-intent-focus="${idx}">Modify DNA</button>
            <button class="btn btn-secondary btn-small" type="button" data-intent-remap="${idx}">Remap Essence</button>
          </div>
          <button class="btn btn-danger btn-small" type="button" data-intent-delete="${idx}">Vanish</button>
        </div>
      </article>
    `;
  }).join('');

  intentGalleryEl.innerHTML = cards + `
    <article class="intent-card add-card glass-card" data-edge-light>
      <button type="button" id="add-intent-card">+ Add another intent</button>
    </article>
  `;

  intentGalleryEl.querySelectorAll('[data-intent-text]').forEach((textarea) => {
    textarea.addEventListener('input', () => {
      const idx = Number(textarea.dataset.intentText);
      if (state.currentIntents[idx]) state.currentIntents[idx].text = textarea.value;
    });
  });
  intentGalleryEl.querySelectorAll('[data-intent-focus]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const textarea = intentGalleryEl.querySelector(`[data-intent-text="${btn.dataset.intentFocus}"]`);
      if (textarea) textarea.focus();
    });
  });
  intentGalleryEl.querySelectorAll('[data-intent-delete]').forEach((btn) => btn.addEventListener('click', () => removeIntent(Number(btn.dataset.intentDelete))));
  intentGalleryEl.querySelectorAll('[data-intent-remap]').forEach((btn) => btn.addEventListener('click', () => openRemapModal(Number(btn.dataset.intentRemap))));
  document.getElementById('add-intent-card').addEventListener('click', addIntent);
}

function renderRefinement() {
  renderRefinementHeader();
  renderCoverage();
  renderIntentGallery();
  wireEdgeLighting();
}

function renderArtifactOverview() {
  const rows = [
    ['JIRA ID', state.storyDetail ? state.storyDetail.issue_key : '-'],
    ['Authored By', state.authorName || 'CASForge'],
    ['Type', state.flowType || '-'],
    ['Scenarios', String(state.quality.scenario_count ?? 0)],
    ['Grounded Steps', `${state.quality.grounded_steps ?? 0}/${state.quality.total_steps ?? 0}`],
    ['Scope Relaxations', String(state.quality.scope_relaxations ?? 0)],
  ];
  artifactOverviewEl.innerHTML = rows.map(([label, value]) => `
    <div class="metric-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>
  `).join('');
}

function highlightLine(line) {
  let escaped = escapeHtml(line);
  if (/^\s*@/.test(line)) return `<span class="kw-tag">${escaped}</span>`;
  if (/^\s*#/.test(line)) return `<span class="kw-comment">${escaped}</span>`;
  if (/^\s*\|/.test(line)) return `<span class="kw-table">${escaped}</span>`;
  if (/^\s*Feature:/.test(line)) return escaped.replace(/Feature:/, '<span class="kw-feature">Feature:</span>');
  if (/^\s*Scenario/.test(line)) return escaped.replace(/Scenario(?: Outline)?:/, '<span class="kw-scenario">$&</span>');
  if (/^\s*Background:/.test(line)) return escaped.replace(/Background:/, '<span class="kw-scenario">Background:</span>');
  if (/^\s*Examples:/.test(line)) return escaped.replace(/Examples:/, '<span class="kw-and">Examples:</span>');
  escaped = escaped.replace(/^(\s*)(Given)(\s+)/, '$1<span class="kw-given">$2</span>$3');
  escaped = escaped.replace(/^(\s*)(When)(\s+)/, '$1<span class="kw-when">$2</span>$3');
  escaped = escaped.replace(/^(\s*)(Then)(\s+)/, '$1<span class="kw-then">$2</span>$3');
  escaped = escaped.replace(/^(\s*)(And|But)(\s+)/, '$1<span class="kw-and">$2</span>$3');
  return escaped;
}

function renderFeatureEditor() {
  const feature = state.feature;
  document.getElementById('artifact-filename').textContent = feature ? feature.filename : 'artifact.feature';
  if (!feature) {
    featureEditorEl.innerHTML = '<div class="editor-line"><span class="line-no">1</span><span class="line-code">Feature output will appear here after generation.</span></div>';
    return;
  }
  const unresolvedStrings = (state.unresolvedSteps || []).map((item) => `${item.keyword} ${item.step_text}`.toLowerCase());
  featureEditorEl.innerHTML = feature.text.split(/\r?\n/).map((line, index) => {
    const lower = line.trim().toLowerCase();
    const unresolved = lower.includes('[new_step_not_in_repo]') || unresolvedStrings.some((needle) => lower.includes(needle) || lower.includes(needle.replace(/^(given|when|then|and|but)\s+/, '')));
    const comment = /^\s*#/.test(line);
    return `
      <div class="editor-line ${unresolved ? 'unresolved' : ''} ${comment ? 'comment' : ''}">
        <span class="line-no">${index + 1}</span>
        <span class="line-code">${highlightLine(line)}</span>
      </div>
    `;
  }).join('');
}

function renderUnresolved() {
  if (!state.unresolvedSteps.length) {
    unresolvedListEl.innerHTML = '<div class="unresolved-item"><strong>OK</strong> Every final step was grounded or replaced from repository material.</div>';
    return;
  }
  unresolvedListEl.innerHTML = state.unresolvedSteps.map((item) => `
    <div class="unresolved-item"><strong>${escapeHtml(item.keyword)}</strong> ${escapeHtml(item.step_text)}</div>
  `).join('');
}

function renderOmittedList() {
  const el = document.getElementById('omitted-list');
  if (!el) return;
  const items = [...(state.omittedItems || []), ...(state.coverageGaps || [])];
  if (!items.length) {
    el.innerHTML = '<div class="card-copy">All intents produced scenarios.</div>';
    return;
  }
  el.innerHTML = items.map(item => `
    <div class="unresolved-item">
      <span class="mono" style="font-size:0.78rem;opacity:0.6">${escapeHtml(item.intent_id || item.gap_id || '')}</span>
      <div>${escapeHtml(item.intent || item.description || '')}</div>
      <div style="font-size:0.78rem;opacity:0.5;margin-top:4px">Reason: ${escapeHtml(item.reason || 'low retrieval confidence')}</div>
    </div>
  `).join('');
}

function renderArtifact() {
  renderFeatureEditor();
  renderArtifactOverview();
  renderUnresolved();
  renderOmittedList();
  wireEdgeLighting();
}

function addIntent() {
  const next = state.currentIntents.length + 1;
  state.currentIntents.push({
    id: `intent_${String(next).padStart(3, '0')}`,
    text: '',
    family: 'positive',
    inherit_story_scope: true,
    lob_scope: null,
    stage_scope: null,
    action_target: null,
    screen_hint: null,
    expected_outcome: null,
  });
  renderRefinement();
}

function removeIntent(idx) {
  state.currentIntents.splice(idx, 1);
  renderRefinement();
}

function openRemapModal(idx) {
  state.remapIndex = idx;
  const intent = state.currentIntents[idx];
  if (!intent) return;
  document.getElementById('remap-inherit').checked = intent.inherit_story_scope !== false;
  renderRemapClouds();
  updateRemapPreview();
  remapModalEl.classList.add('active');
}

function closeRemapModal() {
  state.remapIndex = null;
  remapModalEl.classList.remove('active');
  document.getElementById('remap-custom-lob').value = '';
  document.getElementById('remap-custom-stage').value = '';
}

function openManualModal() {
  document.getElementById('manual-status').textContent = '';
  document.getElementById('manual-modal').classList.add('active');
}

function closeManualModal() {
  document.getElementById('manual-modal').classList.remove('active');
}

async function submitManualStory() {
  const key = (document.getElementById('manual-key').value || '').trim().toUpperCase();
  const summary = (document.getElementById('manual-summary').value || '').trim();
  const statusEl = document.getElementById('manual-status');

  if (!key) { statusEl.textContent = 'JIRA ID is required.'; return; }
  if (!summary) { statusEl.textContent = 'Summary is required.'; return; }

  statusEl.textContent = 'Adding...';
  try {
    const res = await fetch('/api/story/manual', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        issue_key:           key,
        summary:             summary,
        description:         document.getElementById('manual-description').value || '',
        new_process:         document.getElementById('manual-system-process').value || '',
        acceptance_criteria: document.getElementById('manual-acceptance').value || '',
        impacted_areas:      document.getElementById('manual-impacted').value || '',
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      statusEl.textContent = err.detail || `Error ${res.status}`;
      return;
    }
    state.csvPath = 'manual';
    document.getElementById('csv-path').value = 'manual';
    closeManualModal();
    await loadStories();
  } catch (e) {
    statusEl.textContent = `Network error: ${e.message}`;
  }
}

function updateRemapPreview() {
  const intent = state.currentIntents[state.remapIndex];
  if (!intent) return;
  const effective = getEffectiveIntentScope(intent);
  const text = intent.inherit_story_scope !== false
    ? `This intent will inherit story scope: ${scopeLabel(effective.lob_scope, 'lob')} / ${scopeLabel(effective.stage_scope, 'stage')}`
    : `Override will use: ${scopeLabel(effective.lob_scope, 'lob')} / ${scopeLabel(effective.stage_scope, 'stage')}`;
  setStatus('remap-preview', text, '');
}

function renderRemapClouds() {
  const intent = state.currentIntents[state.remapIndex];
  if (!intent) return;
  const lobScope = intent.inherit_story_scope !== false ? { mode: 'all', values: [] } : normalizeScope(intent.lob_scope);
  const stageScope = intent.inherit_story_scope !== false ? { mode: 'all', values: [] } : normalizeScope(intent.stage_scope);
  renderScopeCloud('remap-lob-cloud', lobScope, LOB_PRESETS, 'lob', (label) => {
    const current = state.currentIntents[state.remapIndex];
    current.inherit_story_scope = false;
    current.lob_scope = toggleScopeValue(current.lob_scope, label, 'lob');
    document.getElementById('remap-inherit').checked = false;
    renderRemapClouds();
    updateRemapPreview();
  });
  renderScopeCloud('remap-stage-cloud', stageScope, STAGE_PRESETS, 'stage', (label) => {
    const current = state.currentIntents[state.remapIndex];
    current.inherit_story_scope = false;
    current.stage_scope = toggleScopeValue(current.stage_scope, label, 'stage');
    document.getElementById('remap-inherit').checked = false;
    renderRemapClouds();
    updateRemapPreview();
  });
}

function addCustomRemapValues() {
  const intent = state.currentIntents[state.remapIndex];
  if (!intent) return;
  const lobs = parseCsvValues(document.getElementById('remap-custom-lob').value);
  const stages = parseCsvValues(document.getElementById('remap-custom-stage').value);
  if (!lobs.length && !stages.length) return;
  intent.inherit_story_scope = false;
  if (lobs.length) intent.lob_scope = { mode: 'specific', values: uniq([...(intent.lob_scope?.values || []), ...lobs]) };
  if (stages.length) intent.stage_scope = { mode: 'specific', values: uniq([...(intent.stage_scope?.values || []), ...stages]) };
  document.getElementById('remap-inherit').checked = false;
  renderRemapClouds();
  updateRemapPreview();
}

function saveRemap() {
  const intent = state.currentIntents[state.remapIndex];
  if (!intent) return;
  const inherit = document.getElementById('remap-inherit').checked;
  intent.inherit_story_scope = inherit;
  if (inherit) {
    intent.lob_scope = null;
    intent.stage_scope = null;
  }
  closeRemapModal();
  renderRefinement();
}

function openSynthesis(statusText) {
  synthesisModalEl.classList.add('active');
  document.getElementById('synthesis-status').textContent = statusText || 'Preparing the forge...';
  let idx = 0;
  document.getElementById('synthesis-line').textContent = SYNTHESIS_LINES[idx];
  window.clearInterval(state.synthesisTimer);
  state.synthesisTimer = window.setInterval(() => {
    idx = (idx + 1) % SYNTHESIS_LINES.length;
    document.getElementById('synthesis-line').textContent = SYNTHESIS_LINES[idx];
  }, 1800);
}

function closeSynthesis() {
  synthesisModalEl.classList.remove('active');
  window.clearInterval(state.synthesisTimer);
  state.synthesisTimer = null;
}
async function loadStories() {
  const csvPath = document.getElementById('csv-path').value.trim();
  if (!csvPath) {
    setStatus('upload-status', 'Provide a CSV path or upload a CSV first.', 'err');
    return;
  }
  state.csvPath = csvPath;
  setStatus('upload-status', 'Loading JIRA queue...', '');
  try {
    const response = await fetch(`/api/stories?csv=${encodeURIComponent(csvPath)}`);
    if (!response.ok) throw new Error(await response.text());
    state.stories = await response.json();
    state.selectedStory = null;
    state.storyDetail = null;
    state.storyScopeDefaults = emptyStoryScopeDefaults();
    state.storyScopeAuto = true;
    state.currentIntents = [];
    state.feature = null;
    state.quality = {};
    state.unresolvedSteps = [];
    state.omittedItems = [];
    state.coverageGaps = [];
    renderIntake();
    renderRefinement();
    renderArtifact();
    setStatus('upload-status', `${state.stories.length} stories ready for review.`, 'ok');
  } catch (error) {
    setStatus('upload-status', `Unable to load stories: ${error.message}`, 'err');
  }
}

async function selectStory(storyKey) {
  if (!state.csvPath) return;
  setStatus('intake-status', 'Loading story context...', '');
  try {
    const response = await fetch(`/api/story/${encodeURIComponent(storyKey)}?csv=${encodeURIComponent(state.csvPath)}`);
    if (!response.ok) throw new Error(await response.text());
    const detail = await response.json();
    state.selectedStory = state.stories.find((story) => story.key === storyKey) || { key: storyKey, summary: detail.summary, type: detail.issue_type };
    state.storyDetail = detail;
    state.storyScopeDefaults = emptyStoryScopeDefaults();
    state.storyScopeAuto = true;
    renderIntake();
    setStatus('intake-status', 'Story context loaded.', 'ok');
  } catch (error) {
    setStatus('intake-status', `Unable to load story: ${error.message}`, 'err');
  }
}

async function uploadCsvFile(file) {
  if (!file) return;
  setStatus('upload-status', 'Uploading CSV into workspace...', '');
  try {
    const content = await file.text();
    const response = await fetch('/api/upload-csv', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: file.name, content }),
    });
    if (!response.ok) throw new Error(await response.text());
    const data = await response.json();
    state.csvPath = data.stored_path;
    document.getElementById('csv-path').value = data.stored_path;
    setStatus('upload-status', `Stored as ${data.stored_path}`, 'ok');
    await loadStories();
  } catch (error) {
    setStatus('upload-status', `Upload failed: ${error.message}`, 'err');
  }
}

async function igniteForge() {
  if (!state.storyDetail) {
    setStatus('intake-status', 'Choose a story before extracting intents.', 'err');
    return;
  }
  openSynthesis('Extracting intents from JIRA context...');
  setStatus('intake-status', 'Extracting intents...', '');
  try {
    const response = await fetch('/api/intents', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        csv_path: state.csvPath,
        story_key: state.storyDetail.issue_key,
        story_scope_defaults: storyScopePayload(),
      }),
    });
    if (!response.ok) throw new Error(await response.text());
    const data = await response.json();
    state.storyScopeDefaults = data.story_scope_defaults || state.storyScopeDefaults;
    state.storyScopeAuto = false;
    state.currentIntents = (data.intents || []).map((intent, idx) => normalizeIntentItem(intent, idx));
    renderIntake();
    renderRefinement();
    setPage('refine');
    setStatus('intake-status', `${state.currentIntents.length} intents extracted.`, 'ok');
  } catch (error) {
    setStatus('intake-status', `Intent extraction failed: ${error.message}`, 'err');
  } finally {
    closeSynthesis();
  }
}

async function commenceGeneration() {
  if (!state.storyDetail || !state.currentIntents.length) {
    setStatus('intake-status', 'No intents are ready for generation.', 'err');
    return;
  }
  openSynthesis('Streaming generation progress...');
  try {
    const response = await fetch('/api/generate/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        csv_path: state.csvPath,
        story_key: state.storyDetail.issue_key,
        flow_type: state.flowType,
        story_scope_defaults: storyScopePayload(),
        intents: state.currentIntents.map((intent, idx) => normalizeIntentItem(intent, idx)).filter((intent) => String(intent.text || '').trim()),
      }),
    });
    if (!response.ok) throw new Error(await response.text());

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split('\n\n');
      buffer = chunks.pop();
      for (const chunk of chunks) {
        if (!chunk.startsWith('data:')) continue;
        let payload;
        try {
          payload = JSON.parse(chunk.slice(5).trim());
        } catch {
          continue;
        }
        const { event, data } = payload;
        if (event === 'status') {
          document.getElementById('synthesis-status').textContent = data;
        } else if (event === 'feature') {
          state.feature = {
            text: data.text,
            filename: `${state.storyDetail.issue_key.replace(/-/g, '_')}.feature`,
          };
          state.quality = data.quality || {};
          state.unresolvedSteps = data.unresolved_steps || [];
          state.omittedItems = data.omitted_plan_items || [];
          state.coverageGaps = data.coverage_gaps || [];
          renderArtifact();
          setPage('artifact');
        } else if (event === 'error') {
          throw new Error(data);
        }
      }
    }
  } catch (error) {
    setStatus('intake-status', `Generation failed: ${error.message}`, 'err');
  } finally {
    closeSynthesis();
  }
}

async function submitDirectForge() {
  const title = document.getElementById('direct-title').value.trim();
  const intentsText = document.getElementById('direct-intents').value.trim();
  if (!intentsText) {
    setStatus('direct-status', 'Add at least one intent line.', 'err');
    return;
  }
  openSynthesis('Direct Forge in progress...');
  try {
    const response = await fetch('/api/forge/direct', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title,
        intents_text: intentsText,
        flow_type: state.directFlowType,
      }),
    });
    if (!response.ok) throw new Error(await response.text());

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split('\n\n');
      buffer = chunks.pop();
      for (const chunk of chunks) {
        if (!chunk.startsWith('data:')) continue;
        let payload;
        try { payload = JSON.parse(chunk.slice(5).trim()); } catch { continue; }
        const { event, data } = payload;
        if (event === 'status') {
          document.getElementById('synthesis-status').textContent = data;
        } else if (event === 'feature') {
          state.feature = { text: data.text, filename: `${(title || 'direct_forge').replace(/\s+/g, '_')}.feature` };
          state.quality = data.quality || {};
          state.unresolvedSteps = data.unresolved_steps || [];
          state.omittedItems = data.omitted_plan_items || [];
          state.coverageGaps = data.coverage_gaps || [];
          renderArtifact();
          setPage('artifact');
        } else if (event === 'error') {
          throw new Error(data);
        }
      }
    }
  } catch (error) {
    setStatus('direct-status', `Forge failed: ${error.message}`, 'err');
  } finally {
    closeSynthesis();
  }
}

function copyFeature() {
  if (!state.feature) return;
  const btn = document.getElementById('copy-btn');
  const original = btn.textContent;
  const doCopy = () => {
    btn.textContent = 'Copied!';
    setTimeout(() => { btn.textContent = original; }, 1500);
  };
  const onFail = () => {
    btn.textContent = 'Copy failed';
    setTimeout(() => { btn.textContent = original; }, 2000);
  };
  navigator.clipboard.writeText(state.feature.text)
    .then(doCopy)
    .catch(() => {
      try {
        const ta = Object.assign(document.createElement('textarea'), {
          value: state.feature.text, style: 'position:fixed;opacity:0'
        });
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        doCopy();
      } catch { onFail(); }
    });
}

function downloadFeature() {
  if (!state.feature) return;
  const blob = new Blob([state.feature.text], { type: 'text/plain;charset=utf-8' });
  const anchor = document.createElement('a');
  const href = URL.createObjectURL(blob);
  anchor.href = href;
  anchor.download = state.feature.filename;
  anchor.click();
  URL.revokeObjectURL(href);
}

function addCustomScope(kind) {
  const inputId = kind === 'lob' ? 'custom-lob-input' : 'custom-stage-input';
  const values = parseCsvValues(document.getElementById(inputId).value);
  if (!values.length) return;
  state.storyScopeAuto = false;
  const key = kind === 'lob' ? 'lob_scope' : 'stage_scope';
  const existing = state.storyScopeDefaults[key]?.values || [];
  state.storyScopeDefaults[key] = { mode: 'specific', values: uniq([...existing, ...values]) };
  document.getElementById(inputId).value = '';
  renderIntake();
}

function wireEdgeLighting() {
  document.querySelectorAll('[data-edge-light]').forEach((card) => {
    if (card.dataset.edgeBound === 'true') return;
    card.dataset.edgeBound = 'true';
    card.addEventListener('mousemove', (event) => {
      const rect = card.getBoundingClientRect();
      card.style.setProperty('--mx', `${event.clientX - rect.left}px`);
      card.style.setProperty('--my', `${event.clientY - rect.top}px`);
      card.classList.add('edge-active');
    });
    card.addEventListener('mouseleave', () => card.classList.remove('edge-active'));
  });
}

function attachEvents() {
  document.getElementById('browse-btn').addEventListener('click', () => document.getElementById('csv-file-input').click());
  document.getElementById('csv-file-input').addEventListener('change', (event) => uploadCsvFile(event.target.files[0]));
  document.getElementById('load-stories-btn').addEventListener('click', loadStories);
  document.getElementById('ignite-btn').addEventListener('click', igniteForge);
  document.getElementById('generate-btn').addEventListener('click', commenceGeneration);
  document.getElementById('back-to-intake').addEventListener('click', () => setPage('intake'));
  document.getElementById('back-to-refine').addEventListener('click', () => setPage('refine'));
  document.getElementById('copy-btn').addEventListener('click', copyFeature);
  document.getElementById('download-btn').addEventListener('click', downloadFeature);
  document.getElementById('flow-ordered').addEventListener('click', () => { state.flowType = 'ordered'; renderIntake(); });
  document.getElementById('flow-unordered').addEventListener('click', () => { state.flowType = 'unordered'; renderIntake(); });
  document.getElementById('author-name').addEventListener('input', (event) => { state.authorName = event.target.value; });
  document.getElementById('toggle-custom-scope').addEventListener('click', () => document.getElementById('custom-scope-panel').classList.toggle('is-hidden'));
  document.getElementById('add-custom-lob').addEventListener('click', () => addCustomScope('lob'));
  document.getElementById('add-custom-stage').addEventListener('click', () => addCustomScope('stage'));
  document.getElementById('close-remap').addEventListener('click', closeRemapModal);
  document.querySelector('[data-close-remap]').addEventListener('click', closeRemapModal);
  document.getElementById('add-manually-btn').addEventListener('click', openManualModal);
  document.getElementById('close-manual').addEventListener('click', closeManualModal);
  document.querySelector('[data-close-manual]').addEventListener('click', closeManualModal);
  document.getElementById('manual-submit').addEventListener('click', submitManualStory);
  document.getElementById('remap-inherit').addEventListener('change', (event) => {
    const intent = state.currentIntents[state.remapIndex];
    if (!intent) return;
    intent.inherit_story_scope = event.target.checked;
    if (event.target.checked) {
      intent.lob_scope = null;
      intent.stage_scope = null;
    }
    renderRemapClouds();
    updateRemapPreview();
  });
  document.getElementById('remap-add-custom').addEventListener('click', addCustomRemapValues);
  document.getElementById('remap-save').addEventListener('click', saveRemap);
  document.getElementById('footer-mail').addEventListener('click', () => { window.location.href = 'mailto:anand.singh1@nucleussoftware.com'; });
  document.getElementById('direct-forge-entry').addEventListener('click', () => setPage('direct'));
  document.getElementById('back-to-intake-direct').addEventListener('click', () => setPage('intake'));
  document.getElementById('direct-forge-btn').addEventListener('click', submitDirectForge);
  document.getElementById('direct-flow-ordered').addEventListener('click', () => {
    state.directFlowType = 'ordered';
    document.getElementById('direct-flow-ordered').classList.add('active');
    document.getElementById('direct-flow-unordered').classList.remove('active');
  });
  document.getElementById('direct-flow-unordered').addEventListener('click', () => {
    state.directFlowType = 'unordered';
    document.getElementById('direct-flow-unordered').classList.add('active');
    document.getElementById('direct-flow-ordered').classList.remove('active');
  });
  document.getElementById('direct-intents').addEventListener('input', () => {
    const lines = document.getElementById('direct-intents').value.split('\n').filter((l) => l.trim() && !l.trim().startsWith('#'));
    document.getElementById('direct-intent-count').textContent = `${lines.length} intent${lines.length !== 1 ? 's' : ''}`;
  });

  const dropzone = document.getElementById('dropzone');
  ['dragenter', 'dragover'].forEach((eventName) => {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropzone.classList.add('dragover');
    });
  });
  ['dragleave', 'drop'].forEach((eventName) => {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropzone.classList.remove('dragover');
    });
  });
  dropzone.addEventListener('drop', (event) => {
    const file = event.dataTransfer && event.dataTransfer.files ? event.dataTransfer.files[0] : null;
    if (file) uploadCsvFile(file);
  });
}

loadConfig().then(() => {
  attachEvents();
  renderIntake();
  renderRefinement();
  renderArtifact();
  setPage('intake');

  const params = new URLSearchParams(window.location.search);
  if (params.get('csv')) {
    document.getElementById('csv-path').value = params.get('csv');
    state.csvPath = params.get('csv');
    loadStories();
  }
});
