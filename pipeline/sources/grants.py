"""Research grants and funding calls, worldwide: UKRI, NSF, Grants.gov (US agencies), the EU Funding & Tenders
portal (Horizon Europe, ERC, MSCA) and fundsforngos. Each returns raw item dicts."""
import html
import json
import re

from bs4 import BeautifulSoup

from ..common import clean, fetch, parse_date, today

def _tag(block, name):
    m = re.search(rf"<{name}(?:\s[^>]*)?>(.*?)</{name}>", block, re.S | re.I)
    if not m:
        return ""
    v = m[1].strip()
    c = re.match(r"<!\[CDATA\[(.*)\]\]>$", v, re.S)
    return c[1] if c else html.unescape(v)


def parse_rss(xml_text):
    """Generic RSS 2.0 -> [{title, link, desc, date, cats}]. Regex-based on purpose: real feeds (NSF's) contain
    unescaped ampersands that a strict XML parser rejects, and one malformed item must not lose the feed."""
    out = []
    for blk in re.findall(r"<item[ >].*?</item>", xml_text, re.S | re.I):
        out.append({
            "title": clean(_tag(blk, "title")), "link": clean(_tag(blk, "link")),
            "desc": _tag(blk, "description"), "date": parse_date(_tag(blk, "pubDate")),
            "cats": [clean(_tag(c, "category")) for c in re.findall(r"<category[ >].*?</category>", blk, re.S | re.I)],
        })
    return out


# ---------- NSF ----------
NSF_FEEDS = [
    "https://www.nsf.gov/rss/rss_www_funding_pgm_annc_inf.xml",   # program announcements
    "https://www.nsf.gov/rss/rss_www_funding_upcoming.xml",       # upcoming due dates
]


def parse_nsf(xml_text):
    out = []
    for r in parse_rss(xml_text):
        text = clean(r["desc"])
        dl = None
        m = re.search(r"(?:Full Proposal (?:Deadline Date|Window)|Deadline Date|Letter of Intent[^:]*|Proposal Deadline Date):\s*([A-Z][a-z]+ \d{1,2}, \d{4})", text)
        if m:
            dl = parse_date(m[1])
        # NSF puts boilerplate ("Available Formats ...") in program announcements; keep the useful sentence
        text = re.sub(r"Available Formats:.*?Document Number: [\w -]+", "", text)
        text = re.sub(r"This is an NSF [\w ]+ item\.?", "", text).strip()
        text = re.sub(r"(Full Proposal (Deadline Date|Window)|Proposal Deadline Date|Deadline Date):\s*[A-Z][a-z]+ \d{1,2}, \d{4}", "", text).strip()
        text = re.sub(r"Program Guidelines:\s*NSF [\d-]+", "", text).strip()
        text = re.sub(r"More at https?://\S+", "", text).strip(" .")
        text = text or "NSF program announcement. See the solicitation for eligibility and dates."
        out.append({"title": r["title"], "url": r["link"], "summary": clean(text, 420), "deadline": dl,
                    "posted": r["date"], "org": "U.S. National Science Foundation", "source": "nsf", "origin": "US",
                    "amount": None})
    return out


def nsf():
    items = []
    for u in NSF_FEEDS:
        items += parse_nsf(fetch(u).text)
    return items


# ---------- UKRI ----------
UKRI_FEED = "https://www.ukri.org/opportunity/feed/"


UKRI_COUNCIL_FIELDS = {
    "MRC": {"Biomedical Sciences, and Medicine": 4}, "BBSRC": {"Biology and Life Sciences": 4},
    "EPSRC": {"Engineering": 4, "Physics and Physical Sciences": 2}, "ESRC": {"Social Sciences": 4},
    "AHRC": {"Arts, and Humanities": 4}, "NERC": {"Environmental Science": 4, "Earth Sciences and Geosciences": 3},
    "STFC": {"Physics and Physical Sciences": 3, "Astronomy, Space Science": 3},
    "Innovate UK": {"Management, Entrepreneurship, Innovation": 3},
}


def parse_ukri_feed(xml_text):
    out = []
    for r in parse_rss(xml_text):
        out.append({"title": r["title"], "url": r["link"], "summary": clean(re.sub(r'<p aria-label="Councils">.*', "", r["desc"], flags=re.S), 420),
                    "deadline": None, "posted": r["date"], "org": "UKRI" + (f" · {r['cats'][0]}" if r["cats"] else ""),
                    "source": "ukri", "origin": "GB", "amount": None, "status": None,
                    "prior": UKRI_COUNCIL_FIELDS.get(r["cats"][0], {}) if r["cats"] else {}})
    return out


def parse_ukri_page(html):
    """Opportunity status, funding type and dates from a UKRI opportunity page."""
    t = clean(BeautifulSoup(html, "html.parser").get_text(" "))
    info = {}
    m = re.search(r"Opportunity status:\s*(\w+)", t)
    info["status"] = m[1].lower() if m else None
    m = re.search(r"Funding type:\s*(\w+)", t)
    info["funding_type"] = m[1] if m else None
    m = re.search(r"Closing date:\s*(\d{1,2} \w+ \d{4})", t)
    info["deadline"] = parse_date(m[1]) if m else None
    m = re.search(r"Opening date:\s*(\d{1,2} \w+ \d{4})", t)
    info["opens"] = parse_date(m[1]) if m else None
    m = re.search(r"Total fund:\s*([£€$][\d,.]+\s*(?:million|m|k)?)", t, re.I)
    info["amount"] = m[1] if m else None
    return info


def ukri(enrich=30):
    items = parse_ukri_feed(fetch(UKRI_FEED).text)
    for it in items[:enrich]:
        try:
            info = parse_ukri_page(fetch(it["url"], retries=1, pause=0.4).text)
        except Exception:
            continue
        it.update({k: v for k, v in info.items() if k in ("deadline", "status", "amount") and v})
        if info.get("funding_type") and info["funding_type"].lower() not in ("grant",):
            it["summary"] = f"{info['funding_type']}. " + it["summary"]
    # an opportunity UKRI marks closed is not an opportunity
    return [i for i in items if (i.get("status") or "open") != "closed"]


# ---------- Grants.gov ----------
GRANTS_GOV = "https://api.grants.gov/v1/api/search2"
GG_CATEGORY_FIELD = {"HL": "Biomedical Sciences, and Medicine", "ENV": "Environmental Science", "EN": "Energy, Renewable Energy",
                     "AG": "Agriculture and Food Science", "NR": "Environmental Science", "ED": "Education, and Learning Sciences",
                     "HU": "Arts, and Humanities"}


def parse_grantsgov(payload):
    """Documented search2 response: data.oppHits[] with id, number, title, agency, openDate, closeDate, oppStatus."""
    data = payload.get("data") or payload
    out = []
    for h in data.get("oppHits", []):
        if (h.get("oppStatus") or "posted") not in ("posted", "forecasted"):
            continue
        status = h.get("oppStatus")
        out.append({
            "title": clean(h.get("title")), "url": f"https://www.grants.gov/search-results-detail/{h.get('id')}",
            "summary": clean(f"{h.get('agency', '')}. Opportunity {h.get('number', '')}" + (" (forecast)" if status == "forecasted" else "")),
            "deadline": parse_date(h.get("closeDate")), "posted": parse_date(h.get("openDate")),
            "org": clean(h.get("agency")) or "US federal agency", "source": "grantsgov", "origin": "US", "amount": None,
            "status": status,
        })
    return [o for o in out if o["title"] and h]


def grantsgov(rows=250):
    r = fetch(GRANTS_GOV, method="POST", json={"rows": rows, "keyword": "research", "oppStatuses": "forecasted|posted",
                                              "fundingCategories": "ST|HL|ENV|EN|AG|NR|ED|HU", "sortBy": "openDate|desc"})
    return parse_grantsgov(r.json())


# ---------- EU Funding & Tenders portal (Horizon Europe, ERC, MSCA ...) ----------
SEDIA = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
SEDIA_STATUS_OPEN = {"31094501": "forthcoming", "31094502": "open"}


def _first(md, key):
    v = md.get(key)
    if isinstance(v, list):
        return v[0] if v else None
    return v


def parse_sedia(payload):
    out = []
    for r in payload.get("results", []):
        md = r.get("metadata") or {}
        ident = _first(md, "identifier") or ""
        title = clean(_first(md, "title") or r.get("title") or "")
        status = SEDIA_STATUS_OPEN.get(str(_first(md, "status")))
        if not title or not status:
            continue
        deadline = parse_date((_first(md, "deadlineDate") or "")[:10])
        opens = parse_date((_first(md, "startDate") or "")[:10])
        summary = clean(_first(md, "descriptionByte") or r.get("summary") or r.get("content") or "", 420)
        call = _first(md, "callTitle") or _first(md, "callIdentifier") or ""
        out.append({
            "title": title, "url": "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/" + ident.lower() if ident else r.get("url"),
            "summary": summary or clean(call), "deadline": deadline, "posted": opens,
            "org": "European Commission" + (f" · {ident.split('-')[0]}" if ident else ""), "source": "sedia", "origin": "EU",
            "amount": None, "status": status,
        })
    return out


def sedia(page_size=100, pages=3):
    query = {"bool": {"must": [{"terms": {"type": ["1", "2", "8"]}}, {"terms": {"status": ["31094501", "31094502"]}}]}}
    items = []
    for p in range(1, pages + 1):
        r = fetch(SEDIA, method="POST", params={"apiKey": "SEDIA", "text": "***", "pageSize": page_size, "pageNumber": p},
                  files=None) if False else _sedia_page(query, page_size, p)
        batch = parse_sedia(r.json())
        items += batch
        if len(batch) < 1:
            break
    return items


def _sedia_page(query, page_size, page):
    import requests
    from ..common import session
    return session().post(SEDIA, params={"apiKey": "SEDIA", "text": "***", "pageSize": page_size, "pageNumber": page},
                          files={"query": (None, json.dumps(query), "application/json"),
                                 "languages": (None, json.dumps(["en"]), "application/json"),
                                 "sort": (None, json.dumps({"order": "DESC", "field": "startDate"}), "application/json")},
                          timeout=40)


# ---------- fundsforngos (aggregator, general; filtered to research) ----------
FFN = "https://www.fundsforngos.org/feed/"
_RESEARCH = re.compile(r"\b(research|scientist|scientific|fellowship|academic|university|universities|phd|postdoc\w*|scholar\w*|science|innovation|laborator\w+|doctoral)\b", re.I)


def parse_ffn(xml_text):
    out = []
    for r in parse_rss(xml_text):
        text = clean(r["desc"])
        if not _RESEARCH.search(r["title"] + " " + text):
            continue
        mo = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
        m = re.search(rf"deadline[^.]*?\b(\d{{1,2}}(?:st|nd|rd|th)? {mo}(?: \d{{4}})?|{mo} \d{{1,2}}(?:st|nd|rd|th)?(?:, \d{{4}})?)", text)
        dl = parse_date(m[1], ref=r["date"] or today()) if m else None
        text = re.sub(r"The post .* first appeared on .*$", "", text).strip()
        text = re.sub(r"\[Read\s*More\]", "", text).strip()
        out.append({"title": r["title"], "url": r["link"], "summary": clean(text, 420), "deadline": dl, "posted": r["date"],
                    "org": "via fundsforngos", "source": "fundsforngos", "origin": None, "amount": None})
    return out


def fundsforngos():
    return parse_ffn(fetch(FFN).text)
