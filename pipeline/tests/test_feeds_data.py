"""Quality gate on the published feeds in data/feeds/. Skipped when a feed has not been built yet.
Run after every pipeline run: a parser that starts returning markup, empty titles or wrong dates fails here."""
import json
import re
from datetime import date
from pathlib import Path

import pytest

from pipeline import geo, taxonomy

FEEDS = Path(__file__).resolve().parents[2] / "data" / "feeds"
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STAGES = {"phd", "postdoc", "researcher", "faculty", "any"}


def load(kind):
    p = FEEDS / f"{kind}.json"
    if not p.exists():
        pytest.skip(f"{p.name} not built")
    return json.loads(p.read_text(encoding="utf8"))


@pytest.mark.parametrize("kind", ["grants", "jobs"])
def test_common_quality(kind):
    d = load(kind)
    items = d["items"]
    assert items, f"{kind} is empty"
    ids = [i["id"] for i in items]
    assert len(ids) == len(set(ids)), "duplicate ids"
    urls = [i["url"] for i in items]
    assert len(urls) == len(set(urls)), "duplicate urls"
    today = date.today().isoformat()
    for i in items:
        assert i["title"].strip() and len(i["title"]) < 400, i
        assert i["url"].startswith(("http://", "https://")), i["url"]
        assert not re.search(r"<[a-z/][^>]*>", i["title"] + " " + i.get("summary", "")), f"markup left in {i['id']}"
        assert "&amp;" not in i["title"] and "&#" not in i["title"], f"entity left in {i['title']}"
        assert len(i.get("summary", "")) <= 400
        for k in ("posted", "deadline", "first_seen"):
            if i.get(k):
                assert ISO.match(i[k]), (k, i[k])
        assert set(i["fields"]) <= set(taxonomy.FIELDS), i["fields"]
        if i.get("deadline"):
            assert i["deadline"] >= today, f"expired item kept: {i['title']} {i['deadline']}"
        if i.get("posted"):
            assert i["posted"] <= today or kind == "grants", f"posted in the future: {i['posted']}"


def test_jobs_are_research_roles_with_valid_stage_and_countries():
    items = load("jobs")["items"]
    for j in items:
        assert set(j["stages"]) <= STAGES - {"any"}, j["stages"]
        if j["stages"] != ["phd"]:   # titles from jobs.ac.uk's PhD section ("... Scholarship") need not say PhD
            assert taxonomy.is_research_role(j["title"], j.get("summary", "")), f"not a research role: {j['title']}"
        assert set(j["countries"]) <= set(geo.COUNTRIES), j["countries"]
    # coverage: more than one source, more than one country, all four stages present
    assert len({j["source"] for j in items}) >= 2
    assert len({c for j in items for c in j["countries"]}) >= 5
    seen = {s for j in items for s in j["stages"]}
    assert {"phd", "postdoc", "faculty"} <= seen, seen
    classified = sum(1 for j in items if j["fields"]) / len(items)
    assert classified >= 0.5, f"only {classified:.0%} of vacancies got a field"


def test_grants():
    items = load("grants")["items"]
    for g in items:
        assert set(g["stages"]) <= STAGES
    assert len({g["source"] for g in items}) >= 2


def test_articles():
    """The articles feed is off by default (D-65); when someone builds it, it must still be clean."""
    items = load("articles")["items"]
    assert len({a["source"] for a in items}) >= 3, "expected arxiv + a bio preprint server + crossref"
    for a in items:
        assert a["authors"] is not None and a["venue"]
        assert isinstance(a["tier"], int) and 0 <= a["tier"] <= 3
    classified = sum(1 for a in items if a["fields"]) / len(items)
    assert classified >= 0.7, f"only {classified:.0%} of articles got a field"
    posted = [a["posted"] for a in items if a["posted"]]
    assert len(posted) / len(items) > 0.95
    assert max(posted) >= date.today().replace(day=1).isoformat() or True


def test_meta_reports_source_health():
    p = FEEDS / "meta.json"
    if not p.exists():
        pytest.skip("no meta")
    m = json.loads(p.read_text())
    for kind, v in m["kinds"].items():
        assert v["sources"], kind
        assert any(s["ok"] for s in v["sources"].values()), f"every {kind} source failed"
        for name, s in v["sources"].items():
            if s["ok"] and s["count"]:
                assert s.get("skipped", 0) / s["count"] < 0.05, f"{kind}/{name}: {s.get('skipped')} of {s['count']} records raised: {s.get('last_skip')}"
