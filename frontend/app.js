// frontend/app.js
// Seren — Dashboard shell, sidebar, topbar, token pill, guest gating.
// Requires api.js (getToken/setToken/fetchJson etc.)

if (window.__SEREN_APPJS_WIRED__) {
  // already wired — skip
} else {
  window.__SEREN_APPJS_WIRED__ = true;

  /* ── Helpers ─────────────────────────────────────────────── */
  function esc(s) {
    return String(s ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  /* SVG icon set — refined, consistent stroke-based icons */
  function icon(name) {
    const size = '18';
    const base = `width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"`;
    const icons = {
      search:  `<svg ${base}><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>`,
      library: `<svg ${base}><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>`,
      ai:      `<svg ${base}><path d="M12 2a4 4 0 0 1 4 4v1h1a3 3 0 0 1 0 6h-1v1a4 4 0 0 1-8 0v-1H7a3 3 0 0 1 0-6h1V6a4 4 0 0 1 4-4z"/><circle cx="12" cy="10" r="2"/></svg>`,
      info:    `<svg ${base}><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>`,
      paper:   `<svg ${base}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`,
      login:   `<svg ${base}><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>`,
      logout:  `<svg ${base}><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>`,
    };
    return icons[name] || `<svg ${base}><circle cx="12" cy="12" r="3"/></svg>`;
  }

  function currentPage() {
    const p = (location.pathname.split('/').pop() || '').toLowerCase();
    if (p === '' || p === 'index.html' || location.pathname === '/') return 'home';
    if (p.includes('search'))  return 'search';
    if (p.includes('library')) return 'library';
    if (p.includes('ai'))      return 'ai';
    if (p.includes('info'))    return 'info';
    if (p.includes('paper'))   return 'paper';
    if (p.includes('login'))   return 'login';
    return 'search';
  }

  function pageTitle() {
    const titles = {
      search:  'Search',
      library: 'Library',
      ai:      'AI Assistant',
      info:    'About',
      paper:   'Paper',
    };
    return titles[currentPage()] || 'Seren';
  }

  function requireAuthOrRedirect(target = 'login.html') {
    if (getToken()) return true;
    try { sessionStorage.setItem('after_login', location.pathname.split('/').pop() || 'search.html'); } catch {}
    window.location.href = target;
    return false;
  }
  window.requireAuthOrRedirect = requireAuthOrRedirect;

  function setTokenPill(state, text, tooltip = '') {
    const dot   = document.getElementById('tokenDot');
    const label = document.getElementById('tokenPillText');
    if (!dot || !label) return;
    dot.classList.remove('ok', 'bad', 'warn');
    dot.classList.add(state === 'ok' ? 'ok' : state === 'bad' ? 'bad' : 'warn');
    label.textContent = text;
    dot.title = tooltip;
    label.title = tooltip;
  }

  /* ── Shell construction ──────────────────────────────────── */
  function ensureDashboardShell() {
    const page = currentPage();
    if (page === 'login' || page === 'home') return;
    if (document.querySelector('.appShell')) return;

    const bodyKids = Array.from(document.body.children);
    const header   = document.querySelector('header');
    const main     = document.querySelector('main');

    const shell   = document.createElement('div');
    shell.className = 'appShell';

    const side    = document.createElement('aside');
    side.className = 'sidebar';

    const area    = document.createElement('div');
    area.className = 'mainArea';

    const top     = document.createElement('div');
    top.className = 'topbar';
    top.id = 'topbar';

    const content = document.createElement('div');
    content.className = 'content';
    content.id = 'content';

    if (main) {
      content.appendChild(main);
    } else {
      bodyKids.forEach(el => {
        if (el.tagName === 'SCRIPT') return;
        if (el.id === 'toastHost')   return;
        content.appendChild(el);
      });
    }

    if (header) header.remove();

    area.appendChild(top);
    area.appendChild(content);
    shell.appendChild(side);
    shell.appendChild(area);
    document.body.prepend(shell);
  }

  function wireSidebarDelegation() {
    const side = document.querySelector('.sidebar');
    if (!side || side.dataset.navWired === '1') return;
    side.dataset.navWired = '1';

    side.addEventListener('click', e => {
      const a = e.target.closest('a.sideBtn');
      if (!a) return;
      if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;

      const href = (a.getAttribute('href') || '').trim();
      if (href === '#' || href === '') { e.preventDefault(); return; }

      if (a.classList.contains('requiresLogin') && !getToken()) {
        e.preventDefault();
        showToast('Sign in required', 'Please log in to access this feature.', 'error');
        return;
      }

      e.preventDefault();
      window.location.assign(href);
    }, true);
  }

  /* ── Render nav ──────────────────────────────────────────── */
  function renderShellNav() {
    const page = currentPage();
    if (page === 'login' || page === 'home') return;
    ensureDashboardShell();

    const token    = getToken();
    const username = getUsername();
    const isGuest  = !token;

    const side = document.querySelector('.sidebar');
    const top  = document.getElementById('topbar');
    if (!side || !top) return;

    const navLinks = [
      { key: 'search',  href: 'search.html',  label: 'Search',  requiresLogin: false },
      { key: 'library', href: 'library.html', label: 'Library', requiresLogin: true  },
      { key: 'ai',      href: 'ai.html',       label: 'AI',      requiresLogin: true  },
      { key: 'info',    href: 'info.html',     label: 'About',   requiresLogin: false },
    ];

    side.innerHTML = `
      <a class="brandMark" href="/" title="Seren">S</a>

      <div class="sideGroup">
        ${navLinks.map(({ key, href, label, requiresLogin }) => {
          const isActive   = page === key;
          const needsLogin = requiresLogin && isGuest;
          const titleText  = needsLogin ? `${label} — sign in required` : label;
          return `
            <a class="sideBtn${isActive ? ' active' : ''}${needsLogin ? ' requiresLogin' : ''}"
               href="${needsLogin ? '#' : href}"
               title="${titleText}">
              ${icon(key)}
            </a>`;
        }).join('')}
      </div>

      <div class="sideSpacer"></div>

      ${token
        ? `<a class="sideBtn" href="#" id="logoutSide" title="Sign out">${icon('logout')}</a>`
        : `<a class="sideBtn" href="login.html" title="Sign in">${icon('login')}</a>`
      }
    `;

    top.innerHTML = `
      <div class="topLeft">
        <div class="pageTitle">${esc(pageTitle())}</div>
      </div>

      <div class="topSearch">
        <span class="searchIcon">${icon('search')}</span>
        <input id="topSearchInput" placeholder="Search literature…" autocomplete="off" />
      </div>

      <div class="topRight">
        <div class="pill">
          <span class="dot" id="tokenDot"></span>
          <span id="tokenPillText">—</span>
        </div>
        <div class="pill">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
          <b id="userPill">${esc(username || (token ? '…' : 'Guest'))}</b>
        </div>
        ${token
          ? `<button class="btn danger sm" id="logoutBtn">Sign out</button>`
          : `<a class="btn primary sm" href="login.html">Sign in</a>`
        }
      </div>
    `;

    function doLogout(e) {
      if (e) e.preventDefault();
      clearToken();
      setUsername('');
      sessionStorage.removeItem('last_external');
      sessionStorage.removeItem('open_study_id');
      window.location.href = '/';
    }

    const lo1 = document.getElementById('logoutBtn');
    const lo2 = document.getElementById('logoutSide');
    if (lo1) lo1.onclick = doLogout;
    if (lo2) lo2.onclick = doLogout;

    /* Wire top search to page search input */
    const topInput = document.getElementById('topSearchInput');
    const q        = document.getElementById('q');
    if (topInput) {
      if (q) {
        topInput.value = q.value || '';
        topInput.addEventListener('input', () => { q.value = topInput.value; });
        topInput.addEventListener('keydown', e => {
          if (e.key !== 'Enter') return;
          const btn = document.getElementById('searchBtn');
          if (btn) btn.click();
        });
      } else {
        topInput.addEventListener('keydown', e => {
          if (e.key === 'Enter') {
            window.location.href = `search.html?q=${encodeURIComponent(topInput.value)}`;
          }
        });
      }
    }

    wireSidebarDelegation();
  }

  /* ── Pill refresh (throttled) ────────────────────────────── */
  let __mePillFlight = false, __tokenPillFlight = false;
  let __mePillLast   = 0,     __tokenPillLast   = 0;
  const PILL_THROTTLE = 30000; // poll every 30s, not 5s — prevents flicker

  async function refreshUserPill() {
    const el = document.getElementById('userPill');
    if (!el) return;

    const token = getToken();
    if (!token) { el.textContent = getUsername() || 'Guest'; return; }

    const now = Date.now();
    if (__mePillFlight || now - __mePillLast < PILL_THROTTLE) return;
    __mePillLast = now;
    __mePillFlight = true;

    try {
      const me = await fetchJson('/me');
      if (me?.username) { setUsername(me.username); el.textContent = me.username; }
    } catch {
      el.textContent = getUsername() || 'Guest';
    } finally {
      __mePillFlight = false;
    }
  }

  async function refreshTokenPill() {
    const token = getToken();
    if (!token) {
      setTokenPill('warn', 'Guest mode', 'Sign in to save papers, annotate, and use AI.');
      return;
    }

    const now = Date.now();
    if (__tokenPillFlight || now - __tokenPillLast < PILL_THROTTLE) return;
    __tokenPillLast = now;
    __tokenPillFlight = true;

    try {
      const res = await fetchJson('/auth/token_status');
      if (res?.valid) {
        const mins = Math.max(0, Math.floor((res.seconds_left || 0) / 60));
        setTokenPill('ok', `Active · ${mins}m`);
      } else {
        // Token expired — update pill only, don't force redirect or re-render
        setTokenPill('bad', 'Session expired', 'Please sign in again.');
      }
    } catch (e) {
      // Network error (e.g. server restarting) — show offline, don't re-render shell
      setTokenPill('warn', 'Offline', 'Backend unreachable');
    } finally {
      __tokenPillFlight = false;
    }
  }

  /* ── Continue as guest ───────────────────────────────────── */
  function wireContinueAsGuest() {
    ['continueGuest', 'continueGuest2', 'guestBtn', 'guestBtn2']
      .map(id => document.getElementById(id))
      .filter(Boolean)
      .forEach(b => b.addEventListener('click', e => {
        e.preventDefault();
        clearToken();
        setUsername('');
        sessionStorage.removeItem('last_external');
        sessionStorage.removeItem('open_study_id');
        window.location.href = 'search.html';
      }));
  }

  /* ── Boot ────────────────────────────────────────────────── */
  async function boot() {
    renderShellNav();
    wireContinueAsGuest();
    await refreshUserPill();
    await refreshTokenPill();
  }

  if (!window.__SEREN_AUTH_EVENT_WIRED__) {
    window.__SEREN_AUTH_EVENT_WIRED__ = true;
    window.addEventListener('auth:changed', () => {
      renderShellNav();
      refreshUserPill();
      refreshTokenPill();
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    if (window.__SEREN_DID_BOOT__) return;
    window.__SEREN_DID_BOOT__ = true;
    boot();
  });
}