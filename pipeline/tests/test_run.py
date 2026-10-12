"""run.py: normalisation, failure isolation, retention."""
import json
from datetime import date, timedelta

from pipeline import common, run

TODAY = date(2026, 10, 12)
iso = common.iso


def job(url, title="Postdoctoral Research Associate in Astrophysics", **kw):
    r = {"title": title, "url": url, "org": "University of X", "department": "School of Physics", "location": "Cambridge, UK",
         "salary": "", "summary": "", "posted": TODAY, "deadline": TODAY + timedelta(days=30), "source": "t", "default_country": "GB"}
    r.update(kw)
    return r


def test_norm_job_shape_and_filter():
    j = run.norm_job(job("https://x/1"), TODAY)
    assert j["stages"] == ["postdoc"] and j["countries"] == ["GB"] and "Astronomy, Space Science" in j["fields"]
    assert j["id"].startswith("j") and j["first_seen"] == "2026-10-12"
    assert run.norm_job(job("https://x/2", title="Dining Hall Cook"), TODAY) is None


def test_norm_job_country_defaults():
    assert run.norm_job(job("u", location="Suzhou"), TODAY)["countries"] == ["CN"]
    assert run.norm_job(job("u", location="Nowhereville", default_country="GB"), TODAY)["countries"] == ["GB"]
    assert run.norm_job(job("u", location="Nowhereville", default_country=None), TODAY)["countries"] == []
    assert run.norm_job(job("u", location="Remote"), TODAY)["remote"] is True


def test_failure_isolation_and_meta():
    def boom():
        raise RuntimeError("blocked")
    meta = {"sources": {}}
    items = run.build("jobs", [("bad", boom), ("good", lambda: [job("https://x/1")])], {}, TODAY, meta)
    assert len(items) == 1 and meta["sources"]["bad"]["ok"] is False and "blocked" in meta["sources"]["bad"]["error"]
    assert meta["sources"]["good"]["ok"] and meta["sources"]["good"]["kept"] == 1


def test_malformed_record_is_skipped_not_fatal():
    meta = {"sources": {}}
    items = run.build("jobs", [("s", lambda: [{"url": "https://x/bad"}, job("https://x/ok")])], {}, TODAY, meta)
    assert len(items) == 1 and meta["sources"]["s"]["skipped"] == 1


def test_first_seen_survives_and_yesterdays_items_carry_over_when_source_fails():
    meta = {"sources": {}}
    first = run.build("jobs", [("s", lambda: [job("https://x/1")])], {}, TODAY - timedelta(days=3), meta)
    prev = {i["id"]: i for i in first}
    meta2 = {"sources": {}}
    again = run.build("jobs", [("s", lambda: [job("https://x/1")])], prev, TODAY, meta2)
    assert "skipped" not in meta2["sources"]["s"], meta2                      # a silent skip would also pass the next line
    assert again[0]["first_seen"] == iso(TODAY - timedelta(days=3))          # not reset to today
    assert again[0]["last_seen"] == iso(TODAY)                                # refreshed, so it was re-processed, not carried over
    meta3 = {"sources": {}}
    out = run.build("jobs", [("s", lambda: (_ for _ in ()).throw(RuntimeError("down")))], prev, TODAY, meta3)
    assert len(out) == 1                                                      # a failed source does not empty the feed


def test_expired_and_old_items_dropped():
    meta = {"sources": {}}
    expired = job("https://x/e", deadline=TODAY - timedelta(days=1))
    kept = run.build("jobs", [("s", lambda: [expired, job("https://x/ok")])], {}, TODAY, meta)
    assert [i["url"] for i in kept] == ["https://x/ok"]
    old_article = {"title": "Old", "url": "https://a/1", "source": "x", "posted": TODAY - timedelta(days=40), "summary": "quantum", "authors": []}
    assert run.build("articles", [("s", lambda: [old_article])], {}, TODAY, {"sources": {}}) == []


def test_article_normalisation_uses_prior_and_dedupes_on_doi():
    a = {"title": "Place cells", "url": "https://a/1", "doi": "10.1/x", "source": "biorxiv", "posted": TODAY, "summary": "", "authors": ["A"] * 9,
         "prior": {"Neuroscience": 4}, "venue": "biorxiv", "preprint": True, "tier": 0}
    out = run.build("articles", [("s", lambda: [a, dict(a, url="https://a/1v2")])], {}, TODAY, {"sources": {}})
    assert len(out) == 1 and out[0]["fields"] == ["Neuroscience"] and out[0]["authors"][-1] == "et al." and len(out[0]["authors"]) == 7


def test_main_writes_files(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "_sources", lambda quick=False: {"grants": [], "jobs": [("s", lambda: [job("https://x/1")])], "articles": []})
    assert run.main(["--out", str(tmp_path), "--kinds", "jobs,grants,articles"]) == 0
    d = json.loads((tmp_path / "jobs.json").read_text())
    assert d["kind"] == "job" and len(d["items"]) == 1
    meta = json.loads((tmp_path / "meta.json").read_text())
    assert meta["kinds"]["jobs"]["total"] == 1 and meta["kinds"]["jobs"]["new_today"] == 1


def test_future_dates_are_clamped():
    a = {"title": "Scheduled issue", "url": "https://a/f", "source": "crossref", "posted": TODAY + timedelta(days=20), "summary": "", "authors": [],
         "prior": {"Neuroscience": 4}, "venue": "J", "tier": 2}
    out = run.build("articles", [("s", lambda: [a])], {}, TODAY, {"sources": {}})
    assert out[0]["posted"] <= iso(common.today())


def test_phd_hint_survives_a_title_that_does_not_say_phd():
    j = run.norm_job(dict(job("https://x/h", title="Marie Curie Research Fellow (Doctoral Network)"), hint_stage="phd", prior={"Neuroscience": 4}), TODAY)
    assert j and j["fields"][:1] == ["Neuroscience"]
    k = run.norm_job(dict(job("https://x/h2", title="Fully funded project in algae", summary=""), hint_stage="phd"), TODAY)
    assert k and k["stages"] == ["phd"]


def test_admin_roles_are_dropped_but_academic_ones_kept():
    assert run.norm_job(job("https://x/d", title="Dean, School of Science"), TODAY) is None
    assert run.norm_job(job("https://x/p", title="Dean and Professor of Engineering"), TODAY)
    assert run.norm_job(job("https://x/m", title="Research Program Manager"), TODAY) is None


def test_jobs_body_text_can_decide_the_field_when_the_title_cannot():
    j = run.norm_job(job("https://x/b", title="Postdoctoral Fellow", department="", summary="Our lab studies neurons, synaptic plasticity and the hippocampus using electrophysiology."), TODAY)
    assert "Neuroscience" in j["fields"]


def test_article_cap_keeps_journal_papers_when_preprints_flood(monkeypatch):
    monkeypatch.setitem(run.CAPS, "articles", 30)
    pre = [{"title": f"Preprint {i} neural network", "url": f"https://a/p{i}", "source": "arxiv", "posted": TODAY, "summary": "", "authors": [], "prior": {"Artificial Intelligence": 4}, "tier": 0, "preprint": True} for i in range(100)]
    jr = [{"title": f"Journal {i} neural network", "url": f"https://a/j{i}", "source": "crossref", "posted": TODAY - timedelta(days=3), "summary": "", "authors": [], "prior": {"Artificial Intelligence": 4}, "tier": 2} for i in range(8)]
    out = run.build("articles", [("s", lambda: pre + jr)], {}, TODAY, {"sources": {}})
    assert len(out) == 30 and sum(1 for i in out if i["tier"] == 2) == 8


def test_crossref_abstract_heading_is_removed():
    a = {"title": "T", "url": "https://a/ab", "source": "crossref", "posted": TODAY, "summary": "Abstract Controlling crystallization is crucial.", "authors": [], "tier": 2}
    assert run.norm_article(a, TODAY)["summary"] == "Controlling crystallization is crucial."
    b = dict(a, summary="Abstractions of a theory of everything.")
    assert run.norm_article(b, TODAY)["summary"].startswith("Abstractions")        # only a heading, not a word that starts with it


def test_ukri_council_gives_the_field():
    from pipeline.sources import grants as G
    items = G.parse_ukri_feed((__import__("pathlib").Path(__file__).parent / "fixtures" / "ukri_feed.xml").read_text(encoding="utf8"))
    mrc = next(i for i in items if i["org"].endswith("MRC"))
    assert run.norm_grant(mrc, TODAY)["fields"] == ["Biomedical Sciences, and Medicine"]


def test_phd_section_settles_a_vague_title():
    assert run.job_stages("Marie Curie Early Stage Researcher", "", "phd") == ["phd"]
    assert run.job_stages("Postdoctoral Fellow", "", "phd") == ["postdoc"]      # an explicit title wins over the section
    assert run.job_stages("Marie Curie Early Stage Researcher", "", None) == ["researcher"]
