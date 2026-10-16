"""Daily feed builder.  python -m pipeline.run [--kinds articles,grants,jobs] [--out data/feeds] [--quick]

Fetches every source independently (one failing source never loses the others), normalises each record into the
shape the browser expects, merges with yesterday's file so first_seen survives, drops what has expired and writes
data/feeds/{articles,grants,jobs}.json plus meta.json with per-source health."""
import argparse
import json
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from . import common, geo, taxonomy
from .sources import articles as S_art, grants as S_gr, jobs as S_job

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "feeds"

CAPS = {"articles": 3000, "grants": 700, "jobs": 1800}
KEEP_DAYS = {"articles": 21, "grants": 45, "jobs": 30}


def _sources(quick=False):
    qa = {"cats": ["cs.LG", "q-bio.NC", "cond-mat.mtrl-sci"], "per_cat": 15} if quick else {}
    qj = {"queries": ["postdoctoral", "phd"], "pages": 1} if quick else {}
    return {
        "articles": [
            ("arxiv", lambda: S_art.arxiv(**qa)),
            ("biorxiv+medrxiv", lambda: S_art.biorxiv(max_pages=1 if quick else 8)),
            ("crossref-journals", lambda: S_art.crossref_journals(**({"journals": S_art.JOURNALS[:6]} if quick else {}))),
        ],
        "grants": [
            ("ukri", lambda: S_gr.ukri(enrich=3 if quick else 30)), ("nsf", S_gr.nsf), ("grants.gov", S_gr.grantsgov),
            ("eu-funding-tenders", S_gr.sedia), ("fundsforngos", S_gr.fundsforngos),
        ],
        "jobs": [
            ("jobs.ac.uk", lambda: S_job.jobsac(**({"disciplines": {"computer-sciences": "Computer Science", "biological-sciences": "Biology and Life Sciences"}, "phd_pages": 1, "pages": 1} if quick else {}))), ("nature-careers", lambda: S_job.nature_careers(**qj)),
            ("insidehighered", lambda: S_job.inside_higher_ed(**qj)),
        ],
    }


# ---------- normalisation ----------
def strip_abstract_label(s):
    """Crossref's JATS abstracts start with their own heading ("Abstract", "Summary")."""
    return re.sub(r"^(abstract|summary)\s*[:.\-–—]?\s+", "", s or "", flags=re.I)


def not_future(d):
    """Journals schedule issue dates ahead of today; a paper cannot have been posted tomorrow."""
    return min(d, common.today()) if d else d


def norm_article(r, first_seen):
    authors = [a for a in r.get("authors", []) if a]
    f = S_art.finish(dict(r))["fields"]
    return {
        "id": common.item_id("article", r.get("doi") or r["url"]), "kind": "article", "source": r["source"],
        "title": r["title"], "url": r["url"], "summary": strip_abstract_label(common.clean(r.get("summary"), 340)),
        "authors": authors[:6] + (["et al."] if len(authors) > 6 else []), "venue": r.get("venue"), "doi": r.get("doi"),
        "preprint": bool(r.get("preprint")), "tier": r.get("tier", 0), "posted": common.iso(not_future(r.get("posted"))),
        "fields": f, "tags": r.get("tags", [])[:3], "first_seen": common.iso(first_seen),
    }


def norm_grant(r, first_seen):
    title, summ = r["title"], r.get("summary", "")
    f = taxonomy.classify_fields(title, summ + " " + (r.get("org") or ""), r.get("prior"))
    return {
        "id": common.item_id("grant", r["url"]), "kind": "grant", "source": r["source"], "title": title, "url": r["url"],
        "org": r.get("org") or "", "summary": common.clean(summ, 380), "deadline": common.iso(r.get("deadline")),
        "posted": common.iso(not_future(r.get("posted"))), "status": r.get("status") or "open", "origin": r.get("origin"),
        "amount": r.get("amount"), "stages": taxonomy.grant_stages(title, summ), "fields": f,
        "first_seen": common.iso(first_seen),
    }


def job_stages(title, summ, hint):
    """Stage from the title; the board's own section (jobs.ac.uk /phds) settles it when the title is vague."""
    st = taxonomy.detect_stages(title, summ)
    if hint and st in ([], ["researcher"]):
        return [hint]
    return st or ["researcher"]


def norm_job(r, first_seen):
    title, summ = r["title"], r.get("summary", "")
    if not (r.get("hint_stage") and not taxonomy.NOT_RESEARCH.search(title)) and not taxonomy.is_research_role(title, summ):
        return None
    loc = r.get("location", "")
    countries = geo.find_countries(loc + " " + (r.get("org") or ""))
    if not countries and r.get("default_country") and (not loc or r["default_country"] == "US"):
        countries = [r["default_country"]]
    if not countries and r.get("default_country") == "GB":
        countries = ["GB"]  # jobs.ac.uk is overwhelmingly UK; international posts are caught by the gazetteer first
    f = taxonomy.classify_fields(title + " . " + (r.get("department") or ""), summ, r.get("prior"), body_w=2)
    return {
        "id": common.item_id("job", r["url"]), "kind": "job", "source": r["source"], "title": title, "url": r["url"],
        "org": r.get("org") or "", "department": r.get("department") or "", "location": loc, "countries": countries,
        "remote": geo.is_remote(loc + " " + title), "salary": r.get("salary") or "", "summary": common.clean(summ, 380),
        "posted": common.iso(not_future(r.get("posted")) or first_seen), "deadline": common.iso(r.get("deadline")),
        "stages": job_stages(title, summ, r.get("hint_stage")), "fields": f, "first_seen": common.iso(first_seen),
    }


ID_KIND = {"articles": "article", "grants": "grant", "jobs": "job"}
NORMALISE = {"articles": norm_article, "grants": norm_grant, "jobs": norm_job}


def load_previous(path):
    try:
        return {i["id"]: i for i in json.loads(Path(path).read_text(encoding="utf8"))["items"]}
    except Exception:
        return {}


def keep(item, kind, today):
    d = item.get("deadline")
    if d and d < common.iso(today):
        return False
    horizon = common.iso(today - timedelta(days=KEEP_DAYS[kind]))
    return (item.get("posted") or item.get("first_seen") or "9999") >= horizon


def build(kind, sources, prev, today, meta):
    fresh = {}
    for name, fn in sources:
        t0 = time.time()
        rec = {"ok": True, "count": 0, "kept": 0, "error": None}
        try:
            res = fn()
            failures = []
            if isinstance(res, tuple):
                res, failures = res
            raws = res
            rec["count"] = len(raws)
            if failures:
                rec["partial_failures"] = failures[:10]
            for r in raws:
                try:
                    old = prev.get(common.item_id(ID_KIND[kind], (r.get("doi") if kind == "articles" else None) or r["url"]))
                    seen = date.fromisoformat(old["first_seen"]) if old and old.get("first_seen") else today
                    it = NORMALISE[kind](r, seen)
                except Exception as e:  # a single malformed record is skipped, counted and reported
                    rec["skipped"] = rec.get("skipped", 0) + 1
                    rec["last_skip"] = repr(e)[:160]
                    continue
                if it:
                    it["last_seen"] = common.iso(today)
                    fresh[it["id"]] = it
                    rec["kept"] += 1
        except Exception as e:
            rec.update(ok=False, error=repr(e)[:300])
        rec["seconds"] = round(time.time() - t0, 1)
        meta["sources"][name] = rec
        print(f"[{kind}] {name}: " + (f"{rec['kept']}/{rec['count']} kept" if rec["ok"] else "FAILED " + rec["error"]), file=sys.stderr)
    merged = dict(fresh)
    # carry over yesterday's items that are still valid. A source that failed today must not empty the feed.
    for i, it in prev.items():
        if i not in merged and keep(it, kind, today) and (it.get("last_seen") or "") >= common.iso(today - timedelta(days=KEEP_DAYS[kind] if kind != "jobs" else 10)):
            merged[i] = it
    items = [i for i in merged.values() if keep(i, kind, today)]
    items.sort(key=lambda i: ((i.get("posted") or i["first_seen"]), i.get("tier", 0)), reverse=True)
    if kind == "articles":
        # preprints are ~85% of the volume and would crowd journal papers out of a recency-ordered cap
        journals = [i for i in items if i.get("tier", 0) > 0]
        preprints = [i for i in items if not i.get("tier", 0)]
        items = journals[:CAPS[kind] // 3] + preprints[:CAPS[kind] - min(len(journals), CAPS[kind] // 3)]
        items.sort(key=lambda i: ((i.get("posted") or i["first_seen"]), i.get("tier", 0)), reverse=True)
        return items
    return items[:CAPS[kind]]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--kinds", default="grants,jobs",
                    help="articles is still supported (--kinds grants,jobs,articles) but is off by default: the site shows members' papers instead (D-65)")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--quick", action="store_true", help="small fetch, for a smoke test")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    today = common.today()
    srcs = _sources(a.quick)
    meta_path = out / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf8"))
    except Exception:
        meta = {}
    meta["generated_at"] = common.now_iso()
    meta.setdefault("kinds", {})
    for kind in a.kinds.split(","):
        km = {"sources": {}}
        prev = load_previous(out / f"{kind}.json")
        items = build(kind, srcs[kind], prev, today, km)
        km["total"] = len(items)
        km["new_today"] = sum(1 for i in items if i["first_seen"] == common.iso(today))
        km["updated"] = common.iso(today)
        meta["kinds"][kind] = km
        (out / f"{kind}.json").write_text(json.dumps({"updated": common.iso(today), "kind": kind[:-1], "items": items},
                                                      ensure_ascii=False, separators=(",", ":")), encoding="utf8")
        print(f"[{kind}] wrote {len(items)} items ({km['new_today']} new)", file=sys.stderr)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf8")
    failed = [f"{k}/{n}" for k, v in meta["kinds"].items() for n, s in v["sources"].items() if not s["ok"]]
    if failed:
        print("FAILED SOURCES: " + ", ".join(failed), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
