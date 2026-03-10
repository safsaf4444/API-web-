<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Research tool project</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300;0,9..144,400;0,9..144,500;1,9..144,300;1,9..144,400&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;1,9..40,300&display=swap" rel="stylesheet">
<style>
/* ─── TOKENS ─────────────────────────────────────────── */
:root {
  --navy:      #0f2647;
  --navy-mid:  #1B3A6B;
  --navy-lt:   #2d5fa6;
  --cream:     #f5f2eb;
  --warm:      #ede8de;
  --ink:       #0d1b2a;
  --body:      #3a4a5c;
  --muted:     #7a8a9a;
  --rule:      #d4cfc5;
  --accent:    #c8964a;
  --green:     #2d6a4f;
  --green-bg:  #eaf4ef;
  --white:     #ffffff;
}

/* ─── RESET ──────────────────────────────────────────── */
*, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }
html { scroll-behavior: smooth; font-size: 16px; }

body {
  background: var(--cream);
  color: var(--ink);
  font-family: 'DM Sans', sans-serif;
  font-weight: 300;
  line-height: 1.6;
  overflow-x: hidden;
}

/* ─── SUBTLE PAPER TEXTURE ───────────────────────────── */
body::before {
  content: '';
  position: fixed; inset: 0;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='300' height='300'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.75' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='300' height='300' filter='url(%23n)' opacity='0.025'/%3E%3C/svg%3E");
  pointer-events: none;
  z-index: 0;
}

main { position: relative; z-index: 1; }

/* ─── NAV ─────────────────────────────────────────────── */
nav {
  position: fixed; top: 0; left: 0; right: 0;
  z-index: 100;
  padding: 18px 52px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: rgba(245,242,235,0.88);
  backdrop-filter: blur(14px);
  border-bottom: 1px solid var(--rule);
}

.nav-name {
  font-family: 'Fraunces', serif;
  font-size: 15px;
  font-weight: 400;
  color: var(--navy);
  letter-spacing: -0.01em;
}

.nav-links {
  display: flex; gap: 32px; list-style: none;
}

.nav-links a {
  font-size: 13px;
  font-weight: 400;
  color: var(--muted);
  text-decoration: none;
  letter-spacing: 0.01em;
  transition: color 0.2s;
}

.nav-links a:hover { color: var(--navy); }

/* ─── HERO ────────────────────────────────────────────── */
.hero {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 1fr 1fr;
  align-items: center;
  max-width: 1200px;
  margin: 0 auto;
  padding: 100px 52px 60px;
  gap: 80px;
}

.hero-left { opacity: 0; animation: rise 0.8s ease 0.1s forwards; }

.eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--navy-mid);
  margin-bottom: 28px;
}

.eyebrow-dot {
  width: 7px; height: 7px;
  background: var(--accent);
  border-radius: 50%;
  animation: breathe 3s ease-in-out infinite;
}

@keyframes breathe {
  0%,100% { transform: scale(1); opacity: 1; }
  50%      { transform: scale(0.7); opacity: 0.5; }
}

.hero h1 {
  font-family: 'Fraunces', serif;
  font-size: clamp(38px, 4.5vw, 64px);
  font-weight: 300;
  line-height: 1.1;
  letter-spacing: -0.03em;
  color: var(--navy);
  margin-bottom: 24px;
}

.hero h1 em {
  font-style: italic;
  color: var(--navy-lt);
  font-weight: 300;
}

.hero-desc {
  font-size: 16px;
  color: var(--body);
  line-height: 1.75;
  max-width: 460px;
  margin-bottom: 40px;
  font-weight: 300;
}

.hero-ctas {
  display: flex; gap: 12px; flex-wrap: wrap;
}

.btn {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: 'DM Sans', sans-serif;
  font-size: 13px;
  font-weight: 500;
  padding: 11px 22px;
  border-radius: 3px;
  text-decoration: none;
  transition: all 0.2s;
  letter-spacing: 0.01em;
  cursor: pointer;
}

.btn-navy {
  background: var(--navy);
  color: var(--cream);
  border: 1px solid var(--navy);
}
.btn-navy:hover {
  background: var(--navy-mid);
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(15,38,71,0.2);
}

.btn-ghost {
  background: transparent;
  color: var(--navy);
  border: 1px solid var(--rule);
}
.btn-ghost:hover {
  border-color: var(--navy);
  background: var(--warm);
}

/* ─── HERO RIGHT — STAT CARD ─────────────────────────── */
.hero-right {
  opacity: 0;
  animation: rise 0.8s ease 0.3s forwards;
}

.stat-card {
  background: var(--navy);
  color: var(--cream);
  border-radius: 6px;
  padding: 44px;
  position: relative;
  overflow: hidden;
}

.stat-card::before {
  content: '';
  position: absolute;
  top: -60px; right: -60px;
  width: 220px; height: 220px;
  border-radius: 50%;
  background: rgba(255,255,255,0.03);
  pointer-events: none;
}

.stat-card::after {
  content: '';
  position: absolute;
  bottom: -80px; left: -40px;
  width: 280px; height: 280px;
  border-radius: 50%;
  background: rgba(200,150,74,0.06);
  pointer-events: none;
}

.stat-card-label {
  font-size: 11px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: rgba(245,242,235,0.45);
  margin-bottom: 32px;
  font-weight: 500;
}

.stat-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 28px;
  margin-bottom: 36px;
}

.stat-item {}

.stat-num {
  font-family: 'Fraunces', serif;
  font-size: 40px;
  font-weight: 300;
  color: var(--cream);
  line-height: 1;
  margin-bottom: 4px;
  letter-spacing: -0.02em;
}

.stat-num span {
  font-size: 20px;
  color: var(--accent);
}

.stat-desc {
  font-size: 12px;
  color: rgba(245,242,235,0.5);
  font-weight: 300;
  letter-spacing: 0.02em;
}

.stat-rule {
  height: 1px;
  background: rgba(245,242,235,0.1);
  margin-bottom: 28px;
}

.stat-tags {
  display: flex; flex-wrap: wrap; gap: 8px;
}

.stat-tag {
  font-size: 11px;
  font-weight: 400;
  padding: 5px 12px;
  border-radius: 2px;
  background: rgba(245,242,235,0.07);
  color: rgba(245,242,235,0.65);
  border: 1px solid rgba(245,242,235,0.1);
  letter-spacing: 0.04em;
}

/* ─── SECTION COMMONS ────────────────────────────────── */
.section {
  max-width: 1100px;
  margin: 0 auto;
  padding: 80px 52px;
}

.section-rule {
  height: 1px;
  background: var(--rule);
  max-width: 1100px;
  margin: 0 auto 0;
}

.sec-kicker {
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--accent);
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.sec-kicker::after {
  content: '';
  flex: 0 0 32px;
  height: 1px;
  background: var(--accent);
  opacity: 0.4;
}

.sec-title {
  font-family: 'Fraunces', serif;
  font-size: clamp(26px, 3vw, 38px);
  font-weight: 300;
  letter-spacing: -0.02em;
  color: var(--navy);
  margin-bottom: 44px;
  line-height: 1.2;
}

/* ─── WHAT'S BUILT ───────────────────────────────────── */
.built-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1px;
  background: var(--rule);
  border: 1px solid var(--rule);
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 32px;
}

.bcard {
  background: var(--white);
  padding: 28px;
  transition: background 0.2s;
}

.bcard:hover { background: var(--warm); }

.bcard-num {
  font-family: 'Fraunces', serif;
  font-size: 11px;
  color: var(--muted);
  margin-bottom: 16px;
  letter-spacing: 0.08em;
}

.bcard h3 {
  font-family: 'Fraunces', serif;
  font-size: 16px;
  font-weight: 400;
  color: var(--navy);
  margin-bottom: 10px;
  letter-spacing: -0.01em;
  line-height: 1.3;
}

.bcard p {
  font-size: 13px;
  color: var(--body);
  line-height: 1.65;
  font-weight: 300;
}

.built-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 24px;
  background: var(--warm);
  border: 1px solid var(--rule);
  border-radius: 3px;
  flex-wrap: wrap;
  gap: 12px;
}

.built-footer-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.badge-row { display: flex; flex-wrap: wrap; gap: 8px; }

.badge {
  font-size: 11px;
  font-weight: 500;
  padding: 4px 10px;
  border-radius: 2px;
}
.badge-green { background: var(--green-bg); color: var(--green); border: 1px solid #a8d5be; }
.badge-navy  { background: rgba(27,58,107,0.08); color: var(--navy-mid); border: 1px solid rgba(27,58,107,0.18); }

/* ─── WHY IT EXISTS ──────────────────────────────────── */
.why-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 60px;
  align-items: start;
}

.why-text p {
  font-size: 15px;
  color: var(--body);
  line-height: 1.8;
  margin-bottom: 18px;
  font-weight: 300;
}

.why-text p strong {
  color: var(--navy);
  font-weight: 500;
}

.why-aside {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.aside-card {
  background: var(--white);
  border: 1px solid var(--rule);
  border-radius: 4px;
  padding: 22px;
  border-left: 3px solid var(--navy-mid);
  transition: border-left-color 0.2s;
}

.aside-card:hover { border-left-color: var(--accent); }

.aside-card h4 {
  font-family: 'Fraunces', serif;
  font-size: 14px;
  font-weight: 400;
  color: var(--navy);
  margin-bottom: 6px;
  letter-spacing: -0.01em;
}

.aside-card p {
  font-size: 13px;
  color: var(--muted);
  line-height: 1.6;
  font-weight: 300;
}

/* ─── IN DEVELOPMENT ─────────────────────────────────── */
.dev-list {
  display: flex;
  flex-direction: column;
  gap: 0;
  border: 1px solid var(--rule);
  border-radius: 4px;
  overflow: hidden;
  background: var(--white);
}

.dev-row {
  display: grid;
  grid-template-columns: 36px 1fr auto;
  align-items: start;
  gap: 20px;
  padding: 22px 26px;
  border-bottom: 1px solid var(--rule);
  transition: background 0.15s;
}

.dev-row:last-child { border-bottom: none; }
.dev-row:hover { background: var(--warm); }

.dev-index {
  font-family: 'Fraunces', serif;
  font-size: 13px;
  color: var(--muted);
  font-style: italic;
  padding-top: 2px;
}

.dev-content h3 {
  font-size: 14px;
  font-weight: 500;
  color: var(--navy);
  margin-bottom: 3px;
}

.dev-content p {
  font-size: 13px;
  color: var(--muted);
  font-weight: 300;
  line-height: 1.5;
}

.dev-status {
  font-size: 11px;
  font-weight: 500;
  padding: 4px 10px;
  border-radius: 2px;
  white-space: nowrap;
  margin-top: 2px;
  letter-spacing: 0.04em;
}

.status-active  { background: #fef3c7; color: #92400e; border: 1px solid #fde68a; }
.status-planned { background: rgba(27,58,107,0.07); color: var(--navy-mid); border: 1px solid rgba(27,58,107,0.15); }

/* ─── STACK ──────────────────────────────────────────── */
.stack-section {
  background: var(--navy);
  padding: 64px 0;
}

.stack-inner {
  max-width: 1100px;
  margin: 0 auto;
  padding: 0 52px;
}

.stack-inner .sec-kicker { color: rgba(245,242,235,0.45); }
.stack-inner .sec-kicker::after { background: rgba(245,242,235,0.2); }
.stack-inner .sec-title { color: var(--cream); margin-bottom: 36px; }

.stack-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.chip {
  font-size: 13px;
  font-weight: 300;
  padding: 8px 18px;
  border: 1px solid rgba(245,242,235,0.15);
  color: rgba(245,242,235,0.65);
  border-radius: 2px;
  background: rgba(245,242,235,0.04);
  transition: all 0.2s;
  letter-spacing: 0.02em;
}

.chip:hover {
  background: rgba(245,242,235,0.1);
  color: var(--cream);
  border-color: rgba(245,242,235,0.3);
}

/* ─── ABOUT / CONTACT ────────────────────────────────── */
.contact-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 60px;
  align-items: start;
}

.contact-text p {
  font-size: 15px;
  color: var(--body);
  line-height: 1.8;
  font-weight: 300;
  margin-bottom: 14px;
}

.contact-text strong { color: var(--navy); font-weight: 500; }

.contact-links {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.contact-link {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  background: var(--white);
  border: 1px solid var(--rule);
  border-radius: 3px;
  text-decoration: none;
  transition: all 0.2s;
}

.contact-link:hover {
  border-color: var(--navy);
  background: var(--warm);
  transform: translateX(3px);
}

.cl-left { display: flex; flex-direction: column; gap: 2px; }
.cl-lbl  { font-size: 10px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.1em; color: var(--muted); }
.cl-val  { font-size: 13px; color: var(--navy); font-weight: 400; }
.cl-arr  { color: var(--muted); font-size: 16px; transition: transform 0.2s, color 0.2s; }
.contact-link:hover .cl-arr { transform: translateX(4px); color: var(--navy); }

/* ─── FOOTER ─────────────────────────────────────────── */
footer {
  border-top: 1px solid var(--rule);
  padding: 24px 52px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--warm);
}

footer p { font-size: 12px; color: var(--muted); }

/* ─── ANIMATIONS ─────────────────────────────────────── */
@keyframes rise {
  from { opacity: 0; transform: translateY(20px); }
  to   { opacity: 1; transform: translateY(0); }
}

.fade-in {
  opacity: 0;
  transform: translateY(16px);
  transition: opacity 0.6s ease, transform 0.6s ease;
}
.fade-in.visible { opacity: 1; transform: none; }

/* ─── RESPONSIVE ─────────────────────────────────────── */
@media (max-width: 900px) {
  nav { padding: 16px 24px; }
  .hero { grid-template-columns: 1fr; padding: 100px 24px 60px; gap: 40px; min-height: auto; }
  .section { padding: 60px 24px; }
  .built-grid { grid-template-columns: 1fr; }
  .why-grid, .contact-grid { grid-template-columns: 1fr; gap: 32px; }
  .stack-inner { padding: 0 24px; }
  footer { padding: 20px 24px; flex-direction: column; gap: 8px; text-align: center; }
  .nav-links { display: none; }
}

/* ─── PRINT / PDF ────────────────────────────────────── */
@media print {
  * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }

  nav, .hero-ctas, .section-rule, footer { display: none !important; }

  body { background: white; font-size: 11px; }

  /* Hero — single column */
  .hero {
    display: block !important;
    padding: 24px 32px 20px !important;
    min-height: auto !important;
  }

  .hero-left { opacity: 1 !important; animation: none !important; }
  .hero-right { margin-top: 20px !important; opacity: 1 !important; animation: none !important; }

  .hero h1 { font-size: 32px !important; margin-bottom: 10px !important; }
  .hero-desc { font-size: 12px !important; margin-bottom: 0 !important; }

  /* Stat card compact */
  .stat-card { padding: 20px 24px !important; }
  .stat-grid { gap: 16px !important; }
  .stat-num { font-size: 26px !important; }

  /* Sections */
  .section {
    padding: 24px 32px !important;
    opacity: 1 !important;
    transform: none !important;
  }

  .fade-in { opacity: 1 !important; transform: none !important; }

  .sec-title { font-size: 20px !important; margin-bottom: 20px !important; }

  /* Built grid — 2 col for print */
  .built-grid {
    grid-template-columns: repeat(2, 1fr) !important;
  }

  .bcard { padding: 16px !important; }
  .bcard h3 { font-size: 13px !important; }
  .bcard p { font-size: 11px !important; }

  /* Why grid */
  .why-grid { grid-template-columns: 1fr 1fr !important; gap: 24px !important; }
  .why-text p { font-size: 11px !important; margin-bottom: 8px !important; }
  .aside-card { padding: 14px !important; }
  .aside-card h4 { font-size: 12px !important; }
  .aside-card p { font-size: 11px !important; }

  /* Dev list */
  .dev-row { padding: 14px 18px !important; }
  .dev-content h3 { font-size: 12px !important; }
  .dev-content p { font-size: 11px !important; }

  /* Stack section */
  .stack-section { padding: 24px 0 !important; }
  .stack-inner { padding: 0 32px !important; }
  .chip { font-size: 10px !important; padding: 4px 10px !important; }

  /* Contact */
  .contact-grid { grid-template-columns: 1fr 1fr !important; gap: 24px !important; }
  .contact-text p { font-size: 11px !important; }
  .contact-link { padding: 10px 14px !important; }

  /* Page breaks */
  #built { page-break-before: always; }
  .stack-section { page-break-before: always; }
}
</style>
</head>
<body>

<nav>
  <span class="nav-name">Research Conducting Tool</span>
  <ul class="nav-links">
    <li><a href="#built">Built</a></li>
    <li><a href="#why">Background</a></li>
    <li><a href="#development">In Development</a></li>
    <li><a href="#contact">Contact</a></li>
  </ul>
</nav>

<main>

<!-- ── HERO ──────────────────────────────────────────── -->
<section style="padding:0; max-width:none;">
  <div class="hero">
    <div class="hero-left">
      <div class="eyebrow">
        <span class="eyebrow-dot"></span>
        Solo Project — Active Development
      </div>
      <h1>Research Conducting Tool</h1>
      <p class="hero-desc">
        A full-stack tool for searching, importing, and AI-analysing peer-reviewed medical research — built from scratch by a Biomedical Science student who got tired of doing it manually.
      </p>
      <div class="hero-ctas">
        <a href="https://github.com/safsaf4444/API-web-" class="btn btn-navy" target="_blank">View on GitHub ↗</a>
        <a href="#built" class="btn btn-ghost">See what's built</a>
      </div>
    </div>

    <div class="hero-right">
      <div class="stat-card">
        <div class="stat-card-label">Project at a glance</div>
        <div class="stat-grid">
          <div class="stat-item">
            <div class="stat-num">4<span> APIs</span></div>
            <div class="stat-desc">Academic search providers</div>
          </div>
          <div class="stat-item">
            <div class="stat-num">93<span>+</span></div>
            <div class="stat-desc">Tests — all passing</div>
          </div>
          <div class="stat-item">
            <div class="stat-num">CI<span>/CD</span></div>
            <div class="stat-desc">Every push to GitHub</div>
          </div>
          <div class="stat-item">
            <div class="stat-num">0<span> £</span></div>
            <div class="stat-desc">AI included, no key needed</div>
          </div>
        </div>
        <div class="stat-rule"></div>
        <div class="stat-tags">
          <span class="stat-tag">Python</span>
          <span class="stat-tag">FastAPI</span>
          <span class="stat-tag">SQLModel</span>
          <span class="stat-tag">pytest</span>
          <span class="stat-tag">GitHub Actions</span>
          <span class="stat-tag">Gemini · Groq</span>
        </div>
      </div>
    </div>
  </div>
</section>

<div class="section-rule"></div>

<!-- ── WHAT'S BUILT ───────────────────────────────────── -->
<section class="section fade-in" id="built">
  <div class="sec-kicker">What exists</div>
  <h2 class="sec-title">What's been built</h2>

  <div class="built-grid">
    <div class="bcard">
      <div class="bcard-num">01</div>
      <h3>Multi-Source Search</h3>
      <p>Unified search across Europe PMC, Semantic Scholar, OpenAlex, and Crossref via a single provider abstraction layer — with retry logic, caching, and smart ranking.</p>
    </div>
    <div class="bcard">
      <div class="bcard-num">02</div>
      <h3>Deduplication Engine</h3>
      <p>DOI-first matching with cross-source reference tracking. Fuzzy title fallback for papers without a DOI. The same paper from four sources shows up once.</p>
    </div>
    <div class="bcard">
      <div class="bcard-num">03</div>
      <h3>Free-Tier AI Engine</h3>
      <p>Routes through Gemini Flash and Groq — no API key required. BYOK OpenAI also supported with encrypted key storage. Works for any student, immediately.</p>
    </div>
    <div class="bcard">
      <div class="bcard-num">04</div>
      <h3>Auth & API Security</h3>
      <p>JWT authentication, PBKDF2 password hashing, rate limiting middleware, and structured error handling throughout.</p>
    </div>
    <div class="bcard">
      <div class="bcard-num">05</div>
      <h3>Test Suite & CI/CD</h3>
      <p>93 tests covering auth, deduplication, provider parsing, and study management — all passing. GitHub Actions runs lint and tests on every single push.</p>
    </div>
    <div class="bcard">
      <div class="bcard-num">06</div>
      <h3>Smart Filters & Paper Detail</h3>
      <p>Automatic study type detection via regex — RCT, meta-analysis, cohort, systematic review. Open access filtering, quality ranking, and a tabbed paper detail panel.</p>
    </div>
  </div>

  <div class="built-footer">
    <span class="built-footer-label">Current status</span>
    <div class="badge-row">
      <span class="badge badge-green">✓ Search</span>
      <span class="badge badge-green">✓ Deduplication</span>
      <span class="badge badge-green">✓ AI Engine</span>
      <span class="badge badge-green">✓ Auth</span>
      <span class="badge badge-green">✓ CI/CD</span>
      <span class="badge badge-navy">⟳ Evidence Extraction — in progress</span>
    </div>
  </div>
</section>

<div class="section-rule"></div>

<!-- ── WHY IT EXISTS ──────────────────────────────────── -->
<section class="section fade-in" id="why">
  <div class="sec-kicker">Background</div>
  <h2 class="sec-title">Where it came from</h2>

  <div class="why-grid">
    <div class="why-text">
      <p>
        <strong>The problem is straightforward.</strong> Medical research is scattered across dozens of databases, inconsistently formatted, and almost impossible to evaluate quickly without significant training. As a student, you spend more time finding papers than reading them.
      </p>
      <p>
        Existing tools either cost money, require institutional access, or don't go far enough. None of them do what a student actually needs — search everything at once, remove duplicates automatically, and tell you whether a paper is worth reading in under a minute.
      </p>
      <p>
        This platform was built to change that. The target user is anyone trying to understand the evidence on a clinical question — whether that's a student, a clinician, or a patient. The goal is to make the same research accessible to all of them.
      </p>
    </div>

    <div class="why-aside">
      <div class="aside-card">
        <h4>Why four providers?</h4>
        <p>Europe PMC covers biomedical literature with full-text access. Semantic Scholar is strong on citation data. OpenAlex is open and broad. Crossref is authoritative for DOI resolution. Together they cover the vast majority of peer-reviewed literature without paywalls.</p>
      </div>
      <div class="aside-card">
        <h4>Why deduplication matters</h4>
        <p>Search the same term across four databases and the same paper comes back multiple times with slightly different metadata. Without deduplication, 40 results might be 15 papers. The engine fixes this silently.</p>
      </div>
      <div class="aside-card">
        <h4>Why free-tier AI?</h4>
        <p>The target user is a student. A tool that only works with a paid API key is a tool most students won't use. Free-tier routing was a deliberate product decision from day one.</p>
      </div>
    </div>
  </div>
</section>

<div class="section-rule"></div>

<!-- ── IN DEVELOPMENT ─────────────────────────────────── -->
<section class="section fade-in" id="development">
  <div class="sec-kicker">What's next</div>
  <h2 class="sec-title">In development</h2>

  <div class="dev-list">
    <div class="dev-row">
      <span class="dev-index">i.</span>
      <div class="dev-content">
        <h3>Structured Evidence Extraction</h3>
        <p>AI extraction of clinical evidence from abstracts — study design, key findings, limitations, and quality indicators.</p>
      </div>
      <span class="dev-status status-active">In progress</span>
    </div>
    <div class="dev-row">
      <span class="dev-index">ii.</span>
      <div class="dev-content">
        <h3>Multi-Paper Analysis</h3>
        <p>Compare and reason across multiple studies simultaneously — consensus, contradictions, and methodological differences.</p>
      </div>
      <span class="dev-status status-planned">Planned</span>
    </div>
    <div class="dev-row">
      <span class="dev-index">iii.</span>
      <div class="dev-content">
        <h3>Research Translation</h3>
        <p>The same findings rewritten for different audiences — patient, clinician, policy maker, student.</p>
      </div>
      <span class="dev-status status-planned">Planned</span>
    </div>
    <div class="dev-row">
      <span class="dev-index">iv.</span>
      <div class="dev-content">
        <h3>Further Capabilities</h3>
        <p>Citation visualisation, semantic search, document upload, and additional features across a multi-phase roadmap.</p>
      </div>
      <span class="dev-status status-planned">Planned</span>
    </div>
  </div>
</section>

<!-- ── STACK ──────────────────────────────────────────── -->
<div class="stack-section fade-in">
  <div class="stack-inner">
    <div class="sec-kicker">Technologies</div>
    <h2 class="sec-title">Stack</h2>
    <div class="stack-chips">
      <span class="chip">Python</span>
      <span class="chip">FastAPI</span>
      <span class="chip">SQLModel</span>
      <span class="chip">SQLite</span>
      <span class="chip">Alembic</span>
      <span class="chip">JWT Auth</span>
      <span class="chip">pytest</span>
      <span class="chip">GitHub Actions</span>
      <span class="chip">ruff</span>
      <span class="chip">JavaScript</span>
      <span class="chip">HTML / CSS</span>
      <span class="chip">Europe PMC API</span>
      <span class="chip">Semantic Scholar API</span>
      <span class="chip">OpenAlex API</span>
      <span class="chip">Crossref API</span>
      <span class="chip">Gemini Flash</span>
      <span class="chip">Groq — Llama 3.3</span>
      <span class="chip">OpenAI API</span>
      <span class="chip">Fernet Encryption</span>
    </div>
  </div>
</div>

<!-- ── CONTACT ────────────────────────────────────────── -->
<section class="section fade-in" id="contact">
  <div class="sec-kicker">Get in touch</div>
  <h2 class="sec-title">About the builder</h2>

  <div class="contact-grid">
    <div class="contact-text">
      <p>
        Built by a <strong>second-year Biomedical Science student at Royal Holloway, University of London</strong> — with a background in biology, chemistry, and a long-standing interest in neuroscience.
      </p>
      <p>
        The platform is actively in development. The foundation — search, AI engine, deduplication, test infrastructure — is complete and stable. There's a long roadmap ahead.
      </p>
      <p>
        <strong>Immediately available</strong> for internships, placements, and work experience in digital health, software engineering, or related fields.
      </p>
    </div>

    <div class="contact-links">
      <a href="https://github.com/safsaf4444/API-web-" class="contact-link" target="_blank">
        <div class="cl-left">
          <span class="cl-lbl">Repository</span>
          <span class="cl-val">github.com/safsaf4444/API-web-</span>
        </div>
        <span class="cl-arr">→</span>
      </a>
      <a href="https://github.com/safsaf4444" class="contact-link" target="_blank">
        <div class="cl-left">
          <span class="cl-lbl">GitHub</span>
          <span class="cl-val">github.com/safsaf4444</span>
        </div>
        <span class="cl-arr">→</span>
      </a>
      <a href="/cdn-cgi/l/email-protection#83d8faecf6f1a3e6eee2eaefde" class="contact-link">
        <div class="cl-left">
          <span class="cl-lbl">Email</span>
          <span class="cl-val">safasaheerp@gmail.com/span>
        </div>
        <span class="cl-arr">→</span>
      </a>
      <div class="contact-link" style="cursor:default;">
        <div class="cl-left">
          <span class="cl-lbl">University</span>
          <span class="cl-val">Royal Holloway, University of London</span>
        </div>
      </div>
    </div>
  </div>
</section>

</main>

<footer>
  <p>Medical Evidence Platform — actively in development</p>
  <p>Built with Python · FastAPI · HTML/CSS</p>
</footer>

<script data-cfasync="false" src="/cdn-cgi/scripts/5c5dd728/cloudflare-static/email-decode.min.js"></script><script>
  // Scroll-triggered fade-ins
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(e => {
      if (e.isIntersecting) {
        e.target.classList.add('visible');
        observer.unobserve(e.target);
    