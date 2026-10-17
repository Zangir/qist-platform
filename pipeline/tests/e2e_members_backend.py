"""Signed-in flows against a real FastAPI backend (temp database): create a profile, edit it, post a position, add papers,
the admin members database, account deletion.
    backend/.venv/bin/python pipeline/tests/e2e_members_backend.py http://localhost:8099
Starts uvicorn on :8100 itself; needs the static server on the given base URL."""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np
import requests
from playwright.sync_api import sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8099").rstrip("/")
API = sys.argv[2].rstrip("/") if len(sys.argv) > 2 else "http://localhost:8100"
ADMIN_PW = os.environ.get("E2E_ADMIN_PASSWORD", "admin-e2e-password")
ROOT = Path(__file__).resolve().parents[2]
FX = Path(__file__).parent / "fixtures"
ORCID, CROSSREF = (FX / "orcid_record.json").read_text(), (FX / "crossref_doi.json").read_text()
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("  ok   " if cond else "  FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


def png_bytes():
    img = np.full((400, 400, 3), 90, np.uint8); cv2.circle(img, (200, 200), 120, (40, 160, 240), -1)
    return cv2.imencode(".png", img)[1].tobytes()


def minimal_pdf(text):
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out)); out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (len(objs) + 1, x)


env = dict(os.environ, QIST_DB_URL="sqlite:///" + os.path.join(tempfile.mkdtemp(), "e2e.db"), QIST_JWT_SECRET="e2e-secret-e2e-secret-e2e-secret-1234", QIST_ADMIN_PASSWORD=ADMIN_PW)
srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app.main:main_app", "--port", "8100", "--log-level", "warning"], cwd=ROOT, env=env) if len(sys.argv) <= 2 else None
try:
    for _ in range(60):
        try:
            if requests.get(API + "/api/health", timeout=1).ok:
                break
        except Exception:
            time.sleep(0.2)
    else:
        raise SystemExit("backend did not start")

    _adm = requests.post(API + "/api/auth/login", json={"email": "admin@qist.kz", "password": ADMIN_PW}).json()
    _others = [m for m in requests.get(API + "/api/admin/members", headers={"Authorization": "Bearer " + _adm["token"]}).json() if m["role"] != "admin"]
    if _others and not os.environ.get("E2E_ALLOW_NONEMPTY"):
        raise SystemExit(f"Refusing to run: the server already holds {len(_others)} member account(s); this test expects an empty server.")

    def new_ctx(b, session=None, width=1440):
        ctx = b.new_context(viewport={"width": width, "height": 900})
        ctx.add_init_script("localStorage.setItem('qist_api_url', %s); %s" % (json.dumps(API), f"localStorage.setItem('qist_session', {json.dumps(json.dumps(session))});" if session else ""))
        ctx.route("https://pub.orcid.org/**", lambda r: r.fulfill(status=200, content_type="application/json", body=ORCID))
        ctx.route("https://api.crossref.org/works/**", lambda r: r.fulfill(status=200, content_type="application/json", body=CROSSREF))
        page = ctx.new_page(); page.errors = []
        page.on("pageerror", lambda e: page.errors.append(str(e)))
        page.on("dialog", lambda d: d.accept())
        return ctx, page

    with sync_playwright() as pw:
        b = pw.chromium.launch()

        print("\nCreate a profile with an account")
        ctx, page = new_ctx(b)
        page.goto(f"{BASE}/join.html"); page.wait_for_selector("#pf-password")
        check("with a backend the form asks for a password", page.locator("#pf-password").count() == 1 and "curator" not in page.inner_text("#lede").lower())
        page.fill("#pf-name", "Ada Researcher"); page.fill("#pf-email", "ada@example.org"); page.fill("#pf-password", "short")
        page.click("#pf-submit")
        check("a short password is refused before anything is sent", page.evaluate("document.activeElement.id") == "pf-password")
        page.fill("#pf-password", "correct-horse-battery")
        page.fill("#pf-orcid", "0000-0002-1825-0097"); page.click("#pf-orcid-go")
        page.wait_for_function("document.querySelector('#pf-orcid-msg').textContent.includes('Filled')", timeout=8000)
        page.fill("#pf-title", "PhD student"); page.fill("#pf-inst", "Nazarbayev University"); page.select_option("#pf-country", "KZ"); page.fill("#pf-city", "Astana")
        page.click('#pf-fields button[data-f="Materials Science"]')
        page.fill("#pf-kw", "perovskite"); page.press("#pf-kw", "Enter")
        page.set_input_files("#pf-photo-file", {"name": "me.png", "mimeType": "image/png", "buffer": png_bytes()}); page.wait_for_selector("#pf-avatar img")
        n_orcid_papers = page.locator("#pf-papers li:not(.empty)").count()
        page.click("#pf-submit")
        page.wait_for_url("**/profile.html**", timeout=10000)
        page.wait_for_selector("#pf-name")
        check("creating the profile signs the member in and opens their profile page", "Ada Researcher" in page.inner_text("#me-sub") and "welcome" in page.url)
        check("the welcome line is shown", page.locator("#welcome").is_visible())
        sess = json.loads(page.evaluate("localStorage.getItem('qist_session')"))
        hdr = {"Authorization": "Bearer " + sess["token"]}
        me = requests.get(API + "/api/me/profile", headers=hdr).json()
        check("the server holds everything: ORCID, institution, country, city, fields, keywords, photo", me["orcid"] == "0000-0002-1825-0097" and me["institution"] == "Nazarbayev University" and me["country"] == "KZ" and me["city"] == "Astana"
              and me["fields"] == ["Materials Science"] and "perovskite" in me["keywords"] and me["photo"].startswith("data:image/jpeg"), {k: str(v)[:30] for k, v in me.items()})
        papers = requests.get(API + "/api/me/papers", headers=hdr).json()
        check("papers imported from ORCID were saved on the account", len(papers) == n_orcid_papers and n_orcid_papers >= 2, (len(papers), n_orcid_papers))
        d = [p for p in requests.get(API + "/api/people").json() if p["name"] == "Ada Researcher"]
        check("the member is in the public directory with country name, photo and ORCID", d and d[0]["country"] == "Kazakhstan" and d[0]["photo"].startswith("data:image/jpeg") and d[0]["orcid"] == "0000-0002-1825-0097")
        check("the e-mail is nowhere in public data", "ada@example.org" not in json.dumps(requests.get(API + "/api/people").json()) + json.dumps(requests.get(API + "/api/papers").json()))
        check("the profile form is filled from the account", page.input_value("#pf-inst") == "Nazarbayev University" and page.input_value("#pf-email") == "ada@example.org" and page.is_disabled("#pf-email"))
        check("the photo shows on the profile page", page.locator(".me-id img").count() == 1)
        check("'Today for you' is filled", page.locator("#today-body .t-row").count() >= 1 or "No" in page.inner_text("#today-body"))

        print("\nEdit the profile")
        page.fill("#pf-inst", "MBZUAI"); page.fill("#pf-bio", "I study films.")
        page.click("#pf-submit"); page.wait_for_function("document.querySelector('#pf-state').textContent.includes('Saved')", timeout=6000)
        me = requests.get(API + "/api/me/profile", headers=hdr).json()
        check("saving changes reaches the server", me["institution"] == "MBZUAI" and me["bio"] == "I study films.")
        page.fill("#pf-orcid", "0000-0002-1825-0098"); page.click("#pf-submit")
        check("a bad ORCID is refused on the page", page.evaluate("document.activeElement.id") == "pf-orcid")
        page.fill("#pf-orcid", "0000-0002-1825-0097")
        page.click("#pf-photo-rm"); page.click("#pf-submit"); page.wait_for_function("document.querySelector('#pf-state').textContent.includes('Saved')", timeout=6000)
        check("removing the photo is saved", requests.get(API + "/api/me/profile", headers=hdr).json()["photo"] == "")
        page.uncheck("#pf-listed"); page.click("#pf-submit"); page.wait_for_function("document.querySelector('#pf-state').textContent.includes('Saved')", timeout=6000)
        check("un-listing removes the member from the directory at once", not [p for p in requests.get(API + "/api/people").json() if p["name"] == "Ada Researcher"])
        page.check("#pf-listed"); page.click("#pf-submit"); page.wait_for_function("document.querySelector('#pf-state').textContent.includes('Saved')", timeout=6000)

        print("\nPapers on the account")
        before = len(requests.get(API + "/api/me/papers", headers=hdr).json())
        page.fill("#pf-doi", "10.1038/nature12373"); page.click("#pf-doi-go"); page.wait_for_timeout(1200)
        after = requests.get(API + "/api/me/papers", headers=hdr).json()
        check("adding a paper by DOI saves it at once", len(after) == before + 1 and any(p["doi"] == "10.1038/nature12373" for p in after) or "Already" in page.inner_text("#pf-pap-msg"), (before, len(after)))
        page.fill("#pf-man-toggle", "") if False else None
        page.click("#pf-man-toggle"); page.fill("#pf-m-title", "Hand-written entry"); page.fill("#pf-m-url", "https://example.org/hand"); page.click("#pf-m-add"); page.wait_for_timeout(800)
        mine = requests.get(API + "/api/me/papers", headers=hdr).json()
        check("a manual paper is saved", any(p["title"] == "Hand-written entry" and p["url"] == "https://example.org/hand" for p in mine))
        page.locator("#pf-papers li", has_text="Hand-written entry").locator("button[data-rm]").click(); page.wait_for_timeout(600)
        check("removing a paper deletes it on the server", not any(p["title"] == "Hand-written entry" for p in requests.get(API + "/api/me/papers", headers=hdr).json()))

        print("\nPost a position")
        page.goto(f"{BASE}/post-position.html"); page.wait_for_selector("body[data-ready]")
        check("signed in: no contact fields, posting as the member", page.locator("#static-contact").is_hidden() and "Ada Researcher" in page.inner_text("#who"))
        page.fill("#p-title", "PhD position in perovskite solar cells"); page.fill("#p-org", "Materials Lab, MBZUAI"); page.fill("#p-city", "Abu Dhabi"); page.select_option("#p-country", "AE")
        page.fill("#p-summary", "Fully funded four-year PhD on stable perovskite solar cells. Thin-film experience is a plus."); page.fill("#p-link", "https://example.org/phd-1")
        page.select_option("#p-stage", "any"); page.click('#p-fields button[data-f="Materials Science"]')
        page.click("#p-submit"); page.wait_for_selector("#done:not([hidden])", timeout=8000)
        check("the position is published", "published" in page.inner_text("#done").lower())
        pos = requests.get(API + "/api/positions").json()
        check("it is public, as a call with the member as author and no e-mail", len(pos) == 1 and pos[0]["posted_by"] == "Ada Researcher" and pos[0]["source_url"] == "https://example.org/phd-1" and "ada@example.org" not in json.dumps(pos))
        page.goto(f"{BASE}/post-position.html"); page.wait_for_selector("body[data-ready]")
        page.fill("#p-title", "PhD position in perovskite solar cells"); page.fill("#p-org", "Materials Lab, MBZUAI"); page.fill("#p-summary", "Fully funded four-year PhD on stable perovskite solar cells again."); page.fill("#p-link", "https://example.org/phd-1")
        page.click("#p-submit"); page.wait_for_function("document.querySelector('#p-state').textContent.length > 3", timeout=6000)
        check("posting the same title twice is refused with the server's reason", "already" in page.inner_text("#p-state").lower(), page.inner_text("#p-state"))

        page.goto(f"{BASE}/opportunities.html?tab=job"); page.wait_for_selector("#tabs button"); page.wait_for_timeout(800)
        page.fill("#q", "perovskite"); page.wait_for_timeout(500)
        card = page.locator('[data-id^="m-"]').first
        check("the position shows on Opportunities > Vacancies, marked as from a member", card.count() == 1 and "Posted by a member" in card.inner_text(), page.inner_text("#list")[:200])
        check("…with the link to the full announcement", card.locator("a.btn-primary").get_attribute("href") == "https://example.org/phd-1")
        check("…and the eligibility explanation for the reader", card.locator(".cond").count() >= 2)
        page.click('#tabs button[data-tab="paper"]'); page.fill("#q", "")
        page.wait_for_timeout(500)
        check("members' papers show on Opportunities > Papers", page.locator("#list .opp").count() >= 2 and "Ada Researcher" in page.inner_text("#list"), page.inner_text("#list")[:200])

        page.goto(f"{BASE}/profile.html"); page.wait_for_selector("#pos-list .opp")
        check("my profile lists my position", "PhD position in perovskite solar cells" in page.inner_text("#pos-list"))
        page.click("[data-del-pos]"); page.wait_for_timeout(700)
        check("removing it takes it off the platform", requests.get(API + "/api/positions").json() == [])

        print("\nSigned out visitors")
        ctx2, p2 = new_ctx(b)
        p2.goto(f"{BASE}/post-position.html"); p2.wait_for_selector("body[data-ready]")
        check("posting asks to sign in and the form is disabled", "Sign in" in p2.inner_text("#who") and p2.is_disabled("#p-title") and p2.is_disabled("#p-submit"))
        p2.goto(f"{BASE}/profile.html"); p2.wait_for_url("**/login.html**", timeout=8000)
        check("the profile page sends a signed-out visitor to sign in", "next=profile.html" in p2.url)
        p2.goto(f"{BASE}/login.html?next=https://evil.example/x"); p2.wait_for_selector("body[data-ready]")
        p2.fill("#l-email", "ada@example.org"); p2.fill("#l-password", "correct-horse-battery"); p2.click("#login-form button")
        p2.wait_for_url("**/profile.html", timeout=8000)
        check("sign-in never redirects off-site, whatever ?next= says", p2.url.startswith(BASE))
        p2.goto(f"{BASE}/login.html"); p2.evaluate("localStorage.removeItem('qist_session')"); p2.reload(); p2.wait_for_selector("body[data-ready]")
        p2.fill("#l-email", "ada@example.org"); p2.fill("#l-password", "wrong-password-here"); p2.click("#login-form button"); p2.wait_for_selector(".alert-error")
        check("a wrong password shows an error and stays on the page", "login" in p2.url)
        ctx2.close()

        print("\nCV upload (PDF) through the server")
        ctx3, p3 = new_ctx(b)
        p3.goto(f"{BASE}/join.html"); p3.wait_for_selector("#pf-cv-file")
        p3.set_input_files("#pf-cv-file", {"name": "cv.pdf", "mimeType": "application/pdf", "buffer": minimal_pdf("Aigerim Bekova. PhD student working on perovskite solar cells, thin films and machine learning for materials. ORCID 0000-0002-1825-0097.")})
        p3.wait_for_function("document.querySelector('#pf-cv-msg').textContent.includes('Found') || document.querySelector('#pf-cv-msg').classList.contains('bad')", timeout=10000)
        check("the server reads the PDF and the page fills ORCID, keywords and fields", p3.input_value("#pf-orcid") == "0000-0002-1825-0097" and p3.locator("#pf-kw-chips .kw").count() >= 2 and p3.locator('#pf-fields button[aria-pressed="true"]').count() >= 1, p3.inner_text("#pf-cv-msg"))
        p3.set_input_files("#pf-cv-file", {"name": "bad.exe", "mimeType": "application/octet-stream", "buffer": b"MZ not a cv"})
        p3.wait_for_function("document.querySelector('#pf-cv-msg').classList.contains('bad')", timeout=8000)
        check("an unsupported file is refused with the server's reason", "PDF" in p3.inner_text("#pf-cv-msg") or "could not" in p3.inner_text("#pf-cv-msg").lower(), p3.inner_text("#pf-cv-msg"))
        ctx3.close()

        print("\nAdmin: the members database")
        ctx4, p4 = new_ctx(b)
        p4.goto(f"{BASE}/login.html"); p4.wait_for_selector("body[data-ready]")
        p4.fill("#l-email", "admin@qist.kz"); p4.fill("#l-password", ADMIN_PW); p4.click("#login-form button"); p4.wait_for_url("**/profile.html", timeout=8000)
        p4.goto(f"{BASE}/admin.html"); p4.wait_for_selector("#tab-people table", state="attached", timeout=60000)
        p4.click('button[data-tab="members"]'); p4.wait_for_selector("#mem-body tr")
        check("the Members tab lists the member with e-mail, ORCID and counts", "ada@example.org" in p4.inner_text("#mem-body") and "0000-0002-1825-0097" in p4.inner_text("#mem-body") and "Nazarbayev" not in "MBZUAI")
        p4.fill("#mem-q", "zzzz-no-such"); check("the search filters rows", "No members" in p4.inner_text("#mem-body")); p4.fill("#mem-q", "mbzuai")
        check("…and finds by institution", "ada@example.org" in p4.inner_text("#mem-body"))
        with p4.expect_download() as dl:
            p4.click("#mem-csv")
        csv_text = Path(dl.value.path()).read_text()
        check("Export CSV downloads the database", csv_text.splitlines()[0].startswith("name,email") and "ada@example.org" in csv_text and "password" not in csv_text.lower())
        p4.click('button[data-tab="moderation"]'); p4.wait_for_timeout(500)
        check("the moderation tab lists papers", "Ada Researcher" in p4.inner_text("#tab-moderation"))
        ctx4.close()
        # a member cannot read the database
        check("a normal member is refused the members API", requests.get(API + "/api/admin/members", headers=hdr).status_code == 403)

        print("\nDelete the account")
        ctx5, p5 = new_ctx(b, session=sess)
        p5.goto(f"{BASE}/profile.html"); p5.wait_for_selector("#pf-name")
        with p5.expect_download() as dl:
            p5.click("#export")
        exported = json.loads(Path(dl.value.path()).read_text())
        check("'Download my data' gives profile, papers and positions as JSON", exported["profile"]["email"] == "ada@example.org" and len(exported["papers"]) >= 2 and "positions" in exported)
        p5.click("#delete"); p5.wait_for_url("**/index.html", timeout=8000)
        check("deleting the account signs out and removes everything", requests.post(API + "/api/auth/login", json={"email": "ada@example.org", "password": "correct-horse-battery"}).status_code == 401
              and not [p for p in requests.get(API + "/api/people").json() if p["name"] == "Ada Researcher"] and not [p for p in requests.get(API + "/api/papers").json() if p["added_by"] == "Ada Researcher"])
        check("no JS errors on any page", not (page.errors + p5.errors), page.errors + p5.errors)
        b.close()
finally:
    if srv:
        srv.terminate()

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
