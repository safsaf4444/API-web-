// frontend/app.js
// Dashboard shell (sidebar + topbar) + token pill + guest gating.
// Requires api.js (qs/getToken/setToken/fetchJson etc.)

/* ===========================
   ✅ PATCH: hard global guard
   Prevents this file from wiring twice (Live Server / injection / re-eval).
   =========================== */
if (window.__ME_APPJS_WIRED__) {
  // already wired
} else {
  window.__ME_APPJS_WIRED__ = true;

  const API_LABEL = window.API_BASE || "http://127.0.0.1:8000"; // display only

  function esc(s){
    return String(s ?? "")
      .replaceAll("&","&amp;")
      .replaceAll("<","&lt;")
      .replaceAll(">","&gt;")
      .replaceAll('"',"&quot;")
      .replaceAll("'","&#039;");
  }

  function icon(name){
    const m = {
      search: '⌕',
      library: '▦',
      paper: '▤',
      ai: '✦',
      info: 'i',
      login: '⎆',
      logout: '⟲'
    };
    return m[name] || '•';
  }

  function currentPage(){
    const p = (location.pathname.split('/').pop() || '').toLowerCase();
    if(p.includes('search')) return 'search';
    if(p.includes('library')) return 'library';
    if(p.includes('ai')) return 'ai';
    if(p.includes('info')) return 'info';
    if(p.includes('paper')) return 'paper';
    if(p.includes('login')) return 'login';
    return 'search';
  }

  function pageTitle(){
    const t = (document.title || 'Medical Evidence').split('-')[0].trim();
    return t || 'Medical Evidence';
  }

  function requireAuthOrRedirect(target="login.html"){
    if (getToken()) return true;
    try { sessionStorage.setItem("after_login", location.pathname.split('/').pop() || "search.html"); } catch {}
    window.location.href = target;
    return false;
  }

  window.requireAuthOrRedirect = requireAuthOrRedirect;

  function setTokenPill(state, text, tooltip=""){
    const dot = document.getElementById('tokenDot');
    const label = document.getElementById('tokenPillText');
    if(!dot || !label) return;
    dot.classList.remove('ok','bad','warn');
    if(state === 'ok') dot.classList.add('ok');
    else if(state === 'bad') dot.classList.add('bad');
    else dot.classList.add('warn');
    label.textContent = text;
    dot.title = tooltip || '';
    label.title = tooltip || '';
  }

  function ensureDashboardShell(){
    if(currentPage() === 'login') return;
    if(document.querySelector('.appShell')) return;

    const bodyKids = Array.from(document.body.children);
    const header = document.querySelector('header');
    const main = document.querySelector('main');

    const shell = document.createElement('div');
    shell.className = 'appShell';

    const side = document.createElement('aside');
    side.className = 'sidebar';

    const area = document.createElement('div');
    area.className = 'mainArea';

    const top = document.createElement('div');
    top.className = 'topbar';
    top.id = 'topbar';

    const content = document.createElement('div');
    content.className = 'content';
    content.id = 'content';

    if(main){
      content.appendChild(main);
    } else {
      bodyKids.forEach(el=>{
        if(el.tagName === 'SCRIPT') return;
        if(el.id === 'toastHost') return;
        content.appendChild(el);
      });
    }

    if(header) header.remove();

    area.appendChild(top);
    area.appendChild(content);
    shell.appendChild(side);
    shell.appendChild(area);

    document.body.prepend(shell);
  }

  function wireSidebarDelegation(){
    const side = document.querySelector('.sidebar');
    if(!side) return;

    if(side.dataset.navWired === "1") return;
    side.dataset.navWired = "1";

    side.addEventListener("click", (e) => {
      const a = e.target.closest("a.sideBtn");
      if(!a) return;

      if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;

      const href = (a.getAttribute("href") || "").trim();

      if(href === "#" || href === ""){
        e.preventDefault();
        e.stopImmediatePropagation();
        return;
      }

      if(a.classList.contains("requiresLogin") && !getToken()){
        e.preventDefault();
        e.stopImmediatePropagation();
        showToast("Login required","Please login to use this feature.","error");
        return;
      }

      e.preventDefault();
      e.stopImmediatePropagation();

      window.location.assign(href);
    }, true);
  }

  function renderShellNav(){
    if(currentPage() === 'login') return;
    ensureDashboardShell();

    const token = getToken();
    const username = getUsername();
    const isGuest = !token;
    const page = currentPage();

    const side = document.querySelector('.sidebar');
    const top = document.getElementById('topbar');
    if(!side || !top) return;

    side.innerHTML = `
      <div class="brandMark">ME</div>
      <div class="sideGroup">
        <a class="sideBtn ${page==='search'?'active':''}" href="search.html" title="Search"><span class="i">${icon('search')}</span></a>
        <a class="sideBtn ${page==='library'?'active':''} ${isGuest?'requiresLogin':''}" href="library.html" title="${isGuest?'Login required':'Saved papers'}"><span class="i">${icon('library')}</span></a>
        <a class="sideBtn ${page==='ai'?'active':''} ${isGuest?'requiresLogin':''}" href="ai.html" title="${isGuest?'Login required':'AI'}"><span class="i">${icon('ai')}</span></a>
        <a class="sideBtn ${page==='info'?'active':''}" href="info.html" title="Info"><span class="i">${icon('info')}</span></a>
      </div>
      <div class="sideSpacer"></div>
      ${
        token
          ? `<a class="sideBtn" href="#" id="logoutSide" title="Logout"><span class="i">${icon('logout')}</span></a>`
          : `<a class="sideBtn" href="login.html" title="Login"><span class="i">${icon('login')}</span></a>`
      }
    `;

    top.innerHTML = `
      <div class="topLeft">
        <div class="pageTitle">${esc(pageTitle())}</div>
      </div>

      <div class="topSearch">
        <span class="searchIcon">⌕</span>
        <input id="topSearchInput" placeholder="Search…" autocomplete="off" />
      </div>

      <div class="topRight">
        <div class="pill">API: <span class="mono">${esc(API_LABEL)}</span></div>
        <div class="pill">User: <b id="userPill">${esc(username || (token?'…':'guest'))}</b></div>
        <div class="pill"><span class="dot" id="tokenDot"></span><span id="tokenPillText">token: ?</span></div>
        ${token ? `<button class="btn danger" id="logoutBtn">Logout</button>` : `<a class="btn" href="login.html">Login</a>`}
      </div>
    `;

    function doLogout(e){
      if(e) e.preventDefault();
      clearToken();
      setUsername('');
      sessionStorage.removeItem('last_external');
      sessionStorage.removeItem('open_study_id');
      window.location.href = 'search.html';
    }

    const lo1 = document.getElementById('logoutBtn');
    const lo2 = document.getElementById('logoutSide');
    if(lo1) lo1.onclick = doLogout;
    if(lo2) lo2.onclick = doLogout;

    const topInput = document.getElementById('topSearchInput');
    const q = document.getElementById('q');
    if(topInput){
      if(q){
        topInput.value = q.value || '';
        topInput.addEventListener('input', ()=>{ q.value = topInput.value; });
        topInput.addEventListener('keydown', (e)=>{
          if(e.key !== 'Enter') return;
          const btn = document.getElementById('searchBtn');
          if(btn) btn.click();
        });
      } else {
        topInput.addEventListener('keydown', (e)=>{
          if(e.key === 'Enter') showToast('Search','Go to the Search page to run a query.','info');
        });
      }
    }

    wireSidebarDelegation();
  }

  let __ME_PILL_IN_FLIGHT__ = false;
  let __TOKEN_PILL_IN_FLIGHT__ = false;
  let __ME_PILL_LAST_AT__ = 0;
  let __TOKEN_PILL_LAST_AT__ = 0;
  const PILL_THROTTLE_MS = 5000;

  async function refreshUserPill(){
    const el = document.getElementById('userPill');
    if(!el) return;

    const token = getToken();
    if(!token){
      el.textContent = getUsername() || 'guest';
      return;
    }

    const now = Date.now();
    if(__ME_PILL_IN_FLIGHT__) return;
    if(now - __ME_PILL_LAST_AT__ < PILL_THROTTLE_MS) return;
    __ME_PILL_LAST_AT__ = now;
    __ME_PILL_IN_FLIGHT__ = true;

    try{
      const me = await fetchJson('/me');
      if(me && me.username){
        setUsername(me.username);
        el.textContent = me.username;
      }
    }catch{
      el.textContent = getUsername() || 'guest';
    }finally{
      __ME_PILL_IN_FLIGHT__ = false;
    }
  }

  async function refreshTokenPill(){
    const token = getToken();
    if(!token){
      setTokenPill('warn','token: guest','Guest mode: login only needed to save/comment/AI.');
      return;
    }

    const now = Date.now();
    if(__TOKEN_PILL_IN_FLIGHT__) return;
    if(now - __TOKEN_PILL_LAST_AT__ < PILL_THROTTLE_MS) return;
    __TOKEN_PILL_LAST_AT__ = now;
    __TOKEN_PILL_IN_FLIGHT__ = true;

    try{
      const res = await fetchJson('/auth/token_status');
      if(res && res.valid){
        const secs = typeof res.seconds_left === 'number' ? res.seconds_left : 0;
        const mins = Math.max(0, Math.floor(secs/60));
        setTokenPill('ok', `token: ok (${mins}m)`);
      } else {
        setTokenPill('bad','token: bad','Token invalid/expired. Login again.');
      }
    }catch(e){
      setTokenPill('warn','token: err', e?.message || String(e));
    }finally{
      __TOKEN_PILL_IN_FLIGHT__ = false;
    }
  }

  function wireContinueAsGuest(){
    const ids = ['continueGuest','continueGuest2','guestBtn','guestBtn2'];
    const btns = ids.map(id=>document.getElementById(id)).filter(Boolean);
    btns.forEach(b=>b.addEventListener('click', (e)=>{
      e.preventDefault();
      clearToken();
      setUsername('');
      sessionStorage.removeItem('last_external');
      sessionStorage.removeItem('open_study_id');
      window.location.href = 'search.html';
    }));
  }

  async function boot(){
    renderShellNav();
    wireContinueAsGuest();
    await refreshUserPill();
    await refreshTokenPill();
  }

  if (!window.__ME_AUTH_CHANGED_WIRED__) {
    window.__ME_AUTH_CHANGED_WIRED__ = true;
    window.addEventListener("auth:changed", () => {
      renderShellNav();
      refreshUserPill();
      refreshTokenPill();
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    if (window.__ME_DID_BOOT__) return;
    window.__ME_DID_BOOT__ = true;
    boot();
  });
}