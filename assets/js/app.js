/* ============================================================
   QIST Platform — shared application layer
   Data strategy: if a QIST API backend is reachable (see
   QIST.apiBase), use it; otherwise run in "static mode" from
   bundled JSON + a localStorage overlay so the site is fully
   functional on GitHub Pages.
   ============================================================ */
const QIST = {
  // Set to a deployed FastAPI URL (e.g. "https://api.qist.org") to go live.
  // Can also be overridden without redeploy: localStorage.setItem('qist_api_url', '...')
  apiBase: localStorage.getItem('qist_api_url') || '',
  apiAlive: false,
  cache: {},

  /* ---------- generic fetch helpers ---------- */
  async detectApi() {
    if (!this.apiBase) return false;
    try {
      const r = await fetch(this.apiBase + '/api/health', { signal: AbortSignal.timeout(2500) });
      this.apiAlive = r.ok;
    } catch (_) { this.apiAlive = false; }
    return this.apiAlive;
  },

  async loadJSON(name) {
    if (this.cache[name]) return this.cache[name];
    const r = await fetch(`data/${name}.json`);
    this.cache[name] = await r.json();
    return this.cache[name];
  },

  /* localStorage overlay: user-created records on the static site */
  overlay(key) {
    try { return JSON.parse(localStorage.getItem('qist_' + key) || '[]'); }
    catch (_) { return []; }
  },
  saveOverlay(key, arr) { localStorage.setItem('qist_' + key, JSON.stringify(arr)); },
  pushOverlay(key, item) {
    const arr = this.overlay(key);
    item.id = item.id || 'loc_' + Date.now() + '_' + Math.floor(Math.random() * 1e5);
    arr.unshift(item);
    this.saveOverlay(key, arr);
    return item;
  },

  /* ---------- domain data ---------- */
  async getPeople() {
    if (this.apiAlive) {
      const r = await fetch(this.apiBase + '/api/people');
      return r.json();
    }
    const base = await this.loadJSON('people');
    const removed = new Set(this.overlay('removed_people'));
    const edits = Object.fromEntries(this.overlay('edited_people').map(p => [p.id, p]));
    const merged = base.filter(p => !removed.has(p.id)).map(p => edits[p.id] ? { ...p, ...edits[p.id] } : p);
    return [...this.overlay('people'), ...merged];
  },

  async getPosts(channel) {
    let posts;
    if (this.apiAlive) {
      const r = await fetch(this.apiBase + '/api/posts' + (channel ? `?channel=${channel}` : ''));
      posts = await r.json();
    } else {
      const base = await this.loadJSON('posts');
      const removed = new Set(this.overlay('removed_posts'));
      posts = [...this.overlay('posts'), ...base.filter(p => !removed.has(p.id))];
      if (channel) posts = posts.filter(p => p.channel === channel);
    }
    return posts.sort((a, b) => (b.date || '').localeCompare(a.date || ''));
  },

  async addPost(post) {
    post.date = post.date || new Date().toISOString().slice(0, 10);
    const u = this.currentUser();
    post.author = u ? u.name : 'Guest';
    if (this.apiAlive) {
      const r = await fetch(this.apiBase + '/api/posts', {
        method: 'POST', headers: this.authHeaders(), body: JSON.stringify(post)
      });
      return r.json();
    }
    return this.pushOverlay('posts', post);
  },

  async getNewsletter() {
    if (this.apiAlive) {
      const r = await fetch(this.apiBase + '/api/newsletter');
      return r.json();
    }
    return this.loadJSON('newsletter');
  },

  channels() {
    return [
      { id: 'jobs',       name: 'Jobs & Vacancies',        em: '💼', desc: 'Academic and industry positions relevant to Kazakhstani researchers — faculty openings, postdocs, PhD studentships, industry R&D roles.' },
      { id: 'grants',     name: 'Research Grants',         em: '🏛️', desc: 'Funding calls, fellowships and grant programmes — national (Kazakhstan MSHE), international (Horizon Europe, NSF, DFG) and private foundations.' },
      { id: 'conferences',name: 'Conferences & Events',    em: '🎓', desc: 'Calls for papers, upcoming conferences, workshops, summer schools and QIST community meetups.' },
      { id: 'collab',     name: 'Collaboration Requests',  em: '🤝', desc: 'Looking for a co-author, a dataset, lab access or a project partner? Post here and find collaborators across the diaspora.' },
      { id: 'general',    name: 'General Discussion',      em: '💬', desc: 'Everything else: advice on applications, life in academia, relocation, announcements and community news.' }
    ];
  },

  /* ---------- auth (demo/static mode uses localStorage; API mode uses JWT) ---------- */
  currentUser() {
    try { return JSON.parse(localStorage.getItem('qist_session') || 'null'); }
    catch (_) { return null; }
  },
  authHeaders() {
    const u = this.currentUser();
    const h = { 'Content-Type': 'application/json' };
    if (u && u.token) h['Authorization'] = 'Bearer ' + u.token;
    return h;
  },

  seededAccounts() {
    return [
      { email: 'admin@qist.kz', password: 'qist-admin-2026', name: 'QIST Admin', role: 'admin' },
      { email: 'member@qist.kz', password: 'qist-member-2026', name: 'Demo Member', role: 'member' }
    ];
  },

  async login(email, password) {
    if (this.apiAlive) {
      const r = await fetch(this.apiBase + '/api/auth/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      });
      if (!r.ok) throw new Error((await r.json()).detail || 'Invalid credentials');
      const data = await r.json();
      localStorage.setItem('qist_session', JSON.stringify(data));
      return data;
    }
    const users = [...this.seededAccounts(), ...this.overlay('accounts')];
    const u = users.find(x => x.email.toLowerCase() === email.toLowerCase() && x.password === password);
    if (!u) throw new Error('Invalid email or password.');
    const session = { email: u.email, name: u.name, role: u.role || 'member' };
    localStorage.setItem('qist_session', JSON.stringify(session));
    return session;
  },

  async register(fields) {
    if (this.apiAlive) {
      const r = await fetch(this.apiBase + '/api/auth/register', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(fields)
      });
      if (!r.ok) throw new Error((await r.json()).detail || 'Registration failed');
      const data = await r.json();
      localStorage.setItem('qist_session', JSON.stringify(data));
      return data;
    }
    const users = [...this.seededAccounts(), ...this.overlay('accounts')];
    if (users.some(x => x.email.toLowerCase() === fields.email.toLowerCase()))
      throw new Error('An account with this email already exists.');
    this.pushOverlay('accounts', { ...fields, role: 'member' });
    const session = { email: fields.email, name: fields.name, role: 'member' };
    localStorage.setItem('qist_session', JSON.stringify(session));
    return session;
  },

  logout() {
    localStorage.removeItem('qist_session');
    location.href = 'index.html';
  },

  requireRole(role) {
    const u = this.currentUser();
    if (!u || (role === 'admin' && u.role !== 'admin')) {
      location.href = 'login.html?next=' + encodeURIComponent(location.pathname.split('/').pop());
      return null;
    }
    return u;
  },

  /* ---------- UI helpers ---------- */
  initials(name) {
    return name.split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('');
  },
  avatarColor(name) {
    const palette = ['#2c4a77', '#2e6e62', '#7a4a2c', '#5a3d6e', '#a33a3a', '#1f6079', '#6e662e'];
    let h = 0; for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0;
    return palette[h % palette.length];
  },
  esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  },
  toast(msg) {
    let t = document.querySelector('.toast');
    if (!t) { t = document.createElement('div'); t.className = 'toast'; document.body.appendChild(t); }
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(t._h);
    t._h = setTimeout(() => t.classList.remove('show'), 3200);
  },

  personCard(p, opts = {}) {
    const tags = (p.topics || []).map(t =>
      `<span class="tag" data-topic="${this.esc(t)}">${this.esc(t)}</span>`).join('');
    return `
    <div class="card person-card" data-id="${this.esc(p.id)}">
      <div class="top">
        <div class="avatar" style="background:${this.avatarColor(p.name)}">${this.initials(p.name)}</div>
        <div>
          <h3>${this.esc(p.name)}</h3>
          <div class="role">${this.esc(p.title || '')}${p.institution ? ' · ' + this.esc(p.institution) : ''}</div>
          ${(p.city || p.country) ? `<div class="loc">📍 ${this.esc([p.city, p.country].filter(Boolean).join(', '))}</div>` : ''}
        </div>
      </div>
      <div class="tags">${tags}</div>
      ${opts.footer || ''}
    </div>`;
  },

  /* ---------- shared chrome ---------- */
  renderHeader(active) {
    const u = this.currentUser();
    const links = [
      ['index.html', 'Home'], ['map.html', 'Map'], ['directory.html', 'People'],
      ['channels.html', 'Channels'], ['matching.html', 'Matching'], ['newsletter.html', 'Newsletter']
    ];
    const nav = links.map(([href, label]) =>
      `<a href="${href}" class="${active === href ? 'active' : ''}">${label}</a>`).join('');
    const auth = u
      ? `<a class="btn btn-ghost btn-sm" href="profile.html">👤 ${this.esc(u.name.split(' ')[0])}</a>
         ${u.role === 'admin' ? '<a class="btn btn-primary btn-sm" href="admin.html">Admin</a>' : ''}
         <button class="btn btn-ghost btn-sm" onclick="QIST.logout()">Sign out</button>`
      : `<a class="btn btn-ghost btn-sm" href="login.html">Sign in</a>
         <a class="btn btn-primary btn-sm" href="login.html#register">Join QIST</a>`;
    document.getElementById('site-header').innerHTML = `
      <div class="container">
        <a class="brand" href="index.html"><span class="seal">Q</span> QIST</a>
        <button class="nav-toggle" onclick="document.querySelector('.main-nav').classList.toggle('open')">☰</button>
        <nav class="main-nav">${nav}</nav>
        <div class="nav-auth">${auth}</div>
      </div>`;
  },

  renderFooter() {
    const el = document.getElementById('site-footer');
    if (!el) return;
    el.innerHTML = `
      <div class="container">
        <div class="cols">
          <div>
            <h4>QIST — Qazaq International Science and Technology Association</h4>
            <p class="small">The global community of researchers, PhD students, postdocs, professors and
            industry experts from Kazakhstan working in 30+ countries. We connect scholars, share
            opportunities and promote Qazaq science worldwide. <a href="https://qista.org" style="display:inline" target="_blank" rel="noopener">qista.org</a></p>
          </div>
          <div>
            <h4>Platform</h4>
            <a href="map.html">Researcher map</a>
            <a href="directory.html">People directory</a>
            <a href="channels.html">Channels</a>
            <a href="matching.html">Academic matching</a>
          </div>
          <div>
            <h4>Community</h4>
            <a href="newsletter.html">Newsletter</a>
            <a href="channels.html?c=jobs">Jobs board</a>
            <a href="channels.html?c=grants">Grants</a>
            <a href="login.html#register">Become a member</a>
          </div>
        </div>
        <div class="fine">© ${new Date().getFullYear()} QIST community · Built by and for Kazakhstani researchers · <a href="https://github.com/Zangir/qist-platform" style="display:inline">Source on GitHub</a></div>
      </div>`;
  },

  async boot(active) {
    this.renderHeader(active);
    this.renderFooter();
    await this.detectApi();
  }
};
