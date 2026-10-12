"""Deterministic classification: research fields, career stage, and the 'is this a research role' test.
No model is involved; every decision is a term list or a regex that a person can read and change.
The field vocabulary is data/taxonomy.json, which the browser (assets/js/feed.js) reads too."""
import json
import re
from pathlib import Path

TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "data" / "taxonomy.json"
_TAX = json.loads(TAXONOMY_PATH.read_text(encoding="utf8"))
FIELDS = list(_TAX["fields"].keys())
STOPWORDS = set(_TAX["stopwords"])


def norm(s):
    """Lowercase and treat hyphens/slashes/underscores as spaces. The same normalisation runs in feed.js."""
    return re.sub(r"[\s\-‐-―/_]+", " ", (s or "").lower()).strip()


def term_regex(term):
    t = re.escape(norm(term)).replace(r"\ ", " ").replace(r"\*", r"\w*")
    t = t.replace(" ", r"\s")
    return re.compile(r"(?<![a-z0-9])" + t + r"(?![a-z0-9])")


_COMPILED = {f: [(term_regex(t), len(norm(t).split()) > 1) for t in terms] for f, terms in _TAX["fields"].items()}


def field_scores(title, body="", body_w=1):
    ti, bo = norm(title), norm(body)
    out = {}
    for f, terms in _COMPILED.items():
        s = 0
        for rx, multi in terms:
            w = 2 if multi else 1
            if rx.search(ti):
                s += 3 * w
            elif rx.search(bo):
                s += body_w * w
        if s:
            out[f] = s
    return out


def classify_fields(title, body="", prior=None, max_fields=3, body_w=1):
    """Fields for an item. `prior` is {field: score} from a source category (arXiv cs.LG, bioRxiv 'neuroscience'),
    which is stronger evidence than any phrase in the abstract and is added to the text score."""
    scores = field_scores(title, body, body_w)
    for f, s in (prior or {}).items():
        scores[f] = scores.get(f, 0) + s
    if not scores:
        return []
    top = max(scores.values())
    keep = [(f, s) for f, s in scores.items() if s >= 3 and s >= 0.4 * top]
    keep.sort(key=lambda x: -x[1])
    return [f for f, _ in keep[:max_fields]]


# ---------- career stage ----------
_RX = lambda p: re.compile(p, re.I)  # noqa: E731
FACULTY = _RX(r"\b(professor\w*|lecturer\w*|reader in|tenure[- ]?track|tenured|faculty|chair of|chaired|principal investigator|"
              r"group leader|head of (the )?(department|lab\w*|group|school)|full professor|assistant professor|associate professor|"
              r"senior lecturer|adjunct|instructor|\bpi\b|\bdocent\b|junior group leader|research group leader)\b")
POSTDOC = _RX(r"\b(post[- ]?docs?|postdoctoral|post[- ]doctoral|research associate|research fellow|early[- ]career (researcher|fellow\w*|scientist)|"
              r"junior (researcher|fellow)|young (researcher|investigator)|postdoctoral fellow\w*)\b")
PHD = _RX(r"\b(ph\.?\s?d\.?|doctoral|dphil|doctorate|predoctoral|pre-doctoral|graduate research assistant|graduate student|doctoral researcher)\b")
RESEARCHER = _RX(r"\b(research(er| scientist| engineer| assistant| officer| staff| specialist| technician| software engineer| fellow)|"
                 r"scientist|staff scientist|investigator|laboratory (manager|technician)|lab manager|analyst|engineer)\b")
NOT_RESEARCH = _RX(r"\b(janitor|custodian|housekeep\w*|cook|dining|bookkeeper|accountant|payroll|receptionist|secretary|security officer|"
                   r"campus police|coach|athletic\w*|admissions|recruiter|registrar|bursar|nurse|lifeguard|groundskeeper|"
                   r"food service|bus driver|mechanic|electrician|plumber|carpenter|painter|cashier|barista|custodial|"
                   r"marketing manager|fundrais\w*|development officer|financial aid|human resources|hr (partner|manager)|"
                   r"it support|help ?desk|librarian|library assistant|facilities)\b")
ADMIN = _RX(r"\b(dean|provost|chancellor|vice[- ]?president|vice[- ]?chair|chief|manager|coordinator|administrator|physician|clinician|"
            r"counsel+or|advisor|adviser|registrar|officer of|director of (admissions|operations|finance|development|communications|marketing))\b")
ACADEMIC_TITLE = _RX(r"\b(professor|lecturer|post[- ]?doc\w*\s+(fellow|researcher|associate|scholar|position)|postdoctoral\s+(fellow|researcher|associate|scholar|position)|"
                     r"ph\.?d\.?\s+(student|studentship|position)|doctoral (student|researcher|candidate|position))\b")
RESEARCH_WORD = _RX(r"\b(research\w*|science|scientific|laborator\w*|doctoral|phd|postdoc\w*|professor|lectur\w*|fellowship|studentship)\b")


def detect_stages(title, body=""):
    """Career stages a role or call is aimed at, from the title first. Returns a list drawn from
    phd / postdoc / researcher / faculty. Empty means no stage could be read."""
    t = title or ""
    stages = []
    if FACULTY.search(t):
        stages.append("faculty")
    if POSTDOC.search(t):
        stages.append("postdoc")
    if PHD.search(t) and "faculty" not in stages and "postdoc" not in stages:
        stages.append("phd")
    if not stages and RESEARCHER.search(t):
        stages.append("researcher")
    if not stages:  # fall back to the description, which is noisier, so only the strongest cues count
        b = body or ""
        if re.search(r"\b(ph\.?d\.? (student|position|studentship|scholarship)|doctoral (candidate|position|student))\b", b, re.I):
            stages.append("phd")
        elif re.search(r"\bpostdoc\w*\b", b, re.I):
            stages.append("postdoc")
        elif re.search(r"\b(professor|lecturer|faculty position|tenure)\b", b, re.I):
            stages.append("faculty")
    return stages


def is_research_role(title, body=""):
    """True when a vacancy is something a researcher, PhD student, postdoc or professor would want.
    Teaching-only and support roles are dropped."""
    if NOT_RESEARCH.search(title or ""):
        return False
    if ADMIN.search(title or "") and not ACADEMIC_TITLE.search(title or ""):
        return False
    if detect_stages(title, body):
        # "Engineer" / "Analyst" alone is not a research role: it needs a research word somewhere
        t_stages = detect_stages(title)
        if t_stages == ["researcher"] and not RESEARCH_WORD.search((title or "") + " " + (body or "")[:400]):
            return False
        return True
    return bool(RESEARCH_WORD.search(title or ""))


def grant_stages(title, body=""):
    """Grants are open to everyone unless the text says otherwise; 'any' is the honest default."""
    t = (title or "") + " " + (body or "")
    st = []
    if re.search(r"\b(ph\.?d\.? (student|candidate)|doctoral (student|candidate)|graduate (student|fellowship|research fellowship)|predoctoral|pre-doctoral|"
                 r"masters? (student|degree)|undergraduate)\b", t, re.I):
        st.append("phd")
    if re.search(r"\b(post[- ]?docs?|postdoctoral|early[- ]career|early career|junior|starting grant|young (researcher|investigator|scientist)|new investigator|"
                 r"career development|career award|mid[- ]career)\b", t, re.I):
        st.append("postdoc")
    if re.search(r"\b(senior|established|principal investigator|professor|advanced grant|consolidator|synergy|distinguished|chair|team science|center|centre|"
                 r"program grant|programme grant|large[- ]scale)\b", t, re.I):
        st.append("faculty")
    if re.search(r"\b(research (grant|project|proposal)s?|researchers?|investigator[- ]initiated|collaborative research)\b", t, re.I) and not st:
        st.append("researcher")
    return st or ["any"]
