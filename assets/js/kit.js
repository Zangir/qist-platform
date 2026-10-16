/* ============================================================
   Member tools: ORCID, DOI lookup, CV reading, photo, safe links.

   Everything here runs in the browser and calls only public, key-less, CORS-open APIs
   (pub.orcid.org, api.crossref.org). Nothing is sent to QIST until the member presses Save.

   What these tools can and cannot say:
   - An ORCID iD that passes the checksum is well formed. It is NOT proof that the person typing it owns it:
     that needs ORCID's OAuth sign-in, which a static site cannot do. The profile therefore stores it as
     "self-declared" and never shows a "verified" badge.
   - The CV reader is rules, not a model: it lists what is literally in the text (e-mails, ORCID iD, DOIs,
     phrases from data/taxonomy.json) and proposes research fields from them. The member reviews it all.
   ============================================================ */
(function () {
  const ORCID_RE = /^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$/;
  const DOI_RE = /10\.\d{4,9}\/[^\s"<>)\]]+/gi;

  const Kit = {
    /* ---------- links ---------- */
    /* Only http(s) links are ever rendered as links; "javascript:" and friends are dropped. */
    safeUrl(u) {
      u = String(u || '').trim();
      return /^https?:\/\/[^\s]+$/i.test(u) ? u : '';
    },

    /* ---------- ORCID ---------- */
    /* Accepts "0000-0002-1825-0097", "https://orcid.org/0000-0002-1825-0097", or digits without dashes. */
    normOrcid(input) {
      let s = String(input || '').trim().toUpperCase().replace(/^HTTPS?:\/\/(WWW\.)?ORCID\.ORG\//, '').replace(/\/+$/, '');
      if (/^\d{15}[\dX]$/.test(s)) s = s.replace(/(.{4})(?=.)/g, '$1-');
      return this.orcidValid(s) ? s : null;
    },
    /* Format plus the ISO 7064 mod 11-2 check digit. */
    orcidValid(id) {
      if (!ORCID_RE.test(id || '')) return false;
      let total = 0;
      for (const ch of id.replace(/-/g, '').slice(0, -1)) total = (total + Number(ch)) * 2;
      const check = (12 - (total % 11)) % 11;
      return id.slice(-1) === (check === 10 ? 'X' : String(check));
    },

    /* Pure: ORCID public-API record -> what the profile form can use. */
    parseOrcid(rec) {
      const v = o => (o && o.value) || '';
      const person = (rec && rec.person) || {};
      const nm = person.name || {};
      const name = v(nm['credit-name']) || [v(nm['given-names']), v(nm['family-name'])].filter(Boolean).join(' ');

      // current employment first (no end date), else the most recent
      const aff = [];
      (((rec['activities-summary'] || {}).employments || {})['affiliation-group'] || []).forEach(g =>
        (g.summaries || []).forEach(s => s['employment-summary'] && aff.push(s['employment-summary'])));
      const year = d => Number(v(d && d.year)) || 0;
      aff.sort((a, b) => (a['end-date'] ? 1 : 0) - (b['end-date'] ? 1 : 0) || year(b['start-date']) - year(a['start-date']));
      const e = aff[0] || {};
      const org = e.organization || {}, addr = org.address || {};

      let website = '', scholar = '', linkedin = '';
      (((person['researcher-urls'] || {})['researcher-url']) || []).forEach(u => {
        const url = this.safeUrl(v(u.url));
        if (!url) return;
        if (/scholar\.google\./i.test(url)) scholar = scholar || url;
        else if (/linkedin\.com/i.test(url)) linkedin = linkedin || url;
        else website = website || url;
      });

      const works = [];
      const seen = new Set();
      (((rec['activities-summary'] || {}).works || {}).group || []).forEach(g => {
        const w = (g['work-summary'] || [])[0];
        if (!w) return;
        const title = v(((w.title || {}).title));
        const ids = ((g['external-ids'] || {})['external-id']) || [];
        const doiEntry = ids.find(i => (i['external-id-type'] || '').toLowerCase() === 'doi');
        const doi = doiEntry ? String(doiEntry['external-id-value'] || '').replace(/^https?:\/\/(dx\.)?doi\.org\//i, '').toLowerCase() : '';
        const url = this.safeUrl(v(w.url)) || this.safeUrl(doiEntry && doiEntry['external-id-url'] && v(doiEntry['external-id-url']));
        if (!title || !(doi || url)) return;                      // a paper nobody can open is no use to a reader
        const key = doi || title.toLowerCase();
        if (seen.has(key)) return;
        seen.add(key);
        works.push({ title, venue: v(w['journal-title']), year: Number(v(w['publication-date'] && w['publication-date'].year)) || null, doi, url: doi ? '' : url });
      });
      works.sort((a, b) => (b.year || 0) - (a.year || 0));

      return {
        name, title: e['role-title'] || '', institution: org.name || '',
        city: addr.city || '', country: /^[A-Z]{2}$/.test(addr.country || '') ? addr.country : '',
        keywords: (((person.keywords || {}).keyword) || []).map(k => v({ value: k.content })).filter(Boolean),
        bio: v({ value: ((person.biography || {}).content) }), website, scholar, linkedin, works: works.slice(0, 100)
      };
    },

    async fetchOrcid(id) {
      const norm = this.normOrcid(id);
      if (!norm) throw new Error('ORCID_FORMAT');
      let r;
      try {
        r = await fetch(`https://pub.orcid.org/v3.0/${norm}/record`, { headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(15000) });
      } catch (_) { throw new Error('ORCID_NETWORK'); }
      if (r.status === 404) throw new Error('ORCID_NOTFOUND');
      if (!r.ok) throw new Error('ORCID_NETWORK');
      return Object.assign(this.parseOrcid(await r.json()), { orcid: norm });
    },

    /* ---------- DOI ---------- */
    normDoi(s) {
      const d = String(s || '').trim().replace(/^(https?:\/\/(dx\.)?doi\.org\/|doi:\s*)/i, '').replace(/[.,;]+$/, '');
      return /^10\.\d{4,9}\/\S+$/.test(d) ? d.toLowerCase() : null;
    },
    /* Pure: Crossref work -> paper. */
    parseCrossref(j) {
      const m = (j && j.message) || {};
      const strip = x => String(x || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().replace(/^abstract\s*[:.\-]?\s+/i, '');
      const parts = ((m.issued || m.published || {})['date-parts'] || [[]])[0] || [];
      return {
        title: strip((m.title || [])[0]), doi: String(m.DOI || '').toLowerCase(),
        authors: (m.author || []).map(a => [a.given, a.family].filter(Boolean).join(' ') || a.name || '').filter(Boolean).slice(0, 30),
        venue: strip((m['container-title'] || [])[0]), year: parts[0] || null, abstract: strip(m.abstract).slice(0, 1200), url: ''
      };
    },
    async lookupDoi(input) {
      const doi = this.normDoi(input);
      if (!doi) throw new Error('DOI_FORMAT');
      let r;
      try { r = await fetch('https://api.crossref.org/works/' + encodeURIComponent(doi).replace(/%2F/g, '/'), { signal: AbortSignal.timeout(15000) }); }
      catch (_) { throw new Error('DOI_NETWORK'); }
      if (r.status === 404) throw new Error('DOI_NOTFOUND');
      if (!r.ok) throw new Error('DOI_NETWORK');
      const p = this.parseCrossref(await r.json());
      if (!p.title) throw new Error('DOI_NOTFOUND');
      return p;
    },

    /* ---------- CV ---------- */
    /* Reads text the member gave us. Returns only things that are literally in it. */
    analyzeCv(text, taxonomy) {
      text = String(text || '');
      const emails = [...new Set((text.match(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g) || []).map(e => e.toLowerCase()))].slice(0, 5);
      const orcidHit = (text.match(/\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b/g) || []).find(o => this.orcidValid(o)) || null;
      const dois = [...new Set((text.match(DOI_RE) || []).map(d => this.normDoi(d.replace(/[.,;:]+$/, ''))).filter(Boolean))].slice(0, 100);

      // first line that looks like a name: 2-4 words, no digits, no @
      let name = '';
      for (const line of text.split(/\n/).map(l => l.trim()).filter(Boolean).slice(0, 6)) {
        const w = line.split(/\s+/);
        if (w.length >= 2 && w.length <= 4 && !/[\d@:]/.test(line) && w.every(x => /^[\p{Lu}][\p{L}'.\-]+$/u.test(x)) && !/curriculum|vitae|resume|resumé|cv\b/i.test(line)) { name = line; break; }
      }

      // vocabulary hits
      const norm = s => String(s || '').toLowerCase().replace(/[\s\-\u2010-\u2015/_]+/g, ' ');
      // a CV's own headings are not research topics ("curriculum" is a vocabulary term for education research)
      const body = norm(text).replace(/curriculum vitae|\bresume\b|\brésumé\b/g, ' ');
      const hits = [], fieldScore = {};
      for (const [field, terms] of Object.entries((taxonomy && taxonomy.fields) || {})) {
        for (const term of terms) {
          const t = norm(term).trim();
          if (t.length < 4) continue;                              // "ai", "pv", "5g" are too ambiguous to propose from a CV
          const rx = new RegExp('(^|[^a-z0-9])(' + t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\\\*/g, '\\w*').replace(/ /g, '\\s') + ')(?![a-z0-9])', 'g');
          const found = [...body.matchAll(rx)];
          if (!found.length) continue;
          const multi = t.includes(' ');
          hits.push({ term: found[0][2].replace(/\s+/g, ' '), n: found.length, multi });
          fieldScore[field] = (fieldScore[field] || 0) + Math.min(found.length, 3) * (multi ? 2 : 1);
        }
      }
      hits.sort((a, b) => (b.multi - a.multi) || b.n - a.n);
      const keywords = [...new Set(hits.map(h => h.term))].slice(0, 12);
      const ranked = Object.entries(fieldScore).sort((a, b) => b[1] - a[1]);
      const top = ranked.length ? ranked[0][1] : 0;
      const fields = ranked.filter(([, s]) => s >= 4 && s >= 0.4 * top).slice(0, 3).map(x => x[0]);
      return { emails, orcid: orcidHit, dois, name, keywords, fields, chars: text.length };
    },

    /* ---------- photo ---------- */
    /* Centre-crops to a square and re-encodes as JPEG, so a 6 MB phone photo becomes ~15 KB and carries no EXIF. */
    resizePhoto(file, size = 256) {
      return new Promise((resolve, reject) => {
        if (!file || !/^image\/(jpeg|png|webp)$/.test(file.type)) return reject(new Error('PHOTO_TYPE'));
        if (file.size > 12 * 1024 * 1024) return reject(new Error('PHOTO_SIZE'));
        const url = URL.createObjectURL(file), img = new Image();
        img.onload = () => {
          const s = Math.min(img.width, img.height), c = document.createElement('canvas');
          c.width = c.height = size;
          const g = c.getContext('2d');
          g.fillStyle = '#fff'; g.fillRect(0, 0, size, size);
          g.drawImage(img, (img.width - s) / 2, (img.height - s) / 2, s, s, 0, 0, size, size);
          URL.revokeObjectURL(url);
          let q = 0.86, out = c.toDataURL('image/jpeg', q);
          while (out.length > 110000 && q > 0.4) { q -= 0.1; out = c.toDataURL('image/jpeg', q); }
          resolve(out);
        };
        img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('PHOTO_TYPE')); };
        img.src = url;
      });
    }
  };

  QIST.kit = Kit;
})();
