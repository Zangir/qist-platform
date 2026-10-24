"""Browser tests for the home page, the profile builder (join.html, no backend) and the member tools in assets/js/kit.js.
    backend/.venv/bin/python pipeline/tests/e2e_members.py http://localhost:8099
ORCID and Crossref are answered from captured real responses (fixtures/orcid_record.json, crossref_doi.json), so the
checks are deterministic; the live services are exercised separately (see README)."""
import json
import sys
import traceback
from pathlib import Path

import cv2
import numpy as np
from playwright.sync_api import sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8099").rstrip("/")
FX = Path(__file__).parent / "fixtures"
ORCID = (FX / "orcid_record.json").read_text(encoding="utf8")
CROSSREF = (FX / "crossref_doi.json").read_text(encoding="utf8")
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("  ok   " if cond else "  FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


def section(t):
    print("\n" + t)


def png_bytes(w=900, h=600):
    img = np.zeros((h, w, 3), np.uint8)
    img[:, :, 0] = np.linspace(0, 255, w, dtype=np.uint8)[None, :]
    img[:, :, 2] = np.linspace(255, 0, h, dtype=np.uint8)[:, None]
    cv2.putText(img, "QIST", (200, 330), cv2.FONT_HERSHEY_SIMPLEX, 6, (255, 255, 255), 12)
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes()


def open_page(browser, path, query="", width=1440, mocks=True, storage=None):
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    ctx.add_init_script("try { localStorage.setItem('qist_api_url', 'off'); } catch (e) {}")      # these suites test the static (no backend) behaviour
    if storage:
        ctx.add_init_script("(() => { try { const s = %s; for (const k in s) if (!localStorage.getItem(k)) localStorage.setItem(k, s[k]); } catch (e) {} })()" % json.dumps(storage))
    sent = []
    ctx.route("https://formspree.io/**", lambda r: (sent.append(json.loads(r.request.post_data or "{}")), r.fulfill(status=200, content_type="application/json", body='{"ok":true}')))
    if mocks:
        ctx.route("https://pub.orcid.org/**", lambda r: r.fulfill(status=200, content_type="application/json", body=ORCID) if "0000-0002-1825-0097" in r.request.url
                  else r.fulfill(status=404, content_type="application/json", body="{}"))
        ctx.route("https://api.crossref.org/works/**", lambda r: r.fulfill(status=200, content_type="application/json", body=CROSSREF) if "10.1038" in r.request.url
                  else r.fulfill(status=404, content_type="text/plain", body="Resource not found."))
    page = ctx.new_page()
    errors, warns = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: (errors.append("console.error: " + m.text) if m.type == "error" and not any(x in m.text for x in ("favicon", "fonts.g", "ERR_", "Failed to load resource")) else None) or (warns.append(m.text) if "[i18n]" in m.text else None))
    page.goto(f"{BASE}/{path}{query}")
    page.wait_for_timeout(900)
    page.sent = sent
    return ctx, page, errors, warns


# ---------------------------------------------------------------- the tools themselves
def kit_tests(browser):
    section("Member tools (kit.js)")
    ctx, page, errors, _ = open_page(browser, "join.html")
    ev = page.evaluate
    check("ORCID checksum accepts real iDs, rejects a changed digit", ev("() => [QIST.kit.orcidValid('0000-0002-1825-0097'), QIST.kit.orcidValid('0000-0001-5109-3700'), QIST.kit.orcidValid('0000-0002-1825-0098'), QIST.kit.orcidValid('1234')]") == [True, True, False, False])
    check("ORCID input is normalised from URL and bare digits", ev("() => [QIST.kit.normOrcid('https://orcid.org/0000-0002-1825-0097/'), QIST.kit.normOrcid('0000000218250097'), QIST.kit.normOrcid(' 0000-0002-1825-0097 '), QIST.kit.normOrcid('nonsense')]") == ["0000-0002-1825-0097"] * 3 + [None])
    o = ev("(rec) => QIST.kit.parseOrcid(rec)", json.loads(ORCID))
    check("ORCID record: name, current employer, city, country", o["name"] == "Josiah Carberry" and o["institution"] == "Wesleyan University" and o["city"] == "Middletown" and o["country"] == "US", {k: o[k] for k in ("name", "institution", "city", "country")})
    check("ORCID record: role, keywords, bio", o["title"] == "Professor" and len(o["keywords"]) >= 1 and "fictitious" in o["bio"], (o["title"], o["keywords"]))
    check("ORCID record: works with a DOI or link, deduplicated, newest first", len(o["works"]) >= 2 and all(w["title"] and (w["doi"] or w["url"]) for w in o["works"]) and len({w["doi"] or w["title"] for w in o["works"]}) == len(o["works"]) and [w["year"] or 0 for w in o["works"]] == sorted([w["year"] or 0 for w in o["works"]], reverse=True), [(w["title"][:30], w["year"]) for w in o["works"]])
    check("ORCID record: only http(s) links survive", ev("() => QIST.kit.safeUrl('javascript:alert(1)') + '|' + QIST.kit.safeUrl('https://a.org/x') + '|' + QIST.kit.safeUrl('//evil') + '|' + QIST.kit.safeUrl('data:text/html,x')") == "|https://a.org/x||")
    hostile = {"person": {"name": {"given-names": {"value": "<img src=x onerror=alert(1)>"}, "family-name": {"value": "X"}}, "researcher-urls": {"researcher-url": [{"url": {"value": "javascript:alert(1)"}}]}}, "activities-summary": {}}
    h = ev("(r) => QIST.kit.parseOrcid(r)", hostile)
    check("ORCID record with hostile values yields no link, and name is plain text for escaping", h["website"] == "" and "<img" in h["name"])
    c = ev("(j) => QIST.kit.parseCrossref(j)", json.loads(CROSSREF))
    check("Crossref work: title, authors, venue, year, DOI", c["title"] == "Nanometre-scale thermometry in a living cell" and c["venue"] == "Nature" and c["year"] == 2013 and c["doi"] == "10.1038/nature12373" and len(c["authors"]) == 8, c)
    check("DOI input forms are normalised", ev("() => ['https://doi.org/10.1038/NATURE12373', 'doi: 10.1038/nature12373.', '10.1038/nature12373', 'nope', '10.12/x'].map(x => QIST.kit.normDoi(x))") == ["10.1038/nature12373"] * 3 + [None, None])

    cv = """Aigerim Bekova
Curriculum Vitae
aigerim.bekova@nu.edu.kz | ORCID 0000-0002-1825-0097
PhD student, Nazarbayev University. Research: perovskite solar cells, thin films, machine learning for materials discovery, deep learning.
Publications: doi:10.1038/nature12373. Also https://doi.org/10.1021/jacs.2c01234.
Perovskite solar cells have stability limits; we study perovskite solar cells and thin films."""
    tax = ev("() => QIST.feed.loadTaxonomy()")
    a = ev("([t, tax]) => QIST.kit.analyzeCv(t, tax)", [cv, tax])
    check("CV: name, e-mail, valid ORCID iD", a["name"] == "Aigerim Bekova" and a["emails"] == ["aigerim.bekova@nu.edu.kz"] and a["orcid"] == "0000-0002-1825-0097", a)
    check("CV: DOIs found, trailing punctuation stripped", a["dois"] == ["10.1038/nature12373", "10.1021/jacs.2c01234"], a["dois"])
    check("CV: keywords are phrases that are literally in the text", all(k.lower() in cv.lower().replace("-", " ") for k in a["keywords"]) and any("perovskite" in k.lower() for k in a["keywords"]) and "machine learning" in [k.lower() for k in a["keywords"]] and "curriculum" not in " ".join(a["keywords"]).lower(), a["keywords"])
    check("CV: proposes fields from the vocabulary", "Materials Science" in a["fields"] and 1 <= len(a["fields"]) <= 3, a["fields"])
    bad = ev("([t, tax]) => QIST.kit.analyzeCv(t, tax)", ["ORCID 0000-0002-1825-0098 and ai said the maintain", tax])
    check("CV: an ORCID with a wrong check digit is ignored; 'ai' inside words proposes nothing", bad["orcid"] is None and bad["fields"] == [] and bad["keywords"] == [], bad)
    check("CV: empty text is safe", ev("([tax]) => QIST.kit.analyzeCv('', tax)", [tax])["fields"] == [])
    check("no JS errors", not errors, errors)
    ctx.close()


# ---------------------------------------------------------------- join.html without a backend
def join_tests(browser):
    section("join.html (no backend: a request goes to the QIST team)")
    ctx, page, errors, warns = open_page(browser, "join.html")
    check("form renders with ORCID, CV, photo, fields, keywords, links, papers", all(page.locator(s).count() for s in ("#pf-orcid", "#pf-cv-toggle", "#pf-photo-file", "#pf-fields button", "#pf-kw", "#pf-web", "#pf-doi", "#pf-listed")))
    check("no password field without accounts", page.locator("#pf-password").count() == 0)
    check("with no accounts there is no 'Sign in' link that leads nowhere", page.locator(".page-top a[href='login.html']").count() == 0 and "opens when accounts" in page.inner_text(".page-top"), page.inner_text(".page-top")[-200:])
    check("…and no invitation hint (no link can work yet)", not page.locator("#invited").is_visible())
    check("lede says a curator creates the profile by hand", "curator" in page.inner_text("#lede").lower() or "info@qista.org" in page.inner_text("#lede"))
    check("the researcher count on the page is real", page.inner_text("#top-num").isdigit() and int(page.inner_text("#top-num")) >= 20)

    # ORCID: bad, then good, then it must not overwrite what the person typed
    page.fill("#pf-orcid", "0000-0002-1825-0098"); page.click("#pf-orcid-go")
    check("a bad ORCID iD is refused with an example", "valid ORCID" in page.inner_text("#pf-orcid-msg"), page.inner_text("#pf-orcid-msg"))
    page.fill("#pf-orcid", "0000-0001-5109-3700"); page.click("#pf-orcid-go"); page.wait_for_timeout(400)
    check("a well-formed iD with no public record says so", "No public ORCID record" in page.inner_text("#pf-orcid-msg"), page.inner_text("#pf-orcid-msg"))
    page.fill("#pf-name", "Typed Name")
    page.fill("#pf-orcid", "https://orcid.org/0000-0002-1825-0097"); page.click("#pf-orcid-go")
    page.wait_for_function("document.querySelector('#pf-orcid-msg').textContent.includes('Filled')", timeout=8000)
    check("ORCID fills empty fields: institution, title, city, country, bio", page.input_value("#pf-inst") == "Wesleyan University" and page.input_value("#pf-title") == "Professor" and page.input_value("#pf-city") == "Middletown" and page.input_value("#pf-country") == "US" and "fictitious" in page.input_value("#pf-bio"))
    check("…but never overwrites what was already typed", page.input_value("#pf-name") == "Typed Name")
    check("…normalises the iD in the box", page.input_value("#pf-orcid") == "0000-0002-1825-0097")
    check("…and reports what it did", "Filled:" in page.inner_text("#pf-orcid-msg") and "Papers added" in page.inner_text("#pf-orcid-msg"), page.inner_text("#pf-orcid-msg"))
    n_papers = page.locator("#pf-papers li:not(.empty)").count()
    check("ORCID works become papers in the list", n_papers >= 2, n_papers)
    check("paper titles are links only when there is a safe link", page.locator("#pf-papers a").count() >= 1 and all(a.startswith("https://") for a in page.locator("#pf-papers a").evaluate_all("els => els.map(e => e.href)")))
    page.click("#pf-orcid-go"); page.wait_for_timeout(700)
    check("fetching twice does not duplicate papers", page.locator("#pf-papers li:not(.empty)").count() == n_papers)
    page.locator("#pf-papers button[data-rm]").first.click()
    check("a paper can be removed", page.locator("#pf-papers li:not(.empty)").count() == n_papers - 1)

    # photo
    page.set_input_files("#pf-photo-file", {"name": "me.png", "mimeType": "image/png", "buffer": png_bytes()})
    page.wait_for_selector("#pf-avatar img")
    src = page.get_attribute("#pf-avatar img", "src")
    dims = page.evaluate("(s) => new Promise(r => { const i = new Image(); i.onload = () => r([i.width, i.height]); i.src = s; })", src)
    check("photo becomes a 256x256 JPEG under 110 KB", src.startswith("data:image/jpeg;base64,") and dims == [256, 256] and len(src) < 110000, (dims, len(src)))
    page.set_input_files("#pf-photo-file", {"name": "x.txt", "mimeType": "text/plain", "buffer": b"not an image"})
    check("a non-image is refused and the photo kept", "JPEG" in page.inner_text("#pf-photo-msg") and page.get_attribute("#pf-avatar img", "src") == src)
    page.click("#pf-photo-rm")
    check("the photo can be removed (initials return)", page.locator("#pf-avatar img").count() == 0 and page.locator("#pf-avatar span").count() == 1)
    page.set_input_files("#pf-photo-file", {"name": "me.png", "mimeType": "image/png", "buffer": png_bytes()}); page.wait_for_selector("#pf-avatar img")

    # CV (pasted)
    page.click("#pf-cv-toggle")
    page.fill("#pf-cv-text", "Short"); page.click("#pf-cv-go")
    check("a too-short CV is refused", "too short" in page.inner_text("#pf-cv-msg"))
    page.fill("#pf-cv-text", "Aigerim Bekova\nPhD student working on perovskite solar cells, thin films and deep learning for materials.\nPaper: doi:10.1038/nature12373\nperovskite solar cells; thin films; machine learning.")
    page.click("#pf-cv-go")
    page.wait_for_function("document.querySelector('#pf-cv-msg').textContent.includes('Found')", timeout=8000)
    kws = page.locator("#pf-kw-chips .kw").all_inner_texts()
    check("CV adds keywords from its own text", any("perovskite" in k.lower() for k in kws), kws)
    check("CV fills research fields when none are chosen", page.locator('#pf-fields button[aria-pressed="true"]').count() >= 1)
    check("CV DOI is looked up and added as a paper", "Nanometre-scale thermometry in a living cell" in page.inner_text("#pf-papers"))
    check("CV does not overwrite the typed name", page.input_value("#pf-name") == "Typed Name")

    # keywords: chips with keyboard, dedupe, remove
    before = page.locator("#pf-kw-chips .kw").count()
    page.fill("#pf-kw", "Graphene"); page.press("#pf-kw", "Enter")
    page.fill("#pf-kw", "graphene"); page.press("#pf-kw", "Enter")
    check("Enter adds a keyword; duplicates (any case) are ignored", page.locator("#pf-kw-chips .kw").count() == before + 1)
    page.locator("#pf-kw-chips .kw").last.click()
    check("clicking a keyword removes it", page.locator("#pf-kw-chips .kw").count() == before)
    page.fill("#pf-kw", "a, b ,c"); page.press("#pf-kw", ",")
    check("commas split several keywords at once", page.locator("#pf-kw-chips .kw").count() == before + 3)

    # fields: at most six
    while page.locator('#pf-fields button[aria-pressed="true"]').count():
        page.locator('#pf-fields button[aria-pressed="true"]').first.click()
    for f in ["Neuroscience", "Robotics", "Engineering", "Economics", "Electronics", "Materials Science", "Veterinary Sciences"]:
        page.locator(f'#pf-fields button[data-f="{f}"]').click(force=True, timeout=3000) if page.locator(f'#pf-fields button[data-f="{f}"]:not([disabled])').count() else None
    check("at most 6 research fields; the rest are disabled", page.locator('#pf-fields button[aria-pressed="true"]').count() == 6 and page.locator("#pf-fields button:disabled").count() > 5)

    # papers by DOI and by hand
    page.fill("#pf-doi", "not a doi"); page.click("#pf-doi-go")
    check("an invalid DOI is refused with an example", "10.1038" in page.inner_text("#pf-pap-msg"))
    page.fill("#pf-doi", "10.9999/missing"); page.click("#pf-doi-go"); page.wait_for_timeout(400)
    check("an unknown DOI says Crossref has nothing and offers the manual route", "by hand" in page.inner_text("#pf-pap-msg").lower(), page.inner_text("#pf-pap-msg"))
    page.fill("#pf-doi", "10.1038/nature12373"); page.click("#pf-doi-go"); page.wait_for_timeout(400)
    check("the same paper is not added twice", "Already" in page.inner_text("#pf-pap-msg"), page.inner_text("#pf-pap-msg"))
    page.click("#pf-man-toggle")
    page.fill("#pf-m-title", "A paper by hand"); page.click("#pf-m-add")
    check("a manual paper needs a link", "http" in page.inner_text("#pf-pap-msg"))
    page.fill("#pf-m-url", "javascript:alert(1)"); page.click("#pf-m-add")
    check("…and a javascript: link is refused", "A paper by hand" not in page.inner_text("#pf-papers"))
    page.fill("#pf-m-url", "https://example.org/paper"); page.fill("#pf-m-authors", "A. One, B. Two"); page.fill("#pf-m-year", "2024"); page.click("#pf-m-add")
    check("a manual paper with a link is added", "A paper by hand" in page.inner_text("#pf-papers"))

    # validation, then Clear, then a real submit
    page.fill("#pf-name", ""); page.fill("#pf-email", "")
    page.click("#pf-submit")
    check("submitting without name/e-mail is refused, focus goes to the first problem", page.evaluate("document.activeElement.id") == "pf-name" and page.get_attribute("#pf-name", "aria-invalid") == "true" and not page.sent)
    page.fill("#pf-name", "Typed Name"); page.fill("#pf-email", "not-an-email"); page.click("#pf-submit")
    check("a bad e-mail is refused", page.evaluate("document.activeElement.id") == "pf-email" and not page.sent)
    page.fill("#pf-email", "ada@example.org"); page.fill("#pf-web", "ftp://x"); page.click("#pf-submit")
    check("a non-http link is refused", page.evaluate("document.activeElement.id") == "pf-web" and not page.sent)
    page.fill("#pf-web", "https://example.org/ada")
    page.uncheck("#pf-listed")
    page.click("#pf-submit"); page.wait_for_selector("#done:not([hidden])", timeout=8000)
    sent = page.sent[0] if page.sent else {}
    check("the request reaches the endpoint with everything the person filled in", sent.get("kind") == "profile_request" and sent.get("name") == "Typed Name" and sent.get("email") == "ada@example.org"
          and sent.get("orcid") == "0000-0002-1825-0097" and sent.get("institution") == "Wesleyan University" and sent.get("country") == "US" and sent.get("public_link") == "https://example.org/ada", {k: str(v)[:40] for k, v in sent.items()})
    check("…including the photo, fields, keywords and papers", str(sent.get("photo", "")).startswith("data:image/jpeg") and sent.get("fields") and "perovskite" in sent.get("topics", "").lower() and "A paper by hand" in sent.get("papers", ""))
    check("…and the choice not to be listed", sent.get("listed") == "no", sent.get("listed"))
    check("no password was sent", "password" not in sent)
    check("the confirmation names the address", "ada@example.org" in page.inner_text("#done"))
    check("no JS errors", not errors, errors)
    ctx.close()

    section("join.html: Clear, languages, layout")
    ctx, page, errors, warns = open_page(browser, "join.html")
    page.fill("#pf-name", "Someone"); page.fill("#pf-city", "Astana"); page.click('#pf-fields button[data-f="Robotics"]'); page.fill("#pf-kw", "x"); page.press("#pf-kw", "Enter")
    page.click("#pf-clear")
    check("Clear empties every field, chip and keyword", page.input_value("#pf-name") == "" and page.input_value("#pf-city") == "" and page.locator('#pf-fields button[aria-pressed="true"]').count() == 0 and page.locator("#pf-kw-chips .kw").count() == 0)
    ctx.close()
    for lang in ("ru", "kk"):
        ctx, page, errors, warns = open_page(browser, "join.html", f"?lang={lang}")
        body = page.inner_text("body")
        check(f"{lang}: no raw keys, no missing-key warnings", not any(k in body for k in ("pf.", "join.", "common.", "nav.")) and not warns, warns[:3])
        check(f"{lang}: no JS errors", not errors, errors)
        ctx.close()
    for w in (390, 768):
        ctx, page, errors, _ = open_page(browser, "join.html", width=w)
        check(f"{w}px: no horizontal scroll", page.evaluate("document.documentElement.scrollWidth") <= page.evaluate("document.documentElement.clientWidth") + 1)
        ctx.close()


def login_static_tests(browser):
    section("login.html without a backend")
    ctx, page, errors, _ = open_page(browser, "login.html")
    check("it stays on the sign-in page instead of bouncing back to Create profile", page.url.endswith("/login.html"), page.url)
    check("it says sign-in is not available yet and offers the request form", "not available yet" in page.inner_text(".auth-card") and page.locator(".auth-card a[href^='join.html']").count() == 1, page.inner_text(".auth-card")[:200])
    check("there is no password field to type into", page.locator("#l-password").count() == 0)
    check("no JS errors", not errors, errors)
    ctx.close()
    for lang in ("ru", "kk"):
        ctx, page, errors, warns = open_page(browser, "login.html", f"?lang={lang}")
        check(f"{lang}: the message is translated", "login." not in page.inner_text("body") and "not available" not in page.inner_text(".auth-card") and not warns and not errors, (warns[:2], errors[:2]))
        ctx.close()


# ---------------------------------------------------------------- post a position (static)
def position_tests(browser):
    section("post-position.html (no backend: a curator publishes it)")
    ctx, page, errors, _ = open_page(browser, "post-position.html")
    check("form has title, lab, country, stage, fields, description, link, deadline", all(page.locator(s).count() for s in ("#p-title", "#p-org", "#p-country", "#p-stage", "#p-fields button", "#p-summary", "#p-link", "#p-deadline")))
    check("contact fields are shown because there is no account", page.locator("#static-contact").is_visible())
    check("deadline cannot be in the past", page.get_attribute("#p-deadline", "min") >= "2026-10-12")
    page.click("#p-submit")
    check("an empty form is refused at the title", page.evaluate("document.activeElement.id") == "p-title" and not page.sent)
    page.fill("#p-title", "PhD position in perovskite solar cells"); page.fill("#p-org", "Materials Lab, NU"); page.fill("#p-summary", "Fully funded four-year PhD on stable perovskite solar cells.")
    page.fill("#p-link", "javascript:alert(1)"); page.fill("#p-name", "Ada"); page.fill("#p-email", "ada@example.org"); page.click("#p-submit")
    check("a javascript: link is refused", page.evaluate("document.activeElement.id") == "p-link" and not page.sent)
    page.fill("#p-link", "https://example.org/phd")
    page.click('#p-fields button[data-f="Materials Science"]'); page.click('#p-fields button[data-f="Energy, Renewable Energy"]')
    page.select_option("#p-stage", "any"); page.select_option("#p-country", "KZ"); page.fill("#p-city", "Astana")
    page.fill("#p-summary", "x" * 30); page.fill("#p-summary", "Fully funded four-year PhD on stable perovskite solar cells.")
    check("the character counter follows the text", page.inner_text("#p-count") == str(len("Fully funded four-year PhD on stable perovskite solar cells.")))
    page.click("#p-submit"); page.wait_for_selector("#done:not([hidden])", timeout=8000)
    s = page.sent[0]
    check("the submission carries the position, the link and the contact", s.get("kind") == "position_submission" and s.get("title") == "PhD position in perovskite solar cells" and s.get("link") == "https://example.org/phd"
          and s.get("career_stage") == "any" and s.get("country") == "KZ" and "Materials Science" in s.get("fields", "") and s.get("contact_email") == "ada@example.org", {k: str(v)[:30] for k, v in s.items()})
    check("the confirmation says a curator will publish it", "curator" in page.inner_text("#done").lower())
    check("no JS errors", not errors, errors)
    ctx.close()
    for lang in ("ru", "kk"):
        ctx, page, errors, warns = open_page(browser, "post-position.html", f"?lang={lang}")
        check(f"{lang}: no raw keys, no warnings, no errors", not any(k in page.inner_text("body") for k in ("post.", "pf.", "common.")) and not warns and not errors, (warns[:2], errors[:2]))
        ctx.close()


# ---------------------------------------------------------------- the home page
def home_tests(browser):
    section("Home page")
    ctx, page, errors, warns = open_page(browser, "index.html")
    reqs = []
    page.on("response", lambda r: reqs.append((r.url, r.status)))
    page.reload(); page.wait_for_timeout(1500)
    h1 = page.locator("#hero-h1").inner_text()
    check("hero headline is the new one", h1.startswith("Find researchers to solve your R&D needs"), h1)
    check("the hero picture loaded", any("hero-globe.jpg" in u and s == 200 for u, s in reqs), [u for u, s in reqs if "hero" in u])
    check("the old 13/17 numeral is gone from the hero", page.locator(".hg .photo-num").count() == 0)
    check("brand eyebrow, lead, two buttons, four pillars", "SCIENCEBRIDGE AI" in page.inner_text(".hg-eyebrow") and len(page.inner_text(".hg-lead")) > 60 and page.locator(".hg-ctas a.btn").count() == 2 and page.locator(".hg-pillars li").count() == 4)
    check("'Create profile' goes to join.html", page.locator(".hg-ctas a.btn-gold").get_attribute("href") == "join.html")
    check("the live strip shows what the daily feeds hold", page.locator("#hg-live").is_visible() and "vacancies" in page.inner_text("#hg-live"), page.inner_text("#hg-live"))

    # search box -> directory
    page.fill("#hg-q", "perovskite solar cells"); page.press("#hg-q", "Enter")
    page.wait_for_url("**/directory.html?q=*", timeout=8000)
    check("the search box opens the directory with the query", "perovskite" in page.url and page.input_value("#f-q") == "perovskite solar cells", page.url)
    page.goto(f"{BASE}/index.html"); page.wait_for_timeout(700)
    page.click("#hg-search button");
    check("an empty search does not navigate", page.url.endswith("index.html"))
    page.click(".hg-chips a >> nth=0")
    page.wait_for_url("**/directory.html?q=*", timeout=8000)
    check("topic chips open the directory for that topic", "q=" in page.url)

    page.goto(f"{BASE}/index.html"); page.wait_for_timeout(2200)
    stats = page.evaluate("() => Object.fromEntries([...document.querySelectorAll('[data-count]')].map(e => [e.dataset.count, e.textContent]))")
    people = page.evaluate("async () => { const p = QIST.uniquePeople(await QIST.getPeople()); const n = x => String(x || '').trim().toLowerCase().replace(/\\s+/g, ' '); return {r: p.length, i: new Set(p.map(x => n(x.institution)).filter(Boolean)).size, t: new Set(p.flatMap(x => (x.topics || []).map(n)).filter(Boolean)).size, c: new Set(p.map(x => x.country).filter(Boolean)).size}; }")
    check("the four numbers are computed from the data, not typed in", stats == {"researchers": str(people["r"]), "institutions": str(people["i"]), "topics": str(people["t"]), "countries": str(people["c"])}, (stats, people))
    size = page.evaluate("parseFloat(getComputedStyle(document.querySelector('.stat dd')).fontSize)")
    old = page.evaluate("16 * .9375")
    check("the stats are large (>= 40px figures) in a band under the hero", size >= 40 and page.locator(".stats-band").is_visible(), size)
    check("stat labels", [t.lower() for t in page.locator(".stat dt").all_inner_texts()] == ["researchers", "institutions", "research topics", "countries"])

    # the fit bar and the board still work
    n0 = page.inner_text("#fit-n")
    page.select_option("#demo-stage", "pi_only"); page.wait_for_timeout(900)
    check("the 'I'm a … based in …' check recounts fitting calls", page.inner_text("#fit-n") != n0 or page.inner_text("#open-n").isdigit(), (n0, page.inner_text("#fit-n")))
    check("open calls and the fit count are numbers with fit <= open", int(page.inner_text("#fit-n")) <= int(page.inner_text("#open-n")))
    check("'Show these calls' carries the country and stage", "stage=pi_only" in page.get_attribute("#hero-show", "href") and "country=" in page.get_attribute("#hero-show", "href"))
    rows = page.locator("#board-rows a.board-row")
    check("the closing-next board still lists calls", rows.count() >= 1)
    href = rows.first.get_attribute("href")
    check("board rows deep-link into Opportunities", href.startswith("opportunities.html?") and "#opp-" in href, href)
    page.goto(f"{BASE}/{href}"); page.wait_for_function("document.querySelectorAll('#tabs button').length", timeout=8000); page.wait_for_timeout(900)
    target = href.split("#opp-")[1]
    check("…and land on that call, even one the reader cannot apply to", page.locator(f'[data-id="{target}"]').count() == 1, target)
    check("no JS errors", not errors, errors)
    ctx.close()

    for lang in ("ru", "kk"):
        ctx, page, errors, warns = open_page(browser, "index.html", f"?lang={lang}")
        body = page.inner_text("body")
        check(f"{lang}: hero translated, no raw keys, no warnings", not any(k in body for k in ("hero.", "stat.", "home.", "nav.")) and "Find researchers" not in body and not warns and not errors, (warns[:2], errors[:2]))
        ctx.close()
    for w in (390, 768, 1100):
        ctx, page, errors, _ = open_page(browser, "index.html", width=w)
        check(f"{w}px: no horizontal scroll; headline, search and stats visible", page.evaluate("document.documentElement.scrollWidth") <= page.evaluate("document.documentElement.clientWidth") + 1 and page.locator("#hero-h1").is_visible() and page.locator("#hg-q").is_visible() and page.locator(".stats").is_visible())
        ctx.close()
    ctx, page, errors, _ = open_page(browser, "index.html")
    page.screenshot(path=str(Path(sys.argv[3]) / "home_desktop.png") if len(sys.argv) > 3 else "/dev/null") if len(sys.argv) > 3 else None
    ctx.close()


with sync_playwright() as pw:
    b = pw.chromium.launch()
    only = sys.argv[2].split(",") if len(sys.argv) > 2 and sys.argv[2] != "-" else None
    for fn in (kit_tests, join_tests, login_static_tests, position_tests, home_tests):
        if only and fn.__name__ not in only:
            continue
        try:
            fn(b)
        except Exception:
            traceback.print_exc()
            check(f"{fn.__name__} completed", False, "exception")
    b.close()

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
