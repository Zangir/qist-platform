"""Shared helpers for the feed pipeline: HTTP, dates, text cleaning, item identity."""
import hashlib
import html
import re
import time
from datetime import date, datetime, timedelta, timezone

import requests

# UKRI resets connections from UAs that look like scripts; a browser-shaped UA with our name at the end gets through.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36 QISTFeedBot/1.0")

_session = None


def session():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": UA, "Accept-Language": "en"})
    return _session


def fetch(url, *, method="GET", params=None, json=None, data=None, headers=None, retries=3, timeout=(10, 40),
          pause=0.0):
    """GET/POST with retries. Raises on the final failure so the caller can record it."""
    last = None
    for attempt in range(retries + 1):
        try:
            if pause:
                time.sleep(pause)
            r = session().request(method, url, params=params, json=json, data=data, headers=headers,
                                  timeout=timeout)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"{r.status_code} for {url}", response=r)
            r.raise_for_status()
            return r
        except Exception as e:  # noqa: BLE001 - re-raised below
            last = e
            if isinstance(e, requests.exceptions.ConnectTimeout) and attempt >= 1:
                break  # host unreachable: do not spend minutes on it
            time.sleep(1.5 * (attempt + 1))
    raise last


def today():
    return datetime.now(timezone.utc).date()


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso(d):
    return d.isoformat() if d else None


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def clean(s, limit=None):
    """HTML/JATS markup -> plain text, entities decoded, whitespace collapsed."""
    if not s:
        return ""
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = _TAG.sub(" ", s)
    s = html.unescape(s)
    s = _WS.sub(" ", s).strip()
    if limit and len(s) > limit:
        cut = s[:limit].rsplit(" ", 1)[0]
        s = cut.rstrip(",;:-") + "…"
    return s


def item_id(kind, key):
    return kind[0] + hashlib.sha1(key.encode("utf8")).hexdigest()[:11]


MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_date(s, ref=None):
    """Accepts ISO, RFC 822, '12 Oct', 'October 14, 2026', '14 October 2026'. Returns date or None.
    A date without a year takes ref's year, rolling forward/back so it lands within ~6 months of ref."""
    if not s:
        return None
    s = s.strip()
    ref = ref or today()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)  # US style, as Grants.gov prints it
    if m:
        try:
            return date(int(m[3]), int(m[1]), int(m[2]))
        except ValueError:
            return None
    m = re.match(r"\w{3},\s+(\d{1,2})\s+(\w{3})\w*\s+(\d{4})", s)  # RFC 822
    if m and m[2][:3].lower() in MONTHS:
        return date(int(m[3]), MONTHS[m[2][:3].lower()], int(m[1]))
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s*(\d{4})?", s)
    if m and m[2][:3].lower() in MONTHS:
        return _with_year(int(m[1]), MONTHS[m[2][:3].lower()], m[3], ref)
    m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})?", s)
    if m and m[1][:3].lower() in MONTHS:
        return _with_year(int(m[2]), MONTHS[m[1][:3].lower()], m[3], ref)
    return None


def _with_year(d, mo, y, ref):
    try:
        if y:
            return date(int(y), mo, d)
        cand = date(ref.year, mo, d)
    except ValueError:
        return None
    if (cand - ref).days > 200:
        cand = date(ref.year - 1, mo, d)
    elif (ref - cand).days > 200:
        cand = date(ref.year + 1, mo, d)
    return cand


def days_ago(n):
    return today() - timedelta(days=n)
