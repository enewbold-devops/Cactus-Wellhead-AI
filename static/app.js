/* ================================================================
   Cactus Wellhead MTR Portal — app.js
   Three namespaces:
     Api   — fetch wrappers for all four used Azure Function routes
     Views — DOM population and show/hide logic per view
     App   — DOMContentLoaded init, event binding, navigation,
             polling lifecycle management
   ================================================================ */

'use strict';

/* ──────────────────────────────────────────────────────────────
   CONSTANTS
   ────────────────────────────────────────────────────────────── */
const BASE_URL = 'http://localhost:7071/api';

const ALLOWED_EXTENSIONS = new Set([
  '.pdf', '.docx', '.xlsx', '.jpg', '.jpeg', '.png', '.tif', '.tiff',
]);

const POLL_INTERVAL_MS  = 5000;
const TERMINAL_STATUSES = new Set(['complete', 'failed', 'queue_error']);

const HISTORY_KEY = 'cactus_mtr_history';
const HISTORY_MAX = 50;

const STATUS_BADGE = {
  queued:      ['badge--gray',  'Queued'],
  processing:  ['badge--amber', 'Processing'],
  complete:    ['badge--green', 'Complete'],
  failed:      ['badge--red',   'Failed'],
  queue_error: ['badge--red',   'Queue Error'],
};

/* ──────────────────────────────────────────────────────────────
   API  — Azure Function route wrappers
   ────────────────────────────────────────────────────────────── */
const Api = {

  /** POST /api/mtr/intake — multipart file upload */
  async submitMtr(file) {
    const form = new FormData();
    form.append('file', file, file.name);
    const resp = await fetch(`${BASE_URL}/mtr/intake`, {
      method: 'POST',
      body: form,
    });
    const body = await resp.json();
    return { ok: resp.ok, status: resp.status, body };
  },

  /** GET /api/mtr/{case_id}/status */
  async getMtrStatus(caseId) {
    const resp = await fetch(`${BASE_URL}/mtr/${encodeURIComponent(caseId)}/status`);
    const body = await resp.json();
    return { ok: resp.ok, status: resp.status, body };
  },

  /** GET /api/cms/providers */
  async getProviders() {
    const resp = await fetch(`${BASE_URL}/cms/providers`);
    const body = await resp.json();
    return { ok: resp.ok, status: resp.status, body };
  },

  /** GET /api/cms/crosswalk */
  async getCrosswalk() {
    const resp = await fetch(`${BASE_URL}/cms/crosswalk`);
    const body = await resp.json();
    return { ok: resp.ok, status: resp.status, body };
  },
};

/* ──────────────────────────────────────────────────────────────
   HISTORY  — localStorage helpers
   ────────────────────────────────────────────────────────────── */
const History = {
  _read() {
    try { return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]'); }
    catch { return []; }
  },
  _write(arr) {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(arr.slice(0, HISTORY_MAX)));
  },
  getAll() { return this._read(); },
  add(entry) {
    const arr = this._read().filter(e => e.case_id !== entry.case_id);
    arr.unshift(entry);
    this._write(arr);
  },
  updateStatus(caseId, status) {
    const arr = this._read().map(e =>
      e.case_id === caseId ? { ...e, last_status: status } : e
    );
    this._write(arr);
  },
  clear() { localStorage.removeItem(HISTORY_KEY); },
};

/* ──────────────────────────────────────────────────────────────
   UTILS  — small DOM helpers
   ────────────────────────────────────────────────────────────── */
const $ = id => document.getElementById(id);

function formatBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

function formatDate(iso) {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleString(); }
  catch { return iso; }
}

function ext(filename) {
  const idx = filename.lastIndexOf('.');
  return idx === -1 ? '' : filename.slice(idx).toLowerCase();
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function makeBadge(statusKey) {
  const [cls, label] = STATUS_BADGE[statusKey] || ['badge--gray', statusKey];
  return `<span class="badge ${cls}">${escHtml(label)}</span>`;
}

/* ──────────────────────────────────────────────────────────────
   TOAST
   ────────────────────────────────────────────────────────────── */
let _toastTimer = null;
function showToast(msg, type = 'default', duration = 4000) {
  const el = $('toast');
  el.textContent = msg;
  el.className = `toast toast--${type}`;
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { el.className = 'toast hidden'; }, duration);
}

/* ──────────────────────────────────────────────────────────────
   VIEWS
   ────────────────────────────────────────────────────────────── */
const Views = {

  /** Switch the active main view and update nav tab styling */
  show(viewId) {
    document.querySelectorAll('.view').forEach(s => {
      s.classList.remove('active');
      s.classList.add('hidden');
    });
    document.querySelectorAll('.nav-tab').forEach(b => {
      b.classList.toggle('active', b.dataset.view === viewId);
      b.setAttribute('aria-selected', String(b.dataset.view === viewId));
    });
    const target = document.getElementById(`view-${viewId}`);
    if (target) {
      target.classList.remove('hidden');
      target.classList.add('active');
    }
  },

  /* ── VIEW 1: Upload ──────────────────────────────────────── */
  upload: {
    _file: null,

    init() {
      const dropZone   = $('drop-zone');
      const fileInput  = $('file-input');
      const clearBtn   = $('clear-file');
      const submitBtn  = $('submit-btn');
      const label      = dropZone.querySelector('.btn-outline');

      // Proxy label click to hidden input
      label.addEventListener('click', e => { e.stopPropagation(); fileInput.click(); });
      dropZone.addEventListener('click', () => fileInput.click());
      dropZone.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') fileInput.click(); });

      fileInput.addEventListener('change', () => {
        if (fileInput.files[0]) Views.upload._setFile(fileInput.files[0]);
      });

      // Drag events
      ['dragenter', 'dragover'].forEach(ev =>
        dropZone.addEventListener(ev, e => { e.preventDefault(); dropZone.classList.add('drag-over'); })
      );
      ['dragleave', 'drop'].forEach(ev =>
        dropZone.addEventListener(ev, e => { e.preventDefault(); dropZone.classList.remove('drag-over'); })
      );
      dropZone.addEventListener('drop', e => {
        const file = e.dataTransfer?.files[0];
        if (file) Views.upload._setFile(file);
      });

      clearBtn.addEventListener('click', () => Views.upload._clearFile());
      submitBtn.addEventListener('click', () => Views.upload._submit());
    },

    _setFile(file) {
      const errEl = $('upload-error');
      // Validate extension client-side
      if (!ALLOWED_EXTENSIONS.has(ext(file.name))) {
        errEl.textContent = `Unsupported file type "${ext(file.name)}". Allowed: ${[...ALLOWED_EXTENSIONS].join(', ')}`;
        errEl.classList.remove('hidden');
        return;
      }
      errEl.classList.add('hidden');
      this._file = file;
      $('preview-name').textContent = file.name;
      $('preview-size').textContent = formatBytes(file.size);
      $('file-preview').classList.remove('hidden');
      $('drop-zone').classList.add('hidden');
      $('submit-btn').disabled = false;
    },

    _clearFile() {
      this._file = null;
      $('file-input').value = '';
      $('file-preview').classList.add('hidden');
      $('drop-zone').classList.remove('hidden');
      $('upload-error').classList.add('hidden');
      $('submit-btn').disabled = true;
    },

    async _submit() {
      if (!this._file) return;
      const errEl   = $('upload-error');
      const btn     = $('submit-btn');
      const label   = $('submit-label');
      const spinner = $('submit-spinner');

      // Loading state
      btn.disabled = true;
      label.textContent = 'Submitting…';
      spinner.classList.remove('hidden');
      errEl.classList.add('hidden');

      try {
        const { ok, status, body } = await Api.submitMtr(this._file);

        if (ok) {
          // Save to history
          History.add({
            case_id:      body.case_id,
            filename:     body.filename,
            submitted_at: body.submitted_at,
            last_status:  body.status,
          });
          showToast(`Case created: ${body.case_id.slice(0, 8)}…`, 'success');
          Views.upload._clearFile();
          // Navigate to status view pre-loaded with this case
          Views.status.load(body.case_id);
          Views.show('status');
        } else {
          const msg = body?.error || `Server error ${status}`;
          errEl.textContent = msg;
          errEl.classList.remove('hidden');
        }
      } catch (err) {
        errEl.textContent = `Network error — is the function app running? (${err.message})`;
        errEl.classList.remove('hidden');
      } finally {
        btn.disabled = false;
        label.textContent = 'Submit MTR';
        spinner.classList.add('hidden');
      }
    },
  },

  /* ── VIEW 2: Status ──────────────────────────────────────── */
  status: {
    _pollTimer: null,
    _currentCaseId: null,

    init() {
      $('status-lookup-btn').addEventListener('click', () => {
        const id = $('status-case-input').value.trim();
        if (id) this.load(id);
      });
      $('status-case-input').addEventListener('keydown', e => {
        if (e.key === 'Enter') {
          const id = $('status-case-input').value.trim();
          if (id) this.load(id);
        }
      });
    },

    load(caseId) {
      $('status-case-input').value = caseId;
      this._stopPolling();
      this._currentCaseId = caseId;
      $('status-panel').classList.remove('hidden');
      $('poll-indicator').classList.remove('hidden');
      this._fetch(caseId);
      this._pollTimer = setInterval(() => this._fetch(caseId), POLL_INTERVAL_MS);
    },

    _stopPolling() {
      if (this._pollTimer) {
        clearInterval(this._pollTimer);
        this._pollTimer = null;
      }
      $('poll-indicator').classList.add('hidden');
    },

    async _fetch(caseId) {
      try {
        const { ok, status, body } = await Api.getMtrStatus(caseId);
        if (!ok) {
          this._stopPolling();
          if (status === 404) {
            showToast(`Case not found: ${caseId}`, 'error');
            $('status-panel').classList.add('hidden');
          } else {
            showToast(`Error ${status}: ${body?.error || 'Unknown'}`, 'error');
          }
          return;
        }
        this._render(body);
        History.updateStatus(body.case_id, body.status);
        if (TERMINAL_STATUSES.has(body.status)) this._stopPolling();
      } catch (err) {
        showToast(`Network error polling status: ${err.message}`, 'error');
        this._stopPolling();
      }
    },

    _render(record) {
      this._updateStepper(record.status);
      this._updateMeta(record);
      this._updateArtifacts(record);
    },

    _updateStepper(statusKey) {
      // Map status to which steps are done vs active
      const ORDER = ['received', 'queued', 'processing', 'complete'];
      const isFailed = statusKey === 'failed' || statusKey === 'queue_error';

      // Determine index of active step
      let activeIdx = ORDER.indexOf(statusKey);
      if (isFailed) activeIdx = ORDER.indexOf('processing'); // highlight processing as failed

      document.querySelectorAll('.step').forEach(el => {
        const step = el.dataset.step;
        el.classList.remove('done', 'active');

        if (isFailed && step === 'failed') {
          el.classList.add('active');
          return;
        }
        if (!isFailed && step === 'failed') return; // never highlight failed if not failed

        const idx = ORDER.indexOf(step);
        if (idx < activeIdx) {
          el.classList.add('done');
        } else if (idx === activeIdx && !isFailed) {
          el.classList.add('active');
        }
      });
    },

    _updateMeta(record) {
      const grid = $('status-meta');
      const fields = [
        ['Case ID',      record.case_id],
        ['Filename',     record.filename],
        ['Status',       makeBadge(record.status)],
        ['Submitted',    formatDate(record.submitted_at)],
        ['Completed',    formatDate(record.completed_at)],
        ['Chunks',       record.chunk_count != null ? record.chunk_count : '—'],
      ];
      grid.innerHTML = fields.map(([label, value]) => `
        <div class="meta-item">
          <span class="meta-label">${escHtml(label)}</span>
          <span class="meta-value">${value}</span>
        </div>
      `).join('');

      // Error block
      const errBlock = $('status-error-block');
      if (record.error) {
        errBlock.textContent = record.error;
        errBlock.classList.remove('hidden');
      } else {
        errBlock.classList.add('hidden');
      }
    },

    _updateArtifacts(record) {
      const panel = $('status-artifacts');
      if (record.status !== 'complete' || !record.artifacts) {
        panel.classList.add('hidden');
        return;
      }
      panel.classList.remove('hidden');
      const tbody = $('artifacts-tbody');
      const labels = {
        raw:             'Raw File',
        markdown:        'Markdown',
        chunks_jsonl:    'Chunks JSONL',
        structured_json: 'Structured JSON',
      };
      tbody.innerHTML = Object.entries(record.artifacts).map(([key, path]) => `
        <tr>
          <td class="artifact-label">${escHtml(labels[key] || key)}</td>
          <td>${escHtml(path || '—')}</td>
        </tr>
      `).join('');
    },
  },

  /* ── VIEW 3: CMS Lookup ──────────────────────────────────── */
  cms: {
    _providersData: null,
    _crosswalkData: null,
    _loaded: { providers: false, crosswalk: false },

    init() {
      document.querySelectorAll('.sub-tab').forEach(btn => {
        btn.addEventListener('click', () => this._switchSub(btn.dataset.sub));
      });
      $('provider-filter-code').addEventListener('input',   () => this._renderProviders());
      $('provider-filter-status').addEventListener('change', () => this._renderProviders());
    },

    onShow() {
      // Load providers on first show
      if (!this._loaded.providers) this._loadProviders();
    },

    _switchSub(sub) {
      document.querySelectorAll('.sub-tab').forEach(b => b.classList.toggle('active', b.dataset.sub === sub));
      document.querySelectorAll('.sub-view').forEach(v => v.classList.toggle('hidden', v.id !== `sub-${sub}`));
      if (sub === 'crosswalk' && !this._loaded.crosswalk) this._loadCrosswalk();
    },

    async _loadProviders() {
      try {
        const { ok, body } = await Api.getProviders();
        if (!ok) throw new Error(body?.error || 'Load failed');
        this._providersData = body;
        this._loaded.providers = true;
        this._renderProviders();
      } catch (err) {
        $('providers-tbody').innerHTML =
          `<tr><td colspan="7" class="table-empty" style="color:var(--red-600)">Failed to load providers: ${escHtml(err.message)}</td></tr>`;
      }
    },

    _renderProviders() {
      if (!this._providersData) return;
      const codeFilter   = $('provider-filter-code').value.trim().toLowerCase();
      const statusFilter = $('provider-filter-status').value;

      const filtered = this._providersData.filter(p => {
        const matchCode   = !codeFilter   || (p.process_code || '').toLowerCase().includes(codeFilter);
        const matchStatus = !statusFilter || p.approval_status === statusFilter;
        return matchCode && matchStatus;
      });

      $('provider-count').textContent = `${filtered.length.toLocaleString()} of ${this._providersData.length.toLocaleString()} records`;

      const tbody = $('providers-tbody');
      if (filtered.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="table-empty">No providers match the current filter.</td></tr>`;
        return;
      }

      tbody.innerHTML = filtered.map(p => {
        const notes     = p.notes || '';
        const isManual  = notes.includes('MANUAL REVIEW');
        const isSingle  = notes.includes('SINGLE SOURCE');
        const rowCls    = isManual ? 'row--manual' : isSingle ? 'row--single' : '';
        const statusCls = p.approval_status === 'Active' ? 'badge--active' : 'badge--inactive';

        const notesHtml = [
          isManual ? `<span class="risk-pill risk-pill--manual">Manual Review</span>` : '',
          isSingle ? `<span class="risk-pill risk-pill--single">Single Source</span>` : '',
          !isManual && !isSingle && notes ? `<span style="font-size:.78rem;color:var(--gray-500)">${escHtml(notes)}</span>` : '',
        ].filter(Boolean).join(' ');

        return `
          <tr class="${rowCls}">
            <td>${escHtml(p.supplier_name || '—')}</td>
            <td>${escHtml(p.site_city    || '—')}</td>
            <td>${escHtml(p.site_state   || '—')}</td>
            <td><code style="font-size:.8rem">${escHtml(p.process_code || '—')}</code></td>
            <td>${escHtml(p.process_category || '—')}</td>
            <td><span class="badge ${statusCls}">${escHtml(p.approval_status || '—')}</span></td>
            <td>${notesHtml || '—'}</td>
          </tr>`;
      }).join('');
    },

    async _loadCrosswalk() {
      try {
        const { ok, body } = await Api.getCrosswalk();
        if (!ok) throw new Error(body?.error || 'Load failed');
        this._crosswalkData = body;
        this._loaded.crosswalk = true;
        this._renderCrosswalk();
      } catch (err) {
        $('crosswalk-grid').innerHTML =
          `<p style="color:var(--red-600);font-size:.875rem">Failed to load crosswalk: ${escHtml(err.message)}</p>`;
      }
    },

    _renderCrosswalk() {
      if (!this._crosswalkData) return;
      const grid = $('crosswalk-grid');

      grid.innerHTML = this._crosswalkData.map(entry => {
        const mandatory    = (entry.mandatory_process_codes || [])
          .map(c => `<span class="code-pill code-pill--mandatory">${escHtml(c)}</span>`).join('');
        const conditional  = (entry.conditional_process_codes || [])
          .map(c => `<span class="code-pill code-pill--conditional">${escHtml(c)}</span>`).join('');
        const sopNotes     = (entry.sop_notes || []);
        const notesHtml    = sopNotes.length
          ? `<details class="crosswalk-notes">
               <summary>SOP Notes (${sopNotes.length})</summary>
               <ul>${sopNotes.map(n => `<li>${escHtml(n)}</li>`).join('')}</ul>
             </details>`
          : '';

        return `
          <div class="crosswalk-card">
            <div class="crosswalk-card-title">${escHtml(entry.cms_spec || '—')}</div>
            <div class="crosswalk-card-scope">${escHtml(entry.scope || '')}</div>
            ${mandatory ? `<div class="codes-label">Mandatory</div><div class="code-pills">${mandatory}</div>` : ''}
            ${conditional ? `<div class="codes-label">Conditional</div><div class="code-pills">${conditional}</div>` : ''}
            ${notesHtml}
          </div>`;
      }).join('');
    },
  },

  /* ── VIEW 4: History ─────────────────────────────────────── */
  history: {
    init() {
      $('clear-history-btn').addEventListener('click', () => {
        History.clear();
        this.render();
        showToast('History cleared.', 'default');
      });
    },

    onShow() {
      this.render();
      this._refreshStatuses();
    },

    render() {
      const entries = History.getAll();
      const count   = entries.length;
      $('history-count').textContent = count
        ? `${count} case${count !== 1 ? 's' : ''}`
        : '0 cases';

      const tbody = $('history-tbody');
      if (count === 0) {
        tbody.innerHTML = `<tr><td colspan="5" class="table-empty">No cases submitted this session.</td></tr>`;
        return;
      }

      tbody.innerHTML = entries.map(e => `
        <tr data-case="${escHtml(e.case_id)}">
          <td><code style="font-size:.78rem">${escHtml(e.case_id)}</code></td>
          <td>${escHtml(e.filename || '—')}</td>
          <td>${escHtml(formatDate(e.submitted_at))}</td>
          <td><span class="badge ${(STATUS_BADGE[e.last_status] || ['badge--gray'])[0]}">${escHtml((STATUS_BADGE[e.last_status] || ['', e.last_status || '?'])[1])}</span></td>
          <td style="text-align:right">
            <button class="btn btn-outline btn-sm history-check-btn" data-case-id="${escHtml(e.case_id)}">Check Status</button>
          </td>
        </tr>
      `).join('');

      // Wire "Check Status" buttons
      tbody.querySelectorAll('.history-check-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          Views.status.load(btn.dataset.caseId);
          Views.show('status');
        });
      });
    },

    async _refreshStatuses() {
      const entries = History.getAll();
      if (entries.length === 0) return;

      // Fire all status checks in parallel for non-terminal entries
      const checks = entries
        .filter(e => !TERMINAL_STATUSES.has(e.last_status))
        .map(async e => {
          try {
            const { ok, body } = await Api.getMtrStatus(e.case_id);
            if (ok) History.updateStatus(e.case_id, body.status);
          } catch { /* network errors are silent in history refresh */ }
        });

      await Promise.allSettled(checks);
      this.render(); // re-render with refreshed badges
    },
  },
};

/* ──────────────────────────────────────────────────────────────
   APP  — init, nav wiring
   ────────────────────────────────────────────────────────────── */
const App = {
  _activeView: 'upload',

  init() {
    // Wire nav tabs
    document.querySelectorAll('.nav-tab').forEach(btn => {
      btn.addEventListener('click', () => this._navigate(btn.dataset.view));
    });

    // Init each view's internal event handlers
    Views.upload.init();
    Views.status.init();
    Views.cms.init();
    Views.history.init();

    // Show default view
    Views.show('upload');
  },

  _navigate(viewId) {
    if (this._activeView === viewId) return;
    this._activeView = viewId;
    Views.show(viewId);

    // Stop status polling when leaving that view
    if (viewId !== 'status') Views.status._stopPolling();

    // Per-view on-show hooks
    if (viewId === 'cms')     Views.cms.onShow();
    if (viewId === 'history') Views.history.onShow();
  },
};

/* ──────────────────────────────────────────────────────────────
   BOOT
   ────────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => App.init());
