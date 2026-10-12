"""Research articles, worldwide: arXiv, bioRxiv, medRxiv and a curated list of journals through Crossref.
Every function returns a list of raw item dicts (see pipeline/run.py for the final schema)."""
import re
import xml.etree.ElementTree as ET

from ..common import clean, days_ago, fetch, item_id, iso, parse_date, today
from ..taxonomy import classify_fields

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"

# arXiv category -> QIST field. A category is strong evidence, so it carries prior weight 4 (the minimum
# to assign a field is 3); the abstract can still add a second field.
ARXIV_CATS = {
    "cs.AI": "Artificial Intelligence", "cs.LG": "Artificial Intelligence", "cs.CL": "Artificial Intelligence",
    "cs.CV": "Artificial Intelligence", "cs.NE": "Artificial Intelligence", "cs.MA": "Artificial Intelligence",
    "stat.ML": "Artificial Intelligence", "cs.RO": "Robotics", "cs.CR": "Cybersecurity, and Digital Technologies",
    "cs.DC": "Computer Science", "cs.SE": "Computer Science", "cs.DS": "Computer Science", "cs.DB": "Computer Science",
    "cs.PL": "Computer Science", "cs.HC": "Computer Science", "cs.IR": "Computer Science", "cs.NI": "Computer Science",
    "cs.CY": "Social Sciences", "stat.ME": "Data Science, and Statistics", "stat.AP": "Data Science, and Statistics",
    "math.PR": "Mathematics and Computational Sciences", "math.NA": "Mathematics and Computational Sciences",
    "math.AP": "Mathematics and Computational Sciences", "math.CO": "Mathematics and Computational Sciences",
    "math.OC": "Mathematics and Computational Sciences", "math.DS": "Mathematics and Computational Sciences",
    "math.AG": "Mathematics and Computational Sciences", "math.NT": "Mathematics and Computational Sciences",
    "quant-ph": "Physics and Physical Sciences", "cond-mat.str-el": "Physics and Physical Sciences",
    "cond-mat.mes-hall": "Physics and Physical Sciences", "cond-mat.mtrl-sci": "Materials Science",
    "cond-mat.soft": "Materials Science", "hep-th": "Physics and Physical Sciences", "hep-ph": "Physics and Physical Sciences",
    "nucl-th": "Physics and Physical Sciences", "physics.optics": "Physics and Physical Sciences",
    "physics.flu-dyn": "Engineering", "physics.app-ph": "Engineering", "physics.chem-ph": "Chemistry and Chemical Sciences",
    "physics.ao-ph": "Earth Sciences and Geosciences", "physics.geo-ph": "Earth Sciences and Geosciences",
    "physics.med-ph": "Biomedical Sciences, and Medicine", "physics.soc-ph": "Social Sciences",
    "astro-ph.CO": "Astronomy, Space Science", "astro-ph.GA": "Astronomy, Space Science", "astro-ph.EP": "Astronomy, Space Science",
    "astro-ph.HE": "Astronomy, Space Science", "astro-ph.SR": "Astronomy, Space Science", "astro-ph.IM": "Astronomy, Space Science",
    "gr-qc": "Astronomy, Space Science", "physics.plasm-ph": "Physics and Physical Sciences", "physics.space-ph": "Astronomy, Space Science",
    "cond-mat.stat-mech": "Physics and Physical Sciences", "cond-mat.supr-con": "Physics and Physical Sciences",
    "cond-mat.quant-gas": "Physics and Physical Sciences", "hep-ex": "Physics and Physical Sciences",
    "physics.comp-ph": "Mathematics and Computational Sciences", "math.ST": "Data Science, and Statistics",
    "q-bio.NC": "Neuroscience", "q-bio.GN": "Biotechnology, Genetics, and Bioinformatics",
    "q-bio.BM": "Biology and Life Sciences", "q-bio.PE": "Biology and Life Sciences", "q-bio.QM": "Biology and Life Sciences",
    "eess.SP": "Electronics", "eess.SY": "Engineering", "eess.IV": "Artificial Intelligence",
    "econ.GN": "Economics", "econ.EM": "Economics", "q-fin.GN": "Economics", "q-fin.MF": "Economics",
}
ARXIV_PER_CAT = 60


def parse_arxiv(xml_text):
    root = ET.fromstring(xml_text)
    out = []
    for e in root.findall(ATOM + "entry"):
        aid = (e.findtext(ATOM + "id") or "").strip()
        if not aid:
            continue
        cats = [c.get("term") for c in e.findall(ATOM + "category")]
        prim = e.find(ARXIV + "primary_category")
        prim = prim.get("term") if prim is not None else (cats[0] if cats else "")
        link = re.sub(r"v\d+$", "", aid.replace("http://", "https://"))
        out.append({
            "title": clean(e.findtext(ATOM + "title")),
            "summary": clean(e.findtext(ATOM + "summary")),
            "authors": [clean(a.findtext(ATOM + "name")) for a in e.findall(ATOM + "author")],
            "posted": parse_date(e.findtext(ATOM + "published")),
            "url": link, "venue": "arXiv", "source": "arxiv", "preprint": True, "tier": 0,
            "doi": clean(e.findtext(ARXIV + "doi")) or None,
            "cats": cats, "primary": prim,
        })
    return out


def arxiv(per_cat=ARXIV_PER_CAT, cats=None):
    seen, items = set(), []
    for cat in (cats or ARXIV_CATS):
        r = fetch("https://export.arxiv.org/api/query",
                  params={"search_query": f"cat:{cat}", "sortBy": "submittedDate", "sortOrder": "descending",
                          "max_results": per_cat}, pause=3.2)
        for it in parse_arxiv(r.text):
            if it["url"] in seen:
                continue
            seen.add(it["url"])
            prior = {}
            for c in [it["primary"]] + it["cats"][:2]:
                f = ARXIV_CATS.get(c)
                if f:
                    prior[f] = max(prior.get(f, 0), 4 if c == it["primary"] else 2)
            it["prior"] = prior
            it["tags"] = it["cats"][:3]
            items.append(it)
    return items


# ---------- bioRxiv / medRxiv ----------
BIORXIV_CATS = {
    "neuroscience": "Neuroscience", "bioinformatics": "Biotechnology, Genetics, and Bioinformatics",
    "genomics": "Biotechnology, Genetics, and Bioinformatics", "genetics": "Biotechnology, Genetics, and Bioinformatics",
    "synthetic biology": "Biotechnology, Genetics, and Bioinformatics", "bioengineering": "Biotechnology, Genetics, and Bioinformatics",
    "genetic and genomic medicine": "Biotechnology, Genetics, and Bioinformatics",
    "cancer biology": "Biomedical Sciences, and Medicine", "immunology": "Biomedical Sciences, and Medicine",
    "pathology": "Biomedical Sciences, and Medicine", "pharmacology and toxicology": "Pharmaceutical Sciences",
    "pharmacology and therapeutics": "Pharmaceutical Sciences", "epidemiology": "Public Health, Epidemiology",
    "public and global health": "Public Health, Epidemiology", "health policy": "Public Health, Epidemiology",
    "infectious diseases": "Public Health, Epidemiology", "health economics": "Economics",
    "psychiatry and clinical psychology": "Behavioral Sciences", "neurology": "Neuroscience",
    "ecology": "Environmental Science", "plant biology": "Biology and Life Sciences",
}
_BIO_DEFAULT = "Biology and Life Sciences"
_MED_DEFAULT = "Biomedical Sciences, and Medicine"


def parse_biorxiv(payload, server):
    out = []
    for r in payload.get("collection", []):
        cat = (r.get("category") or "").strip().lower()
        field = BIORXIV_CATS.get(cat) or (_MED_DEFAULT if server == "medrxiv" else _BIO_DEFAULT)
        doi = r.get("doi")
        out.append({
            "title": clean(r.get("title")), "summary": clean(r.get("abstract")),
            "authors": [a.strip() for a in (r.get("authors") or "").split(";") if a.strip()],
            "posted": parse_date(r.get("date")),
            "url": f"https://www.{server}.org/content/{doi}v{r.get('version', 1)}" if doi else None,
            "venue": server, "source": server, "preprint": True, "tier": 0, "doi": doi,
            "affiliation": clean(r.get("author_corresponding_institution")),
            "prior": {field: 4}, "tags": [cat] if cat else [],
        })
    return [o for o in out if o["url"] and o["title"]]


def biorxiv(servers=("biorxiv", "medrxiv"), days=2, max_pages=8):
    items = []
    start, end = iso(days_ago(days)), iso(today())
    for server in servers:
        cursor = 0
        for _ in range(max_pages):
            r = fetch(f"https://api.biorxiv.org/details/{server}/{start}/{end}/{cursor}/json", pause=0.5)
            payload = r.json()
            batch = parse_biorxiv(payload, server)
            items += batch
            msg = (payload.get("messages") or [{}])[0]
            total, count = int(msg.get("total", 0) or 0), int(msg.get("count", 0) or 0)
            cursor += count
            if not count or cursor >= total:
                break
    # one entry per DOI: keep the newest version
    best = {}
    for it in items:
        best[it["doi"]] = it
    return list(best.values())


# ---------- journals via Crossref ----------
# (name, ISSN, field prior, tier). Tier 3 = flagship general journals, 2 = leading field journals.
JOURNALS = [
    ("Nature", "0028-0836", None, 3), ("Science", "0036-8075", None, 3), ("Cell", "0092-8674", "Biology and Life Sciences", 3),
    ("PNAS", "0027-8424", None, 2), ("Nature Communications", "2041-1723", None, 2), ("Science Advances", "2375-2548", None, 2),
    ("The Lancet", "0140-6736", "Biomedical Sciences, and Medicine", 3), ("New England Journal of Medicine", "0028-4793", "Biomedical Sciences, and Medicine", 3),
    ("JAMA", "0098-7484", "Biomedical Sciences, and Medicine", 3), ("BMJ", "1756-1833", "Biomedical Sciences, and Medicine", 2),
    ("Nature Medicine", "1078-8956", "Biomedical Sciences, and Medicine", 2), ("Nature Genetics", "1061-4036", "Biotechnology, Genetics, and Bioinformatics", 2),
    ("Nature Biotechnology", "1087-0156", "Biotechnology, Genetics, and Bioinformatics", 2), ("Nature Neuroscience", "1097-6256", "Neuroscience", 2),
    ("Neuron", "0896-6273", "Neuroscience", 2), ("Nature Physics", "1745-2473", "Physics and Physical Sciences", 2),
    ("Physical Review Letters", "0031-9007", "Physics and Physical Sciences", 2), ("Nature Materials", "1476-1122", "Materials Science", 2),
    ("Advanced Materials", "0935-9648", "Materials Science", 2), ("Nature Chemistry", "1755-4330", "Chemistry and Chemical Sciences", 2),
    ("Journal of the American Chemical Society", "0002-7863", "Chemistry and Chemical Sciences", 2),
    ("Angewandte Chemie", "1433-7851", "Chemistry and Chemical Sciences", 2), ("Nature Energy", "2058-7546", "Energy, Renewable Energy", 2),
    ("Energy & Environmental Science", "1754-5692", "Energy, Renewable Energy", 2), ("Nature Machine Intelligence", "2522-5839", "Artificial Intelligence", 2),
    ("Nature Climate Change", "1758-678X", "Environmental Science", 2), ("Nature Geoscience", "1752-0894", "Earth Sciences and Geosciences", 2),
    ("Nature Astronomy", "2397-3366", "Astronomy, Space Science", 2), ("The Astrophysical Journal", "0004-637X", "Astronomy, Space Science", 1),
    ("Annals of Mathematics", "0003-486X", "Mathematics and Computational Sciences", 2), ("Journal of the AMS", "0894-0347", "Mathematics and Computational Sciences", 2),
    ("Econometrica", "0012-9682", "Economics", 2), ("American Economic Review", "0002-8282", "Economics", 2),
    ("Quarterly Journal of Economics", "0033-5533", "Economics", 2), ("American Political Science Review", "0003-0554", "Politics, International Relations, and Public Policy", 2),
    ("American Sociological Review", "0003-1224", "Social Sciences", 2), ("Psychological Science", "0956-7976", "Behavioral Sciences", 2),
    ("Nature Human Behaviour", "2397-3374", "Behavioral Sciences", 2), ("eLife", "2050-084X", "Biology and Life Sciences", 2),
    ("Nature Sustainability", "2398-9629", "Environmental Science", 2), ("Nature Food", "2662-1355", "Agriculture and Food Science", 2),
    ("IEEE Transactions on Pattern Analysis and Machine Intelligence", "0162-8828", "Artificial Intelligence", 2),
    ("Nature Electronics", "2520-1131", "Electronics", 2), ("Nature Nanotechnology", "1748-3387", "Materials Science", 2),
    ("Nature Reviews Drug Discovery", "1474-1776", "Pharmaceutical Sciences", 2),
]
CROSSREF = "https://api.crossref.org/journals/{issn}/works"


def parse_crossref(payload, journal, tier, prior_field):
    out = []
    for w in (payload.get("message") or {}).get("items", []):
        title = clean((w.get("title") or [""])[0])
        doi = w.get("DOI")
        if not title or not doi:
            continue
        issued = (w.get("published") or w.get("issued") or {}).get("date-parts", [[None]])[0]
        d = None
        if issued and issued[0]:
            parts = (issued + [1, 1])[:3]
            try:
                from datetime import date
                d = date(parts[0], parts[1] or 1, parts[2] or 1)
            except ValueError:
                d = None
        authors = []
        for a in w.get("author", [])[:12]:
            n = f"{a.get('given', '')} {a.get('family', '')}".strip() or a.get("name", "")
            if n:
                authors.append(n)
        out.append({
            "title": title, "summary": clean(w.get("abstract"), 600), "authors": authors, "posted": d,
            "url": w.get("URL") or f"https://doi.org/{doi}", "venue": journal, "source": "crossref", "preprint": False,
            "tier": tier, "doi": doi, "prior": {prior_field: 4} if prior_field else {},
            "tags": [s for s in (w.get("subject") or [])[:2]],
        })
    return out


def crossref_journals(days=4, rows=30, journals=None, mailto="qist-feeds@users.noreply.github.com"):
    items, failures = [], []
    since = iso(days_ago(days))
    for name, issn, field, tier in (journals or JOURNALS):
        try:
            r = fetch(CROSSREF.format(issn=issn), params={
                "filter": f"from-pub-date:{since},type:journal-article", "sort": "published", "order": "desc", "rows": rows,
                "select": "DOI,title,abstract,author,published,URL,subject", "mailto": mailto}, pause=0.3, retries=1)
            items += parse_crossref(r.json(), name, tier, field)
        except Exception as e:  # one journal failing must not lose the others
            failures.append(f"{name}: {e}")
    return items, failures


def finish(it):
    """Common tail: classify fields from title + abstract + the source prior."""
    it["fields"] = classify_fields(it["title"], it.get("summary", ""), it.get("prior"))
    return it
