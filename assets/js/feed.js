/* ============================================================
   Opportunities — per-reader matching of grants, vacancies, collaborations and members' papers.

   Four kinds of item share one engine:
     grant / job  the daily feeds (data/feeds/*.json, built by pipeline/run.py) AND the calls QIST curates by hand
                  (data/opportunities.json) AND positions members post (backend /api/positions). Curated calls
                  carry a checked eligibility verdict (QIST.matchOpportunity) with its reasons and sources.
     collab       consortium roles, co-author calls, R&D challenges, expert requests, conferences (curated)
     paper        papers members list on their profile
   Everything in this
   file runs in the reader's browser: the profile never leaves it unless the reader is signed in
   to a QIST backend, and the same profile + the same data always give the same ranking. There
   is no model in the loop; every point of a score has a named reason that the card shows.

   Score (0-100) = 100 x relevance x stage x place x freshness x quality, where

     relevance  how well the item fits what the reader works on
                  field   1 - the item is in one of the reader's fields (first-listed field 1.0, others .6) x .6
                  keyword the reader's own phrases found in the title (.7 each) or the abstract (.35)
                  relevance = 1 - (1 - field)(1 - keyword)
     stage      career stage fit (matrix below). A vacancy for the wrong stage is hidden, a grant is demoted.
     place      jobs only. The reader's chosen countries; unknown location is demoted slightly, remote counts.
     freshness  half-life 10 days for articles, 21 for jobs; grants by deadline.
     quality    articles: journal tier (preprints lower). Others 1.

   The vocabulary (data/taxonomy.json) is the one pipeline/taxonomy.py classified the items with.
   ============================================================ */
(function () {
  const STAGES = ['any', 'phd_student', 'phd_plus', 'postdoc_plus', 'pi_only'];  // same values as opportunities.html

  /* reader stage -> how well an item aimed at `phd | postdoc | researcher | faculty | any` suits them */
  const FIT = {
    any:          { phd: 1,  any: 1, researcher: .2, postdoc: 0,  faculty: 0 },
    phd_student:  { phd: 1,  any: 1, researcher: .3, postdoc: .3, faculty: 0 },
    phd_plus:     { phd: .1, any: 1, researcher: 1,  postdoc: 1,  faculty: .3 },
    postdoc_plus: { phd: 0,  any: 1, researcher: .8, postdoc: 1,  faculty: .7 },
    pi_only:      { phd: 0,  any: 1, researcher: .5, postdoc: .2, faculty: 1 }
  };

  const norm = s => String(s || '').toLowerCase().replace(/[\s\-\u2010-\u2015/_]+/g, ' ').trim();
  const escRe = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  /* A term matches on word boundaries; a trailing * allows any word ending. Same rule as taxonomy.py. */
  const termRe = t => new RegExp('(^|[^a-z0-9])' + escRe(norm(t)).replace(/\\\*/g, '\\w*').replace(/ /g, '\\s') + '(?![a-z0-9])');
  /* The reader's own phrase: "perovskite solar cell" should also find "perovskite solar cells". */
  const phraseRe = p => new RegExp('(^|[^a-z0-9])' + escRe(norm(p)).replace(/ /g, '\\s') + '(s|es)?(?![a-z0-9])');

  const DAY = 86400000;
  const daysBetween = (isoDate, now) => Math.round((now - new Date(isoDate + 'T00:00:00Z').getTime()) / DAY);

  const Feed = {
    KINDS: ['grant', 'job', 'collab', 'paper'],
    /* curated opportunity type -> tab */
    OPP_KIND: { grant: 'grant', academic_job: 'job', industry_job: 'job', consortium_role: 'collab', coauthor: 'collab',
                rnd_challenge: 'collab', expert_request: 'collab', conference: 'collab' },
    MIN_RELEVANCE: 0.15,
    _tax: null, _compiled: null,

    /* ---------- vocabulary ---------- */
    async loadTaxonomy() {
      if (!this._tax) {
        this._tax = await (await fetch('data/taxonomy.json')).json();
        this._compiled = {};
        for (const [f, terms] of Object.entries(this._tax.fields)) {
          this._compiled[f] = terms.map(t => [termRe(t), norm(t).split(' ').length > 1]);
        }
      }
      return this._tax;
    },
    /* Fields suggested by free text (the reader's keywords). Needs loadTaxonomy() first. */
    fieldsFromText(text) {
      const ti = norm(text), out = [];
      for (const [f, terms] of Object.entries(this._compiled || {})) {
        let s = 0;
        for (const [rx, multi] of terms) if (rx.test(ti)) s += 3 * (multi ? 2 : 1);
        if (s >= 3) out.push([f, s]);
      }
      return out.sort((a, b) => b[1] - a[1]).slice(0, 3).map(x => x[0]);
    },

    /* ---------- profile ---------- */
    defaultProfile() {
      return { stage: 'phd_plus', country: 'KZ', fields: [], keywords: [], jobCountries: [], remote: true, allStages: false };
    },
    sanitizeProfile(p) {
      const o = Object.assign(this.defaultProfile(), p || {});
      if (!STAGES.includes(o.stage)) o.stage = this.defaultProfile().stage;
      const list = v => (Array.isArray(v) ? v : []).map(x => String(x).trim()).filter(Boolean);
      o.fields = list(o.fields).filter(f => !this._tax || this._tax.fields[f]).slice(0, 6);
      o.keywords = [...new Set(list(o.keywords).map(k => k.slice(0, 60)))].slice(0, 12);
      o.jobCountries = list(o.jobCountries).map(c => c.toUpperCase()).slice(0, 8);
      o.country = String(o.country || '').toUpperCase().slice(0, 2);
      o.remote = o.remote !== false;
      o.allStages = !!o.allStages;
      return o;
    },
    loadProfile() {
      try { return this.sanitizeProfile(JSON.parse(localStorage.getItem('qist_feed_profile') || 'null')); }
      catch (_) { return this.sanitizeProfile(null); }
    },
    hasProfile() {
      try { return !!localStorage.getItem('qist_feed_profile'); } catch (_) { return false; }
    },
    saveProfile(p) {
      const clean = this.sanitizeProfile(p);
      try { localStorage.setItem('qist_feed_profile', JSON.stringify(clean)); } catch (_) {}
      return clean;
    },
    /* Signed-in readers keep the profile on the account; everyone else keeps it in the browser. */
    async pullRemoteProfile() {
      if (!QIST.apiAlive || !QIST.currentUser()) return null;
      try {
        const r = await fetch(QIST.apiBase + '/api/me/feed-profile', { headers: QIST.authHeaders() });
        if (!r.ok) return null;
        const d = await r.json();
        return d && d.profile ? this.sanitizeProfile(d.profile) : null;
      } catch (_) { return null; }
    },
    async pushRemoteProfile(p) {
      if (!QIST.apiAlive || !QIST.currentUser()) return false;
      try {
        const r = await fetch(QIST.apiBase + '/api/me/feed-profile', {
          method: 'PUT', headers: QIST.authHeaders(), body: JSON.stringify({ profile: p })
        });
        return r.ok;
      } catch (_) { return false; }
    },

    /* ---------- saved / dismissed / last visit ---------- */
    _state() {
      try { return Object.assign({ saved: {}, dismissed: {}, visit: {} }, JSON.parse(localStorage.getItem('qist_feed_state') || '{}')); }
      catch (_) { return { saved: {}, dismissed: {}, visit: {} }; }
    },
    _put(s) { try { localStorage.setItem('qist_feed_state', JSON.stringify(s)); } catch (_) {} },
    isSaved(id) { return !!this._state().saved[id]; },
    isDismissed(id) { return !!this._state().dismissed[id]; },
    savedItems() { return Object.values(this._state().saved); },
    toggleSaved(item) {
      const s = this._state();
      if (s.saved[item.id]) delete s.saved[item.id]; else s.saved[item.id] = item;
      this._put(s);
      return !!s.saved[item.id];
    },
    isDismissedAny() { return Object.keys(this._state().dismissed).length > 0; },
    dismiss(id) { const s = this._state(); s.dismissed[id] = new Date().toISOString().slice(0, 10); this._put(s); },
    undismissAll() { const s = this._state(); s.dismissed = {}; this._put(s); },
    /* The date of the reader's previous visit: items first seen after it are "new for you". */
    touchVisit(today) {
      const s = this._state(), v = s.visit || {};
      if (v.cur !== today) { v.prev = v.cur || null; v.cur = today; }
      s.visit = v; this._put(s);
      return v.prev;
    },

    /* ---------- data ---------- */
    /* A curated call or a member's post, in the shape the matcher uses. The original stays on `opp`
       because the eligibility check reads it. */
    fromOpp(o) {
      const kind = this.OPP_KIND[o.type] || 'collab';
      const where = [o.city, o.country].filter(Boolean).join(', ');
      return {
        id: o.id, kind, curated: true, origin: o.origin || 'external', type: o.type, opp: o, title: o.title, org: o.organization || '',
        summary: o.summary || '', url: o.source_url || '', deadline: o.deadline || null, fields: o.all_fields ? [] : (o.fields || []),
        allFields: !!o.all_fields, countries: o.country && kind === 'job' ? [o.country] : [], location: o.where || where,
        remote: !!o.remote, stages: ['any'], posted: o.curated_at || null, first_seen: o.curated_at || null, postedBy: o.posted_by || ''
      };
    },
    fromPaper(p) {
      return Object.assign({ kind: 'paper', org: '', stages: ['any'], first_seen: p.first_seen || p.posted || null }, p);
    },

    async _json(url, fallback) {
      try { const r = await fetch(url); return r.ok ? await r.json() : fallback; } catch (_) { return fallback; }
    },
    /* All four lists. The static site has the daily feeds and the curated file; a backend adds
       members' positions and papers. A missing piece degrades to an empty list, never to an error page. */
    async load() {
      await this.loadTaxonomy();
      const api = QIST.apiAlive ? QIST.apiBase : '';
      const [meta, grants, jobs, opps, papersStatic, positions, papersApi] = await Promise.all([
        this._json('data/feeds/meta.json', null),
        this._json('data/feeds/grants.json', { items: [], failed: true }),
        this._json('data/feeds/jobs.json', { items: [], failed: true }),
        QIST.getOpportunities().catch(() => []),
        this._json('data/papers.json', []),
        api ? this._json(api + '/api/positions', []) : [],
        api ? this._json(api + '/api/papers', []) : []
      ]);
      const data = { grant: [], job: [], collab: [], paper: [] };
      (grants.items || []).forEach(i => data.grant.push(i));
      (jobs.items || []).forEach(i => data.job.push(i));
      [...opps, ...positions].forEach(o => { const it = this.fromOpp(o); data[it.kind].push(it); });
      const seen = new Set();
      [...papersApi, ...papersStatic].forEach(p => {
        const key = (p.doi || p.title || '').toLowerCase();
        if (key && !seen.has(key)) { seen.add(key); data.paper.push(this.fromPaper(p)); }
      });
      return { meta, data, failed: { grant: !!grants.failed, job: !!jobs.failed } };
    },

    /* ---------- scoring ---------- */
    /* Prepare a profile once: compile phrases, merge explicit fields with the ones the keywords imply. */
    prepare(profile) {
      const p = this.sanitizeProfile(profile);
      const implied = this.fieldsFromText(p.keywords.join(' . ')).filter(f => !p.fields.includes(f));
      return {
        profile: p,
        fields: p.fields,
        impliedFields: implied,
        phrases: p.keywords.map(k => ({ k, rx: phraseRe(k) })),
        empty: !p.fields.length && !p.keywords.length
      };
    },

    /* -> { score, hidden, why, reasons: [{kind, text}] }. `now` is a ms timestamp (injectable for tests). */
    score(item, prep, now, ctx) {
      now = now || Date.now();
      if (item.kind === 'paper') return this._scorePaper(item, prep, now);
      if (item.curated) return this._scoreCurated(item, prep, now, ctx || {});
      const T = k => QIST.t(k);
      const reasons = [];
      const title = norm(item.title), body = norm((item.summary || '') + ' ' + (item.org || '') + ' ' + (item.department || '') + ' ' + (item.venue || ''));

      // --- relevance
      let fieldW = 0, hitField = null;
      const mine = prep.fields.concat(prep.impliedFields);
      (item.fields || []).forEach((f, i) => {
        const w = (i === 0 ? 1 : .6) * (prep.fields.includes(f) ? 1 : .8);
        if (mine.includes(f) && w > fieldW) { fieldW = w; hitField = f; }
      });
      if (hitField) reasons.push({ kind: 'field', text: hitField });
      let miss = 1;
      const hits = [];
      for (const { k, rx } of prep.phrases) {
        if (rx.test(title)) { miss *= .3; hits.push(k); }
        else if (rx.test(body)) { miss *= .65; hits.push(k); }
      }
      hits.slice(0, 3).forEach(k => reasons.push({ kind: 'keyword', text: k }));
      const kw = 1 - miss;
      let rel = 1 - (1 - fieldW * .6) * (1 - kw);
      if (prep.empty) rel = .3;
      if (rel < this.MIN_RELEVANCE) return { score: 0, hidden: true, why: 'relevance', reasons };

      // --- stage
      const stages = item.stages && item.stages.length ? item.stages : ['any'];
      const fit = Math.max(...stages.map(s => (FIT[prep.profile.stage] || FIT.phd_plus)[s] || 0));
      let stageF = 1;
      if (item.kind === 'job') {
        if (fit === 0 && !prep.profile.allStages) return { score: 0, hidden: true, why: 'stage', reasons };
        stageF = .6 + .4 * fit;
        if (fit >= 1) reasons.push({ kind: 'stage', text: T('feed.why.stage') });
      } else if (item.kind === 'grant') {
        stageF = .4 + .6 * fit;
        if (fit >= 1 && !(stages.length === 1 && stages[0] === 'any')) reasons.push({ kind: 'stage', text: T('feed.why.stage') });
      }

      // --- place (vacancies)
      let placeF = 1;
      if (item.kind === 'job') {
        const want = prep.profile.jobCountries;
        const have = item.countries || [];
        if (want.length) {
          if (have.some(c => want.includes(c))) { placeF = 1; reasons.push({ kind: 'place', text: T('feed.why.place') }); }
          else if (item.remote && prep.profile.remote) { placeF = .9; reasons.push({ kind: 'place', text: T('feed.remote') }); }
          else if (!have.length) placeF = .7;
          else return { score: 0, hidden: true, why: 'place', reasons };
        }
      }

      // --- freshness
      const ref = item.posted || item.first_seen;
      const age = ref ? Math.max(0, daysBetween(ref, now)) : 7;
      let fresh;
      if (item.kind === 'article') fresh = Math.max(.25, Math.pow(.5, age / 10));
      else if (item.kind === 'job') fresh = Math.max(.3, Math.pow(.5, age / 21));
      else fresh = item.deadline ? 1 : .8;
      let left = null;
      if (item.deadline) {
        left = Math.ceil((new Date(item.deadline + 'T23:59:59Z').getTime() - now) / DAY);
        if (left < 0) return { score: 0, hidden: true, why: 'expired', reasons };
        if (left <= 14) reasons.push({ kind: 'soon', text: T('feed.why.closing').replace('{n}', left) });
        if (item.kind !== 'article') fresh = Math.max(fresh, .6) * (left <= 3 ? .85 : 1);
      }

      // --- quality
      let q = 1;
      if (item.kind === 'article') {
        q = [.55, .7, .85, 1][Math.min(3, item.tier || 0)];
        if (item.preprint) q = .55;
        if (item.tier >= 3) reasons.push({ kind: 'venue', text: item.venue });
      }

      const score = Math.round(100 * rel * stageF * placeF * (.6 + .4 * fresh) * (.7 + .3 * q));
      return { score: Math.min(100, score), hidden: false, why: null, reasons, left, age };
    },

    /* relevance shared by every kind: fields the item is filed under, and the reader's own phrases */
    _relevance(item, prep) {
      const title = norm(item.title);
      const body = norm((item.summary || '') + ' ' + (item.org || '') + ' ' + (item.department || '') + ' ' + (item.venue || '') + ' ' + (item.authors || []).join(' '));
      const mine = prep.fields.concat(prep.impliedFields);
      let fieldW = 0, hitField = null;
      (item.fields || []).forEach((f, i) => {
        const w = (i === 0 ? 1 : .6) * (prep.fields.includes(f) ? 1 : .8);
        if (mine.includes(f) && w > fieldW) { fieldW = w; hitField = f; }
      });
      let miss = 1; const hits = [];
      for (const { k, rx } of prep.phrases) {
        if (rx.test(title)) { miss *= .3; hits.push(k); } else if (rx.test(body)) { miss *= .65; hits.push(k); }
      }
      const reasons = [];
      if (hitField) reasons.push({ kind: 'field', text: hitField });
      hits.slice(0, 3).forEach(k => reasons.push({ kind: 'keyword', text: k }));
      let rel = 1 - (1 - fieldW * .6) * (1 - (1 - miss));
      if (prep.empty) rel = .3;
      return { rel, reasons };
    },
    _age(item, now, dflt) {
      const ref = item.posted || item.first_seen;
      return ref ? Math.max(0, daysBetween(ref, now)) : dflt;
    },
    _scorePaper(item, prep, now) {
      const { rel, reasons } = this._relevance(item, prep);
      const yearAge = item.year ? Math.max(0, new Date(now).getUTCFullYear() - item.year) : 3;
      const fresh = Math.max(.3, Math.pow(.5, yearAge / 2));
      // papers are never hidden for being off-topic: there are few, and a reader can browse them
      return { score: Math.round(100 * Math.max(rel, .1) * (.6 + .4 * fresh)), hidden: false, why: null, reasons };
    },
    /* A call QIST curated: eligibility is checked, not guessed (QIST.matchOpportunity). A call the reader
       cannot apply to is hidden unless they ask to see it; one that merely sits outside their field is kept,
       because there are few of them and each is checked. */
    _scoreCurated(item, prep, now, ctx) {
      const T = k => QIST.t(k);
      const prof = prep.profile;
      let m = null;
      if (ctx.elig) {
        m = QIST.matchOpportunity(item.opp, { country: prof.country, stage: prof.stage, fields: prep.fields.concat(prep.impliedFields), methods: [] }, ctx.elig);
        if (m.blocked && !ctx.showIneligible) return { score: 0, hidden: true, why: 'eligibility', reasons: [], m };
      }
      const { rel, reasons } = this._relevance(item, prep);
      const relevance = item.allFields ? Math.max(rel, .5) : Math.max(rel, .25);
      if (item.kind === 'job') {                                  // the reader's countries, as for any vacancy
        const want = prof.jobCountries, have = item.countries || [];
        if (want.length && have.length && !have.some(c => want.includes(c)) && !(item.remote && prof.remote)) return { score: 0, hidden: true, why: 'place', reasons, m };
      }
      let left = null, fresh = 1;
      if (item.deadline) {
        left = Math.ceil((new Date(item.deadline + 'T23:59:59Z').getTime() - now) / DAY);
        if (left < 0 && !(ctx.showExpired)) return { score: 0, hidden: true, why: 'expired', reasons, m };
      } else if (item.kind === 'job') fresh = Math.max(.3, Math.pow(.5, this._age(item, now, 14) / 21));
      reasons.push({ kind: 'verified', text: T('opp.verified') });
      const blockedPenalty = m && m.blocked ? .3 : 1;
      const score = Math.min(100, Math.round(100 * relevance * (.6 + .4 * fresh) * blockedPenalty * 1.15));
      return { score, hidden: false, why: null, reasons, left, m };
    },

    /* Rank a whole feed for a profile. Returns [{item, score, reasons, isNew}] best first. */
    rank(items, profile, opts) {
      opts = opts || {};
      const prep = this.prepare(profile), now = opts.now || Date.now();
      const state = this._state();
      const out = [];
      for (const item of items) {
        if (!opts.keepDismissed && state.dismissed[item.id]) continue;
        if (opts.q && !this.textMatch(item, opts.q)) continue;
        const r = this.score(item, prep, now, opts);
        if (r.hidden) continue;
        out.push({ item, score: r.score, reasons: r.reasons, left: r.left, age: r.age, m: r.m,
                   isNew: !!(opts.since ? item.first_seen > opts.since : false) });
      }
      const by = opts.sort || 'match';
      out.sort((a, b) => {
        if (by === 'new') return (b.item.first_seen || '').localeCompare(a.item.first_seen || '') || b.score - a.score;
        if (by === 'soon') return (a.item.deadline || '9999').localeCompare(b.item.deadline || '9999') || b.score - a.score;
        return b.score - a.score || (b.item.posted || '').localeCompare(a.item.posted || '');
      });
      return out;
    },

    /* Free-text search over what a reader sees: every word must appear. */
    textMatch(item, q) {
      const hay = norm([item.title, item.summary, item.org, item.department, item.venue, item.location, (item.authors || []).join(' '), (item.fields || []).join(' ')].join(' '));
      return norm(q).split(' ').filter(Boolean).every(w => hay.includes(w));
    },

    /* Today's picks: the best few among what appeared since the reader last looked
       (or in the last two days), falling back to the best overall. */
    picks(ranked, n, sinceIso) {
      const fresh = ranked.filter(r => r.item.first_seen >= sinceIso);
      return (fresh.length >= Math.min(n, 3) ? fresh : ranked).slice(0, n);
    }
  };

  QIST.feed = Feed;          // QIST is a top-level const in app.js, shared by every classic script
  QIST.FEED_STAGES = STAGES;
})();
