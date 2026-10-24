"""Invited members: the admin imports a spreadsheet, sends personal links, each person claims their profile.
    backend/.venv/bin/python pipeline/tests/e2e_claims.py http://localhost:8099 [api-url]
With no api-url it starts uvicorn on :8100 itself. Every person in the workbook is invented."""
import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from openpyxl import Workbook
from playwright.sync_api import sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8099").rstrip("/")
API = sys.argv[2].rstrip("/") if len(sys.argv) > 2 else "http://localhost:8100"
ADMIN_PW = os.environ.get("E2E_ADMIN_PASSWORD", "admin-e2e-password")
ROOT = Path(__file__).resolve().parents[2]
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("  ok   " if cond else "  FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


def xlsx():
    wb = Workbook(); ws = wb.active; ws.title = "list of (non)members"
    ws.append(["Name Surname", "Primary Field", "Keywords", "Statement", "Country Work", "Institution", "Position", "Email"])
    ws.append(["Aigerim Bekova", "Materials Science", "perovskite solar cells; thin films", "PRIVATE-NOTE-1", "Kazakhstan", "Nazarbayev University", "PhD student", "aigerim.e2e@example.org"])
    ws.append(["Dias Omarov", "Neuroscience", "hippocampus", "", "Germany", "Charite Berlin", "Postdoc", "dias.e2e@example.org"])
    ws.append(["Nomail Person", "Economics", "", "", "Turkey", "Koc University", "Professor", ""])
    ws.append(["Mira Sadykova", "Public health", "maternal health", "", "Kyrgyzstan", "AUCA", "Lecturer", "mira.e2e@example.org"])
    ws2 = wb.create_sheet("attendees"); ws2.append(["Name", "Surname", "Email", "Hobbies & Interests"]); ws2.append(["Dias", "Omarov", "dias.e2e@example.org", "PRIVATE-HOBBY"])
    buf = io.BytesIO(); wb.save(buf)
    return buf.getvalue()


srv = None
if len(sys.argv) <= 2:
    env = dict(os.environ, QIST_DB_URL="sqlite:///" + os.path.join(tempfile.mkdtemp(), "e2e.db"), QIST_JWT_SECRET="e2e-secret-e2e-secret-e2e-secret-1234", QIST_ADMIN_PASSWORD=ADMIN_PW)
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app.main:main_app", "--port", "8100", "--log-level", "warning"], cwd=ROOT, env=env)
try:
    for _ in range(60):
        try:
            if requests.get(API + "/api/health", timeout=3).ok:
                break
        except Exception:
            time.sleep(0.5)
    else:
        raise SystemExit("backend did not start")

    admin_session = requests.post(API + "/api/auth/login", json={"email": "admin@qist.kz", "password": ADMIN_PW}).json()
    existing = [m for m in requests.get(API + "/api/admin/members", headers={"Authorization": "Bearer " + admin_session["token"]}).json() if m["role"] != "admin"]
    if existing and not os.environ.get("E2E_ALLOW_NONEMPTY"):
        raise SystemExit(f"Refusing to run: the server already holds {len(existing)} member account(s). This test creates and deletes accounts "
                         "and expects an empty server (a fresh or throwaway one). Set E2E_ALLOW_NONEMPTY=1 only if you are sure.")

    def new_ctx(b, session=None, width=1440):
        ctx = b.new_context(viewport={"width": width, "height": 900}, accept_downloads=True)
        ctx.add_init_script("localStorage.setItem('qist_api_url', %s); %s" % (json.dumps(API), f"localStorage.setItem('qist_session', {json.dumps(json.dumps(session))});" if session else ""))
        page = ctx.new_page(); page.errors = []
        page.on("pageerror", lambda e: page.errors.append(str(e)))
        page.on("dialog", lambda d: d.accept())
        return ctx, page

    with sync_playwright() as pw:
        b = pw.chromium.launch()
        tmp = Path(tempfile.mkdtemp()); (tmp / "members.xlsx").write_bytes(xlsx())

        print("\nAdmin: import a spreadsheet")
        ctx, page = new_ctx(b, admin_session)
        page.goto(f"{BASE}/admin.html"); page.wait_for_selector("#tab-people table", state="attached", timeout=60000); page.click('button[data-tab="invites"]')
        page.wait_for_selector("#inv-file")
        check("the Invitations tab explains that links are shown once and unclaimed accounts are hidden", "once" in page.inner_text("#tab-invites") and "not public" in page.inner_text("#tab-invites"))
        page.click("#inv-preview")
        check("preview without a file asks for one", page.locator("#inv-report table").count() == 0)
        page.set_input_files("#inv-file", str(tmp / "members.xlsx")); page.fill("#inv-site", BASE); page.click("#inv-preview")
        page.wait_for_selector("#inv-report table")
        page.click("#inv-report summary")
        rep = page.inner_text("#inv-report")
        check("the preview counts rows, people, merges and lists the person with no e-mail", "People who will get an account" in rep and "No e-mail address" in rep and "Nomail Person" in rep and "Same person on several rows" in rep, rep[:300])
        check("…showing a sample of who will be created", "aigerim.e2e@example.org" in rep)
        check("a preview creates nothing", not [m for m in requests.get(API + "/api/admin/members", headers={"Authorization": "Bearer " + admin_session["token"]}).json() if m["status"] == "unclaimed"])
        with page.expect_download() as dl:
            page.click("#inv-commit")
        links_csv = Path(dl.value.path()).read_text()
        rows = list(csv.DictReader(io.StringIO(links_csv)))
        links = {r["email"]: r["claim_link"] for r in rows}
        check("the accounts are created and a links file is downloaded", set(links) == {"aigerim.e2e@example.org", "dias.e2e@example.org", "mira.e2e@example.org"} and all(l.startswith(BASE + "/claim.html?t=") for l in links.values()), links_csv[:200])
        check("the notes and hobbies columns were never imported", "PRIVATE" not in json.dumps(requests.get(API + "/api/admin/members", headers={"Authorization": "Bearer " + admin_session["token"]}).json()))
        page.click('button[data-tab="members"]'); page.wait_for_selector("#mem-body tr")
        page.select_option("#mem-status", "unclaimed")
        check("the Members tab filters by status and shows the three as unclaimed", page.locator("#mem-body tr").count() == 3 and "unclaimed" in page.inner_text("#mem-body"))
        pub = requests.get(API + "/api/people").json()
        check("unclaimed people are not in the public directory", not [p for p in pub if "e2e" in json.dumps(p) or p["name"] in ("Aigerim Bekova", "Dias Omarov", "Mira Sadykova")])
        check("no JS errors in the admin page", not page.errors, page.errors)
        ctx.close()

        print("\nA member opens their personal link")
        ctx, page = new_ctx(b)
        page.goto(links["aigerim.e2e@example.org"]); page.wait_for_selector("#pf-name", timeout=15000)
        check("the page greets them by first name and shows what was prepared", "Aigerim" in page.inner_text("#h1") and page.input_value("#pf-name") == "Aigerim Bekova" and page.input_value("#pf-inst") == "Nazarbayev University" and page.input_value("#pf-title") == "PhD student")
        check("country, fields and keywords are pre-filled", page.input_value("#pf-country") == "KZ" and page.locator('#pf-fields button[aria-pressed="true"]').count() == 1 and "perovskite solar cells" in page.inner_text("#pf-kw-chips"))
        check("the e-mail is shown and cannot be changed", page.input_value("#pf-email") == "aigerim.e2e@example.org" and page.is_disabled("#pf-email"))
        check("the personal link is removed from the address bar", "t=" not in page.url and "claim.html" in page.url, page.url)
        check("the page says when the link expires, is not indexed and sends no referrer", "until" in page.inner_text("#expires") and page.get_attribute('meta[name=robots]', "content") == "noindex" and page.get_attribute('meta[name=referrer]', "content") == "no-referrer")
        check("listing in the directory is NOT pre-ticked (opt-in)", not page.is_checked("#pf-listed"))
        check("terms are not pre-ticked either", not page.is_checked("#pf-terms"))
        page.fill("#pf-password", "short"); page.click("#pf-submit")
        check("a short password is refused", page.evaluate("document.activeElement.id") == "pf-password")
        page.fill("#pf-password", "correct-horse-battery"); page.click("#pf-submit")
        check("the terms must be accepted", page.evaluate("document.activeElement.id") == "pf-terms")
        page.fill("#pf-city", "Astana"); page.check("#pf-terms")
        page.click("#pf-submit"); page.wait_for_url("**/profile.html**", timeout=10000)
        page.wait_for_selector("#pf-name")
        check("accepting signs them in and opens their profile", "Aigerim Bekova" in page.inner_text("#me-sub") and page.input_value("#pf-city") == "Astana")
        pub = requests.get(API + "/api/people").json()
        check("still hidden from the directory because they did not tick the box", not [p for p in pub if p["name"] == "Aigerim Bekova"])
        page.check("#pf-listed"); page.click("#pf-submit"); page.wait_for_function("document.querySelector('#pf-state').textContent.includes('Saved')", timeout=6000)
        check("ticking it later lists them, with the details that were prepared", [p for p in requests.get(API + "/api/people").json() if p["name"] == "Aigerim Bekova" and p["country"] == "Kazakhstan" and p["institution"] == "Nazarbayev University"])
        check("their e-mail is nowhere in public data", "aigerim.e2e" not in json.dumps(requests.get(API + "/api/people").json()))
        ctx.close()

        print("\nAfter claiming")
        ctx, page = new_ctx(b)
        page.goto(links["aigerim.e2e@example.org"]); page.wait_for_selector("#state:not([hidden])", timeout=10000)
        check("the link cannot be used a second time (same message as a wrong link)", "not valid any more" in page.inner_text("#state") and page.locator("#pf-name").count() == 0 or page.locator("#form-root").is_hidden())
        ctx.close()
        ctx, page = new_ctx(b)
        page.goto(f"{BASE}/claim.html?t=" + "x" * 43); page.wait_for_selector("#state:not([hidden])", timeout=10000)
        check("a wrong link gets the same message and an offer to create a profile", "not valid any more" in page.inner_text("#state") and page.locator("#state a[href='join.html']").count() == 1)
        page.goto(f"{BASE}/claim.html"); page.wait_for_selector("#state:not([hidden])", timeout=10000)
        check("no link at all: the same message, no error", "not valid any more" in page.inner_text("#state") and not page.errors)
        page.goto(f"{BASE}/login.html"); page.wait_for_selector("body[data-ready]")
        page.fill("#l-email", "aigerim.e2e@example.org"); page.fill("#l-password", "correct-horse-battery"); page.click("#login-form button")
        page.wait_for_url("**/profile.html", timeout=8000)
        check("they sign in later with e-mail and password", page.url.endswith("/profile.html") and "Aigerim" in page.inner_text("#me-sub") if page.wait_for_selector("#me-sub") else False)
        ctx.close()
        ctx, page = new_ctx(b)
        page.goto(f"{BASE}/login.html"); page.wait_for_selector("body[data-ready]")
        page.fill("#l-email", "dias.e2e@example.org"); page.fill("#l-password", "anything-at-all"); page.click("#login-form button"); page.wait_for_selector(".alert-error")
        check("an unclaimed person cannot sign in or guess their way in", "login" in page.url)
        page.goto(f"{BASE}/join.html"); page.wait_for_selector("#pf-password")
        page.fill("#pf-name", "Somebody Else"); page.fill("#pf-email", "dias.e2e@example.org"); page.fill("#pf-password", "correct-horse-battery"); page.click("#pf-submit")
        page.wait_for_function("document.querySelector('#pf-state').textContent.length > 5", timeout=6000)
        check("nobody can take an invited address by signing up with it", "already exists" in page.inner_text("#pf-state").lower(), page.inner_text("#pf-state"))
        page.goto(f"{BASE}/join.html"); page.wait_for_selector("#lede"); page.wait_for_timeout(400)
        on_join = "personal link" in page.inner_text(".page-top")
        page.goto(f"{BASE}/login.html"); page.wait_for_selector("body[data-ready]")
        check("the invitation is mentioned on the sign-up and sign-in pages", on_join and "personal link" in page.inner_text(".auth-card"))
        ctx.close()

        print("\nDecline")
        ctx, page = new_ctx(b)
        page.goto(links["mira.e2e@example.org"]); page.wait_for_selector("#decline", timeout=15000)
        page.click("#decline"); page.wait_for_selector("#state:not([hidden])")
        check("'delete this record' confirms the deletion", "deleted" in page.inner_text("#state").lower() or "no longer hold" in page.inner_text("#state"))
        members = requests.get(API + "/api/admin/members", headers={"Authorization": "Bearer " + admin_session["token"]}).json()
        check("the record is gone from the database", not [m for m in members if m["email"] == "mira.e2e@example.org"])
        ctx.close()
        ctx, page = new_ctx(b, admin_session)
        page.goto(f"{BASE}/admin.html"); page.wait_for_selector("#tab-people table", state="attached", timeout=60000); page.click('button[data-tab="invites"]'); page.wait_for_selector("#inv-file")
        page.set_input_files("#inv-file", str(tmp / "members.xlsx")); page.click("#inv-preview"); page.wait_for_selector("#inv-report table")
        check("a later import skips the person who asked to be removed and those who already have accounts", "Asked to be removed earlier" in page.inner_text("#inv-report") and "1" in page.inner_text("#inv-report"))

        print("\nNew links and clean-up")
        page.click('button[data-tab="invites"]')
        page.fill("#inv-emails", "dias.e2e@example.org")
        with page.expect_download() as dl:
            page.click("#inv-regen")
        new = {r["email"]: r["claim_link"] for r in csv.DictReader(io.StringIO(Path(dl.value.path()).read_text()))}
        check("new links can be issued for chosen addresses", list(new) == ["dias.e2e@example.org"] and new["dias.e2e@example.org"] != links["dias.e2e@example.org"])
        check("the old link stopped working and the new one works", requests.get(API + "/api/claim/" + parse_qs(urlparse(links["dias.e2e@example.org"]).query)["t"][0]).status_code == 404
              and requests.get(API + "/api/claim/" + parse_qs(urlparse(new["dias.e2e@example.org"]).query)["t"][0]).status_code == 200)
        page.fill("#inv-days", "1"); page.click("#inv-del"); page.wait_for_function("document.querySelector('#inv-state2').textContent.includes('deleted')", timeout=6000)
        check("clean-up leaves recent accounts alone", "0 deleted" in page.inner_text("#inv-state2"))
        check("no JS errors in the admin page", not page.errors, page.errors)
        ctx.close()

        print("\nLanguages, layout and no backend")
        for lang in ("ru", "kk"):
            ctx, page = new_ctx(b)
            page.goto(f"{BASE}/claim.html?lang={lang}&t=" + "x" * 43); page.wait_for_selector("#state:not([hidden])", timeout=10000)
            body = page.inner_text("body")
            check(f"{lang}: the message is translated, no raw keys", "claim." not in body and "not valid any more" not in body and not page.errors, page.errors)
            ctx.close()
        ctx = b.new_context(viewport={"width": 390, "height": 900}); ctx.add_init_script("localStorage.setItem('qist_api_url', 'off')"); page = ctx.new_page(); page.errors = []
        page.on("pageerror", lambda e: page.errors.append(str(e)))
        page.goto(f"{BASE}/claim.html?t=abc"); page.wait_for_selector("#state:not([hidden])", timeout=10000)
        check("with no backend the page says accounts are not on yet; no errors", "not switched on" in page.inner_text("#state") and not page.errors)
        check("390px: no horizontal scroll", page.evaluate("document.documentElement.scrollWidth") <= page.evaluate("document.documentElement.clientWidth") + 1)
        ctx.close()
        b.close()
finally:
    if srv:
        srv.terminate()

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
