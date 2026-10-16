"""Academic and research vacancies, worldwide: jobs.ac.uk (UK and international), Nature Careers (worldwide) and
Inside Higher Ed Careers (US). Searches are role keywords, newest first; every vacancy then goes through the same
research-role filter, stage detection and country detection."""
import re
from datetime import timedelta
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from ..common import clean, fetch, parse_date, today, days_ago

ROLE_QUERIES = ["phd", "postdoctoral", "research associate", "research fellow", "research scientist",
                "assistant professor", "associate professor", "professor", "lecturer", "faculty position"]


# ---------- jobs.ac.uk ----------
def parse_jobsac(html, ref=None):
    ref = ref or today()
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for r in soup.select("div.j-search-result__result"):
        a = r.select_one(".j-search-result__text > a")
        if not a:
            continue
        info = r.select_one(".j-search-result__info")
        salary = clean(info.get_text(" ")).replace("Salary:", "").strip() if info else ""
        loc, placed = "", None
        for d in r.select(".j-search-result__text > div"):
            t = clean(d.get_text(" "))
            if t.startswith("Location:"):
                loc = t.replace("Location:", "").strip()
            elif t.startswith("Date Placed:"):
                placed = parse_date(t.replace("Date Placed:", "").strip(), ref)
        closes = None
        spans = r.select(".j-search-result__date-span")
        if len(spans) >= 2:
            closes = parse_date(clean(spans[1].get_text()), ref)
        dept = r.select_one(".j-search-result__department")
        emp = r.select_one(".j-search-result__employer")
        out.append({
            "title": clean(a.get_text()), "url": urljoin("https://www.jobs.ac.uk", a["href"]),
            "org": clean(emp.get_text()) if emp else "", "department": clean(dept.get_text()) if dept else "",
            "location": loc, "salary": salary, "posted": placed, "deadline": closes, "summary": "",
            "source": "jobsac", "default_country": "GB",
        })
    return out


# jobs.ac.uk files every vacancy under an academic discipline, which is better evidence than any word in the
# title ("Postdoctoral Researcher" says nothing about the field). Discipline slug -> QIST field.
JOBSAC_DISCIPLINES = {
    "agriculture-food-and-veterinary": "Agriculture and Food Science", "architecture-building-and-planning": "Architecture, and Design",
    "biological-sciences": "Biology and Life Sciences", "business-and-management-studies": "Management, Entrepreneurship, Innovation",
    "computer-sciences": "Computer Science", "creative-arts-and-design": "Arts, and Humanities", "economics": "Economics",
    "education-studies-inc-tefl": "Education, and Learning Sciences", "engineering-and-technology": "Engineering",
    "health-and-medical": "Biomedical Sciences, and Medicine", "historical-and-philosophical-studies": "Arts, and Humanities",
    "languages-literature-and-culture": "Arts, and Humanities", "law": "Law, Legal Studies, and Governance",
    "mathematics-and-statistics": "Mathematics and Computational Sciences", "media-and-communications": "Communication and Media",
    "physical-and-environmental-sciences": None,   # physics, chemistry, earth and environment: the text decides
    "politics-and-government": "Politics, International Relations, and Public Policy", "psychology": "Behavioral Sciences",
    "social-sciences-and-social-care": "Social Sciences",
}


def _jobsac_pages(path, pages):
    items = []
    for p in range(pages):
        r = fetch("https://www.jobs.ac.uk" + path, params={"startIndex": 1 + 25 * p}, pause=0.7)
        batch = parse_jobsac(r.text)
        items += batch
        if len(batch) < 25:
            break
    return items


def jobsac(disciplines=None, phd_pages=7, pages=2, queries=None):
    """PhD vacancies from /search/phds (so they carry the 'phd' stage even when the title does not say so),
    then every academic discipline, newest first. A vacancy listed under several is merged."""
    by_url = {}

    def add(batch, prior_field, hint):
        for it in batch:
            cur = by_url.setdefault(it["url"], dict(it, prior={}, hint_stage=None))
            if prior_field:
                cur["prior"][prior_field] = 4
            if hint and not cur["hint_stage"]:
                cur["hint_stage"] = hint

    add(_jobsac_pages("/search/phds", phd_pages), None, "phd")
    for slug, field in (disciplines or JOBSAC_DISCIPLINES).items():
        add(_jobsac_pages("/search/" + slug, pages), field, None)
    for q in (queries or []):          # optional extra keyword searches
        r = fetch("https://www.jobs.ac.uk/search/", params={"keywords": q, "sortOrder": 1}, pause=0.7)
        add(parse_jobsac(r.text), None, None)
    return list(by_url.values())


# ---------- Madgex boards: Nature Careers, Inside Higher Ed ----------
def _ago(text, ref):
    """'12 days ago', 'Today', 'Yesterday', '3 hours ago' -> date, counted back from `ref`."""
    t = (text or "").lower()
    if "today" in t or "hour" in t or "minute" in t:
        return ref
    if "yesterday" in t:
        return ref - timedelta(days=1)
    for unit, days in (("day", 1), ("week", 7), ("month", 30)):
        m = re.search(rf"(\d+)\s+{unit}", t)
        if m:
            return ref - timedelta(days=days * int(m[1]))
    return None


def parse_madgex(html, base, source, default_country=None, ref=None):
    ref = ref or today()
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for li in soup.select("li.lister__item"):
        a = li.select_one(".lister__header a")
        if not a or not a.get("href"):
            continue
        href = re.sub(r"\s+", "", a["href"])
        href = re.sub(r"\?LinkSource=.*$", "", href)
        meta = {k: clean(li.select_one(f".lister__meta-item--{k}").get_text()) if li.select_one(f".lister__meta-item--{k}") else ""
                for k in ("location", "salary", "recruiter")}
        desc = li.select_one(".lister__description")
        ago = li.select_one(".job-actions__action.pipe")
        out.append({
            "title": clean(a.get_text()), "url": urljoin(base, href), "org": meta["recruiter"], "department": "",
            "location": meta["location"], "salary": meta["salary"], "summary": clean(desc.get_text(" "), 420) if desc else "",
            "posted": _ago(ago.get_text(), ref) if ago else None, "deadline": None,
            "source": source, "default_country": default_country,
        })
    return out


MADGEX = {
    "nature": ("https://www.nature.com/naturecareers/jobs/", "https://www.nature.com", None),
    "insidehighered": ("https://careers.insidehighered.com/jobs/", "https://careers.insidehighered.com", "US"),
}


def madgex(site, queries=ROLE_QUERIES, pages=2):
    url, base, country = MADGEX[site]
    items = []
    for q in queries:
        for p in range(1, pages + 1):
            r = fetch(url, params={"keywords": q, "sort": "Date", "Page": p}, pause=0.8)
            batch = parse_madgex(r.text, base, site, country)
            items += batch
            if len(batch) < 10:
                break
    return items


def nature_careers(**kw):
    return madgex("nature", **kw)


def inside_higher_ed(**kw):
    return madgex("insidehighered", **kw)
