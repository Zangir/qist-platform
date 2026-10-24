/* ============================================================
   QIST Platform — shared application layer
   Data strategy: if a QIST API backend is reachable (see
   QIST.apiBase), use it; otherwise run in "static mode" from
   bundled JSON + a localStorage overlay so the site is fully
   functional on GitHub Pages.
   ============================================================ */
const QIST = {
  /* Build stamp. Open the browser console on the live site: if this does not match the
     release you uploaded, the file did not reach the server. */
  BUILD: '2026-10-17a',

  /* Positioning, in one place, so it cannot drift between pages.
     MVP phase 1: nine countries of Central Asia, the Caucasus and Mongolia, plus their
     researchers anywhere in the world. Later phases: worldwide. */
  BRAND: 'ScienceBridge AI',
  BRAND_BY: 'by QIST',
  REGION_SHORT: 'Central Asia, the Caucasus and Mongolia',
  REGION_LONG: 'Kazakhstan, Uzbekistan, Kyrgyzstan, Tajikistan, Turkmenistan, Azerbaijan, Georgia, Armenia and Mongolia',


  /* ================= LANGUAGE =================
     Three languages: Kazakh, Russian, English. The dictionaries live in assets/js/i18n.js,
     which loads before this file, so a page never flashes English before switching.

     What is translated: the interface — menus, buttons, forms, headings, and the sentences the
     match engine generates.

     What is NOT translated, deliberately: the conditions a funder publishes. An opportunity's
     title, summary and eligibility note stay in the language of the source, with a label saying
     so. Machine-translating "the host institution must be in an EU Member State" is exactly the
     class of harm this product exists to prevent — a researcher loses a week to a mistranslated
     condition. A curator may add title_kk / summary_kk / title_ru / summary_ru by hand, and
     those are used when present. Researchers' own names are never transliterated (D-15).

     Choosing the language: ?lang= in the URL, then the visitor's saved choice, then the
     browser, then English. */
  LANGS: [
    { code: 'kk', label: 'ҚАЗ', name: 'Қазақша' },
    { code: 'ru', label: 'РУС', name: 'Русский' },
    { code: 'en', label: 'ENG', name: 'English' }
  ],
  lang: 'en',

  detectLang() {
    const valid = c => this.LANGS.some(l => l.code === c);
    const fromUrl = new URLSearchParams(location.search).get('lang');
    if (valid(fromUrl)) return fromUrl;
    let saved = null;
    try { saved = localStorage.getItem('qist_lang'); } catch (_) {}
    if (valid(saved)) return saved;
    const nav = (navigator.languages || [navigator.language || '']).map(x => String(x).slice(0, 2).toLowerCase());
    const hit = nav.find(valid);
    return hit || 'en';
  },

  setLang(code, reload) {
    if (!this.LANGS.some(l => l.code === code)) return;
    this.lang = code;
    try { localStorage.setItem('qist_lang', code); } catch (_) {}
    document.documentElement.setAttribute('lang', code);
    const p = new URLSearchParams(location.search);
    p.set('lang', code);
    history.replaceState(null, '', '?' + p + location.hash);
    if (reload) location.reload();
  },

  /* Translate one key. Missing keys fall back to English and then to the key itself, so a
     gap shows up as a visible key rather than an empty box — and the tests fail on it. */
  t(key, vars) {
    const dicts = (typeof QIST_I18N !== 'undefined') ? QIST_I18N : {};
    const val = (dicts[this.lang] && dicts[this.lang][key])
             || (dicts.en && dicts.en[key]);
    if (val === undefined) {
      if (this.lang !== 'en') console.warn('[i18n] missing key:', key, 'for', this.lang);
      return key;
    }
    if (!vars) return val;
    return val.replace(/\{(\w+)\}/g, (m, k) => (vars[k] !== undefined ? vars[k] : m));
  },

  /* Apply the dictionary to markup. Three attributes, so a page carries its strings as keys:
       data-i18n              -> textContent
       data-i18n-html         -> innerHTML (only for strings that contain our own markup)
       data-i18n-attr="placeholder:key;aria-label:key"  -> attributes */
  applyI18n(root) {
    (root || document).querySelectorAll('[data-i18n]').forEach(el => {
      el.textContent = this.t(el.getAttribute('data-i18n'));
    });
    (root || document).querySelectorAll('[data-i18n-html]').forEach(el => {
      el.innerHTML = this.t(el.getAttribute('data-i18n-html'));
    });
    (root || document).querySelectorAll('[data-i18n-attr]').forEach(el => {
      el.getAttribute('data-i18n-attr').split(';').filter(Boolean).forEach(pair => {
        const [attr, key] = pair.split(':');
        if (attr && key) el.setAttribute(attr.trim(), this.t(key.trim()));
      });
    });
    const title = (root || document).querySelector('title[data-i18n-title]');
    if (title) document.title = `${this.t(title.getAttribute('data-i18n-title'))} · ${this.BRAND}`;
  },

  /* Opportunity text in the reader's language when a curator supplied it, otherwise the
     funder's own words plus an honest label. Never machine-translated. */
  oppText(o, field) {
    const localised = o[field + '_' + this.lang];
    if (localised) return { text: localised, translated: true };
    return { text: o[field] || '', translated: false };
  },

  // Set to a deployed FastAPI URL (e.g. "https://api.qist.org") to go live.
  // Can also be overridden without redeploy: localStorage.setItem('qist_api_url', '...')
  /* The address of the deployed API (see render.yaml). Empty = the site runs in static mode: profiles and positions are
     sent to the QIST team as requests instead of being stored. A browser can override it for testing. */
  API_DEFAULT: 'https://zangir-qist-api.hf.space',
  /* localStorage.qist_api_url overrides it for testing; the value 'off' forces static mode (what the site does whenever the API
     does not answer, so visitors are never left with a broken page). */
  apiBase: (() => { let v = ''; try { v = localStorage.getItem('qist_api_url') || ''; } catch (_) {} return v === 'off' ? '' : (v || 'https://zangir-qist-api.hf.space'); })(),
  apiAlive: false,
  cache: {},

  /* ---------- generic fetch helpers ---------- */
  async detectApi() {
    if (!this.apiBase) return false;
    try {
      const r = await fetch(this.apiBase + '/api/health', { signal: AbortSignal.timeout(6000) });
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

  /* Every public count and list uses this. Records flagged as a probable duplicate stay in
     the data for a human to resolve (D-14), but showing them made the same site say 492 on
     the home page and 497 in the directory, the map and the organizations page. */
  uniquePeople(people) {
    return people.filter(p => !p.possible_duplicate_of);
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
    /* A post that became a structured opportunity is not shown twice. The record itself is
       kept, with `superseded_by` pointing at the entry that replaced it — we do not delete
       people's posts to tidy up an interface. Posts in retired channels drop out the same way. */
    const live = new Set(this.channels().map(c => c.id));
    posts = posts.filter(p => !p.superseded_by && live.has(p.channel));
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

  /* Discussion channels.
     Jobs, Research Grants and Collaboration Requests were removed: every post in them was
     already a structured entry in Opportunities, where it carries an eligibility verdict and a
     source link. Two places for the same call is one place too many, and the weaker one wins
     the visitor's attention. What is left is what Opportunities cannot hold: events and talk. */
  channels() {
    return [
      { id: 'conferences', name: this.t('ch.conferences.name'), icon: 'cap',  desc: this.t('ch.conferences.desc') },
      { id: 'general',     name: this.t('ch.general.name'),     icon: 'chat', desc: this.t('ch.general.desc') }
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

  /* Accounts exist on the server only.
     This used to hold a demo login and the administrator password in public JS, so any
     visitor could sign into the admin console. Removed 2026-09-18, see DECISIONS D-11. */
  authAvailable() { return this.apiAlive; },

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
    // No backend: say so plainly instead of handing out a fake session.
    throw new Error('NO_BACKEND');
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
    // Registering into localStorage created the illusion of an account: the data stayed
    // in the visitor's browser and never reached us. Removed 2026-09-18.
    throw new Error('NO_BACKEND');
  },

  logout() {
    localStorage.removeItem('qist_session');
    location.href = 'index.html';
  },

  requireRole(role) {
    const u = this.currentUser();
    if (!u || (role === 'admin' && u.role !== 'admin')) {
      // Carry the chosen language through the redirect: landing on a sign-in page in a language
      // you did not choose is how a translated site still feels untranslated.
      location.href = 'login.html?lang=' + encodeURIComponent(this.lang) +
                      '&next=' + encodeURIComponent(location.pathname.split('/').pop());
      return null;
    }
    return u;
  },

  /* ---------- UI helpers ---------- */
  initials(name) {
    return name.split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('');
  },
  /* Four tones from the brand, not seven unrelated hues: a page of purple, red and olive
     avatars read as noise, and red already means "not eligible" everywhere else. */
  /* A member's photo when they added one, otherwise their initials on one of four brand tones. Only an inline
     image the member uploaded is accepted as a photo; anything else falls back to the initials. */
  avatarHtml(p, cls = '', attrs = '') {
    const ok = p && typeof p.photo === 'string' && /^data:image\/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+$/.test(p.photo);
    return ok
      ? `<div class="avatar has-photo ${cls}" ${attrs}><img src="${p.photo}" alt="" loading="lazy"></div>`
      : `<div class="avatar ${cls}" style="background:${this.avatarColor(p.name)}" ${attrs} aria-hidden="true">${this.initials(p.name)}</div>`;
  },
  avatarColor(name) {
    const palette = ['#2c4a77', '#2e6e62', '#4b5d78', '#1f4f63'];
    let h = 0; for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0;
    return palette[h % palette.length];
  },
  /* Inline stroke icons in place of emoji. Emoji render differently on every OS, ignore the
     text colour and carry their own mood (🤝, 📮) — an icon here is a label, not decoration.
     The pin means a known city; the globe means the record only holds a country (D-12). */
  ICONS: {
    pin: '<path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    external: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    map: '<path d="M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2zM9 4v14M15 6v14"/>',
    calendar: '<rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
    chat: '<path d="M20 15a2 2 0 0 1-2 2H8l-4 4V6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2z"/>',
    cap: '<path d="M2 9l10-5 10 5-10 5z"/><path d="M6 11v5c3 2 9 2 12 0v-5"/>'
  },
  icon(name) {
    return `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">${this.ICONS[name] || ''}</svg>`;
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
        ${this.avatarHtml(p)}
        <div>
          <h3>${this.esc(p.name)}</h3>
          <div class="role">${this.esc(p.title || '')}${p.institution ? ' · ' + this.esc(p.institution) : ''}</div>
          ${(p.city || p.country) ? `<div class="loc">${this.icon(this.hasPreciseGeo(p) ? 'pin' : 'globe')} ${this.esc(this.geoLabel(p))}</div>` : ''}
          ${p.possible_duplicate_of ? '<div class="loc" style="color:var(--red)">possible duplicate record — under review</div>' : ''}
        </div>
      </div>
      <div class="tags">${tags}</div>
      ${opts.footer || ''}
    </div>`;
  },

  /* ---------- shared chrome ---------- */
  renderHeader(active) {
    const u = this.currentUser();
    /* Public navigation lists objects, never audiences — with one deliberate exception.
       "For organizations" is the only audience item, because a university research office
       and a company arrive with a different question from a researcher: they want to put
       work in, not take opportunities out. See DECISIONS.md D-01 and D-27.
       map.html and matching.html are still absent: the map is a view inside Researchers,
       and matching is personal, so it lives behind sign-in. */
    const links = [
      ['index.html', this.t('nav.home')], ['opportunities.html', this.t('nav.opportunities')],
      ['directory.html', this.t('nav.researchers')], ['organizations.html', this.t('nav.organizations')],
      ['about.html', this.t('nav.about')]
    ];
    const nav = links.map(([href, label]) =>
      `<a href="${href}" class="${active === href ? 'active' : ''}"${active === href ? ' aria-current="page"' : ''}>${label}</a>`).join('');
    /* "Sign in" is shown only when a backend is configured. Without one, sign-in is disabled
       (D-11), and the button led to a form that could not be used — a dead end in the most
       prominent place on every page. "Create profile" works without a backend (D-29). */
    const auth = u
      ? `<a class="btn btn-ghost btn-sm" href="profile.html">${this.esc(u.name.split(' ')[0])}</a>
         ${u.role === 'admin' ? '<a class="btn btn-gold btn-sm" href="admin.html">Admin</a>' : ''}
         <button class="btn btn-ghost btn-sm" onclick="QIST.logout()">${this.t('nav.signout')}</button>`
      : `${this.apiBase ? `<a class="btn btn-ghost btn-sm" href="login.html">${this.t('nav.signin')}</a>` : ''}
         <a class="btn btn-gold btn-sm" href="join.html">${this.t('nav.create')}</a>`;

    /* Language switcher. Three codes, current one marked; the choice is remembered and also
       written into the address, so a link can be sent in the language it was read in. */
    const langs = this.LANGS.map(l =>
      `<button type="button" class="lang-opt${l.code === this.lang ? ' is-on' : ''}"
               data-lang="${l.code}" lang="${l.code}" title="${this.esc(l.name)}"
               aria-pressed="${l.code === this.lang}">${l.label}</button>`).join('');
    /* Brand lockup: the product name on the first line, the association under it in small
       capitals. "by QIST" used to sit in a bordered pill, which read as a separate badge
       stuck onto the name. It is an attribution line, so it is set as one. */
    document.getElementById('site-header').innerHTML = `
      <div class="container">
        <a class="brand" href="index.html">
          <span class="seal">Q</span>
          <span class="brand-lockup">
            <span class="brand-name">${this.BRAND}</span>
            <span class="brand-by">${this.BRAND_BY}</span>
          </span>
        </a>
        <nav class="main-nav" id="main-nav">${nav}
          ${u ? '' : `<a class="btn btn-gold nav-create" href="join.html">${this.t('nav.create')}</a>`}
        </nav>
        <div class="nav-auth">
          <div class="lang-switch" role="group" aria-label="${this.esc(this.t('nav.language'))}">${langs}</div>
          ${auth}
        </div>
        <button class="nav-toggle" type="button" aria-controls="main-nav" aria-expanded="false"
                aria-label="${this.esc(this.t('nav.menu'))}">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>
        </button>
      </div>`;

    document.querySelectorAll('.lang-opt').forEach(b =>
      b.addEventListener('click', () => this.setLang(b.dataset.lang, true)));
    const toggle = document.querySelector('.nav-toggle');
    const menu = document.getElementById('main-nav');
    toggle.addEventListener('click', () =>
      toggle.setAttribute('aria-expanded', String(menu.classList.toggle('open'))));
  },

  renderFooter() {
    const el = document.getElementById('site-footer');
    if (!el) return;
    el.innerHTML = `
      <div class="container">
        <div class="cols">
          <div>
            <h4>${this.t('foot.title', { brand: this.BRAND })}</h4>
            <p class="small">${this.t('foot.about', { short: this.t('region.short'), long: this.t('region.long') })}
            <a href="https://qista.org" style="display:inline" target="_blank" rel="noopener">qista.org</a></p>
          </div>
          <div>
            <h4>${this.t('foot.platform')}</h4>
            <a href="opportunities.html">${this.t('nav.opportunities')}</a>
            <a href="directory.html">${this.t('nav.researchers')}</a>
            <a href="map.html">${this.t('foot.map')}</a>
            <a href="organizations.html">${this.t('nav.organizations')}</a>
          </div>
          <div>
            <h4>${this.t('foot.community')}</h4>
            <a href="about.html">${this.t('nav.about')}</a>
            <a href="newsletter.html">${this.t('foot.newsletter')}</a>
            <a href="channels.html">${this.t('foot.discussions')}</a>
            <a href="join.html">${this.t('nav.create')}</a>
          </div>
        </div>
        <div class="fine">© ${new Date().getFullYear()} QIST · ${this.t('foot.fine', { short: this.t('region.short') })} · <a href="https://github.com/Aika369/qist-platform">${this.t('foot.source')}</a>
          <br><span class="photos">${this.t('foot.photos')}</span></div>
      </div>`;
  },

  /* ---------- QIST primary research fields ----------
     The canonical list researchers pick from. Keep this array as the single source of
     truth — the map, directory and matching pages all read it from here.

     Records may carry their own value:
       p.primaryField  = "Neuroscience"
       p.primaryFields = ["Neuroscience", "Biomedical Sciences, and Medicine"]
     When neither is set, the rules below infer fields from the free-text `topics` and
     `title` already in data/people.json. That inference is a bridge for the legacy
     records, not a permanent answer: ask people to choose their field at registration
     and store it on the record.
     ------------------------------------------------------------------ */
  PRIMARY_FIELDS: [
    'Artificial Intelligence',
    'Computer Science',
    'Data Science, and Statistics',
    'Cybersecurity, and Digital Technologies',
    'Robotics',
    'Engineering',
    'Electronics',
    'Materials Science',
    'Physics and Physical Sciences',
    'Mathematics and Computational Sciences',
    'Chemistry and Chemical Sciences',
    'Astronomy, Space Science',
    'Biology and Life Sciences',
    'Biotechnology, Genetics, and Bioinformatics',
    'Biomedical Sciences, and Medicine',
    'Neuroscience',
    'Pharmaceutical Sciences',
    'Public Health, Epidemiology',
    'Environmental Science',
    'Earth Sciences and Geosciences',
    'Energy, Renewable Energy',
    'Agriculture and Food Science',
    'Veterinary Sciences',
    'Economics',
    'Management, Entrepreneurship, Innovation',
    'Education, and Learning Sciences',
    'Law, Legal Studies, and Governance',
    'Politics, International Relations, and Public Policy',
    'Social Sciences',
    'Behavioral Sciences',
    'Communication and Media',
    'Architecture, and Design',
    'Arts, and Humanities',
    'Interdisciplinary Research',
    'Other Research Area'
  ],

  // keyword rules, evaluated against `topics` + `title` only (bios are too noisy)
  FIELD_RULES: [
    ['Artificial Intelligence', /\b(a\.?i\.?|artificial intelligence|machine learning|deep learning|llms?|large language models?|nlp|natural language processing|neural networks?|computer vision|generative ai|edge ai|ai accelerators|word embeddings|semantic parsing|multimodal ai|vision.language|kazllm|reasoning)\b/],
    ['Computer Science', /\b(computer science|software engineer|programming|algorithms?|computer engineering|computer graphics|devops|hci|human.computer interaction|media computer science|computational linguist|informatics)\b/],
    ['Data Science, and Statistics', /\b(data science|data analysis|data analytics|statistic|biostatistic|big data|econometric|bayesian|analytics|quantitat\w+ analys|data.driven|predictive modeling)\b/],
    ['Cybersecurity, and Digital Technologies', /\b(cyber ?security|syber security|information security|network security|blockchain|digital transformation|digital technolog|data protection|digital ethics|digital health algorithms)\b/],
    ['Robotics', /\b(robot\w*|human.robot|industrial automation|cyber.physical|intelligent control|drone technolog)\b/],
    ['Engineering', /\b(engineering|engineer\b|mechanical|civil\b|tribology|manufacturing|metrology|hydraulic|thermal.fluid|combustion|aerospace|transport\w* engineer|surface engineering|biomechanics|construction)\b/],
    ['Electronics', /\b(electronic\w*|semiconductor|integrated circuit|microelectrode|photonic|optoelectronic|electrical engineering|medium voltage|signal processing|wireless communication|fiber optic|sensing)\b/],
    ['Materials Science', /\b(material\w*|nanomaterial|nanotechnolog|nanoscience|polymer|coatings|corrosion|composite|perovskite|graphene|biomaterial|metallurg|ceramic|additive manufacturing|3d printing)\b/],
    ['Physics and Physical Sciences', /\b(physic\w*|optics|spectroscopy|quantum|laser|plasma|condensed matter|terahertz|nonlinear optics|gravitation|accelerator|ultrafast|topological insulators)\b/],
    ['Mathematics and Computational Sciences', /\b(mathematic\w*|mathemeatics|math\b|algebra|differential equations|pdes?|functional analysis|spectral theory|optimal stopping|optimization|game theory|integrable systems|computational (science|economics|materials|biology|microbiology)|inverse problems|navier.stokes)\b/],
    ['Chemistry and Chemical Sciences', /\b(chemistry|chemical\w*|catalysis|electrochemi\w*|organometallic|supramolecular|sorption|mass spectrometry|ssnmr|nmr\b|photocatalysis|cheminformatics|xps|xrd)\b/],
    ['Astronomy, Space Science', /\b(astronom\w*|astrophysic\w*|cosmolog\w*|space\b|nasa|black holes?|primordial|universe|satellite)\b/],
    ['Biology and Life Sciences', /\b(biolog\w*|life science\w*|microbiolog\w*|cell (biology|therapy|signaling)|plant\b|evolution|evo.devo|embryolog\w*|physiolog\w*|redox biology|mitophagy|parasitolog\w*)\b/],
    ['Biotechnology, Genetics, and Bioinformatics', /\b(biotech\w*|genetic\w*|genomic\w*|bioinformatic\w*|synthetic biology|gene therapy|epigenetic\w*|proteomic\w*|metagenomic\w*|dna|rna\b|stem cells?|protein (engineering|biomarker)|enetics)\b/],
    ['Biomedical Sciences, and Medicine', /\b(medicine|medical|biomedic\w*|biomedicine|clinical|oncolog\w*|cancer|cardio\w*|surger\w*|surgeon|immuno\w*|diabet\w*|nephrolog\w*|patholog\w*|radiolog\w*|pediatric\w*|obstetric\w*|gynecolog\w*|ophthalmolog\w*|anesthes\w*|hematolog\w*|md\b|patient|disease\w*|therapy|tissue engineering|regenerative medicine|vaccin\w*|nursing|dialysis|transplantation|endocrin\w*|rheumato\w*|dermatolog\w*|otolaryngolog\w*)\b/],
    ['Neuroscience', /\b(neuroscience|neurolog\w*|neurosurg\w*|neuromodulation|neurorehab\w*|neuroimaging|neurodegeneration|brain|parkinson\w*|alzheimer\w*|cognitive neuro\w*|dbs\b|eeg|fmri|stroke)\b/],
    ['Pharmaceutical Sciences', /\b(pharmac\w*|drug (discovery|delivery)|biopharma\w*|pharma\b|mucoadhesive)\b/],
    ['Public Health, Epidemiology', /\b(public health\w*|publich? healt|epidemiolog\w*|health (policy|polic\w*|system\w*|equity|financing|literacy|communication|awareness)|global health|nutrition|hpv|screening|biosafety)\b/],
    ['Environmental Science', /\b(environment\w*|sustainab\w*|climate|pollution|waste\w*|water (quality|purification|resources|treatment|technolog\w*)|circular\w*|life cycle assessment|carbon capture|co.?2|emissions|sewage|wastewater|ccs\b)\b/],
    ['Earth Sciences and Geosciences', /\b(geolog\w*|geophys\w*|geoscience\w*|earth (science|observation)|geodesy|gnss|seismic|hydrolog\w*|glaciolog\w*|glacier|soil\b|mining|oceanograph\w*|remote sensing|gis\b|petrol\b|oil ?& ?gas|rare earth|ore enrichment)\b/],
    ['Energy, Renewable Energy', /\b(energy|renewable|solar|hydrogen|batter\w+|lithium|photovoltaic|smart grid\w*|e.fuel|biofuel\w*|nuclear\b|wind\b|bess\b|fcr\b)\b/],
    ['Agriculture and Food Science', /\b(agricultur\w*|agro\w*|food\b|crop\w*|fertiliz\w*|precision agriculture|forestry|rural development|honey)\b/],
    ['Veterinary Sciences', /\b(veterinar\w*|animal health)\b/],
    ['Economics', /\b(economic\w*|economist|economics|finance|financial|macroeconom\w*|monetary|trade\b|banking|accounting|fintech|equity valuation|market.data)\b/],
    ['Management, Entrepreneurship, Innovation', /\b(management|manager|entrepreneur\w*|innovation|business|leadership|hrm\b|human capital|marketing|branding|strategy|strategic|startup|consulting|project management|supply chain|logistics|corporate governance|csr\b|people analytics|productivity|hospitality|tourism)\b/],
    ['Education, and Learning Sciences', /\b(education\w*|educator|teach\w*|learning|pedagog\w*|curriculum|school\b|edtech|literacy|college (access|success|counseling)|academic mobility|mentoring)\b/],
    ['Law, Legal Studies, and Governance', /\b(law\b|legal\b|governance|human rights|regulation\b|compliance|civil service|public administration)\b/],
    ['Politics, International Relations, and Public Policy', /\b(politic\w*|international relations|public policy|policy\b|diplomacy|foreign policy|geopolit\w*|security studies|elite studies|migration|development studies|eurasia|institutional development)\b/],
    ['Social Sciences', /\b(social science\w*|sociolog\w*|social polic\w*|anthropolog\w*|human geography|gender|social\b|demograph\w*)\b/],
    ['Behavioral Sciences', /\b(behavio\w*|psycholog\w*|cognitive|consumer behavior|well.being|burnout|affective touch)\b/],
    ['Communication and Media', /\b(communication|media\b|journalis\w*|public relations|social media)\b/],
    ['Architecture, and Design', /\b(architect\w*|design\b|urban (planning|road|forestry)|built environment|smart buildings|robotic fabrication)\b/],
    ['Arts, and Humanities', /\b(arts?\b|humanities|histor\w*|philosoph\w*|literature|language\w*|culture|cultural heritage|museum\w*|islamic studies|linguist\w*)\b/],
    ['Interdisciplinary Research', /\b(interdisciplinar\w*|multidisciplinar\w*|transdisciplinar\w*)\b/]
  ],

  _fieldCache: new WeakMap(),

  /* Returns the canonical field(s) for a person, always at least one. */
  primaryFields(p) {
    if (!p || typeof p !== 'object') return ['Other Research Area'];

    // 1. an explicit value on the record always wins
    const explicit = []
      .concat(p.primaryFields || [])
      .concat(p.primaryField ? [p.primaryField] : [])
      .filter(f => this.PRIMARY_FIELDS.indexOf(f) > -1);
    if (explicit.length) return explicit;

    // 2. otherwise infer, and remember the answer
    if (this._fieldCache.has(p)) return this._fieldCache.get(p);
    const hay = ((p.topics || []).join(' ') + ' ' + (p.title || '')).toLowerCase();
    const hits = [];
    for (const [field, re] of this.FIELD_RULES) {
      if (re.test(hay)) hits.push(field);
    }
    const out = hits.length ? hits.slice(0, 4) : ['Other Research Area'];
    this._fieldCache.set(p, out);
    return out;
  },

  /* Convenience: the single best field, for badges and cards. */
  primaryField(p) { return this.primaryFields(p)[0]; },

  /* { field: count } across a list of people. */
  fieldCounts(people) {
    const counts = {};
    (people || []).forEach(p => this.primaryFields(p).forEach(f => {
      counts[f] = (counts[f] || 0) + 1;
    }));
    return counts;
  },

  /* ================= OPPORTUNITIES AND ELIGIBILITY =================
     Data: data/opportunities.json + data/eligibility.json
     A verdict is never invented. It is read from the programmes table and always
     carries a link to the source it came from.
     ================================================================ */

  OPPORTUNITY_TYPES: {
    grant:           'Grant / call',
    consortium_role: 'Consortium role',
    academic_job:    'Academic position',
    industry_job:    'Industry R&D position',
    coauthor:        'Co-author wanted',
    rnd_challenge:   'Industry R&D challenge',
    expert_request:  'Expertise request',
    conference:      'Conference & publication'
  },

  FUNDING_LABELS: {
    confirmed:          'funding confirmed',
    not_confirmed:      'funding not confirmed',
    cofunding_required: 'co-funding required'
  },
  /* Labels in the reader's language. The two tables above stay as the canonical English
     values: the curator screen and validateOpportunity() read their keys. */
  typeLabel(type) {
    const v = this.t('opp.type.' + type);
    return v === 'opp.type.' + type ? (this.OPPORTUNITY_TYPES[type] || type) : v;
  },
  fundingLabel(status) {
    const v = this.t('opp.fund.' + status);
    return v === 'opp.fund.' + status ? (this.FUNDING_LABELS[status] || status) : v;
  },

  // Career-stage ranks: the declared stage must be at least the required one.
  STAGE_RANK: { any: 0, phd_student: 1, phd_plus: 2, postdoc_plus: 3, pi_only: 4 },

  /* Where an "Interested" response goes.
     Empty means responses are not wired up and the button honestly disables itself.
     Accepts a form endpoint that takes a JSON POST (Formspree, Web3Forms, Basin, or your
     own backend) or "mailto:address". Tally does NOT work here: its API only creates
     forms and needs a secret key. See README.md → "Wiring up responses". */
  INTEREST_ENDPOINT: 'https://formspree.io/f/xyezzgdo',

  /* QIST team contact. Used on about.html for the "this is my profile" and
     "delete my data" requests. While empty, those buttons disable themselves
     rather than leading nowhere. */
  CONTACT_EMAIL: 'info@qista.org',

  /* Where pilot sign-ups and digest subscriptions go.
     May be the same URL as INTEREST_ENDPOINT. While empty, the form disables itself
     instead of pretending it captured the address. */
  SIGNUP_ENDPOINT: 'https://formspree.io/f/xyezzgdo',

  async getOpportunities() {
    // curated calls live in data/opportunities.json (curate.html); members' positions come from /api/positions (feed.js)
    const all = await this.loadJSON('opportunities');
    return all.filter(o => o.status === 'published');
  },

  async getEligibility() { return this.loadJSON('eligibility'); },

  /* Returns the country verdict. Never throws: "unknown" is a legitimate answer.

     Two layers, checked in this order:

     1. The funder's own country list, carried on the opportunity itself as
        eligibility.countries_excluded / eligibility.countries_allowed. Some calls do not
        follow any programme-wide table: Faculty for the Future takes Uzbekistan, Kyrgyzstan,
        Tajikistan and Turkmenistan but not Kazakhstan; the TWAS developing-countries list
        omits Georgia and Armenia. A programme table cannot express that, and guessing it
        wrong costs a researcher a week of work.
     2. The programme table in data/eligibility.json (Horizon Europe, national schemes, open).

     A list on the opportunity must bring its own source link, exactly like a programme does.
     Empty or missing lists mean "no explicit list" and fall through to layer 2. */
  /* Country names in the reader's language.
     Shipping a 250-country table in three languages would be 750 strings to maintain and to
     get wrong. The browser already has the CLDR data, so we ask it; if it cannot answer (old
     browser, missing locale) we fall back to the English name in data/eligibility.json, which
     is always present. */
  countryName(code, elig) {
    const fallback = (elig && elig.countries && elig.countries[code]) || code || '';
    if (!code) return fallback;
    /* A hand-written name wins: not every browser ships Kazakh region data, and a verdict that
       says "Қазақстан" in one browser and "Kazakhstan" in another is a bug the reader sees. */
    const own = elig && elig['countries_' + this.lang];
    if (own && own[code]) return own[code];
    try {
      const dn = new Intl.DisplayNames([this.lang], { type: 'region' });
      const name = dn.of(code);
      // Chromium falls back to English silently; treat that as "no translation" only when it
      // matches the English name exactly, which is harmless either way.
      if (name) return name;
    } catch (_) { /* no Intl data for this locale */ }
    return fallback;
  },

  /* Pick `field_<lang>` when the data file carries it, otherwise the English original.
     Applies to eligibility statuses, programme names and career-stage labels. */
  loc(obj, field) {
    if (!obj) return '';
    return obj[field + '_' + this.lang] || obj[field] || '';
  },

  checkCountry(opp, countryCode, elig) {
    const e    = opp.eligibility || {};
    const key  = e.programme || 'open';
    const prog = elig.programmes[key] || elig.programmes.open;
    const countryName = this.countryName(countryCode, elig) || this.t('match.your_country');

    const listSource = e.countries_source_url ? {
      url: e.countries_source_url,
      name: e.countries_source_name || 'Funder country list',
      version: '', date: e.countries_source_date || ''
    } : null;

    const excluded = Array.isArray(e.countries_excluded) ? e.countries_excluded : [];
    const allowed  = Array.isArray(e.countries_allowed)  ? e.countries_allowed  : [];

    if (countryCode && excluded.includes(countryCode)) {
      const def = elig.statuses.not_eligible;
      return {
        status: 'not_eligible', verdict: def.verdict, label: this.loc(def, 'label'),
        text: this.t('elig.list.no', { country: countryName }),
        programme: this.loc(prog, 'name'), source: listSource || null
      };
    }
    if (allowed.length) {
      const ok  = countryCode && allowed.includes(countryCode);
      const def = ok ? elig.statuses.eligible : elig.statuses.not_eligible;
      return {
        status: ok ? 'eligible' : 'not_eligible', verdict: def.verdict, label: this.loc(def, 'label'),
        text: this.t(ok ? 'elig.list.yes' : 'elig.list.no', { country: countryName }),
        programme: this.loc(prog, 'name'), source: listSource || null
      };
    }

    const status = prog.countries[countryCode] || prog.default || 'unknown';
    const def = elig.statuses[status] || elig.statuses.unknown;
    return {
      status, verdict: def.verdict, label: this.loc(def, 'label'),
      text: this.loc(def, 'text').replace('{country}', countryName),
      programme: this.loc(prog, 'name'),
      source: prog.source_url ? {
        url: prog.source_url, name: prog.source_name,
        version: prog.source_version, date: prog.source_date
      } : null
    };
  },

  /* Does this opportunity belong under this research field?
     A call that is open to every discipline carries all_fields: true instead of a copy of
     the 35-item list, so the filter still finds it and the card does not show 35 tags. */
  fieldsMatch(opp, field) {
    if (!field) return true;
    if (opp.all_fields) return true;
    return (opp.fields || []).includes(field);
  },

  /* How many opportunities sit under each research field. Used to disable empty options
     in the filter, so nobody picks a field and lands on an empty page. */
  oppFieldCounts(opps) {
    const counts = {};
    this.PRIMARY_FIELDS.forEach(f => { counts[f] = 0; });
    opps.forEach(o => {
      if (o.all_fields) { this.PRIMARY_FIELDS.forEach(f => counts[f]++); return; }
      (o.fields || []).forEach(f => { if (f in counts) counts[f]++; });
    });
    return counts;
  },

  /* ---------- curator validation ----------
     One definition of a valid opportunity record, used by curate.html and by the tests.
     Errors block publication; warnings are for the curator to judge.
     `elig` is data/eligibility.json, `existing` the records already in the file. */
  validateOpportunity(o, elig, existing) {
    const errors = [], warnings = [];
    const others = (existing || []).filter(x => x !== o);
    const has = v => typeof v === 'string' && v.trim().length > 0;

    if (!has(o.id)) errors.push('id is required');
    else {
      if (!/^[a-z0-9][a-z0-9-]*$/.test(o.id)) errors.push('id may contain only lowercase letters, digits and hyphens');
      if (others.some(x => x.id === o.id)) errors.push(`id "${o.id}" is already used by another record`);
    }

    if (!(o.type in this.OPPORTUNITY_TYPES)) errors.push('type must be one of: ' + Object.keys(this.OPPORTUNITY_TYPES).join(', '));
    if (!['published', 'draft'].includes(o.status)) errors.push('status must be "published" or "draft"');
    if (!has(o.title) || o.title.trim().length < 10) errors.push('title is required and must say what the opportunity is (10 characters or more)');
    if (!has(o.organization)) errors.push('organization is required — the reader needs to know who is offering this');
    if (!has(o.summary) || o.summary.trim().length < 40) errors.push('summary is required and must be at least 40 characters');

    /* Where the entry came from. An external call must link to the funder's page — a reader
       who cannot check it has to take our word on a deadline. A post written by a QIST member
       ("looking for a co-author") has no funder page and is not forced to invent one. */
    const origin = o.origin || 'external';
    if (!['external', 'community'].includes(origin)) errors.push('origin must be "external" or "community"');
    if (origin === 'external') {
      if (!has(o.source_url)) errors.push('source_url is required: an external call must link to the page it was taken from');
      else if (!/^https:\/\/[^\s]+\.[^\s]+/.test(o.source_url)) errors.push('source_url must be a full https:// address');
      if (!has(o.source_name)) warnings.push('source_name is empty — say which site the entry came from');
    } else {
      if (has(o.source_url) && !/^https:\/\/[^\s]+\.[^\s]+/.test(o.source_url)) errors.push('source_url must be a full https:// address');
      if (!has(o.source_url)) warnings.push('posted inside QIST with no external link — the reader can only contact us about it');
    }

    if (!(o.career_stage in this.STAGE_RANK)) errors.push('career_stage must be one of: ' + Object.keys(this.STAGE_RANK).join(', '));
    if (!(o.funding_status in this.FUNDING_LABELS)) errors.push('funding_status must be one of: ' + Object.keys(this.FUNDING_LABELS).join(', '));

    if (has(o.deadline)) {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(o.deadline) || isNaN(new Date(o.deadline).getTime())) {
        errors.push('deadline must be a real date in YYYY-MM-DD form, or empty');
      } else if (this.isExpired(o)) {
        warnings.push('the deadline is in the past — the entry will be published as expired');
      }
    } else {
      warnings.push('no deadline — the card will say "no deadline", so make sure the call really is rolling');
    }

    const fields = o.fields || [];
    const unknown = fields.filter(f => !this.PRIMARY_FIELDS.includes(f));
    if (unknown.length) errors.push('research fields not in the QIST list: ' + unknown.join(', '));
    if (!o.all_fields && !fields.length) errors.push('choose at least one research field, or tick "open to all fields"');
    if (o.all_fields && fields.length) warnings.push('"open to all fields" is ticked, so the individual fields chosen are ignored');

    const e = o.eligibility || {};
    if (elig) {
      if (!has(e.programme) || !(e.programme in elig.programmes)) {
        errors.push('eligibility.programme must be one of: ' + Object.keys(elig.programmes).join(', '));
      }
      const codes = [].concat(e.countries_allowed || [], e.countries_excluded || []);
      const badCodes = codes.filter(c => !(c in elig.countries));
      if (badCodes.length) errors.push('unknown country codes: ' + badCodes.join(', '));
      if (codes.length && !has(e.countries_source_url)) {
        errors.push('a country list needs countries_source_url — a verdict without a source is a guess');
      }
      if ((e.countries_allowed || []).length && (e.countries_excluded || []).length) {
        warnings.push('both an allowed and an excluded list are set; the excluded list is checked first');
      }
      if (has(o.country) && !(o.country in elig.countries)) errors.push(`country "${o.country}" is not a known ISO code`);
    }

    return { ok: errors.length === 0, errors, warnings };
  },

  /* ================= MATCH ANALYSIS =================
     What this number is: the share of the opportunity's own stated requirements that you meet.
     Nothing else. It is counted, not predicted, and every line can be checked against the
     funder's page.

     What it is NOT: a probability of winning. We have no response data yet, so any weighted
     model would be a guess wearing the costume of mathematics (DECISIONS.md D-07). When
     `match_event` has real outcomes in it, a calibrated model can sit on top of this breakdown
     without changing what the reader sees.

     Two kinds of requirement:
       blocking — country eligibility, career stage, an open deadline. Fail one and the
                  application cannot be submitted, whatever the other lines say.
       soft     — research field, required methods. A mismatch costs you nothing to try.
     A requirement that the opportunity does not state is not counted at all, so a call with
     three conditions is scored out of three and not diluted to look weaker than it is. */
  matchOpportunity(opp, profile, elig) {
    const T = (k, v) => this.t(k, v);
    const criteria = [];
    const c = this.checkCountry(opp, profile.country, elig);
    const countryName = this.countryName(profile.country, elig) || T('match.your_country');

    criteria.push({
      key: 'country', label: T('match.country'), blocking: true,
      ok: c.verdict === 'ok', unknown: c.verdict === 'unk',
      detail: c.text,
      source: c.source
    });

    const s = this.checkStage(opp, profile.stage);
    const stages = elig['career_stages_' + this.lang] || elig.career_stages || {};
    const need = stages[opp.career_stage] || opp.career_stage;
    const have = stages[profile.stage] || profile.stage;
    criteria.push({
      key: 'stage', label: T('match.stage'), blocking: true, ok: s.ok, unknown: false,
      detail: s.ok ? T('match.stage.ok', { need, have }) : T('match.stage.bad', { need, have }),
      source: null
    });

    if (opp.deadline) {
      const expired = this.isExpired(opp), left = this.daysLeft(opp);
      criteria.push({
        key: 'deadline', label: T('match.deadline'), blocking: true, ok: !expired, unknown: false,
        detail: expired ? T('match.deadline.past', { date: opp.deadline })
                        : T('match.deadline.left', { days: left, date: opp.deadline }),
        source: null
      });
    }

    if (!opp.all_fields && (opp.fields || []).length) {
      const mine = profile.fields || [];
      const hit = (opp.fields || []).filter(f => mine.includes(f));
      criteria.push({
        key: 'field', label: T('match.field'), blocking: false,
        ok: mine.length ? hit.length > 0 : false,
        unknown: mine.length === 0,
        detail: !mine.length ? T('match.field.unknown')
              : hit.length   ? T('match.field.ok', { list: hit.join(', ') })
                             : T('match.field.bad', { list: (opp.fields || []).join(', ') }),
        source: null
      });
    }

    if ((opp.methods_required || []).length) {
      const mine = (profile.methods || []).map(m => m.toLowerCase());
      const hit = opp.methods_required.filter(m => mine.includes(m.toLowerCase()));
      const list = opp.methods_required.join(', ');
      criteria.push({
        key: 'methods', label: T('match.methods'), blocking: false,
        ok: hit.length === opp.methods_required.length,
        unknown: !mine.length,
        detail: !mine.length ? T('match.methods.unknown', { list })
              : hit.length === opp.methods_required.length ? T('match.methods.ok', { list })
              : T('match.methods.partial', { list, have: hit.length, total: opp.methods_required.length }),
        source: null
      });
    }

    const counted  = criteria.filter(x => !x.unknown);
    const met      = counted.filter(x => x.ok).length;
    const total    = counted.length;
    const unknown  = criteria.length - counted.length;
    const blockers = criteria.filter(x => x.blocking && !x.ok && !x.unknown);
    const pct      = total ? Math.round((met / total) * 100) : 0;

    /* The sentence a reader actually acts on. A blocking failure is stated first and plainly,
       because "84%" next to "you are not eligible" is how people waste a week. */
    let verdict, tone;
    if (blockers.length) {
      tone = 'bad';
      verdict = T('match.verdict.blocked', { list: blockers.map(b => b.label.toLowerCase()).join(' + ') });
    } else if (met === total && !unknown) {
      tone = 'ok';
      verdict = T('match.verdict.all');
    } else if (met === total) {
      /* Names what could not be checked instead of counting it: "1 more depend on details"
         was both ungrammatical and vaguer than the list itself. */
      tone = 'ok';
      const unchecked = criteria.filter(x => x.unknown).map(x => x.label.toLowerCase());
      verdict = T('match.verdict.all_known', { n: unknown, list: unchecked.join(', ') });
    } else {
      tone = 'warn';
      const soft = criteria.filter(x => !x.blocking && !x.ok && !x.unknown).map(x => x.label.toLowerCase());
      verdict = T('match.verdict.soft', { list: soft.join(' + ') });
    }

    return { met, total, unknown, pct, tone, verdict, criteria, blocked: blockers.length > 0 };
  },

  /* Condition chips, shown wherever a call appears (home page and Opportunities). Each chip
     names the condition in the reader's own terms, their country and their stage, and its
     colour is the result. The full sentence is in the title and in the details panel. */
  condChips(m, profile, elig) {
    const stages = elig['career_stages_' + this.lang] || elig.career_stages || {};
    const names = {
      country: this.countryName(profile.country, elig) || this.t('match.country'),
      stage: stages[profile.stage] || this.t('match.stage'),
      deadline: this.t('match.deadline'),
      field: this.t('match.field'),
      methods: this.t('match.methods')
    };
    return `<div class="conds">${m.criteria.map(c => {
      const cls = c.unknown ? 'unk' : c.ok ? 'ok' : 'bad';
      return `<span class="cond ${cls}" data-k="${c.key}" title="${this.esc(c.detail)}">${this.esc(names[c.key] || c.label)}</span>`;
    }).join('')}</div>`;
  },

  /* A select inside a sentence is as wide as the option it shows, not as wide as the longest
     of 250 country names, so "I'm a PhD based in Kazakhstan" stays on one line. */
  fitSelect(sel) {
    const measure = () => {
      const probe = document.createElement('span');
      const cs = getComputedStyle(sel);
      probe.style.cssText = `position:absolute;visibility:hidden;white-space:pre;font:${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily};letter-spacing:${cs.letterSpacing}`;
      probe.textContent = sel.options[sel.selectedIndex] ? sel.options[sel.selectedIndex].text : '';
      document.body.appendChild(probe);
      const pad = parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight);
      sel.style.width = Math.ceil(probe.getBoundingClientRect().width + pad + 8) + 'px';
      probe.remove();
    };
    measure();
    // Measured again once the web font is in: the fallback font is narrower than Inter.
    if (document.fonts && document.fonts.status !== 'loaded') document.fonts.ready.then(measure);
  },

  /* The left column of a call: the closing date in the reader's language and how far off it is. */
  whenCell(o) {
    if (!o.deadline) return `<div class="when"><b>${this.t('opp.col.none')}</b></div>`;
    /* Kazakh month abbreviations are written out: some browsers' ICU has no short Kazakh
       months and prints "M09 30" (the same gap as the country names, D-44). */
    const KK_MONTHS = ['қаң', 'ақп', 'нау', 'сәу', 'мам', 'мау', 'шіл', 'там', 'қыр', 'қаз', 'қар', 'жел'];
    const d = new Date(o.deadline + 'T00:00:00');
    let date = o.deadline;
    if (this.lang === 'kk') date = `${d.getDate()} ${KK_MONTHS[d.getMonth()]}`;
    else try { date = new Intl.DateTimeFormat(this.lang, { day: 'numeric', month: 'short' }).format(d); } catch (_) {}
    if (this.isExpired(o)) return `<div class="when"><b>${this.esc(date)}</b><span>${this.t('opp.col.closed')}</span></div>`;
    /* The bar under the date is how much of a 60-day window is left: a column of calls can
       be scanned for what is closing without reading every "in N days". */
    const n = this.daysLeft(o);
    const left = Math.max(0.04, Math.min(1, n / 60));
    return `<div class="when${n <= 7 ? ' soon' : n <= 30 ? ' near' : ''}"><b>${this.esc(date)}</b><span>${this.t('opp.deadline.days', { n })}</span><i class="left" style="--left:${left.toFixed(2)}" aria-hidden="true"></i></div>`;
  },

  /* On a pointer device the photograph inside the home numeral follows the cursor a little,
     so the figure reads as a window onto the picture rather than a flat fill. */
  parallax(el, strength = 4) {
    if (!el || this.reducedMotion() || !matchMedia('(hover: hover)').matches) return;
    const base = getComputedStyle(el).backgroundPosition.split(' ').map(v => parseFloat(v));
    if (base.length < 2 || base.some(Number.isNaN)) return;
    let raf = 0, tx = 0, ty = 0;
    const apply = () => { raf = 0; el.style.backgroundPosition = `${base[0] + tx}% ${base[1] + ty}%`; };
    window.addEventListener('pointermove', e => {
      tx = (e.clientX / innerWidth - .5) * strength * 2;
      ty = (e.clientY / innerHeight - .5) * strength * 2;
      if (!raf) raf = requestAnimationFrame(apply);
    }, { passive: true });
  },

  reducedMotion() {
    return !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches);
  },

  /* Count from one number to another, so a changed result is seen changing. */
  tweenNumber(el, from, to, ms = 450) {
    if (!el) return;
    if (from === to || this.reducedMotion()) { el.textContent = to; return; }
    const t0 = performance.now();
    const step = now => {
      const k = Math.min(1, (now - t0) / ms), e = 1 - Math.pow(1 - k, 3);
      el.textContent = Math.round(from + (to - from) * e);
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  },

  /* Re-render a list of calls and mark every condition chip whose result changed. When the
     reader switches country, the eye goes to the chips that flipped, not to all of them. */
  flashChanges(container, render) {
    const before = {};
    container.querySelectorAll('[data-opp] .cond[data-k]').forEach(c => {
      before[c.closest('[data-opp]').dataset.opp + ':' + c.dataset.k] = c.className;
    });
    render();
    if (!Object.keys(before).length) return;
    container.querySelectorAll('[data-opp] .cond[data-k]').forEach(c => {
      const was = before[c.closest('[data-opp]').dataset.opp + ':' + c.dataset.k];
      if (was && was !== c.className) c.classList.add('changed');
    });
  },

  checkStage(opp, userStage) {
    const need = this.STAGE_RANK[opp.career_stage] ?? 0;
    const have = this.STAGE_RANK[userStage] ?? 0;
    return { ok: have >= need, need: opp.career_stage, have: userStage };
  },

  isExpired(opp) {
    if (!opp.deadline) return false;
    return new Date(opp.deadline) < new Date(new Date().toDateString());
  },

  daysLeft(opp) {
    if (!opp.deadline) return null;
    return Math.ceil((new Date(opp.deadline) - new Date()) / 86400000);
  },

  /* Response. Returns {ok, reason}; the caller decides what to show. */
  /* Generic form submit to a configured endpoint. Returns {ok, reason}. */
  async submitForm(endpoint, payload) {
    if (!endpoint) return { ok: false, reason: 'not_configured' };
    if (endpoint.startsWith('mailto:')) {
      const subj = encodeURIComponent(payload._subject || 'ScienceBridge');
      const body = encodeURIComponent(JSON.stringify(payload, null, 2));
      location.href = `${endpoint}?subject=${subj}&body=${body}`;
      return { ok: true, reason: 'mailto' };
    }
    try {
      const r = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify(payload)
      });
      return r.ok ? { ok: true, reason: 'posted' } : { ok: false, reason: 'http_' + r.status };
    } catch (_) { return { ok: false, reason: 'network' }; }
  },

  /* How to present coordinates. 338 directory records hold a country centroid rather
     than a workplace: the source data has neither city nor organisation for them.
     Presenting those as a precise address would invent precision we do not have. */
  geoLabel(person) {
    const prec = person.geo_precision || (person.city ? 'city' : 'country');
    if (prec === 'city')    return [person.city, person.country].filter(Boolean).join(', ');
    if (prec === 'country') return (person.country || '') + ' · city not recorded';
    return 'Location not recorded';
  },

  /* Fills a <select> with countries: the nine priority ones first, then the rest. */
  fillCountrySelect(sel, elig, selected) {
    const names = elig.countries;
    const pri = elig.priority_countries || [];
    const esc = s => this.esc(s);
    const label = c => this.countryName(c, elig);
    const opt = c => `<option value="${esc(c)}"${c === selected ? ' selected' : ''}>${esc(label(c))}</option>`;
    // Sorted in the reader's language, so the list reads alphabetically in Kazakh and Russian too.
    const coll = new Intl.Collator(this.lang);
    const rest = Object.keys(names).filter(c => !pri.includes(c))
      .sort((a, b) => coll.compare(label(a), label(b)));
    sel.innerHTML =
      `<optgroup label="${esc(this.t('region.group.priority'))}">${pri.filter(c => names[c]).map(opt).join('')}</optgroup>` +
      `<optgroup label="${esc(this.t('common.allcountries'))}">${rest.map(opt).join('')}</optgroup>`;
  },
  hasPreciseGeo(person) { return (person.geo_precision || (person.city ? 'city' : 'country')) === 'city'; },

  /* Everything an organization sends goes through one function, so every request lands in the
     same inbox with a `kind` we can count later. Three kinds today:
       org_need           — a posted R&D task, vacancy or consortium search (goes to the curator)
       org_introduction   — a request to be introduced to a named researcher
       org_conversation   — a request for a 30-minute discovery call
     No contact detail of a researcher is ever returned by this call. An introduction request
     reaches QIST, and QIST asks that person first: PRD, "контакт не раскрывается без согласия". */
  async submitOrgRequest(kind, subject, payload) {
    return this.submitForm(this.SIGNUP_ENDPOINT, {
      _subject: subject,
      kind,
      ...payload,
      page: 'organizations.html',
      at: new Date().toISOString()
    });
  },

  async recordInterest(opp, ctx) {
    return this.submitForm(this.INTEREST_ENDPOINT, {
      _subject: 'Interested in: ' + opp.title,
      kind: 'opportunity_interest',
      opportunity_id: opp.id, opportunity_title: opp.title,
      country: ctx.country, career_stage: ctx.stage,
      user: (this.currentUser() || {}).email || '',
      at: new Date().toISOString()
    });
  },

  async boot(active) {
    console.info('QIST build', this.BUILD);
    /* Language is settled before anything is drawn, so no page shows English and then
       swaps under the reader's eyes. */
    this.lang = this.detectLang();
    document.documentElement.setAttribute('lang', this.lang);
    this.applyI18n(document);
    this.renderHeader(active);
    this.renderFooter();
    /* "/" puts the cursor in the page's search box, as on most search-heavy sites. */
    document.addEventListener('keydown', e => {
      if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return;
      const tag = (document.activeElement && document.activeElement.tagName) || '';
      if (/INPUT|TEXTAREA|SELECT/.test(tag) || document.activeElement.isContentEditable) return;
      const box = document.querySelector('[data-slash]');
      if (box) { e.preventDefault(); box.focus(); box.select && box.select(); }
    });
    await this.detectApi();
  }
};
