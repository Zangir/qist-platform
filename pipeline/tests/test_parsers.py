from datetime import date
from pathlib import Path

from pipeline.sources import articles as A, grants as G, jobs as J

FX = Path(__file__).parent / "fixtures"
read = lambda n: (FX / n).read_text(encoding="utf8")  # noqa: E731
REF = date(2026, 10, 12)


# ---------- articles ----------
def test_arxiv():
    items = A.parse_arxiv(read("arxiv.xml"))
    assert len(items) == 4
    for it in items:
        assert it["title"] and it["summary"] and it["authors"] and it["posted"]
        assert it["url"].startswith("https://arxiv.org/abs/") and not it["url"].rsplit("/", 1)[-1].count("v")  # version stripped
        assert it["preprint"] and it["venue"] == "arXiv" and it["primary"]


def test_biorxiv():
    items = A.parse_biorxiv(__import__("json").loads(read("biorxiv.json")), "biorxiv")
    assert len(items) == 5
    for it in items:
        assert it["url"].startswith("https://www.biorxiv.org/content/10.") and it["doi"] and it["posted"]
        assert it["prior"] and it["preprint"]


def test_crossref():
    items = A.parse_crossref(__import__("json").loads(read("crossref.json")), "Nature", 3, None)
    assert items
    for it in items:
        assert it["doi"] and it["title"] and it["posted"] and it["venue"] == "Nature" and it["tier"] == 3 and not it["preprint"]
        assert "<" not in it["summary"]


def test_journal_issns_unique():
    issns = [j[1] for j in A.JOURNALS]
    assert len(issns) == len(set(issns))


# ---------- grants ----------
def test_nsf_deadlines_and_boilerplate():
    items = G.parse_nsf(read("nsf_upcoming.xml"))
    assert items and all(i["url"].startswith("https://") for i in items)
    dated = [i for i in items if i["deadline"]]
    assert dated and all(i["deadline"].year >= 2026 for i in dated)
    assert all("Full Proposal Deadline Date" not in i["summary"] and "This is an NSF" not in i["summary"] for i in items)
    pgm = G.parse_nsf(read("nsf_pgm.xml"))
    assert pgm and all(i["summary"] for i in pgm) and all("Available Formats" not in i["summary"] for i in pgm)


def test_ukri_feed_and_page():
    items = G.parse_ukri_feed(read("ukri_feed.xml"))
    assert len(items) >= 10 and all(i["origin"] == "GB" and i["url"].startswith("https://www.ukri.org/opportunity/") for i in items)
    assert all("<" not in i["summary"] for i in items)
    info = G.parse_ukri_page(read("ukri_page.html"))
    assert info["status"] == "open" and info["funding_type"] == "Grant"
    assert info["deadline"] is None  # "Open - no closing date" must not be read as a date


def test_fundsforngos_filters_to_research_and_reads_deadline():
    items = G.parse_ffn(read("ffn.xml"))
    assert items and all(G._RESEARCH.search(i["title"] + i["summary"]) for i in items)
    nserc = [i for i in items if "NSERC" in i["title"]]
    assert nserc and nserc[0]["deadline"] == date(2026, 11, 15)


def test_grantsgov_live_capture():
    items = G.parse_grantsgov(__import__("json").loads(read("grantsgov.json")))
    assert len(items) >= 4
    for i in items:
        assert i["title"] and i["url"].startswith("https://www.grants.gov/search-results-detail/") and i["org"]
        assert i["status"] in ("posted", "forecasted") and i["origin"] == "US"
        assert i["posted"] is None or i["posted"].year >= 2025


def test_grantsgov_edge_cases():
    items = G.parse_grantsgov(__import__("json").loads(read("grantsgov_synthetic.json")))
    assert [i["title"][:8] for i in items] == ["Research", "Quantum "]          # archived dropped
    assert items[0]["deadline"] == date(2027, 1, 5) and items[0]["posted"] == date(2026, 9, 20)
    assert items[1]["deadline"] is None and "forecast" in items[1]["summary"]
    assert items[0]["url"] == "https://www.grants.gov/search-results-detail/350001"


def test_sedia_documented_shape():
    items = G.parse_sedia(__import__("json").loads(read("sedia.json")))
    assert [i["title"] for i in items] == ["Advanced materials for sustainable batteries", "ERC Starting Grant 2027"]  # closed dropped
    assert items[0]["deadline"] == date(2027, 2, 18) and items[0]["status"] == "open"
    assert items[0]["url"].endswith("/topic-details/horizon-cl4-2027-resilience-01-01") and "<" not in items[0]["summary"]
    assert items[1]["summary"].startswith("ERC Starting Grants")


# ---------- jobs ----------
def test_jobsac():
    items = J.parse_jobsac(read("jobsac.html"), REF)
    assert len(items) == 6
    for it in items:
        assert it["title"] and it["url"].startswith("https://www.jobs.ac.uk/job/") and it["org"]
        assert it["posted"] and it["posted"] <= REF and it["deadline"] and it["deadline"] >= it["posted"]


def test_madgex_nature_and_ihe():
    n = J.parse_madgex(read("nature_careers.html"), "https://www.nature.com", "nature", None, REF)
    assert len(n) == read("nature_careers.html").count('class="lister__header') and len(n) >= 5 and all("/naturecareers/job/" in i["url"] and "LinkSource" not in i["url"] and " " not in i["url"] for i in n)
    assert any(i["posted"] for i in n) and all(i["org"] for i in n)
    h = J.parse_madgex(read("insidehighered.html"), "https://careers.insidehighered.com", "insidehighered", "US", REF)
    assert len(h) == read("insidehighered.html").count('class="lister__header') and all(i["url"].startswith("https://careers.insidehighered.com/job/") for i in h)


def test_ago():
    assert J._ago("12 days ago", REF) == date(2026, 9, 30)
    assert J._ago("Today", REF) == REF and J._ago("Yesterday", REF) == date(2026, 10, 11) and J._ago("", REF) is None


def test_jobsac_merges_disciplines_and_marks_phds(monkeypatch):
    page = J.parse_jobsac(read("jobsac.html"), REF)
    calls = []

    def fake(path, pages):
        calls.append(path)
        return [dict(i) for i in page[:3]]
    monkeypatch.setattr(J, "_jobsac_pages", fake)
    out = J.jobsac(disciplines={"computer-sciences": "Computer Science", "physical-and-environmental-sciences": None}, phd_pages=1, pages=1)
    assert calls == ["/search/phds", "/search/computer-sciences", "/search/physical-and-environmental-sciences"]
    assert len(out) == 3                                           # same three vacancies, not 9
    assert all(o["hint_stage"] == "phd" and o["prior"] == {"Computer Science": 4} for o in out)
