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

  /* ---------- Science Bridge: expert intelligence engine ----------
     Deterministic V1 per the platform architecture doc (§9/§10):
     semantic-ish term matching over structured profiles + weighted
     criteria + generated explanation. No black box: every subscore
     derives from a real profile field. */
  SB_STOP: new Set(('a,an,and,are,as,at,be,by,for,from,has,have,in,into,is,it,its,of,on,or,that,the,their,' +
    'to,we,with,who,need,needs,needed,looking,find,expert,experts,expertise,researcher,researchers,' +
    'working,work,based,using,use,help,solve,our,your,new,can,how').split(',')),
  SB_SYN: {
    'ai': ['artificial intelligence', 'machine learning', 'deep learning', 'data science', 'neural'],
    'ml': ['machine learning', 'deep learning', 'ai'],
    'artificial': ['ai', 'machine learning'],
    'intelligence': ['ai', 'machine learning'],
    'nlp': ['natural language processing', 'language models', 'llm'],
    'llm': ['language models', 'nlp', 'generative'],
    'vision': ['computer vision', 'image', 'imaging'],
    'battery': ['batteries', 'lithium', 'energy storage', 'electrochemistry'],
    'batteries': ['battery', 'lithium', 'energy storage'],
    'lithium': ['battery', 'batteries', 'energy storage'],
    'solar': ['photovoltaic', 'renewable'],
    'renewable': ['solar', 'wind', 'energy transition', 'sustainable'],
    'hydrogen': ['fuel cell', 'energy'],
    'water': ['wastewater', 'membrane', 'hydrology', 'desalination'],
    'wastewater': ['water', 'membrane', 'treatment'],
    'oil': ['petroleum', 'gas', 'hydrocarbon'],
    'gas': ['oil', 'petroleum', 'hydrocarbon'],
    'mining': ['metallurgy', 'minerals', 'extraction'],
    'metallurgy': ['mining', 'metals', 'materials'],
    'materials': ['material', 'nanomaterials', 'polymers', 'metallurgy'],
    'cancer': ['oncology', 'tumor', 'immunotherapy'],
    'oncology': ['cancer', 'tumor'],
    'medical': ['medicine', 'clinical', 'health', 'biomedical'],
    'medicine': ['medical', 'clinical', 'biomedical', 'health'],
    'health': ['medical', 'public health', 'epidemiology'],
    'drug': ['pharmaceutical', 'pharmacology', 'therapeutics'],
    'genomics': ['genetics', 'sequencing', 'bioinformatics'],
    'agriculture': ['crop', 'farming', 'food'],
    'climate': ['environmental', 'carbon', 'sustainability'],
    'environmental': ['environment', 'climate', 'ecology', 'sustainability'],
    'robotics': ['robot', 'automation', 'mechatronics', 'control'],
    'manufacturing': ['production', 'industrial', 'automation'],
    'quantum': ['photonics', 'physics'],
    'finance': ['fintech', 'economics', 'banking'],
    'economics': ['economic', 'policy', 'finance'],
    'law': ['legal', 'policy', 'regulation'],
    'education': ['learning', 'pedagogy', 'teaching'],
    'security': ['cybersecurity', 'cryptography'],
    'space': ['satellite', 'aerospace', 'remote sensing'],
    'logistics': ['supply chain', 'transport', 'operations'],
    'defect': ['quality', 'inspection', 'detection'],
    'defects': ['quality', 'inspection', 'detection']
  },
  SB_REGION: ['Kazakhstan', 'Uzbekistan', 'Kyrgyzstan', 'Mongolia', 'Turkey', 'Pakistan', 'India'],
  SB_CRITERIA: [
    ['topic', 'Research-topic similarity', 35],
    ['pubs', 'Publication & profile relevance', 20],
    ['activity', 'Recent research activity', 10],
    ['projects', 'Relevant projects & breadth', 10],
    ['industry', 'Industry experience', 10],
    ['network', 'Network proximity', 5],
    ['geo', 'Geography & language', 5],
    ['collab', 'Collaboration interest', 5]
  ],

  sbTerms(query) {
    const words = (query || '').toLowerCase().replace(/[^a-zа-яё0-9&+\- ]/gi, ' ')
      .split(/[\s\-]+/).filter(w => (w.length > 2 || w === 'ai' || w === 'ml') && !this.SB_STOP.has(w));
    const seen = new Set(); const terms = [];
    for (const w of words) {
      if (seen.has(w)) continue;
      seen.add(w);
      terms.push({ term: w, alts: this.SB_SYN[w] || [] });
    }
    return terms;
  },

  expertSearch(query, people) {
    const terms = this.sbTerms(query);
    if (!terms.length) return { terms: [], results: [] };
    const results = [];
    for (const p of people) {
      const topics = (p.topics || []).map(t => t.toLowerCase());
      const kws = (p.keywords || []).map(t => t.toLowerCase());
      const fields = topics.concat(kws);
      const text = `${p.bio || ''} ${p.title || ''} ${p.institution || ''}`.toLowerCase();
      let topicHits = 0, textHits = 0;
      const matched = new Set();
      // short tokens ("ai", "ion", "gas") match whole words only — substring
      // matching there produces false hits like ion ⊂ sorption
      const hit = (hay, c) => c.length > 3 ? hay.includes(c)
        : hay.split(/[^a-zа-яё0-9]+/).includes(c);
      for (const { term, alts } of terms) {
        const cands = [term, ...alts];
        const fHit = fields.find(f => cands.some(c =>
          hit(f, c) || (c.length > 3 && f.length > 3 && c.includes(f))));
        if (fHit) { topicHits++; matched.add(fHit); continue; }
        if (cands.some(c => hit(text, c))) textHits++;
      }
      if (!topicHits && !textHits) continue;
      const coverage = (topicHits + 0.5 * textHits) / terms.length;
      if (coverage < 0.25) continue;

      const nMatch = matched.size;
      const title = (p.title || '').toLowerCase();
      const sub = {
        topic: Math.round(Math.min(100, 35 + 65 * Math.min(1, coverage * 1.15))),
        pubs: Math.round(Math.min(100, 40 + (p.link ? 32 : 0) + 28 * Math.min(1, nMatch / 3))),
        activity: Math.round(Math.min(100, 45 + (p.bio ? 22 : 0) +
          11 * Math.min(3, (p.topics || []).length + (p.keywords || []).length > 6 ? 3 : 1))),
        projects: Math.round(Math.min(100, 40 + 20 * Math.min(3, nMatch))),
        industry: p.sector === 'Industry' ? 95 : p.sector === 'Academia & Industry' ? 85 :
          /industry|engineer|founder|lead|director|manager|scientist at/.test(title) ? 75 : 45,
        network: p.featured ? 92 : p.institution ? 68 : 52,
        geo: this.SB_REGION.includes(p.country) ? 88 :
          (query.toLowerCase().includes((p.country || '¤').toLowerCase()) ? 95 : 72),
        collab: p.collab === 'yes' ? 95 : p.collab === 'maybe' ? 82 : 60
      };
      let score = 0;
      for (const [key, , w] of this.SB_CRITERIA) score += sub[key] * w / 100;
      score = Math.min(99, Math.round(score));
      results.push({ p, score, sub, matched: [...matched], coverage });
    }
    results.sort((a, b) => b.score - a.score || a.p.name.localeCompare(b.p.name));
    return { terms, results };
  },

  /* Generated, fact-based explanation — cites only real profile fields. */
  sbWhy(r, rank) {
    const p = r.p, bits = [];
    if (r.matched.length)
      bits.push(`Research profile spans ${r.matched.slice(0, 4).join(', ')} — directly matching your challenge`);
    if (p.title && p.institution) bits.push(`${p.title} at ${p.institution}`);
    else if (p.title) bits.push(p.title);
    else if (p.institution) bits.push(`based at ${p.institution}`);
    if (p.sector === 'Industry') bits.push('works in industry R&D rather than pure academia');
    else if (p.sector === 'Academia & Industry') bits.push('has experience across both academia and industry');
    if (p.collab === 'yes') bits.push('has volunteered for the QIST expert panel');
    else if (p.collab === 'maybe') bits.push('has expressed interest in the QIST expert panel');
    if (p.country) bits.push(`currently in ${p.country}`);
    return bits.map(b => b.charAt(0).toUpperCase() + b.slice(1)).join('. ') + '.';
  },

  /* ---------- shared chrome ---------- */
  renderHeader(active) {
    const u = this.currentUser();
    const links = [
      ['index.html', 'Home'], ['finder.html', 'Expert Finder'], ['map.html', 'Map'],
      ['directory.html', 'People'], ['channels.html', 'Channels'], ['matching.html', 'Matching'],
      ['newsletter.html', 'Newsletter'], ['organizations.html', 'For Organizations']
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
