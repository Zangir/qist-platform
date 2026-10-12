"""Signed-in behaviour of the feed against a real FastAPI backend (temp database).
    backend/.venv/bin/python pipeline/tests/e2e_feed_backend.py http://localhost:8099
Starts uvicorn on :8100 itself. Needs the static server on the given base URL."""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8099").rstrip("/")
API = "http://localhost:8100"
ROOT = Path(__file__).resolve().parents[2]
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("  ok   " if cond else "  FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


env = dict(os.environ, QIST_DB_URL="sqlite:///" + os.path.join(tempfile.mkdtemp(), "e2e.db"), QIST_JWT_SECRET="e2e-secret-e2e-secret-e2e-secret-1234")
srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app.main:main_app", "--port", "8100", "--log-level", "warning"], cwd=ROOT, env=env)
try:
    for _ in range(50):
        try:
            if requests.get(API + "/api/health", timeout=1).ok:
                break
        except Exception:
            time.sleep(0.2)
    else:
        raise SystemExit("backend did not start")

    reg = requests.post(API + "/api/auth/register", json={"email": "reader@example.org", "name": "Ada Reader", "password": "correct-horse-battery"}).json()
    hdr = {"Authorization": "Bearer " + reg["token"]}
    server_profile = {"stage": "pi_only", "country": "KZ", "fields": ["Astronomy, Space Science"], "keywords": ["exoplanet"], "jobCountries": [], "remote": True, "allStages": False}
    check("server accepts a profile", requests.put(API + "/api/me/feed-profile", json={"profile": server_profile}, headers=hdr).ok)

    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_init_script("localStorage.setItem('qist_api_url', %s); localStorage.setItem('qist_session', %s)" % (json.dumps(API), json.dumps(json.dumps(reg))))
        page = ctx.new_page(); errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{BASE}/feed.html"); page.wait_for_selector("#tabs button")
        line = page.inner_text("#pf-line")
        check("signed in: the account's profile is loaded, not an empty local one", "Professor" in line and "Astronomy" in line and "exoplanet" in line, line)
        check("…and a signed-in first visit does not force the form open", page.locator("#pf-form").is_hidden())
        local = json.loads(page.evaluate("localStorage.getItem('qist_feed_profile')"))
        check("…and is cached in the browser", local["fields"] == ["Astronomy, Space Science"])
        arts = page.evaluate("""async () => { const d = await (await fetch('data/feeds/articles.json')).json(); const F = QIST.feed;
            return F.rank(d.items, F.loadProfile(), {now: Date.now()}).slice(0, 15).map(r => r.item.fields.concat([r.item.title])); }""")
        check("ranking follows the account profile", sum(1 for a in arts if "Astronomy, Space Science" in a or "exoplanet" in " ".join(a).lower()) >= 13, arts[:3])

        # edit and save: goes to the server
        page.click("#pf-toggle")
        check("form says it is stored on the account", "account" in page.inner_text("#pf-where"))
        page.fill("#pf-kw", "gravitational waves")
        page.click('#pf-form button[type="submit"]'); page.wait_for_function("document.querySelector('#pf-form').hidden", timeout=5000)
        got = requests.get(API + "/api/me/feed-profile", headers=hdr).json()["profile"]
        check("saving writes the profile to the server", got["keywords"] == ["gravitational waves"] and got["stage"] == "pi_only", got)

        # a different browser (fresh storage) sees the same profile after signing in
        ctx2 = b.new_context(viewport={"width": 1440, "height": 900})
        ctx2.add_init_script("localStorage.setItem('qist_api_url', %s); localStorage.setItem('qist_session', %s)" % (json.dumps(API), json.dumps(json.dumps(reg))))
        p2 = ctx2.new_page(); p2.goto(f"{BASE}/feed.html"); p2.wait_for_selector("#tabs button")
        check("second device gets the same profile", "gravitational waves" in p2.inner_text("#pf-line"), p2.inner_text("#pf-line"))

        # profile page: Today for you
        p2.goto(f"{BASE}/profile.html"); p2.wait_for_selector("#today-body .t-row", timeout=10000)
        rows = p2.locator("#today-body .t-row").count()
        check("profile page shows today's matches", rows >= 3, rows)
        check("…each linking out in a new tab", p2.locator("#today-body .t-row a").first.get_attribute("target") == "_blank")
        check("…and the full-feed link works", p2.locator("#today-card a.btn").get_attribute("href") == "feed.html")

        # a stale token must not break the page: falls back to local profile
        ctx3 = b.new_context(); ctx3.add_init_script("localStorage.setItem('qist_api_url', %s); localStorage.setItem('qist_session', %s); localStorage.setItem('qist_feed_profile', %s)" % (
            json.dumps(API), json.dumps(json.dumps(dict(reg, token="garbage"))), json.dumps(json.dumps(dict(server_profile, fields=["Neuroscience"], keywords=[])))))
        p3 = ctx3.new_page(); e3 = []; p3.on("pageerror", lambda e: e3.append(str(e)))
        p3.goto(f"{BASE}/feed.html"); p3.wait_for_selector("#tabs button")
        check("invalid token: page still works from the local profile", "Neuroscience" in p3.inner_text("#pf-line") and not e3, e3)
        check("no JS errors signed in", not errors, errors)
        b.close()
finally:
    srv.terminate()

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
