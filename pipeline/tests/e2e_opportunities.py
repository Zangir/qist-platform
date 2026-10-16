"""Browser tests for the merged Opportunities page (opportunities.html) and the matching engine (assets/js/feed.js).
    backend/.venv/bin/python pipeline/tests/e2e_opportunities.py http://localhost:8099 [scoring_tests,page_tests,...]
Serve the repo root first:  python3 -m http.server 8099
The curated calls and the members' papers are replaced by fixtures (far-future deadlines) so the checks do not rot;
the daily feeds (grants, vacancies) are the real data/feeds/*.json."""
import json
import sys
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8099").rstrip("/")
FX = Path(__file__).parent / "fixtures"
OPPS = (FX / "opps_e2e.json").read_text(encoding="utf8")
PAPERS = (FX / "papers_e2e.json").read_text(encoding="utf8")
NOW = "new Date('2026-10-12T12:00:00Z').getTime()"
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("  ok   " if cond else "  FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


def section(t):
    print("\n" + t)


def open_page(browser, path="opportunities.html", query="", width=1440, storage=None, fixtures=True):
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    if storage:
        ctx.add_init_script("(() => { try { const s = %s; for (const k in s) if (!localStorage.getItem(k)) localStorage.setItem(k, s[k]); } catch (e) {} })()" % json.dumps(storage))
    if fixtures:
        ctx.route("**/data/opportunities.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=OPPS))
        ctx.route("**/data/papers.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=PAPERS))
    sent = []
    ctx.route("https://formspree.io/**", lambda r: (sent.append(r.request.post_data), r.fulfill(status=200, content_type="application/json", body='{"ok":true}')))
    page = ctx.new_page()
    errors, warns = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: (errors.append("console.error: " + m.text) if m.type == "error" and not any(x in m.text for x in ("favicon", "fonts.g", "ERR_")) else None) or (warns.append(m.text) if "[i18n]" in m.text else None))
    page.goto(f"{BASE}/{path}{query}")
    page.wait_for_function("document.querySelectorAll('#tabs button').length > 0 || document.querySelector('.empty')", timeout=15000)
    page.sent = sent
    return ctx, page, errors, warns


PROFILE = {"stage": "phd_student", "country": "KZ", "fields": ["Neuroscience"], "keywords": [], "jobCountries": [], "remote": True, "allStages": False}
PROF_STORE = {"qist_feed_profile": json.dumps(PROFILE)}


# ---------------------------------------------------------------- scoring (pure functions, synthetic items)
def scoring_tests(browser):
    section("Scoring engine")
    ctx, page, errors, _ = open_page(browser)

    def job(**kw):
        d = {"id": "j1", "kind": "job", "title": "Postdoctoral Researcher in Hippocampal Memory", "org": "ETH", "summary": "We study place cells.",
             "stages": ["postdoc"], "fields": ["Neuroscience"], "countries": ["CH"], "remote": False, "posted": "2026-10-11",
             "first_seen": "2026-10-11", "deadline": "2099-11-30"}
        d.update(kw); return d

    def score(item, profile, ctx_=None):
        return page.evaluate("([i, p, c]) => { const F = QIST.feed; return F.score(i, F.prepare(p), %s, c); }" % NOW, [item, profile, ctx_ or {}])

    base = {"stage": "postdoc_plus", "fields": ["Neuroscience"], "keywords": [], "jobCountries": []}
    s = score(job(), base)
    check("matching field + stage scores well", s["score"] >= 40 and not s["hidden"], s)
    check("reasons name the field and the stage", {"field", "stage"} <= {r["kind"] for r in s["reasons"]}, s["reasons"])
    check("a different field is hidden, not just ranked low", score(job(fields=["Economics"], title="Postdoc in Monetary Economics", summary="inflation"), base)["why"] == "relevance")
    faculty = job(stages=["faculty"], title="Professor of Neuroscience")
    check("faculty job hidden from a PhD student", score(faculty, dict(base, stage="phd_student"))["hidden"])
    check("…unless they ask to include other stages", not score(faculty, dict(base, stage="phd_student", allStages=True))["hidden"])
    check("faculty job fits a professor best", score(faculty, dict(base, stage="pi_only"))["score"] > score(faculty, dict(base, stage="postdoc_plus"))["score"])
    check("PhD position hidden from a professor", score(job(stages=["phd"]), dict(base, stage="pi_only"))["hidden"])
    check("PhD position shown to a PhD student", not score(job(stages=["phd"]), dict(base, stage="phd_student"))["hidden"])

    kw_title = score(job(fields=[], title="Postdoc studying perovskite solar cells", summary="x"), {"stage": "postdoc_plus", "keywords": ["perovskite solar cell"]})
    kw_body = score(job(fields=[], title="Postdoc in energy materials", summary="Work on perovskite solar cells"), {"stage": "postdoc_plus", "keywords": ["perovskite solar cell"]})
    kw_none = score(job(fields=[], title="Postdoc in energy materials", summary="Work on silicon"), {"stage": "postdoc_plus", "keywords": ["perovskite solar cell"]})
    check("keyword in title beats keyword in abstract beats none", kw_title["score"] > kw_body["score"] > 0 and kw_none["hidden"], (kw_title["score"], kw_body["score"]))
    check("short keyword 'ai' does not match 'said'/'maintain'", score(job(fields=[], title="Postdoc", summary="He said we maintain the trail"), {"stage": "postdoc_plus", "keywords": ["ai"]})["hidden"])
    check("…but matches the word AI", not score(job(fields=[], title="Postdoc in AI for science", summary=""), {"stage": "postdoc_plus", "keywords": ["ai"]})["hidden"])
    check("hyphen and space are equivalent", not score(job(fields=[], title="Postdoc on human computer interaction"), {"stage": "postdoc_plus", "keywords": ["human-computer interaction"]})["hidden"])

    de = dict(base, jobCountries=["DE"])
    check("job in another country hidden when countries are chosen", score(job(countries=["CH"]), de)["hidden"])
    check("job in a chosen country shown, with reason", "place" in [r["kind"] for r in score(job(countries=["DE"]), de)["reasons"]])
    check("remote role shown if remote allowed, hidden if not", not score(job(countries=["CH"], remote=True), de)["hidden"] and score(job(countries=["CH"], remote=True), dict(de, remote=False))["hidden"])
    unk, known = score(job(countries=[]), de), score(job(countries=["DE"]), de)
    check("unknown location kept but below a known match", not unk["hidden"] and unk["score"] < known["score"])
    check("expired item hidden", score(job(deadline="2026-10-01"), base)["hidden"])
    check("deadline today is still open", not score(job(deadline="2026-10-12"), base)["hidden"])
    check("fresher vacancy outranks an older identical one", score(job(posted="2026-10-12"), base)["score"] > score(job(posted="2026-08-01"), base)["score"])

    g = {"id": "g1", "kind": "grant", "title": "Neuroscience research grant", "org": "UKRI", "summary": "", "stages": ["any"], "fields": ["Neuroscience"], "deadline": None, "posted": "2026-10-10", "first_seen": "2026-10-10"}
    check("open-ended grant with no deadline is shown", not score(g, base)["hidden"])
    check("grant for the wrong stage is demoted, not hidden", 0 < score(dict(g, stages=["faculty"]), dict(base, stage="phd_student"))["score"] < score(g, dict(base, stage="phd_student"))["score"])

    # ---- curated calls: eligibility is checked, not guessed
    elig = page.evaluate("() => QIST.getEligibility()")
    opps = json.loads(OPPS)
    items = {o["id"]: page.evaluate("(o) => QIST.feed.fromOpp(o)", o) for o in opps}
    kz = {"stage": "phd_student", "country": "KZ", "fields": ["Neuroscience"], "keywords": [], "jobCountries": []}
    cx = {"elig": elig}
    check("fromOpp maps types to tabs", [items[i]["kind"] for i in ("t-open", "t-co", "m-1")] == ["grant", "collab", "job"], [items[i]["kind"] for i in items])
    check("a call open to everyone passes", not score(items["t-open"], kz, cx)["hidden"] and score(items["t-open"], kz, cx)["m"]["blocked"] is False)
    nokz = score(items["t-nokz"], kz, cx)
    check("a call that excludes the reader's country is hidden", nokz["hidden"] and nokz["why"] == "eligibility", nokz.get("why"))
    shown = score(items["t-nokz"], kz, dict(cx, showIneligible=True))
    check("…and shown, demoted, when the reader asks to see it", not shown["hidden"] and shown["m"]["blocked"] and shown["score"] < score(items["t-open"], kz, cx)["score"])
    why = [c for c in shown["m"]["criteria"] if c["key"] == "country"][0]
    check("the country verdict names the funder's own list as its source", why["source"] and why["source"]["url"] == "https://example.org/rules" and not why["ok"], why)
    check("the verdict sentence is in plain words", "country" in shown["m"]["verdict"].lower(), shown["m"]["verdict"])
    check("PI-only call is hidden from a PhD student, shown to a professor", score(items["t-pi"], kz, cx)["hidden"] and not score(items["t-pi"], dict(kz, stage="pi_only"), cx)["hidden"])
    check("a call for all fields is not hidden by the reader's field", not score(items["t-pi"], dict(kz, stage="pi_only", fields=["Economics"]), cx)["hidden"])
    check("curated calls outside the reader's field are kept (few, and checked)", not score(dict(items["t-open"], fields=["Economics"]), kz, cx)["hidden"])
    check("curated calls carry the 'checked' reason", any(r["kind"] == "verified" for r in score(items["t-open"], kz, cx)["reasons"]))
    check("a member's post follows the vacancy country filter", score(items["m-1"], dict(kz, jobCountries=["FR"]), cx)["hidden"] and not score(items["m-1"], dict(kz, jobCountries=["DE"]), cx)["hidden"])
    check("expired curated call is hidden", score(dict(items["t-open"], deadline="2020-01-01", opp=dict(items["t-open"]["opp"], deadline="2020-01-01")), kz, dict(cx, showIneligible=True))["hidden"])

    # ---- papers
    paper = {"id": "p1", "kind": "paper", "title": "Place cells remap", "summary": "", "fields": ["Neuroscience"], "year": 2025, "authors": ["A. Member"]}
    on, off = score(paper, base), score(dict(paper, id="p2", fields=["Economics"], title="Monetary policy"), base)
    check("papers are never hidden, but on-topic ones rank first", not off["hidden"] and on["score"] > off["score"], (on["score"], off["score"]))
    check("a newer paper outranks an older one", score(dict(paper, year=2026), base)["score"] > score(dict(paper, year=2010), base)["score"])
    check("an empty profile shows everything", not score(job(fields=["Economics"]), {"stage": "postdoc_plus"})["hidden"])
    check("deterministic: same input, same score", score(job(), base) == score(job(), base))

    san = page.evaluate("""() => QIST.feed.sanitizeProfile({stage:'god', fields:['Neuroscience','Robotics','Engineering','Economics','Physics and Physical Sciences','Electronics','Materials Science','Nonsense'],
        keywords: Array.from({length: 20}, (_, i) => 'k' + i), jobCountries: ['de','ch'], country: 'kaz', remote: undefined})""")
    check("sanitize: bad stage reset, caps applied, unknown field dropped", san["stage"] == "phd_plus" and len(san["fields"]) == 6 and "Nonsense" not in san["fields"] and len(san["keywords"]) == 12 and san["jobCountries"] == ["DE", "CH"], san)
    check("default country is Kazakhstan (the region this serves)", page.evaluate("() => QIST.feed.defaultProfile().country") == "KZ")
    ranked = page.evaluate("""([items, p]) => QIST.feed.rank(items, p, {now: %s}).map(r => r.item.id)""" % NOW,
                           [[job(id="far", countries=["DE"], posted="2026-08-01", first_seen="2026-08-01"), job(id="best"), job(id="wrongstage", stages=["phd"]), job(id="gone", deadline="2026-01-01"), job(id="offtopic", fields=["Economics"], title="Postdoc in economics", summary="")], base])
    check("rank: best first; wrong-stage, expired and off-topic removed", ranked[0] == "best" and not {"wrongstage", "gone", "offtopic"} & set(ranked), ranked)
    check("textMatch needs every word", page.evaluate("() => { const F = QIST.feed; const it = {title: 'Postdoc in hippocampal circuits', summary: 'mice'}; return [F.textMatch(it, 'hippocampal mice'), F.textMatch(it, 'hippocampal rats')]; }") == [True, False])
    check("page had no JS errors", not errors, errors)
    ctx.close()


# ---------------------------------------------------------------- the page
def page_tests(browser):
    section("opportunities.html")
    ctx, page, errors, warns = open_page(browser)
    check("nav marks Opportunities current and has no separate My feed", page.locator("#main-nav a.active").inner_text().strip() == "Opportunities" and "My feed" not in page.locator("#main-nav").inner_text())
    check("first visit opens the profile form", page.locator("#pf-form").is_visible())
    tabs = page.locator("#tabs button")
    check("five tabs: Grants, Vacancies, Collaborations, Papers, Saved", tabs.all_inner_texts() and [t.split()[0] for t in tabs.all_inner_texts()] == ["Grants", "Vacancies", "Collaborations", "Papers", "Saved"], tabs.all_inner_texts())
    check("no Articles tab any more", "Articles" not in page.inner_text("#tabs"))
    check("no raw i18n keys on screen", not any(k in page.inner_text("body") for k in ("opp2.", "feed.", "pf.", "nav.opp")))
    check("no JS errors", not errors, errors)

    # a Kazakh PhD candidate in Neuroscience
    page.select_option("#pf-stage", "phd_student")
    page.click('#pf-fields button[data-f="Neuroscience"]')
    page.fill("#pf-kw", "hippocampus")
    page.click('#pf-form button[type="submit"]')
    page.wait_for_function("document.querySelector('#pf-form').hidden", timeout=5000)
    saved = json.loads(page.evaluate("localStorage.getItem('qist_feed_profile')"))
    check("profile saved", saved["stage"] == "phd_student" and saved["fields"] == ["Neuroscience"] and saved["keywords"] == ["hippocampus"] and saved["country"] == "KZ", saved)

    page.click('#tabs button[data-tab="grant"]')
    text = page.inner_text("#picks-list") + page.inner_text("#list")
    check("grant open to everyone is listed", "Open neuroscience grant" in text)
    check("grant excluding Kazakhstan is hidden by default", "Grant not open to Kazakhstan" not in text)
    check("PI-only grant is hidden from a PhD candidate", "PI-only synergy grant" not in text)
    card = page.locator('[data-id="t-open"]')
    check("curated call shows condition chips for the reader's country and stage", card.locator(".cond").count() >= 2 and "Kazakhstan" in card.inner_text(), card.inner_text()[:200])
    check("…and says it is checked by QIST", "Checked by QIST" in card.inner_text())
    check("unchecked feed grants say eligibility is not checked", page.locator(".opp-unchecked").count() > 0 and "not checked" in page.locator(".opp-unchecked").first.inner_text().lower())

    # the explanation
    card.locator(".opp-toggle").click()
    panel = card.locator(".opp-panel")
    check("'Details' opens the eligibility explanation", panel.is_visible() and panel.locator("table.checks tr").count() >= 2, panel.inner_text()[:200])
    check("…with a verdict sentence and the caveat that this is not a chance of winning", len(panel.locator(".opp-panel-verdict").inner_text()) > 10 and "chance" in panel.inner_text().lower(), panel.inner_text()[-200:])

    page.check("#inelig")
    text = page.inner_text("#picks-list") + page.inner_text("#list")
    check("'also show calls I cannot apply to' reveals the blocked ones", "Grant not open to Kazakhstan" in text and "PI-only synergy grant" in text)
    bad = page.locator('[data-id="t-nokz"]')
    check("the blocked call shows its reason in red", bad.locator(".cond.bad").count() >= 1 and bad.locator(".opp-blocker").count() == 1, bad.inner_text()[:300])
    bad.locator(".opp-toggle").click()
    src = bad.locator(".opp-panel a.src")
    check("…and the funder's own list as a source link", src.count() == 1 and src.get_attribute("href") == "https://example.org/rules" and "_blank" == src.get_attribute("target"))
    page.uncheck("#inelig")

    # search + clear
    page.fill("#q", "perovskite zzzz")
    page.wait_for_timeout(400)
    check("search with no match shows the empty state", page.locator(".empty").count() == 1)
    page.click("#clear")
    check("Clear empties the search and restores the list", page.input_value("#q") == "" and "Open neuroscience grant" in page.inner_text("#picks-list") + page.inner_text("#list"))
    page.fill("#q", "test foundation")
    page.wait_for_timeout(400)
    check("search narrows the list to the matching item (and hides today's picks)", page.locator("#list .opp").count() == 1 and "Open neuroscience grant" in page.inner_text("#list") and page.locator("#picks").is_hidden(), page.locator("#list .opp").count())
    page.click("#clear")
    page.keyboard.press("Escape")

    # vacancies: feeds + curated + member posts, all matched and explained
    page.click('#tabs button[data-tab="job"]')
    jobs_text = page.inner_text("#picks-list") + page.inner_text("#list")
    check("a member's position appears among vacancies", "PhD position from a member lab" in jobs_text)
    mem = page.locator('[data-id="m-1"]')
    check("…marked as posted by a member, with a link out", "Posted by a member" in mem.inner_text() and mem.locator("a[target=_blank]").first.get_attribute("href") == "https://example.org/member-phd")
    check("…and checked against the reader's stage like any call", mem.locator(".cond").count() >= 2)
    check("a 'Post a position' button is on the Vacancies tab", page.locator("#tab-actions a[href='post-position.html']").count() == 1)
    jobs = page.evaluate("""async () => { const {data} = await QIST.feed.load(); const F = QIST.feed; const elig = await QIST.getEligibility();
        return F.rank(data.job, F.loadProfile(), {now: Date.now(), elig}).map(r => ({feed: !r.item.curated, stages: r.item.stages})); }""")
    check("PhD-candidate profile: feed vacancies are PhD-level or general, never faculty-only", all(not j["feed"] or "faculty" not in j["stages"] or len(j["stages"]) > 1 for j in jobs) and any(j["feed"] for j in jobs), len(jobs))

    # collaborations
    page.click('#tabs button[data-tab="collab"]')
    check("collaborations tab lists the co-author call", "Co-author wanted for brain imaging review" in page.inner_text("#picks-list") + page.inner_text("#list") + page.inner_text("#tab-actions"))

    # papers
    page.click('#tabs button[data-tab="paper"]')
    check("papers tab lists members' papers", "Place cells remap when goals change" in page.inner_text("#list"))
    first = page.locator("#list .opp").first
    check("on-topic paper first (reader works on neuroscience)", "Place cells" in first.inner_text(), first.inner_text()[:80])
    check("paper shows authors, venue, year, DOI and who added it", all(x in first.inner_text() for x in ("A. Member", "Neuron", "2025", "10.1000/place", "Ada Member")), first.inner_text())
    check("authors are shortened with 'et al.'", "et al." in first.inner_text())
    check("paper title links to the paper in a new tab", first.locator("h3 a").get_attribute("href") == "https://doi.org/10.1000/place" and first.locator("h3 a").get_attribute("target") == "_blank")
    check("an 'Add your paper' action points to join or profile", page.locator("#tab-actions a").first.get_attribute("href") in ("join.html", "profile.html#papers"))
    check("no percentages anywhere (D-07)", "%" not in page.inner_text("#list"))

    # save / dismiss
    page.click('#tabs button[data-tab="grant"]')
    title = page.locator("#picks-list h3 a, #list h3 a").first.inner_text()
    page.locator("[data-save]").first.click()
    page.click('#tabs button[data-tab="saved"]')
    check("saved tab lists it", title in page.inner_text("#list"))
    page.reload(); page.wait_for_selector("#tabs button"); page.click('#tabs button[data-tab="saved"]')
    check("saved item survives reload", title in page.inner_text("#list"))
    page.click('#tabs button[data-tab="grant"]')
    victim = page.locator("#list .opp").first; vt = victim.locator("h3 a").inner_text()
    victim.locator("[data-dismiss]").click()
    check("dismissed item disappears and stays gone", vt not in page.inner_text("#list") + page.inner_text("#picks-list"))
    page.reload(); page.wait_for_selector("#tabs button")
    check("…after reload too", vt not in page.inner_text("#list") + page.inner_text("#picks-list"))
    check("no JS errors during interaction", not errors, errors)

    # interested button posts to the configured endpoint
    page.click('#tabs button[data-tab="grant"]')
    n0 = len(page.sent)
    page.locator('[data-id="t-open"] [data-interest]').click()
    page.wait_for_timeout(500)
    check("'I'm interested' sends the response", len(page.sent) == n0 + 1 and "t-open" in page.sent[-1], page.sent[-1:] )
    ctx.close()

    section("Profile form: clear, URL params, deep links")
    ctx, page, errors, _ = open_page(browser, storage=PROF_STORE)
    page.click("#pf-toggle")
    page.click('#pf-form button[type="button"]#pf-reset')
    check("'Clear profile' empties fields and keywords in the form", page.input_value("#pf-kw") == "" and page.locator('#pf-fields button[aria-pressed="true"]').count() == 0)
    page.click("#pf-cancel")
    check("clearing is not saved until Save", json.loads(page.evaluate("localStorage.getItem('qist_feed_profile')"))["fields"] == ["Neuroscience"])
    page.click("#pf-toggle"); page.click("#pf-reset"); page.click('#pf-form button[type="submit"]')
    page.wait_for_function("document.querySelector('#pf-form').hidden")
    check("saving a cleared profile gives the empty-profile banner", page.locator(".feed-notice").count() == 1)
    ctx.close()

    ctx, page, errors, _ = open_page(browser, query="?country=DE&stage=pi_only&tab=grant", storage=PROF_STORE)
    check("home-page links can carry a country and a stage for this view", "Germany" in page.inner_text("#pf-line") and "Professor" in page.inner_text("#pf-line"), page.inner_text("#pf-line"))
    check("…without overwriting the saved profile", json.loads(page.evaluate("localStorage.getItem('qist_feed_profile')"))["country"] == "KZ")
    check("…and the checks use them (PI-only call is open to a professor)", page.locator('[data-id="t-pi"]').count() == 1)
    ctx.close()

    ctx, page, errors, _ = open_page(browser, query="#opp-t-nokz", storage=PROF_STORE)
    page.wait_for_timeout(600)
    check("a deep link to a blocked call still lands on it", page.locator('[data-id="t-nokz"]').count() == 1 and page.locator('[data-id="t-nokz"] .opp-panel').is_visible())
    check("…opening its explanation", page.locator("#inelig").is_checked())
    ctx.close()
    ctx, page, errors, _ = open_page(browser, query="#opp-m-1", storage=PROF_STORE)
    page.wait_for_timeout(500)
    check("a deep link to a vacancy opens the Vacancies tab", page.locator('#tabs button[data-tab="job"][aria-selected="true"]').count() == 1 and page.locator('[data-id="m-1"]').count() == 1)
    ctx.close()

    section("Daily behaviour")
    prof = json.dumps({"stage": "phd_plus", "country": "KZ", "fields": ["Neuroscience"], "keywords": [], "jobCountries": [], "remote": True, "allStages": False})
    ctx, page, errors, _ = open_page(browser, storage={"qist_feed_profile": prof, "qist_feed_state": json.dumps({"saved": {}, "dismissed": {}, "visit": {"cur": "2000-01-01"}})})
    check("after a long absence the headline counts new matches", "last visit" in page.inner_text("#top-unit"))
    v = json.loads(page.evaluate("localStorage.getItem('qist_feed_state')"))["visit"]
    check("visit date recorded, previous kept", v["prev"] == "2000-01-01" and v["cur"] != "2000-01-01", v)
    page.reload(); page.wait_for_selector("#tabs button")
    check("a second visit the same day keeps 'previous'", json.loads(page.evaluate("localStorage.getItem('qist_feed_state')"))["visit"]["prev"] == "2000-01-01")
    ctx.close()


def i18n_and_layout(browser):
    section("Languages and layout")
    prof = json.dumps({"stage": "phd_student", "country": "KZ", "fields": ["Neuroscience"], "keywords": ["hippocampus"], "jobCountries": [], "remote": True, "allStages": False})
    for lang in ("ru", "kk"):
        ctx, page, errors, warns = open_page(browser, query=f"?lang={lang}&tab=grant", storage={"qist_feed_profile": prof})
        page.check("#inelig")
        page.locator('[data-id="t-open"] .opp-toggle').click()
        body = page.inner_text("body")
        check(f"{lang}: no raw keys and no missing-key warnings", not any(k in body for k in ("opp2.", "feed.", "pf.", "nav.opp", "match.", "elig.")) and not warns, warns[:3])
        check(f"{lang}: heading and eligibility panel translated", page.locator("h1").inner_text() != "Opportunities" and "Checked by QIST" not in body)
        check(f"{lang}: no JS errors", not errors, errors)
        ctx.close()
    for w in (390, 768):
        ctx, page, errors, _ = open_page(browser, width=w, storage={"qist_feed_profile": prof})
        cw = page.evaluate("document.documentElement.clientWidth")
        check(f"{w}px: no horizontal scroll", page.evaluate("document.documentElement.scrollWidth") <= cw + 1)
        page.click("#pf-toggle")
        check(f"{w}px: profile form usable, no horizontal scroll", page.locator("#pf-kw").is_visible() and page.evaluate("document.documentElement.scrollWidth") <= cw + 1)
        page.click("#pf-cancel")
        page.check("#inelig"); page.locator('[data-id="t-nokz"] .opp-toggle').click()
        check(f"{w}px: eligibility table fits", page.evaluate("document.documentElement.scrollWidth") <= cw + 1)
        ctx.close()
    ctx, page, errors, _ = open_page(browser, storage={"qist_feed_profile": prof})
    check("keyboard: tabs are buttons", page.locator("#tabs button").first.evaluate("e => e.tagName") == "BUTTON")
    check("details toggle exposes aria-expanded/controls", page.locator(".opp-toggle").first.get_attribute("aria-expanded") == "false" and page.locator(".opp-toggle").first.get_attribute("aria-controls"))
    ctx.close()


def redirect_and_nav(browser):
    section("Old links and navigation")
    ctx = browser.new_context(); page = ctx.new_page()
    page.goto(f"{BASE}/feed.html?tab=job"); page.wait_for_url("**/opportunities.html**", timeout=8000)
    check("feed.html redirects to opportunities.html, keeping the query", "tab=job" in page.url)
    for p in ("index.html", "directory.html", "about.html", "organizations.html", "map.html", "join.html", "login.html", "post-position.html"):
        pg = ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(f"{BASE}/{p}"); pg.wait_for_timeout(1200)
        links = pg.locator("#main-nav a").all_inner_texts()
        check(f"{p}: loads without errors; nav is Home / Opportunities / Researchers / For organizations / About", not errs and links[:5] == ["Home", "Opportunities", "Researchers", "For organizations", "About QIST"], errs or links)
        pg.close()
    pg = ctx.new_page(); pg.goto(f"{BASE}/index.html"); pg.wait_for_timeout(800)
    check("'Create profile' goes to join.html", pg.locator(".nav-auth a.btn-gold").get_attribute("href") == "join.html")
    ctx.close()


with sync_playwright() as pw:
    b = pw.chromium.launch()
    only = sys.argv[2].split(",") if len(sys.argv) > 2 else None
    for fn in (scoring_tests, page_tests, i18n_and_layout, redirect_and_nav):
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
