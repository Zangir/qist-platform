"""Whole-site sweep: every page, three languages, three widths.
Checks per page: no JS errors, no failed same-site requests, no raw translation keys on screen, no horizontal scroll,
every internal link and image resolves. Also the member tools against the REAL ORCID and Crossref services (no mocks).
    backend/.venv/bin/python pipeline/tests/e2e_site_sweep.py https://zangir.github.io/qist-platform [outdir]"""
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from playwright.sync_api import sync_playwright

BASE = sys.argv[1].rstrip("/")
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else None
PAGES = ["index", "opportunities", "directory", "map", "organizations", "about", "channels", "newsletter", "matching", "join", "login",
         "post-position", "claim", "curate", "feed"]
RAW = re.compile(r"\b(?:nav|opp2?|feed|pf|post|prof|join|hero|stat|home|common|match|elig|login|org|dir|board|foot|top|globe|region|about|cur|news|chan|m)\.[a-z0-9_]+(?:\.[a-z0-9_]+)*\b")
results, links_seen = [], set()


def check(name, cond, detail=""):
    results.append(bool(cond))
    if not cond or "-v" in sys.argv:
        print(("  ok   " if cond else "  FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


with sync_playwright() as pw:
    b = pw.chromium.launch()
    for lang in ("en", "ru", "kk"):
        for width in (1440, 768, 390):
            ctx = b.new_context(viewport={"width": width, "height": 900})
            for name in PAGES:
                page = ctx.new_page(); errs, bad, warns = [], [], []
                page.on("pageerror", lambda e: errs.append(str(e)))
                page.on("console", lambda m: warns.append(m.text) if "[i18n]" in m.text else (errs.append(m.text) if m.type == "error" and not any(x in m.text for x in ("favicon", "fonts.g", "ERR_", "Failed to load resource")) else None))
                page.on("response", lambda r: bad.append((r.status, r.url)) if r.status >= 400 and r.url.startswith(BASE) else None)
                page.goto(f"{BASE}/{name}.html?lang={lang}"); page.wait_for_timeout(1300)
                tag = f"{name}.html {lang} {width}px"
                body = page.inner_text("body")
                check(f"{tag}: no JS errors", not errs, errs[:2])
                check(f"{tag}: no failed requests", not bad, bad[:2])
                check(f"{tag}: no raw keys / i18n warnings", not RAW.findall(body) and not warns, (RAW.findall(body)[:3], warns[:2]))
                check(f"{tag}: no horizontal scroll", page.evaluate("document.documentElement.scrollWidth") <= page.evaluate("document.documentElement.clientWidth") + 1)
                check(f"{tag}: page has content", len(body.strip()) > 150, len(body))
                if lang == "en" and width == 1440:
                    for h in page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))"):
                        u = urljoin(f"{BASE}/{name}.html", h.split("#")[0])
                        if u.startswith(BASE) and not h.startswith(("mailto:", "javascript:")):
                            links_seen.add((name, u))
                    bad_img = page.evaluate("[...document.images].filter(i => i.complete && i.naturalWidth === 0 && i.src.startsWith('%s')).map(i => i.src)" % BASE)
                    check(f"{tag}: images load", not bad_img, bad_img)
                    if OUT and name in ("index", "opportunities", "join", "post-position", "directory", "map"):
                        page.screenshot(path=str(OUT / f"sweep_{name}.png"), full_page=True)
                page.close()
            ctx.close()
    # every internal link, once
    for src, u in sorted(links_seen, key=lambda x: x[1]):
        ok = requests.get(u, timeout=20).status_code == 200
        check(f"link from {src}: {u.replace(BASE, '')} resolves", ok)

    # the member tools against the real services
    ctx = b.new_context(viewport={"width": 1440, "height": 900}); page = ctx.new_page(); errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(f"{BASE}/join.html"); page.wait_for_selector("#pf-orcid")
    page.fill("#pf-orcid", "0000-0002-1825-0097"); page.click("#pf-orcid-go")
    page.wait_for_function("document.querySelector('#pf-orcid-msg').textContent.length > 12 && !document.querySelector('#pf-orcid-msg').textContent.includes('Reading')", timeout=30000)
    msg = page.inner_text("#pf-orcid-msg")
    check("LIVE ORCID: the public demo record is fetched and fills the form", "Filled" in msg and page.input_value("#pf-name") == "Josiah Carberry" and page.input_value("#pf-inst") == "Wesleyan University", msg)
    check("LIVE ORCID: its works become papers", page.locator("#pf-papers li:not(.empty)").count() >= 2)
    page.fill("#pf-doi", "10.1038/nature12373"); page.click("#pf-doi-go")
    page.wait_for_function("!document.querySelector('#pf-pap-msg').textContent.includes('Looking') && document.querySelector('#pf-pap-msg').textContent.length > 3", timeout=30000)
    check("LIVE Crossref: a real DOI is looked up and added", "Nanometre-scale thermometry" in page.inner_text("#pf-papers"), page.inner_text("#pf-pap-msg"))
    check("LIVE tools: no JS errors", not errs, errs)
    ctx.close()
    b.close()

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
