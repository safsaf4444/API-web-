/**
 * trust.js — Trust & Validity UI layer
 *
 * Exports:
 *   renderTrustBadge(trustData)          → HTMLElement
 *   renderEvidenceBasisBadge(basis)      → HTMLElement
 *   renderLimitationBanner(trustData)    → HTMLElement | null
 *   ProvenanceDrawer                     → class
 *   initTrustAlertDot(navEl)             → void
 *
 * trustData shape (comes from backend TrustSummary):
 *   { ai_run_id, trust_score, confidence_ceiling, flagged, flag_reason,
 *     evidence_basis, claim_count, provider, model }
 */

'use strict';

// ── Constants ────────────────────────────────────────────────────────────────

const EVIDENCE_LABELS = {
  rct:               'RCT',
  systematic_review: 'Systematic Review',
  cohort:            'Cohort',
  case_control:      'Case-Control',
  cross_sectional:   'Cross-Sectional',
  case_report:       'Case Report',
  expert_opinion:    'Expert Opinion',
  unknown:           'Unknown',
};

const EVIDENCE_ICONS = {
  rct:               '🔬',
  systematic_review: '📚',
  cohort:            '👥',
  case_control:      '↔️',
  cross_sectional:   '📊',
  case_report:       '📋',
  expert_opinion:    '🎓',
  unknown:           '❓',
};

// ── renderTrustBadge ─────────────────────────────────────────────────────────

/**
 * Render a clickable trust score badge.
 *
 * @param {Object} trustData
 * @param {Function} [onClick]  called with trustData when badge is clicked
 * @returns {HTMLElement}
 */
function renderTrustBadge(trustData, onClick) {
  const badge = document.createElement('span');
  badge.className = 'trust-badge';
  badge.setAttribute('role', 'button');
  badge.setAttribute('tabindex', '0');

  const score = trustData && trustData.trust_score;

  let tier, icon, label;
  if (score === null || score === undefined) {
    tier = 'none'; icon = '–'; label = 'No trust data';
  } else if (score >= 0.75) {
    tier = 'high';   icon = '✓'; label = `Trust ${Math.round(score * 100)}%`;
  } else if (score >= 0.50) {
    tier = 'medium'; icon = '⚠'; label = `Trust ${Math.round(score * 100)}%`;
  } else {
    tier = 'low';    icon = '✗'; label = `Trust ${Math.round(score * 100)}%`;
  }

  badge.classList.add(`trust-badge--${tier}`);
  badge.innerHTML = `<span class="trust-badge__icon">${icon}</span>${label}`;
  badge.title = _buildTooltip(trustData);

  if (onClick) {
    badge.addEventListener('click', () => onClick(trustData));
    badge.addEventListener('keydown', e => { if (e.key === 'Enter') onClick(trustData); });
  }

  return badge;
}


// ── renderEvidenceBasisBadge ─────────────────────────────────────────────────

/**
 * @param {string} basis
 * @returns {HTMLElement}
 */
function renderEvidenceBasisBadge(basis) {
  const key = (basis || 'unknown').toLowerCase().replace(/[\s-]/g, '_');
  const label = EVIDENCE_LABELS[key] || basis;
  const icon  = EVIDENCE_ICONS[key]  || '❓';
  const el = document.createElement('span');
  el.className = `evidence-basis-badge evidence-basis-badge--${key}`;
  el.innerHTML = `${icon} ${label}`;
  el.title = `Evidence basis: ${label}`;
  return el;
}


// ── renderLimitationBanner ───────────────────────────────────────────────────

/**
 * Returns a warning banner if the output was flagged, or null if clean.
 *
 * @param {Object} trustData
 * @returns {HTMLElement|null}
 */
function renderLimitationBanner(trustData) {
  if (!trustData || !trustData.flagged) return null;

  const banner = document.createElement('div');
  banner.className = 'trust-banner trust-banner--warning';

  const reason = trustData.flag_reason || 'Output flagged for review';
  const ceiling = trustData.confidence_ceiling
    ? ` Confidence ceiling: ${Math.round(trustData.confidence_ceiling * 100)}%.`
    : '';

  banner.innerHTML = `
    <span class="trust-banner__icon">⚠️</span>
    <div class="trust-banner__body">
      <div class="trust-banner__title">AI Output Flagged</div>
      <div>${_humaniseReason(reason)}${ceiling}</div>
    </div>
    <button class="trust-banner__dismiss" title="Dismiss">✕</button>
  `;

  banner.querySelector('.trust-banner__dismiss').addEventListener('click', () => {
    banner.style.display = 'none';
    if (trustData.ai_run_id) {
      _dismissAlert(trustData.ai_run_id);
    }
  });

  return banner;
}


// ── ProvenanceDrawer ─────────────────────────────────────────────────────────

class ProvenanceDrawer {
  constructor() {
    this._drawer  = null;
    this._overlay = null;
    this._build();
  }

  /** Open the drawer and load provenance for a given ai_run_id */
  async open(aiRunId) {
    if (!aiRunId) return;
    this._drawer.classList.add('open');
    this._overlay.classList.add('open');
    document.body.style.overflow = 'hidden';
    this._setBody('<p style="color:#888;font-size:13px">Loading provenance…</p>');

    try {
      const token = localStorage.getItem('token');
      const res = await fetch(`/api/trust/runs/${aiRunId}/provenance`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      this._render(data);
    } catch (err) {
      this._setBody(`<p style="color:#dc2626;font-size:13px">Failed to load: ${err.message}</p>`);
    }
  }

  close() {
    this._drawer.classList.remove('open');
    this._overlay.classList.remove('open');
    document.body.style.overflow = '';
  }

  // ── private ────────────────────────────────────────────────────────────────

  _build() {
    // Overlay
    this._overlay = document.createElement('div');
    this._overlay.className = 'provenance-overlay';
    this._overlay.addEventListener('click', () => this.close());

    // Drawer
    this._drawer = document.createElement('div');
    this._drawer.className = 'provenance-drawer';
    this._drawer.setAttribute('role', 'dialog');
    this._drawer.setAttribute('aria-label', 'AI Provenance');
    this._drawer.innerHTML = `
      <div class="provenance-drawer__header">
        <h3 class="provenance-drawer__title">🔍 AI Provenance</h3>
        <button class="provenance-drawer__close" aria-label="Close">✕</button>
      </div>
      <div class="provenance-drawer__body" id="prov-body"></div>
    `;
    this._drawer.querySelector('.provenance-drawer__close').addEventListener('click', () => this.close());

    document.body.appendChild(this._overlay);
    document.body.appendChild(this._drawer);
  }

  _setBody(html) {
    this._drawer.querySelector('#prov-body').innerHTML = html;
  }

  _render(data) {
    const run    = data.ai_run       || {};
    const spans  = data.evidence_spans || [];
    const claims = data.claims        || [];
    const audit  = data.audit_trail   || [];

    let html = '';

    // ── Run metadata ──
    html += `<div class="prov-section">
      <div class="prov-section__title">Run Details</div>
      <div class="prov-meta">
        <span class="prov-meta__key">Provider</span><span class="prov-meta__value">${run.provider || '–'} / ${run.model || '–'}</span>
        <span class="prov-meta__key">Endpoint</span><span class="prov-meta__value">${run.endpoint || '–'}</span>
        <span class="prov-meta__key">Status</span><span class="prov-meta__value">${run.status || '–'}</span>
        <span class="prov-meta__key">Trust score</span><span class="prov-meta__value">${run.trust_score != null ? (run.trust_score * 100).toFixed(0) + '%' : '–'}</span>
        <span class="prov-meta__key">Ceiling</span><span class="prov-meta__value">${run.confidence_ceiling != null ? (run.confidence_ceiling * 100).toFixed(0) + '%' : '–'}</span>
        <span class="prov-meta__key">Latency</span><span class="prov-meta__value">${run.latency_ms != null ? run.latency_ms + ' ms' : '–'}</span>
        <span class="prov-meta__key">Tokens in/out</span><span class="prov-meta__value">${run.input_tokens || 0} / ${run.output_tokens || 0}</span>
      </div>
    </div>`;

    // ── Evidence spans ──
    if (spans.length) {
      html += `<div class="prov-section"><div class="prov-section__title">Evidence Spans (${spans.length})</div>`;
      for (const s of spans) {
        const basisKey = (s.basis || 'unknown').toLowerCase().replace(/[\s-]/g, '_');
        const basisLabel = EVIDENCE_LABELS[basisKey] || s.basis;
        html += `
          <div class="prov-span">
            <div class="prov-span__claim">${_esc(s.claim_text)}</div>
            <div class="prov-span__source">"${_esc(s.source_text.slice(0, 120))}${s.source_text.length > 120 ? '…' : ''}"</div>
            <div class="prov-span__meta">
              <span class="evidence-basis-badge evidence-basis-badge--${basisKey}">${EVIDENCE_ICONS[basisKey] || '❓'} ${basisLabel}</span>
              ${s.confidence != null ? `<span style="font-size:11px;color:#6b7280">conf ${(s.confidence * 100).toFixed(0)}%</span>` : ''}
            </div>
          </div>`;
      }
      html += '</div>';
    }

    // ── Claims with verify buttons ──
    if (claims.length) {
      html += `<div class="prov-section"><div class="prov-section__title">Claims (${claims.length})</div>`;
      for (const c of claims) {
        const stateIcon = { approved: '✅', rejected: '❌', needs_review: '🔄', pending: '⏳' }[c.verification_state] || '⏳';
        html += `
          <div class="prov-claim" data-claim-id="${c.id}">
            <div class="prov-claim__text">${_esc(c.text)}</div>
            <div class="prov-claim__controls">
              <span style="font-size:11px">${stateIcon} ${c.verification_state}</span>
              <button class="verify-btn verify-btn--approve" data-claim="${c.id}" data-dec="approved">✓ Approve</button>
              <button class="verify-btn verify-btn--reject"  data-claim="${c.id}" data-dec="rejected">✗ Reject</button>
            </div>
          </div>`;
      }
      html += '</div>';
    }

    // ── Audit trail ──
    if (audit.length) {
      html += `<div class="prov-section"><div class="prov-section__title">Audit Trail</div>`;
      for (const entry of audit) {
        const ts = entry.created_at ? new Date(entry.created_at).toLocaleTimeString() : '';
        html += `
          <div class="prov-audit-entry">
            <div>
              <span class="prov-audit-entry__event">${_esc(entry.event)}</span>
              ${entry.detail ? `<span class="prov-audit-entry__detail"> · ${_esc(entry.detail.slice(0, 80))}</span>` : ''}
            </div>
            <span class="prov-audit-entry__time">${ts}</span>
          </div>`;
      }
      html += '</div>';
    }

    this._setBody(html);

    // Wire up verify buttons (only available if user has trust_reviewer role)
    this._drawer.querySelectorAll('.verify-btn').forEach(btn => {
      btn.addEventListener('click', () => this._verifyClaim(
        parseInt(btn.dataset.claim, 10),
        btn.dataset.dec,
        btn.closest('.prov-claim'),
      ));
    });
  }

  async _verifyClaim(claimId, decision, claimEl) {
    try {
      const token = localStorage.getItem('token');
      const res = await fetch(`/api/trust/claims/${claimId}/verify`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ claim_id: claimId, decision }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert(err.detail || `Error ${res.status}`);
        return;
      }
      const stateEl = claimEl.querySelector('.prov-claim__controls span');
      const icon = decision === 'approved' ? '✅' : '❌';
      if (stateEl) stateEl.textContent = `${icon} ${decision}`;
    } catch (err) {
      alert(`Failed to verify: ${err.message}`);
    }
  }
}


// ── initTrustAlertDot ────────────────────────────────────────────────────────

/**
 * Poll for unread trust alerts and show a red dot on a nav element.
 * @param {HTMLElement} navEl  the nav item to decorate
 */
function initTrustAlertDot(navEl) {
  if (!navEl) return;
  let dot = null;

  async function check() {
    try {
      const token = localStorage.getItem('token');
      if (!token) return;
      const res = await fetch('/api/trust/alerts?dismissed=false', {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) return;
      const alerts = await res.json();
      if (alerts.length > 0) {
        if (!dot) {
          dot = document.createElement('span');
          dot.className = 'trust-alert-dot';
          dot.title = `${alerts.length} unread trust alert${alerts.length > 1 ? 's' : ''}`;
          navEl.appendChild(dot);
        } else {
          dot.title = `${alerts.length} unread trust alert${alerts.length > 1 ? 's' : ''}`;
        }
      } else if (dot) {
        dot.remove();
        dot = null;
      }
    } catch (_) { /* silent */ }
  }

  check();
  setInterval(check, 60_000);  // re-check every minute
}


// ── Private helpers ───────────────────────────────────────────────────────────

function _esc(str) {
  if (!str) return '';
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function _buildTooltip(td) {
  if (!td) return 'No trust data';
  const parts = [];
  if (td.provider) parts.push(`${td.provider}/${td.model}`);
  if (td.evidence_basis) parts.push(`Basis: ${EVIDENCE_LABELS[td.evidence_basis] || td.evidence_basis}`);
  if (td.confidence_ceiling != null) parts.push(`Ceiling: ${Math.round(td.confidence_ceiling * 100)}%`);
  if (td.claim_count) parts.push(`${td.claim_count} claims`);
  if (td.flagged) parts.push(`⚠ ${_humaniseReason(td.flag_reason)}`);
  return parts.join(' · ') || 'Click for provenance';
}

function _humaniseReason(reason) {
  const map = {
    empty_output:                        'Model returned empty output.',
    model_self_reported_hallucination:   'Model may have hallucinated — review carefully.',
    pre_validation_failed:               'Input failed validation checks.',
    output_flagged:                      'Output flagged for human review.',
  };
  return map[reason] || reason || 'Unknown reason';
}

async function _dismissAlert(aiRunId) {
  try {
    const token = localStorage.getItem('token');
    // Find the alert ID for this run first
    const listRes = await fetch('/api/trust/alerts?dismissed=false', {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!listRes.ok) return;
    const alerts = await listRes.json();
    const match = alerts.find(a => a.ai_run_id === aiRunId);
    if (!match) return;
    await fetch('/api/trust/alerts/dismiss', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ alert_id: match.id }),
    });
  } catch (_) { /* silent */ }
}


// ── Exports ───────────────────────────────────────────────────────────────────

if (typeof window !== 'undefined') {
  window.TrustUI = {
    renderTrustBadge,
    renderEvidenceBasisBadge,
    renderLimitationBanner,
    ProvenanceDrawer,
    initTrustAlertDot,
  };
}
