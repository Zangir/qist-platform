/* ============================================================
   The profile form, used to create a profile (join.html) and to edit it (profile.html).

   Two ways in, both optional: type everything, or let ORCID and a CV do the typing. Whatever they
   fill in lands in the same fields, which the member reviews before saving. Fetching never overwrites
   a field the member has already written.

   Needs: QIST (app.js), QIST.kit (kit.js), QIST.feed.loadTaxonomy() (feed.js).
   ============================================================ */
(function () {
  const MAX_FIELDS = 6;

  QIST.profileForm = {
    /* opts: { mode: 'create'|'edit', initial, backend, elig, taxonomy, paperApi, onSubmit(values) -> Promise<{ok, message}> } */
    mount(root, opts) {
      const T = (k, v) => QIST.t(k, v), esc = s => QIST.esc(s);
      const init = opts.initial || {};
      const S = {
        photo: init.photo || '', fields: [...(init.fields || [])], keywords: [...(init.keywords || [])],
        papers: [...(init.papers || [])], orcid: init.orcid || ''
      };
      const creating = opts.mode === 'create';
      const claiming = opts.mode === 'claim';          // an invited member reviewing the profile prepared for them
      const needsAccount = (creating || claiming) && opts.backend;

      root.innerHTML = `
      <form class="pform" id="pf" novalidate autocomplete="off">
        <div class="pf-live sr-only" id="pf-live" role="status" aria-live="polite"></div>

        <section class="pf-sec" aria-labelledby="pf-h-fast">
          <h2 id="pf-h-fast">${T('pf.fast.h')}</h2>
          <p class="hint">${T('pf.fast.p')}</p>
          <div class="pf-fast">
            <div class="pf-box">
              <label for="pf-orcid">${T('pf.orcid')}</label>
              <div class="pf-inline"><input id="pf-orcid" type="text" inputmode="text" placeholder="0000-0002-1825-0097" spellcheck="false">
                <button type="button" class="btn btn-outline btn-sm" id="pf-orcid-go">${T('pf.orcid.fetch')}</button></div>
              <p class="hint">${T('pf.orcid.hint')}</p>
              <p class="pf-msg" id="pf-orcid-msg"></p>
            </div>
            <div class="pf-box">
              <label for="pf-cv-file">${T('pf.cv')}</label>
              <div class="pf-inline">
                ${opts.backend ? `<input id="pf-cv-file" type="file" accept=".pdf,.docx,.txt,application/pdf">` : ''}
                <button type="button" class="btn btn-outline btn-sm" id="pf-cv-toggle" aria-expanded="false">${T('pf.cv.paste')}</button>
              </div>
              <textarea id="pf-cv-text" rows="6" hidden placeholder="${esc(T('pf.cv.ph'))}"></textarea>
              <button type="button" class="btn btn-outline btn-sm" id="pf-cv-go" hidden>${T('pf.cv.read')}</button>
              <p class="hint">${opts.backend ? T('pf.cv.hint') : T('pf.cv.hint.static')}</p>
              <p class="pf-msg" id="pf-cv-msg"></p>
            </div>
          </div>
        </section>

        <section class="pf-sec" aria-labelledby="pf-h-you">
          <h2 id="pf-h-you">${T('pf.you.h')}</h2>
          <div class="pf-photo">
            <div class="pf-avatar" id="pf-avatar" aria-hidden="true"></div>
            <div>
              <label for="pf-photo-file">${T('pf.photo')}</label>
              <div class="pf-inline"><input id="pf-photo-file" type="file" accept="image/jpeg,image/png,image/webp">
                <button type="button" class="btn btn-quiet btn-sm" id="pf-photo-rm" hidden>${T('pf.photo.rm')}</button></div>
              <p class="hint">${T('pf.photo.hint')}</p>
              <p class="pf-msg" id="pf-photo-msg"></p>
            </div>
          </div>
          <div class="row-2">
            <div><label for="pf-name">${T('pf.name')} *</label><input id="pf-name" type="text" required maxlength="120" placeholder="Aigerim Bekova"></div>
            <div><label for="pf-email">${T('common.email')}${creating ? ' *' : ''}</label><input id="pf-email" type="email" ${creating ? 'required' : 'disabled'} placeholder="you@university.edu"></div>
          </div>
          ${needsAccount ? `<div><label for="pf-password">${T('pf.password')} *</label><input id="pf-password" type="password" minlength="8" autocomplete="new-password" placeholder="${esc(T('pf.password.ph'))}"></div>` : ''}
          <div class="row-2">
            <div><label for="pf-title">${T('pf.title')}</label><input id="pf-title" type="text" maxlength="120" placeholder="PhD student"></div>
            <div><label for="pf-inst">${T('pf.inst')}</label><input id="pf-inst" type="text" maxlength="160" placeholder="Nazarbayev University"></div>
          </div>
          <div class="row-2">
            <div><label for="pf-country">${T('common.country')}</label><select id="pf-country"></select></div>
            <div><label for="pf-city">${T('pf.city')}</label><input id="pf-city" type="text" maxlength="80" placeholder="Astana"></div>
          </div>
          <div><label for="pf-bio">${T('pf.bio')}</label><textarea id="pf-bio" rows="3" maxlength="1200" placeholder="${esc(T('pf.bio.ph'))}"></textarea></div>
        </section>

        <section class="pf-sec" aria-labelledby="pf-h-res">
          <h2 id="pf-h-res">${T('pf.res.h')}</h2>
          <div><span class="lab" id="pf-fields-l">${T('pf.fields')}</span><div class="fchips" id="pf-fields" role="group" aria-labelledby="pf-fields-l"></div></div>
          <div><label for="pf-kw">${T('pf.keywords')}</label>
            <div class="kw-box" id="pf-kw-box"><span id="pf-kw-chips"></span><input id="pf-kw" type="text" maxlength="60" placeholder="${esc(T('pf.keywords.ph'))}"></div>
            <p class="hint">${T('pf.keywords.hint')}</p></div>
          <div class="row-3">
            <div><label for="pf-web">${T('pf.web')}</label><input id="pf-web" type="url" placeholder="https://"></div>
            <div><label for="pf-scholar">Google Scholar</label><input id="pf-scholar" type="url" placeholder="https://scholar.google.com/…"></div>
            <div><label for="pf-linkedin">LinkedIn</label><input id="pf-linkedin" type="url" placeholder="https://linkedin.com/in/…"></div>
          </div>
        </section>

        <section class="pf-sec" aria-labelledby="pf-h-pap">
          <h2 id="pf-h-pap">${T('pf.pap.h')}</h2>
          <p class="hint">${T('pf.pap.p')}</p>
          <ul class="pf-papers" id="pf-papers"></ul>
          <div class="pf-inline"><input id="pf-doi" type="text" placeholder="10.1038/… ${esc(T('pf.pap.doi.ph'))}" spellcheck="false">
            <button type="button" class="btn btn-outline btn-sm" id="pf-doi-go">${T('pf.pap.add')}</button>
            <button type="button" class="btn btn-quiet btn-sm" id="pf-man-toggle" aria-expanded="false">${T('pf.pap.manual')}</button></div>
          <p class="pf-msg" id="pf-pap-msg"></p>
          <div class="pf-manual" id="pf-man" hidden>
            <div><label for="pf-m-title">${T('pf.pap.title')} *</label><input id="pf-m-title" type="text" maxlength="300"></div>
            <div class="row-3">
              <div><label for="pf-m-authors">${T('pf.pap.authors')}</label><input id="pf-m-authors" type="text" placeholder="A. Author, B. Author"></div>
              <div><label for="pf-m-venue">${T('pf.pap.venue')}</label><input id="pf-m-venue" type="text" maxlength="160"></div>
              <div><label for="pf-m-year">${T('pf.pap.year')}</label><input id="pf-m-year" type="number" min="1900" max="2100"></div>
            </div>
            <div><label for="pf-m-url">${T('pf.pap.link')} *</label><input id="pf-m-url" type="url" placeholder="https://"></div>
            <div><button type="button" class="btn btn-outline btn-sm" id="pf-m-add">${T('pf.pap.add')}</button></div>
          </div>
        </section>

        <section class="pf-sec">
          <label class="check"><input type="checkbox" id="pf-listed" checked> <span>${T('pf.listed')}</span></label>
          <p class="hint">${T('pf.listed.hint')}</p>
        </section>

        ${opts.terms ? `<section class="pf-sec"><label class="check"><input type="checkbox" id="pf-terms"> <span>${T('pf.terms')} <a href="about.html#data" target="_blank" rel="noopener">${T('pf.terms.link')}</a></span></label></section>` : ''}

        <div class="pf-actions">
          <button type="submit" class="btn btn-primary btn-lg" id="pf-submit">${T(claiming ? 'pf.submit.claim' : creating ? (opts.backend ? 'pf.submit.create' : 'pf.submit.request') : 'pf.submit.save')}</button>
          <button type="button" class="btn btn-quiet" id="pf-clear">${T('common.clear')}</button>
          <span class="state" id="pf-state" role="status" aria-live="polite"></span>
        </div>
      </form>`;

      const $ = id => root.querySelector('#' + id);
      const say = (id, msg, kind) => { const el = $(id); el.textContent = msg || ''; el.className = 'pf-msg' + (kind ? ' ' + kind : ''); };
      const live = msg => { $('pf-live').textContent = msg; };

      /* ---------- values <-> inputs ---------- */
      if (opts.elig) {
        QIST.fillCountrySelect($('pf-country'), opts.elig, init.country || '');
        $('pf-country').insertAdjacentHTML('afterbegin', `<option value="">${esc(T('pf.country.none'))}</option>`);
        $('pf-country').value = init.country || '';
      }
      const set = {
        name: init.name, email: init.email, title: init.title, inst: init.institution, city: init.city, bio: init.bio,
        web: init.website, scholar: init.scholar, linkedin: init.linkedin, orcid: init.orcid
      };
      Object.entries(set).forEach(([k, v]) => { if ($('pf-' + k) && v) $('pf-' + k).value = v; });
      if (init.listed === false) $('pf-listed').checked = false;

      const fillIfEmpty = (id, value) => {
        const el = $(id);
        if (value && !el.value.trim()) { el.value = value; return true; }
        return false;
      };

      function drawAvatar() {
        const name = $('pf-name').value || '?';
        $('pf-avatar').innerHTML = S.photo
          ? `<img src="${esc(S.photo)}" alt="">`
          : `<span style="background:${QIST.avatarColor(name)}">${esc(QIST.initials(name))}</span>`;
        $('pf-photo-rm').hidden = !S.photo;
      }
      function drawFields() {
        const all = (QIST.PRIMARY_FIELDS || []).filter(f => f !== 'Other Research Area');
        $('pf-fields').innerHTML = all.map(f => {
          const on = S.fields.includes(f);
          return `<button type="button" data-f="${esc(f)}" aria-pressed="${on}"${!on && S.fields.length >= MAX_FIELDS ? ' disabled' : ''}>${esc(f)}</button>`;
        }).join('');
      }
      function drawKeywords() {
        $('pf-kw-chips').innerHTML = S.keywords.map((k, i) =>
          `<button type="button" class="kw" data-i="${i}" aria-label="${esc(T('pf.kw.remove', { k }))}">${esc(k)} <i aria-hidden="true">×</i></button>`).join('');
      }
      function drawPapers() {
        $('pf-papers').innerHTML = S.papers.length ? S.papers.map((p, i) => {
          const link = p.url || (p.doi ? 'https://doi.org/' + p.doi : '');
          const safe = QIST.kit.safeUrl(link);
          return `<li><div><b>${safe ? `<a href="${esc(safe)}" target="_blank" rel="noopener">${esc(p.title)}</a>` : esc(p.title)}</b>
            <span class="muted">${esc([(p.authors || []).slice(0, 3).join(', ') + ((p.authors || []).length > 3 ? ' et al.' : ''), p.venue, p.year].filter(Boolean).join(' · '))}</span></div>
            <button type="button" class="btn btn-quiet btn-sm" data-rm="${i}" aria-label="${esc(T('pf.pap.remove', { t: p.title }))}">${T('pf.pap.rm')}</button></li>`;
        }).join('') : `<li class="muted empty">${T('pf.pap.none')}</li>`;
      }
      function addKeyword(raw) {
        raw.split(/[,;\n]/).map(s => s.trim()).filter(Boolean).forEach(k => {
          if (S.keywords.length < 20 && !S.keywords.some(x => x.toLowerCase() === k.toLowerCase())) S.keywords.push(k.slice(0, 60));
        });
        drawKeywords();
      }
      async function addPaper(p) {
        const key = p.doi || p.title.toLowerCase();
        if (S.papers.some(x => (x.doi || x.title.toLowerCase()) === key)) return 'dup';
        if (opts.paperApi) {
          const r = await opts.paperApi.add(p);
          if (!r.ok) return r.message || 'fail';
          p = r.paper || p;
        }
        S.papers.unshift(p);
        return 'ok';
      }

      $('pf-name').addEventListener('input', () => { if (!S.photo) drawAvatar(); });
      drawAvatar(); drawFields(); drawKeywords(); drawPapers();

      /* ---------- chips ---------- */
      $('pf-fields').addEventListener('click', e => {
        const b = e.target.closest('button[data-f]'); if (!b) return;
        const f = b.dataset.f, i = S.fields.indexOf(f);
        if (i > -1) S.fields.splice(i, 1); else if (S.fields.length < MAX_FIELDS) S.fields.push(f);
        drawFields();
        $('pf-fields').querySelector(`[data-f="${CSS.escape(f)}"]`)?.focus();
      });
      $('pf-kw-box').addEventListener('click', e => {
        const b = e.target.closest('button[data-i]');
        if (b) { S.keywords.splice(Number(b.dataset.i), 1); drawKeywords(); $('pf-kw').focus(); }
        else $('pf-kw').focus();
      });
      $('pf-kw').addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); addKeyword($('pf-kw').value); $('pf-kw').value = ''; }
        else if (e.key === 'Backspace' && !$('pf-kw').value && S.keywords.length) { S.keywords.pop(); drawKeywords(); }
      });
      $('pf-kw').addEventListener('blur', () => { if ($('pf-kw').value.trim()) { addKeyword($('pf-kw').value); $('pf-kw').value = ''; } });

      /* ---------- photo ---------- */
      $('pf-photo-file').addEventListener('change', async e => {
        const f = e.target.files[0]; if (!f) return;
        try { S.photo = await QIST.kit.resizePhoto(f); say('pf-photo-msg', T('pf.photo.ok'), 'ok'); drawAvatar(); }
        catch (err) { say('pf-photo-msg', T(err.message === 'PHOTO_SIZE' ? 'pf.photo.big' : 'pf.photo.bad'), 'bad'); }
        e.target.value = '';
      });
      $('pf-photo-rm').addEventListener('click', () => { S.photo = ''; drawAvatar(); say('pf-photo-msg', ''); });

      /* ---------- ORCID ---------- */
      $('pf-orcid-go').addEventListener('click', async () => {
        const id = QIST.kit.normOrcid($('pf-orcid').value);
        if (!id) return say('pf-orcid-msg', T('pf.orcid.bad'), 'bad');
        $('pf-orcid').value = id;
        say('pf-orcid-msg', T('pf.orcid.loading'));
        $('pf-orcid-go').disabled = true;
        try {
          const o = await QIST.kit.fetchOrcid(id);
          const filled = [];
          if (fillIfEmpty('pf-name', o.name)) filled.push(T('pf.name'));
          if (fillIfEmpty('pf-title', o.title)) filled.push(T('pf.title'));
          if (fillIfEmpty('pf-inst', o.institution)) filled.push(T('pf.inst'));
          if (fillIfEmpty('pf-city', o.city)) filled.push(T('pf.city'));
          if (o.country && !$('pf-country').value && [...$('pf-country').options].some(x => x.value === o.country)) { $('pf-country').value = o.country; filled.push(T('common.country')); }
          if (fillIfEmpty('pf-bio', o.bio.slice(0, 1200))) filled.push(T('pf.bio'));
          fillIfEmpty('pf-web', o.website); fillIfEmpty('pf-scholar', o.scholar); fillIfEmpty('pf-linkedin', o.linkedin);
          const before = S.keywords.length;
          o.keywords.forEach(k => addKeyword(k));
          if (S.keywords.length > before) filled.push(T('pf.keywords'));
          let added = 0;
          for (const w of o.works) if (await addPaper(w) === 'ok') added++;
          drawPapers(); drawAvatar();
          say('pf-orcid-msg', T('pf.orcid.ok', { filled: filled.join(', ') || '—', n: added }), 'ok');
          live(T('pf.orcid.ok', { filled: filled.join(', ') || '—', n: added }));
        } catch (err) {
          say('pf-orcid-msg', T({ ORCID_NOTFOUND: 'pf.orcid.nf', ORCID_FORMAT: 'pf.orcid.bad' }[err.message] || 'pf.orcid.net'), 'bad');
        }
        $('pf-orcid-go').disabled = false;
      });

      /* ---------- CV ---------- */
      $('pf-cv-toggle').addEventListener('click', () => {
        const open = $('pf-cv-text').hidden;
        $('pf-cv-text').hidden = !open; $('pf-cv-go').hidden = !open;
        $('pf-cv-toggle').setAttribute('aria-expanded', String(open));
      });
      function applyCv(text) {
        const a = QIST.kit.analyzeCv(text, opts.taxonomy);
        const found = [];
        if (a.orcid && !$('pf-orcid').value) { $('pf-orcid').value = a.orcid; found.push('ORCID'); }
        if (a.name && fillIfEmpty('pf-name', a.name)) found.push(T('pf.name'));
        if (a.emails[0] && creating && fillIfEmpty('pf-email', a.emails[0])) found.push(T('common.email'));
        const kw0 = S.keywords.length; a.keywords.forEach(k => addKeyword(k));
        if (S.keywords.length > kw0) found.push(T('pf.keywords'));
        if (!S.fields.length && a.fields.length) { S.fields = a.fields.slice(0, MAX_FIELDS); drawFields(); found.push(T('pf.fields')); }
        drawAvatar();
        return { a, found };
      }
      $('pf-cv-go').addEventListener('click', async () => {
        const text = $('pf-cv-text').value.trim();
        if (text.length < 40) return say('pf-cv-msg', T('pf.cv.short'), 'bad');
        const { a, found } = applyCv(text);
        let papers = 0;
        for (const d of a.dois.slice(0, 15)) {                       // look the DOIs up so they become real papers
          try { if (await addPaper(Object.assign(await QIST.kit.lookupDoi(d), { doi: d })) === 'ok') papers++; } catch (_) { /* skip */ }
        }
        drawPapers();
        say('pf-cv-msg', T('pf.cv.ok', { found: found.join(', ') || '—', n: papers }), 'ok');
        live(T('pf.cv.ok', { found: found.join(', ') || '—', n: papers }));
      });
      const cvFile = $('pf-cv-file');
      if (cvFile) cvFile.addEventListener('change', async e => {
        const f = e.target.files[0]; if (!f) return;
        say('pf-cv-msg', T('pf.cv.reading'));
        try {
          let text;
          if (/\.txt$/i.test(f.name)) text = await f.text();
          else {
            const fd = new FormData(); fd.append('file', f);
            const r = await fetch(QIST.apiBase + '/api/cv/extract', { method: 'POST', body: fd });
            if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'fail');
            text = (await r.json()).text;
          }
          $('pf-cv-text').value = text.slice(0, 60000);
          $('pf-cv-text').hidden = false; $('pf-cv-go').hidden = false;
          $('pf-cv-toggle').setAttribute('aria-expanded', 'true');
          $('pf-cv-go').click();
        } catch (err) { say('pf-cv-msg', T('pf.cv.fail', { why: err.message === 'fail' ? '' : err.message }), 'bad'); }
        e.target.value = '';
      });

      /* ---------- papers ---------- */
      const paperMsg = r => ({ dup: 'pf.pap.dup' }[r] || null);
      $('pf-doi-go').addEventListener('click', async () => {
        const raw = $('pf-doi').value.trim(); if (!raw) return;
        say('pf-pap-msg', T('pf.pap.loading'));
        try {
          const p = await QIST.kit.lookupDoi(raw);
          const r = await addPaper(p);
          if (r === 'ok') { $('pf-doi').value = ''; say('pf-pap-msg', T('pf.pap.added', { t: p.title }), 'ok'); drawPapers(); }
          else say('pf-pap-msg', paperMsg(r) ? T(paperMsg(r)) : r, 'bad');
        } catch (err) { say('pf-pap-msg', T({ DOI_FORMAT: 'pf.pap.doi.bad', DOI_NOTFOUND: 'pf.pap.doi.nf' }[err.message] || 'pf.pap.net'), 'bad'); }
      });
      $('pf-man-toggle').addEventListener('click', () => {
        const open = $('pf-man').hidden; $('pf-man').hidden = !open; $('pf-man-toggle').setAttribute('aria-expanded', String(open));
      });
      $('pf-m-add').addEventListener('click', async () => {
        const title = $('pf-m-title').value.trim(), url = QIST.kit.safeUrl($('pf-m-url').value);
        if (title.length < 5) return say('pf-pap-msg', T('pf.pap.title.bad'), 'bad');
        if (!url) return say('pf-pap-msg', T('pf.pap.link.bad'), 'bad');
        const p = { title, url, doi: '', venue: $('pf-m-venue').value.trim(), year: Number($('pf-m-year').value) || null,
                    authors: $('pf-m-authors').value.split(',').map(s => s.trim()).filter(Boolean), abstract: '' };
        const r = await addPaper(p);
        if (r === 'ok') { ['title', 'authors', 'venue', 'year', 'url'].forEach(k => { $('pf-m-' + k).value = ''; }); say('pf-pap-msg', T('pf.pap.added', { t: title }), 'ok'); drawPapers(); }
        else say('pf-pap-msg', paperMsg(r) ? T(paperMsg(r)) : r, 'bad');
      });
      $('pf-papers').addEventListener('click', async e => {
        const b = e.target.closest('button[data-rm]'); if (!b) return;
        const i = Number(b.dataset.rm), p = S.papers[i];
        if (opts.paperApi && p.id) { const r = await opts.paperApi.remove(p); if (!r.ok) return say('pf-pap-msg', r.message || 'fail', 'bad'); }
        S.papers.splice(i, 1); drawPapers();
      });

      /* ---------- clear / submit ---------- */
      $('pf-clear').addEventListener('click', () => {
        root.querySelectorAll('input[type=text],input[type=url],input[type=number],input[type=email]:not([disabled]),input[type=password],textarea').forEach(el => { if (!el.disabled) el.value = ''; });
        $('pf-country').value = '';
        Object.assign(S, { photo: '', fields: [], keywords: [] });
        if (creating) S.papers = [];
        ['pf-orcid-msg', 'pf-cv-msg', 'pf-photo-msg', 'pf-pap-msg'].forEach(id => say(id, ''));
        drawAvatar(); drawFields(); drawKeywords(); drawPapers();
        $('pf-state').textContent = '';
      });

      function values() {
        return {
          name: $('pf-name').value.trim(), email: $('pf-email').value.trim(), password: needsAccount ? $('pf-password').value : undefined,
          title: $('pf-title').value.trim(), institution: $('pf-inst').value.trim(), country: $('pf-country').value, city: $('pf-city').value.trim(),
          bio: $('pf-bio').value.trim(), orcid: QIST.kit.normOrcid($('pf-orcid').value) || '', fields: S.fields, keywords: S.keywords,
          website: QIST.kit.safeUrl($('pf-web').value), scholar: QIST.kit.safeUrl($('pf-scholar').value), linkedin: QIST.kit.safeUrl($('pf-linkedin').value),
          photo: S.photo, listed: $('pf-listed').checked, papers: S.papers, acceptTerms: opts.terms ? $('pf-terms').checked : undefined
        };
      }
      function problems(v) {
        const out = [];
        if (v.name.length < 2) out.push(['pf-name', T('pf.err.name')]);
        if (creating && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v.email)) out.push(['pf-email', T('pf.err.email')]);
        if (needsAccount && (v.password || '').length < 8) out.push(['pf-password', T('pf.err.password')]);
        if ($('pf-orcid').value.trim() && !v.orcid) out.push(['pf-orcid', T('pf.orcid.bad')]);
        if (opts.terms && !v.acceptTerms) out.push(['pf-terms', T('pf.terms.err')]);
        [['pf-web', 'website'], ['pf-scholar', 'scholar'], ['pf-linkedin', 'linkedin']].forEach(([id, k]) => {
          if ($(id).value.trim() && !v[k]) out.push([id, T('pf.err.url')]);
        });
        return out;
      }
      $('pf').addEventListener('submit', async e => {
        e.preventDefault();
        const v = values(), bad = problems(v);
        root.querySelectorAll('[aria-invalid]').forEach(el => el.removeAttribute('aria-invalid'));
        if (bad.length) {
          bad.forEach(([id]) => $(id).setAttribute('aria-invalid', 'true'));
          $('pf-state').textContent = bad[0][1]; $(bad[0][0]).focus();
          return;
        }
        const btn = $('pf-submit'), label = btn.textContent;
        btn.disabled = true; btn.textContent = T('common.sending'); $('pf-state').textContent = '';
        let res;
        try { res = await opts.onSubmit(v); } catch (err) { res = { ok: false, message: err.message }; }
        btn.disabled = false; btn.textContent = label;
        $('pf-state').textContent = res.message || '';
        $('pf-state').className = 'state ' + (res.ok ? 'ok' : 'bad');
      });

      return { values, state: S, addPaper, drawPapers };
    }
  };
})();
