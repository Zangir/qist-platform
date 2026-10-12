"""Browser tests for feed.html and the matching engine (assets/js/feed.js).
    backend/.venv/bin/python pipeline/tests/e2e_feed.py http://localhost:8099
Serve the repo root first:  python3 -m http.server 8099
Uses the real data/feeds/*.json for the page tests and synthetic items for the scoring tests."""
import json
import sys
import traceback

from playwright.sync_api import sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8099").rstrip("/")
NOW = "new Date('2026-10-12T12:00:00Z').getTime()"
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("  ok   " if cond else "  FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


def section(t):
    print("\n" + t)


def open_page(browser, path="feed.html", lang=None, width=1440, storage=None):
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    if storage:
        ctx.add_init_script("(() => { try { const s = %s; for (const k in s) if (!localStorage.getItem(k)) localStorage.setItem(k, s[k]); } catch (e) {} })()" % json.dumps(storage))
    page = ctx.new_page()
    errors, warns = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: (errors.append("console.error: " + m.text) if m.type == "error" and "favicon" not in m.text and "fonts.g" not in m.text and "ERR_" not in m.text else None) or (warns.append(m.text) if "[i18n]" in m.text else None))
    page.goto(f"{BASE}/{path}" + (f"?lang={lang}" if lang else ""))
    page.wait_for_function("document.querySelectorAll('#tabs button').length > 0 || document.querySelector('.empty')", timeout=15000)
    return ctx, page, errors, warns


def ev(page, js):
    return page.evaluate(js)


# ---------------------------------------------------------------- scoring (pure functions, synthetic items)
def scoring_tests(browser):
    section("Scoring engine")
    ctx, page, errors, _ = open_page(browser)
    P = """(p) => { const F = QIST.feed; return F.sanitizeProfile(p); }"""
    def job(**kw):
        d = {"id": "j1", "kind": "job", "title": "Postdoctoral Researcher in Hippocampal Memory", "org": "ETH", "summary": "We study place cells.",
             "stages": ["postdoc"], "fields": ["Neuroscience"], "countries": ["CH"], "remote": False, "posted": "2026-10-11",
             "first_seen": "2026-10-11", "deadline": "2026-11-30"}
        d.update(kw); return d
    def score(item, profile):
        return page.evaluate("([i, p]) => { const F = QIST.feed; return F.score(i, F.prepare(p), %s); }" % NOW, [item, profile])

    base = {"stage": "postdoc_plus", "fields": ["Neuroscience"], "keywords": [], "jobCountries": []}
    s = score(job(), base)
    check("matching field + stage scores well", s["score"] >= 40 and not s["hidden"], s)
    check("reasons name the field and the stage", {"field", "stage"} <= {r["kind"] for r in s["reasons"]}, s["reasons"])

    wrong_field = score(job(fields=["Economics"], title="Postdoc in Monetary Economics", summary="inflation"), base)
    check("a different field is hidden, not just ranked low", wrong_field["hidden"] and wrong_field["why"] == "relevance", wrong_field)

    faculty = job(stages=["faculty"], title="Professor of Neuroscience")
    check("faculty job hidden from a PhD student", score(faculty, dict(base, stage="phd_student"))["hidden"])
    check("…unless they ask to include other stages", not score(faculty, dict(base, stage="phd_student", allStages=True))["hidden"])
    check("faculty job fits a professor best", score(faculty, dict(base, stage="pi_only"))["score"] > score(faculty, dict(base, stage="postdoc_plus"))["score"])
    phd_job = job(stages=["phd"], title="PhD position in hippocampal circuits")
    check("PhD position hidden from a professor", score(phd_job, dict(base, stage="pi_only"))["hidden"])
    check("PhD position shown to a PhD student", not score(phd_job, dict(base, stage="phd_student"))["hidden"])

    # keywords
    kw_title = score(job(fields=[], title="Postdoc studying perovskite solar cells", summary="x"), {"stage": "postdoc_plus", "keywords": ["perovskite solar cell"]})
    kw_body = score(job(fields=[], title="Postdoc in energy materials", summary="Work on perovskite solar cells"), {"stage": "postdoc_plus", "keywords": ["perovskite solar cell"]})
    kw_none = score(job(fields=[], title="Postdoc in energy materials", summary="Work on silicon"), {"stage": "postdoc_plus", "keywords": ["perovskite solar cell"]})
    check("keyword in title beats keyword in abstract beats none", kw_title["score"] > kw_body["score"] > 0 and kw_none["hidden"], (kw_title["score"], kw_body["score"], kw_none))
    check("keyword matches plurals", not kw_title["hidden"])
    ai = score(job(fields=[], title="Postdoc", summary="He said we maintain the trail"), {"stage": "postdoc_plus", "keywords": ["ai"]})
    check("short keyword 'ai' does not match 'said'/'maintain'", ai["hidden"], ai)
    ai2 = score(job(fields=[], title="Postdoc in AI for science", summary=""), {"stage": "postdoc_plus", "keywords": ["ai"]})
    check("…but matches the word AI", not ai2["hidden"])
    hy = score(job(fields=[], title="Postdoc on human computer interaction"), {"stage": "postdoc_plus", "keywords": ["human-computer interaction"]})
    check("hyphen and space are equivalent", not hy["hidden"])

    # place
    de = dict(base, jobCountries=["DE"])
    check("job in another country hidden when countries are chosen", score(job(countries=["CH"]), de)["hidden"])
    check("job in a chosen country shown, with reason", "place" in [r["kind"] for r in score(job(countries=["DE"]), de)["reasons"]])
    check("remote role shown if remote allowed", not score(job(countries=["CH"], remote=True), de)["hidden"])
    check("remote role hidden if remote not allowed", score(job(countries=["CH"], remote=True), dict(de, remote=False))["hidden"])
    unk = score(job(countries=[]), de); known = score(job(countries=["DE"]), de)
    check("unknown location is kept but ranked below a known match", not unk["hidden"] and unk["score"] < known["score"], (unk["score"], known["score"]))
    check("no country chosen = anywhere", not score(job(countries=["BR"]), base)["hidden"])

    # time
    check("expired item hidden", score(job(deadline="2026-10-01"), base)["hidden"])
    soon = score(job(deadline="2026-10-15"), base)
    check("closing soon gets a reason", any(r["kind"] == "soon" for r in soon["reasons"]), soon["reasons"])
    check("deadline today is still open", not score(job(deadline="2026-10-12"), base)["hidden"])
    new_ = score(job(posted="2026-10-12", first_seen="2026-10-12"), base); old = score(job(posted="2026-08-01", first_seen="2026-08-01"), base)
    check("fresher vacancy outranks an older identical one", new_["score"] > old["score"], (new_["score"], old["score"]))

    # grants
    g = {"id": "g1", "kind": "grant", "title": "Neuroscience research grant", "org": "UKRI", "summary": "", "stages": ["any"], "fields": ["Neuroscience"], "deadline": None, "posted": "2026-10-10", "first_seen": "2026-10-10"}
    check("open-ended grant with no deadline is shown", not score(g, base)["hidden"])
    gf = dict(g, stages=["faculty"])
    check("grant for the wrong stage is demoted, not hidden", 0 < score(gf, dict(base, stage="phd_student"))["score"] < score(g, dict(base, stage="phd_student"))["score"])

    # articles
    a = {"id": "a1", "kind": "article", "title": "Place cells remap", "summary": "", "fields": ["Neuroscience"], "tier": 3, "preprint": False, "venue": "Nature", "posted": "2026-10-11", "first_seen": "2026-10-11"}
    pre = dict(a, id="a2", tier=0, preprint=True, venue="bioRxiv")
    check("journal article outranks the same preprint", score(a, base)["score"] > score(pre, base)["score"])
    check("flagship journal gets a venue reason", any(r["kind"] == "venue" for r in score(a, base)["reasons"]))
    check("article scoring ignores career stage", score(a, dict(base, stage="phd_student"))["score"] == score(a, dict(base, stage="pi_only"))["score"])

    # empty profile, determinism, sanitising, taxonomy
    e = score(job(fields=["Economics"]), {"stage": "postdoc_plus"})
    check("empty profile shows everything (not hidden)", not e["hidden"])
    check("deterministic: same input, same score", score(job(), base) == score(job(), base))
    san = page.evaluate("""() => QIST.feed.sanitizeProfile({stage:'god', fields:['Neuroscience','Robotics','Engineering','Economics','Physics and Physical Sciences','Electronics','Materials Science','Nonsense'],
        keywords: Array.from({length: 20}, (_, i) => 'k' + i), jobCountries: ['de','ch'], country: 'kaz', remote: undefined})""")
    check("sanitize: bad stage reset, caps applied, unknown field dropped", san["stage"] == "phd_plus" and len(san["fields"]) == 6 and "Nonsense" not in san["fields"] and len(san["keywords"]) == 12 and san["jobCountries"] == ["DE", "CH"] and san["country"] == "KA" and san["remote"] is True, san)
    implied = page.evaluate("() => QIST.feed.fieldsFromText('graph neural networks, soil carbon')")
    check("keywords imply fields", "Artificial Intelligence" in implied, implied)
    check("page had no JS errors", not errors, errors)

    # ranking order across a synthetic list
    ranked = page.evaluate("""([items, p]) => QIST.feed.rank(items, p, {now: %s}).map(r => r.item.id)""" % NOW,
                           [[job(id="far", countries=["DE"], posted="2026-08-01", first_seen="2026-08-01"), job(id="best"), job(id="wrongstage", stages=["phd"]), job(id="gone", deadline="2026-01-01"), job(id="offtopic", fields=["Economics"], title="Postdoc in economics", summary="")], base])
    check("rank: best first, wrong-stage / expired / off-topic removed", ranked[0] == "best" and "wrongstage" not in ranked and "gone" not in ranked and "offtopic" not in ranked, ranked)
    ctx.close()


# ---------------------------------------------------------------- the page, on real data
def page_tests(browser):
    section("feed.html on the published feeds")
    ctx, page, errors, warns = open_page(browser)
    check("nav has My feed, marked current", page.locator("#main-nav a.active").inner_text().strip() == "My feed")
    check("first visit opens the profile form", page.locator("#pf-form").is_visible())
    check("first visit shows the empty-profile banner", page.locator(".feed-notice").count() == 1)
    tabs = page.locator("#tabs button")
    check("four tabs", tabs.count() == 4, tabs.all_inner_texts())
    counts = {t: page.locator(f'#tabs button[data-tab="{t}"] .n').inner_text() for t in ("grant", "job", "article")}
    check("every feed has matches with an empty profile", all(int(c.split()[0]) > 0 for c in counts.values()), counts)
    check("no raw i18n keys on screen", "feed." not in page.inner_text("body") and "nav.feed" not in page.inner_text("body"))
    check("no JS errors", not errors, errors)

    # fill in a profile
    page.select_option("#pf-stage", "postdoc_plus")
    page.click('#pf-fields button[data-f="Neuroscience"]')
    page.click('#pf-fields button[data-f="Biology and Life Sciences"]')
    page.fill("#pf-kw", "hippocampus, memory")
    page.click('#pf-form button[type="submit"]')
    page.wait_for_function("document.querySelector('#pf-form').hidden", timeout=5000)
    saved = json.loads(page.evaluate("localStorage.getItem('qist_feed_profile')"))
    check("profile saved to localStorage", saved["stage"] == "postdoc_plus" and saved["fields"] == ["Neuroscience", "Biology and Life Sciences"] and saved["keywords"] == ["hippocampus", "memory"], saved)
    check("profile summary line shows it", "Neuroscience" in page.inner_text("#pf-line") and "Postdoc" in page.inner_text("#pf-line"))
    check("empty banner gone", page.locator(".feed-notice").count() == 0)

    # articles tab: every top result should be about the reader's topics
    page.click('#tabs button[data-tab="article"]')
    cards = page.locator("#picks-list .feed-item")
    check("today's picks shown for articles", cards.count() >= 3, cards.count())
    top = page.evaluate("""() => QIST.feed.rank(JSON.parse(JSON.stringify(window.__articles || [])), QIST.feed.loadProfile()).length""")
    arts = page.evaluate("""async () => { const d = await (await fetch('data/feeds/articles.json')).json(); const F = QIST.feed; await F.loadTaxonomy();
        return F.rank(d.items, F.loadProfile(), {now: Date.now()}).slice(0, 25).map(r => ({t: r.item.title, f: r.item.fields, s: r.item.summary || '', sc: r.score})); }""")
    on_topic = sum(1 for a in arts if "Neuroscience" in a["f"] or "Biology and Life Sciences" in a["f"] or "hippocamp" in (a["t"] + a["s"]).lower() or "memory" in (a["t"] + a["s"]).lower())
    check("top 25 articles are on the reader's topics", on_topic >= 23, f"{on_topic}/25")
    check("scores are non-increasing down the list", all(arts[i]["sc"] >= arts[i + 1]["sc"] for i in range(len(arts) - 1)))
    first_card = page.locator("#picks-list .feed-item h3 a").first
    check("card links open the source in a new tab", first_card.get_attribute("target") == "_blank" and first_card.get_attribute("href").startswith("http") and "noopener" in first_card.get_attribute("rel"))
    check("a card shows why it matched", page.locator("#picks-list .cond.ok").count() > 0)
    check("no percentages shown (D-07)", "%" not in page.inner_text("#picks-list"))

    # jobs tab: stage + keyword behaviour on real data
    page.click('#tabs button[data-tab="job"]')
    jobs = page.evaluate("""async () => { const d = await (await fetch('data/feeds/jobs.json')).json(); const F = QIST.feed;
        return F.rank(d.items, F.loadProfile(), {now: Date.now()}).map(r => ({stages: r.item.stages, fields: r.item.fields, title: r.item.title, deadline: r.item.deadline})); }""")
    check("postdoc profile: no faculty-only or PhD-only vacancies", all(set(j["stages"]) & {"postdoc", "researcher", "faculty"} for j in jobs) and not any(j["stages"] == ["phd"] for j in jobs), len(jobs))
    check("no expired vacancies listed", all(not j["deadline"] or j["deadline"] >= "2026-10-12" for j in jobs))

    # restrict countries
    page.click("#pf-toggle")
    page.select_option("#pf-jc", "DE")
    page.click('#pf-form button[type="submit"]')
    page.wait_for_function("document.querySelector('#pf-form').hidden", timeout=5000)
    de_jobs = page.evaluate("""async () => { const d = await (await fetch('data/feeds/jobs.json')).json(); const F = QIST.feed;
        return F.rank(d.items, F.loadProfile(), {now: Date.now()}).map(r => ({c: r.item.countries, remote: r.item.remote})); }""")
    check("country filter: every vacancy is in Germany, unknown or remote", all("DE" in j["c"] or not j["c"] or j["remote"] for j in de_jobs), len(de_jobs))
    check("country filter reduced the list", len(de_jobs) < len(jobs), (len(de_jobs), len(jobs)))

    # save / dismiss / saved tab
    page.click('#tabs button[data-tab="article"]')
    title = page.locator("#picks-list .feed-item h3 a").first.inner_text()
    page.locator("#picks-list [data-save]").first.click()
    check("saving marks the button", page.locator("#picks-list [data-save]").first.get_attribute("aria-pressed") == "true")
    page.click('#tabs button[data-tab="saved"]')
    check("saved tab lists it", title in page.inner_text("#list"))
    page.reload(); page.wait_for_selector("#tabs button")
    page.click('#tabs button[data-tab="saved"]')
    check("saved item survives reload", title in page.inner_text("#list"))
    page.click('#tabs button[data-tab="article"]')
    victim = page.locator("#list .feed-item").first
    vt = victim.locator("h3 a").inner_text()
    victim.locator("[data-dismiss]").click()
    check("dismissed item disappears", vt not in page.inner_text("#list") and vt not in page.inner_text("#picks-list"))
    page.reload(); page.wait_for_selector("#tabs button"); page.click('#tabs button[data-tab="article"]')
    check("dismissal survives reload", vt not in page.inner_text("#list"))

    # sort + pagination
    page.select_option("#sort", "new")
    check("sort control works without errors", page.locator("#list .feed-item").count() > 0)
    n0 = page.locator("#list .feed-item").count()
    if page.locator("#more").is_visible():
        page.click("#more-btn")
        check("show more adds items", page.locator("#list .feed-item").count() > n0)
    page.click('#tabs button[data-tab="grant"]')
    check("grants sortable by deadline", "soon" in page.locator("#sort").inner_html())
    check("grants caveat explains eligibility is not checked", "eligib" in page.inner_text("#caveat").lower())
    check("freshness line present", "updated" in page.inner_text("#status").lower())
    check("no JS errors during interaction", not errors, errors)
    ctx.close()

    section("Daily behaviour: 'new since your last visit'")
    prof = json.dumps({"stage": "postdoc_plus", "fields": ["Neuroscience"], "keywords": [], "jobCountries": [], "remote": True, "allStages": False})
    ctx, page, errors, _ = open_page(browser, storage={"qist_feed_profile": prof, "qist_feed_state": json.dumps({"saved": {}, "dismissed": {}, "visit": {"cur": "2000-01-01"}})})
    check("everything counts as new after a long absence", int(page.inner_text("#top-num")) > 0)
    check("headline says 'since your last visit'", "last visit" in page.inner_text("#top-unit"))
    visit = json.loads(page.evaluate("localStorage.getItem('qist_feed_state')"))["visit"]
    check("visit date recorded, previous kept", visit["prev"] == "2000-01-01" and visit["cur"] != "2000-01-01", visit)
    page.reload(); page.wait_for_selector("#tabs button")
    visit2 = json.loads(page.evaluate("localStorage.getItem('qist_feed_state')"))["visit"]
    check("a second visit the same day keeps 'previous'", visit2["prev"] == "2000-01-01", visit2)
    ctx.close()
    prof2 = prof
    ctx, page, errors, _ = open_page(browser, storage={"qist_feed_profile": prof2, "qist_feed_state": json.dumps({"saved": {}, "dismissed": {}, "visit": {"prev": "2000-01-01", "cur": "2999-01-01"}})})
    check("nothing is new when you already visited 'in the future'", int(page.inner_text("#top-num")) == 0, page.inner_text("#top-num"))
    check("picks fall back to best-overall with an honest sentence", "best matches" in page.inner_text("#picks-sub") or page.locator("#picks").is_hidden())
    ctx.close()


def i18n_and_layout(browser):
    section("Languages and layout")
    prof = json.dumps({"stage": "phd_student", "fields": ["Artificial Intelligence"], "keywords": ["transformers"], "jobCountries": [], "remote": True, "allStages": False})
    for lang in ("ru", "kk"):
        ctx, page, errors, warns = open_page(browser, lang=lang, storage={"qist_feed_profile": prof})
        body = page.inner_text("body")
        check(f"{lang}: no raw keys, no missing-key warnings", "feed." not in body and "nav.feed" not in body and not warns, warns[:3])
        check(f"{lang}: heading translated", page.locator("h1").inner_text() != "My feed")
        check(f"{lang}: no JS errors", not errors, errors)
        ctx.close()
    for w in (390, 768):
        ctx, page, errors, _ = open_page(browser, width=w, storage={"qist_feed_profile": prof})
        sw = page.evaluate("document.documentElement.scrollWidth"); cw = page.evaluate("document.documentElement.clientWidth")
        check(f"{w}px: no horizontal scroll", sw <= cw + 1, (sw, cw))
        page.click("#pf-toggle")
        check(f"{w}px: profile form usable", page.locator("#pf-kw").is_visible())
        sw = page.evaluate("document.documentElement.scrollWidth")
        check(f"{w}px: no horizontal scroll with the form open", sw <= cw + 1, (sw, cw))
        ctx.close()
    ctx, page, errors, _ = open_page(browser, storage={"qist_feed_profile": prof})
    page.keyboard.press("Tab")
    check("keyboard: tabs are reachable buttons", page.locator("#tabs button").first.evaluate("e => e.tagName") == "BUTTON")
    ctx.close()


def other_pages(browser):
    section("Other pages still fine")
    for p in ("index.html", "opportunities.html", "directory.html", "about.html", "organizations.html", "map.html"):
        ctx, page, errors, warns = open_page(browser, path=p) if False else (None, None, None, None)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    for p in ("index.html", "opportunities.html", "directory.html", "about.html", "organizations.html", "map.html", "login.html"):
        page = ctx.new_page(); errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto(f"{BASE}/{p}"); page.wait_for_timeout(1200)
        links = page.locator("#main-nav a").all_inner_texts()
        check(f"{p}: loads, nav has My feed", not errs and "My feed" in links, errs or links)
        page.close()
    ctx.close()


with sync_playwright() as pw:
    b = pw.chromium.launch()
    only = sys.argv[2].split(',') if len(sys.argv) > 2 else None
    for fn in (scoring_tests, page_tests, i18n_and_layout, other_pages):
        if only and fn.__name__ not in only:
            continue
        try:
            fn(b)
        except Exception:
            traceback.print_exc()
            check(f"{fn.__name__} completed", False, "exception")
    b.close()

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
