/* ============================================================
   My feed — per-reader matching of the daily grants / jobs / articles feeds.

   The feeds (data/feeds/*.json) are built once a day by pipeline/run.py. Everything in this
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
    KINDS: ['grant', 'job', 'article'],
    FILE: { grant: 'grants', job: 'jobs', article: 'articles' },
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
      return { stage: 'phd_plus', country: '', fields: [], keywords: [], jobCountries: [], remote: true, allStages: false };
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
    async load() {
      await this.loadTaxonomy();
      const [meta, ...sets] = await Promise.all([
        fetch('data/feeds/meta.json').then(r => (r.ok ? r.json() : null)).catch(() => null),
        ...this.KINDS.map(k => fetch(`data/feeds/${this.FILE[k]}.json`).then(r => (r.ok ? r.json() : { items: [] })).catch(() => ({ items: [], failed: true })))
      ]);
      const data = {};
      this.KINDS.forEach((k, i) => { data[k] = sets[i]; });
      return { meta, data };
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
    score(item, prep, now) {
      now = now || Date.now();
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

    /* Rank a whole feed for a profile. Returns [{item, score, reasons, isNew}] best first. */
    rank(items, profile, opts) {
      opts = opts || {};
      const prep = this.prepare(profile), now = opts.now || Date.now();
      const state = this._state();
      const out = [];
      for (const item of items) {
        if (!opts.keepDismissed && state.dismissed[item.id]) continue;
        const r = this.score(item, prep, now);
        if (r.hidden) continue;
        out.push({ item, score: r.score, reasons: r.reasons, left: r.left, age: r.age,
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
