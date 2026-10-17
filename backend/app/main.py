"""QIST Platform API — FastAPI backend.

Serves the same data contract the static frontend uses, so the site can be
switched from GitHub-Pages static mode to live mode by setting
`localStorage.qist_api_url` (or QIST.apiBase) to this server's URL.

Run:  uvicorn app.main:main_app --reload   (from backend/)
"""
import csv
import hashlib
import io
import json
import os
import re
import secrets
import sys
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import jwt
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.hash import pbkdf2_sha256
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlmodel import Field as SQLField
from sqlmodel import Session, SQLModel, create_engine, select, text

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
DATA_DIR = Path(__file__).resolve().parents[2] / "data"   # reuse the site's JSON seeds
def _db_url() -> str:
    url = os.getenv("QIST_DB_URL", "sqlite:///qist.db")
    m = re.match(r"^sqlite:////(.+)$", url)
    if m and os.getenv("QIST_ALLOW_EPHEMERAL"):          # a throwaway run on a host without the persistent disk: use /tmp
        folder = Path("/" + m.group(1)).parent
        if not (folder.is_dir() and os.access(folder, os.W_OK)):
            return "sqlite:////tmp/qist-ephemeral.db"
    return url


DB_URL = _db_url()
JWT_SECRET = os.getenv("QIST_JWT_SECRET", secrets.token_hex(32))
JWT_TTL_HOURS = 24 * 7

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))                       # the importer reuses the site's research-field vocabulary and country names
try:
    from pipeline import geo as _geo, taxonomy as _taxonomy
except Exception:                                   # a deployment without the pipeline folder still runs; imports then lack fields
    _geo = _taxonomy = None
from . import importer                              # noqa: E402

CLAIM_DAYS = int(os.getenv("QIST_CLAIM_DAYS", "60"))
TRUST_PROXY = os.getenv("QIST_TRUST_PROXY") == "1"  # behind Hugging Face / Render the client address is in X-Forwarded-For


def client_ip(request: Request) -> str:
    if TRUST_PROXY:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"


def _load_json(name, default):
    try:
        return json.loads((DATA_DIR / name).read_text(encoding="utf8"))
    except Exception:
        return default


FIELDS = set(_load_json("taxonomy.json", {}).get("fields", {})) | {"Other Research Area"}
COUNTRIES = _load_json("eligibility.json", {}).get("countries", {})   # ISO code -> English name
STAGES = {"any", "phd_student", "phd_plus", "postdoc_plus", "pi_only"}

engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
security = HTTPBearer(auto_error=False)


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------
class Person(SQLModel, table=True):
    id: Optional[int] = SQLField(default=None, primary_key=True)
    name: str
    title: str = ""
    institution: str = ""
    city: str = ""
    country: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None
    topics: str = ""          # comma-separated
    link: str = ""
    bio: str = ""
    experience: Optional[int] = None
    featured: int = 0
    photo: str = ""           # data:image/jpeg;base64,... (256px), set by the member
    orcid: str = ""           # self-declared, not verified

    def api(self) -> dict:
        d = self.model_dump()
        d["topics"] = [t for t in (self.topics or "").split("|") if t]
        return d


class User(SQLModel, table=True):
    id: Optional[int] = SQLField(default=None, primary_key=True)
    email: str = SQLField(index=True, unique=True)
    name: str
    password_hash: str
    role: str = "member"
    title: str = ""
    institution: str = ""
    topics: str = ""
    created: str = ""
    # accounts created from a member list start "unclaimed": no password, not listed, reachable only by a personal link
    status: str = "active"          # active | unclaimed
    claim_hash: str = ""            # sha256 of the invitation token; the token itself is shown once and never stored
    claim_expires: str = ""
    invited: str = ""
    source: str = ""                # where the record came from, e.g. "import 2026-10-17"


class Suppression(SQLModel, table=True):
    """People who asked not to be contacted or to be removed. Stored as a hash so the list itself is not a mailing list;
    an import skips these addresses."""
    email_hash: str = SQLField(primary_key=True)
    created: str = ""


class Profile(SQLModel, table=True):
    """Everything about a member that the directory row cannot hold. JSON so it can grow without a migration."""
    email: str = SQLField(primary_key=True)
    person_id: Optional[int] = None
    listed: bool = True
    data: str = "{}"
    updated: str = ""


class Position(SQLModel, table=True):
    """A vacancy a member posts from their lab. Shown to everyone; the owner's e-mail is never exposed."""
    id: Optional[int] = SQLField(default=None, primary_key=True)
    owner_email: str = SQLField(index=True)
    owner_name: str = ""
    title: str
    org: str = ""             # lab / institution
    department: str = ""
    country: str = ""         # ISO code
    city: str = ""
    remote: bool = False
    career_stage: str = "phd_plus"
    fields: str = "[]"        # JSON list
    summary: str = ""
    link: str = ""
    deadline: str = ""
    created: str = ""


class Paper(SQLModel, table=True):
    """A publication a member lists on the platform (self-declared; auto-fetching comes later)."""
    id: Optional[int] = SQLField(default=None, primary_key=True)
    owner_email: str = SQLField(index=True)
    owner_name: str = ""
    title: str
    authors: str = "[]"       # JSON list
    venue: str = ""
    year: Optional[int] = None
    doi: str = ""
    url: str = ""
    abstract: str = ""
    fields: str = "[]"
    created: str = ""


class FeedProfile(SQLModel, table=True):
    """The reader's matching profile for the daily feed (grants / vacancies / articles), one row per account.
    Stored as JSON text so the profile can grow fields without a schema migration."""
    email: str = SQLField(primary_key=True)
    data: str = "{}"
    updated: str = ""


class Post(SQLModel, table=True):
    id: Optional[int] = SQLField(default=None, primary_key=True)
    channel: str = SQLField(index=True)
    title: str
    body: str = ""
    link: str = ""
    deadline: str = ""
    author: str = "QIST"
    date: str = ""


class Subscriber(SQLModel, table=True):
    id: Optional[int] = SQLField(default=None, primary_key=True)
    email: str = SQLField(unique=True)
    created: str = ""


class CollabRequest(SQLModel, table=True):
    id: Optional[int] = SQLField(default=None, primary_key=True)
    from_email: str
    to_person_id: str
    to_name: str = ""
    topics: str = ""
    goal: str = ""
    date: str = ""


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


def orcid_ok(v: str) -> bool:
    """Format plus the ISO 7064 mod 11-2 check digit. Says the iD is well formed, not that it belongs to the sender."""
    if not ORCID_RE.match(v):
        return False
    total = 0
    for ch in v.replace("-", "")[:-1]:
        total = (total + int(ch)) * 2
    check = (12 - total % 11) % 11
    return v[-1] == ("X" if check == 10 else str(check))


def http_url(v: str) -> str:
    v = (v or "").strip()
    if v and not re.match(r"^https?://[^\s]+$", v):
        raise ValueError("must be an http(s) link")
    if len(v) > 400:
        raise ValueError("link too long")
    return v


def clean_fields(v: list[str]) -> list[str]:
    out = [f.strip() for f in v if f.strip()]
    bad = [f for f in out if f not in FIELDS]
    if bad:
        raise ValueError(f"unknown research field: {bad[0]}")
    return list(dict.fromkeys(out))


def clean_keywords(v: list[str]) -> list[str]:
    return list(dict.fromkeys(k.strip()[:60] for k in v if k.strip()))[:20]


class ProfileFields(BaseModel):
    """What a member can say about themselves. Every field optional so the same schema serves create and edit."""
    title: Optional[str] = Field(None, max_length=120)
    institution: Optional[str] = Field(None, max_length=160)
    country: Optional[str] = Field(None, max_length=2)          # ISO code
    city: Optional[str] = Field(None, max_length=80)
    orcid: Optional[str] = None
    fields: Optional[list[str]] = Field(None, max_length=6)
    keywords: Optional[list[str]] = Field(None, max_length=20)
    bio: Optional[str] = Field(None, max_length=1200)
    website: Optional[str] = None
    scholar: Optional[str] = None
    linkedin: Optional[str] = None
    photo: Optional[str] = None
    listed: Optional[bool] = None

    @field_validator("country")
    @classmethod
    def _country(cls, v):
        if v is None or v == "":
            return ""
        v = v.upper()
        if COUNTRIES and v not in COUNTRIES:
            raise ValueError("unknown country code")
        return v

    @field_validator("orcid")
    @classmethod
    def _orcid(cls, v):
        if not v:
            return ""
        v = v.strip().upper().replace("HTTPS://ORCID.ORG/", "")
        if not orcid_ok(v):
            raise ValueError("not a valid ORCID iD (check the digits)")
        return v

    @field_validator("fields")
    @classmethod
    def _fields(cls, v):
        return None if v is None else clean_fields(v)

    @field_validator("keywords")
    @classmethod
    def _keywords(cls, v):
        return None if v is None else clean_keywords(v)

    @field_validator("website", "scholar", "linkedin")
    @classmethod
    def _urls(cls, v):
        return None if v is None else http_url(v)

    @field_validator("photo")
    @classmethod
    def _photo(cls, v):
        if not v:
            return ""
        if not re.match(r"^data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+$", v) or len(v) > 160_000:
            raise ValueError("photo must be a small JPEG/PNG/WebP (under ~120 KB)")
        return v


class RegisterIn(ProfileFields):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    topics: list[str] = []


class ProfileIn(ProfileFields):
    name: Optional[str] = Field(None, min_length=2, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class PostIn(BaseModel):
    channel: str
    title: str = Field(min_length=3)
    body: str = ""
    link: str = ""
    deadline: str = ""


class PersonIn(BaseModel):
    name: str
    title: str = ""
    institution: str = ""
    city: str = ""
    country: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None
    topics: list[str] = []
    link: str = ""
    bio: str = ""
    experience: Optional[int] = None


FEED_STAGES = {"any", "phd_student", "phd_plus", "postdoc_plus", "pi_only"}


class FeedProfileData(BaseModel):
    stage: str = "phd_plus"
    country: str = Field("", max_length=2)
    fields: list[str] = Field(default_factory=list, max_length=6)
    keywords: list[str] = Field(default_factory=list, max_length=12)
    jobCountries: list[str] = Field(default_factory=list, max_length=8)
    remote: bool = True
    allStages: bool = False


class FeedProfileIn(BaseModel):
    profile: FeedProfileData


class SubscribeIn(BaseModel):
    email: EmailStr


class CollabIn(BaseModel):
    to_person_id: str
    to_name: str = ""
    topics: str = ""
    goal: str = "coauthor"


# --------------------------------------------------------------------------
# Auth helpers
# --------------------------------------------------------------------------
def make_token(user: User) -> str:
    payload = {
        "sub": user.email,
        "name": user.name,
        "role": user.role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_TTL_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def current_user(creds: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    if creds is None:
        raise HTTPException(401, "Not authenticated")
    try:
        return jwt.decode(creds.credentials, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")


def admin_user(user: dict = Depends(current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")
    return user


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def check_deployment() -> None:
    """Refuse to start in a way that would silently lose accounts: a database on a disk that is wiped on restart,
    or a signing key that changes on every start (every member would be signed out)."""
    if not os.getenv("QIST_JWT_SECRET"):
        print("[qist] WARNING: QIST_JWT_SECRET is not set; members will be signed out on every restart.", flush=True)
    url = os.getenv("QIST_DB_URL", "")
    m = re.match(r"^sqlite:////(.+)$", url)
    if m and not os.getenv("QIST_ALLOW_EPHEMERAL"):
        folder = Path("/" + m.group(1)).parent
        if not (folder.is_dir() and os.access(folder, os.W_OK)):
            raise SystemExit(f"[qist] The database folder {folder} does not exist or is not writable. On Hugging Face, enable Persistent "
                             f"Storage for the Space (it is mounted at /data). Set QIST_ALLOW_EPHEMERAL=1 only for a throwaway test.")


def ensure_columns() -> None:
    """create_all adds new tables but never new columns. A database created before photo/orcid/created existed
    would fail on every query, so add what is missing."""
    want = {"person": {"photo": "TEXT DEFAULT ''", "orcid": "TEXT DEFAULT ''"},
            "user": {"created": "TEXT DEFAULT ''", "status": "TEXT DEFAULT 'active'", "claim_hash": "TEXT DEFAULT ''",
                     "claim_expires": "TEXT DEFAULT ''", "invited": "TEXT DEFAULT ''", "source": "TEXT DEFAULT ''"}}
    with engine.begin() as c:
        for table, cols in want.items():
            have = {r[1] for r in c.execute(text(f'PRAGMA table_info("{table}")')).fetchall()} if engine.url.get_backend_name() == "sqlite" else set(cols)
            for col, ddl in cols.items():
                if col not in have:
                    c.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {col} {ddl}'))


# --------------------------------------------------------------------------
# Seeding from the site's JSON files
# --------------------------------------------------------------------------
def seed() -> None:
    with Session(engine) as s:
        if s.exec(select(Person)).first() is None and (DATA_DIR / "people.json").exists():
            for p in json.loads((DATA_DIR / "people.json").read_text()):
                s.add(Person(
                    name=p["name"], title=p.get("title", ""), institution=p.get("institution", ""),
                    city=p.get("city", ""), country=p.get("country", ""),
                    lat=p.get("lat"), lng=p.get("lng"),
                    topics="|".join(p.get("topics", [])), link=p.get("link", ""),
                    bio=p.get("bio", ""), experience=p.get("experience"),
                    featured=p.get("featured", 0),
                ))
        if s.exec(select(Post)).first() is None and (DATA_DIR / "posts.json").exists():
            for p in json.loads((DATA_DIR / "posts.json").read_text()):
                s.add(Post(
                    channel=p["channel"], title=p["title"], body=p.get("body", ""),
                    link=p.get("link", ""), deadline=p.get("deadline", ""),
                    author=p.get("author", "QIST"), date=p.get("date", ""),
                ))
        if s.exec(select(User)).first() is None:
            # The old default password was published in this repository. Without QIST_ADMIN_PASSWORD a random
            # one is generated and printed once, so a forgotten variable cannot leave a known admin login.
            pw = os.getenv("QIST_ADMIN_PASSWORD")
            if not pw:
                pw = secrets.token_urlsafe(14)
                print(f"[qist] QIST_ADMIN_PASSWORD not set - generated admin password for admin@qist.kz: {pw}", flush=True)
            s.add(User(email="admin@qist.kz", name="QIST Admin", role="admin", created=_now(),
                       password_hash=pbkdf2_sha256.hash(pw)))
        s.commit()


# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------
main_app = FastAPI(title="QIST Platform API", version="1.0.0")
main_app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("QIST_CORS_ORIGINS", "*").split(","),
    allow_methods=["*"], allow_headers=["*"],
)


@main_app.on_event("startup")
def on_startup() -> None:
    check_deployment()
    SQLModel.metadata.create_all(engine)
    ensure_columns()
    seed()


@main_app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "qist-api"}


# ---- auth ----
def _profile_data(row: Optional["Profile"]) -> dict:
    return json.loads(row.data) if row and row.data else {}


def apply_profile(s: Session, user: "User", body: ProfileFields, name: Optional[str] = None) -> "Profile":
    """Write the member's details to their Profile row and, when they agree to be listed, to the directory row."""
    row = s.get(Profile, user.email) or Profile(email=user.email)
    data = _profile_data(row)
    given = body.model_dump(exclude_unset=True)
    if name:
        user.name = name
    for k in ("fields", "keywords", "bio", "website", "scholar", "linkedin", "orcid", "country", "city"):
        if k in given and given[k] is not None:
            data[k] = given[k]
    for k in ("title", "institution"):
        if given.get(k) is not None:
            setattr(user, k, given[k])
    if given.get("listed") is not None:
        row.listed = bool(given["listed"])
    if given.get("photo") is not None:
        data["photo"] = given["photo"]
    row.data, row.updated = json.dumps(data, ensure_ascii=False), _now()

    person = s.get(Person, row.person_id) if row.person_id else None
    if row.listed:
        if person is None:
            person = Person(name=user.name)
        person.name = user.name
        person.title = user.title or "Researcher"
        person.institution = user.institution
        person.country = COUNTRIES.get(data.get("country", ""), data.get("country", ""))
        person.city = data.get("city", "")
        person.topics = "|".join((data.get("keywords") or []) + [f for f in (data.get("fields") or []) if f not in (data.get("keywords") or [])])
        person.link = data.get("website") or data.get("scholar") or (f"https://orcid.org/{data['orcid']}" if data.get("orcid") else "")
        person.bio = data.get("bio", "") or "New QIST member."
        person.photo = data.get("photo", "")
        person.orcid = data.get("orcid", "")
        s.add(person); s.flush()
        row.person_id = person.id
    elif person is not None:           # un-listing removes the directory row at once
        s.delete(person)
        row.person_id = None
    s.add(user); s.add(row)
    return row


def me_payload(user: "User", row: Optional["Profile"]) -> dict:
    d = _profile_data(row)
    return {"name": user.name, "email": user.email, "role": user.role, "title": user.title, "institution": user.institution,
            "country": d.get("country", ""), "city": d.get("city", ""), "orcid": d.get("orcid", ""), "fields": d.get("fields", []),
            "keywords": d.get("keywords", []), "bio": d.get("bio", ""), "website": d.get("website", ""), "scholar": d.get("scholar", ""),
            "linkedin": d.get("linkedin", ""), "photo": d.get("photo", ""), "listed": row.listed if row else True}


@main_app.post("/api/auth/register")
def register(body: RegisterIn):
    with Session(engine) as s:
        if s.exec(select(User).where(User.email == body.email.lower())).first():
            raise HTTPException(400, "An account with this email already exists.")
        u = User(email=body.email.lower(), name=body.name, password_hash=pbkdf2_sha256.hash(body.password),
                 title=body.title or "", institution=body.institution or "", topics="|".join(body.topics), created=_now())
        s.add(u)
        s.flush()
        if body.keywords is None and body.topics:
            body.keywords = clean_keywords(body.topics)
        apply_profile(s, u, body)
        s.commit()
        s.refresh(u)
        return {"email": u.email, "name": u.name, "role": u.role, "token": make_token(u)}


@main_app.get("/api/me/profile")
def get_my_profile(user: dict = Depends(current_user)):
    with Session(engine) as s:
        u = s.exec(select(User).where(User.email == user["sub"])).first()
        if not u:
            raise HTTPException(404, "Account not found")
        return me_payload(u, s.get(Profile, u.email))


@main_app.put("/api/me/profile")
def put_my_profile(body: ProfileIn, user: dict = Depends(current_user)):
    with Session(engine) as s:
        u = s.exec(select(User).where(User.email == user["sub"])).first()
        if not u:
            raise HTTPException(404, "Account not found")
        apply_profile(s, u, body, name=body.name)
        s.commit()
        return me_payload(u, s.get(Profile, u.email))


@main_app.delete("/api/me", status_code=204)
def delete_me(user: dict = Depends(current_user)):
    """Delete the account and everything the member put on the platform."""
    with Session(engine) as s:
        email = user["sub"]
        row = s.get(Profile, email)
        if row and row.person_id and (p := s.get(Person, row.person_id)):
            s.delete(p)
        if row:
            s.delete(row)
        for model in (Position, Paper):
            for it in s.exec(select(model).where(model.owner_email == email)).all():
                s.delete(it)
        if (fp := s.get(FeedProfile, email)):
            s.delete(fp)
        for u in s.exec(select(User).where(User.email == email)).all():
            s.delete(u)
        s.commit()


@main_app.post("/api/auth/login")
def login(body: LoginIn):
    with Session(engine) as s:
        u = s.exec(select(User).where(User.email == body.email.lower())).first()
        if not u or u.status != "active" or not u.password_hash or not pbkdf2_sha256.verify(body.password, u.password_hash):
            raise HTTPException(401, "Invalid email or password.")
        return {"email": u.email, "name": u.name, "role": u.role, "token": make_token(u)}


# ---- people ----
@main_app.get("/api/people")
def list_people(
    q: str = "", topic: str = "", country: str = "",
    min_experience: Optional[int] = Query(None), max_experience: Optional[int] = Query(None),
):
    with Session(engine) as s:
        people = [p.api() for p in s.exec(select(Person)).all()]
    if country:
        people = [p for p in people if p["country"] == country]
    if topic:
        people = [p for p in people if topic in p["topics"]]
    if min_experience is not None:
        people = [p for p in people if (p.get("experience") or 0) >= min_experience]
    if max_experience is not None:
        people = [p for p in people if (p.get("experience") or 0) <= max_experience]
    if q:
        ql = q.lower()
        people = [p for p in people if ql in json.dumps(p, ensure_ascii=False).lower()]
    return people


@main_app.post("/api/people", status_code=201)
def add_person(body: PersonIn, _: dict = Depends(admin_user)):
    with Session(engine) as s:
        p = Person(**{**body.model_dump(exclude={"topics"}), "topics": "|".join(body.topics)})
        s.add(p); s.commit(); s.refresh(p)
        return p.api()


@main_app.put("/api/people/{person_id}")
def edit_person(person_id: int, body: PersonIn, _: dict = Depends(admin_user)):
    with Session(engine) as s:
        p = s.get(Person, person_id)
        if not p:
            raise HTTPException(404, "Person not found")
        for k, v in body.model_dump(exclude={"topics"}).items():
            setattr(p, k, v)
        p.topics = "|".join(body.topics)
        s.add(p); s.commit(); s.refresh(p)
        return p.api()


@main_app.delete("/api/people/{person_id}", status_code=204)
def delete_person(person_id: int, _: dict = Depends(admin_user)):
    with Session(engine) as s:
        p = s.get(Person, person_id)
        if not p:
            raise HTTPException(404, "Person not found")
        s.delete(p); s.commit()


# ---- posts ----
@main_app.get("/api/posts")
def list_posts(channel: str = ""):
    with Session(engine) as s:
        stmt = select(Post)
        if channel:
            stmt = stmt.where(Post.channel == channel)
        posts = s.exec(stmt).all()
    return sorted((p.model_dump() for p in posts), key=lambda p: p["date"] or "", reverse=True)


@main_app.post("/api/posts", status_code=201)
def add_post(body: PostIn, user: dict = Depends(current_user)):
    with Session(engine) as s:
        p = Post(**body.model_dump(), author=user["name"],
                 date=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        s.add(p); s.commit(); s.refresh(p)
        return p.model_dump()


@main_app.delete("/api/posts/{post_id}", status_code=204)
def delete_post(post_id: int, _: dict = Depends(admin_user)):
    with Session(engine) as s:
        p = s.get(Post, post_id)
        if not p:
            raise HTTPException(404, "Post not found")
        s.delete(p); s.commit()


# ---- newsletter ----
@main_app.get("/api/newsletter")
def newsletter():
    f = DATA_DIR / "newsletter.json"
    return json.loads(f.read_text()) if f.exists() else []


@main_app.post("/api/subscribe", status_code=201)
def subscribe(body: SubscribeIn):
    with Session(engine) as s:
        if s.exec(select(Subscriber).where(Subscriber.email == body.email.lower())).first():
            return {"status": "already subscribed"}
        s.add(Subscriber(email=body.email.lower(),
                         created=datetime.now(timezone.utc).isoformat()))
        s.commit()
    return {"status": "subscribed"}


# ---- daily feed profile ----
@main_app.get("/api/me/feed-profile")
def get_feed_profile(user: dict = Depends(current_user)):
    with Session(engine) as s:
        row = s.get(FeedProfile, user["sub"])
        return {"profile": json.loads(row.data) if row else None, "updated": row.updated if row else None}


@main_app.put("/api/me/feed-profile")
def put_feed_profile(body: FeedProfileIn, user: dict = Depends(current_user)):
    p = body.profile
    if p.stage not in FEED_STAGES:
        raise HTTPException(422, "Unknown career stage.")
    clean = p.model_copy(update={
        "country": p.country.upper(),
        "fields": [f.strip()[:80] for f in p.fields if f.strip()],
        "keywords": [k.strip()[:60] for k in p.keywords if k.strip()],
        "jobCountries": [c.strip().upper()[:2] for c in p.jobCountries if c.strip()],
    })
    now = datetime.now(timezone.utc).isoformat()
    with Session(engine) as s:
        row = s.get(FeedProfile, user["sub"]) or FeedProfile(email=user["sub"])
        row.data, row.updated = clean.model_dump_json(), now
        s.add(row)
        s.commit()
    return {"status": "saved", "updated": now}


# ---- positions posted by members ----
class PositionIn(BaseModel):
    title: str = Field(min_length=5, max_length=140)
    org: str = Field(min_length=2, max_length=160)
    department: str = Field("", max_length=120)
    country: str = Field("", max_length=2)
    city: str = Field("", max_length=80)
    remote: bool = False
    career_stage: str = "phd_plus"
    fields: list[str] = Field(default_factory=list, max_length=4)
    summary: str = Field(min_length=20, max_length=1500)
    link: str
    deadline: str = ""

    @field_validator("country")
    @classmethod
    def _c(cls, v):
        v = (v or "").upper()
        if v and COUNTRIES and v not in COUNTRIES:
            raise ValueError("unknown country code")
        return v

    @field_validator("career_stage")
    @classmethod
    def _s(cls, v):
        if v not in STAGES:
            raise ValueError("unknown career stage")
        return v

    @field_validator("fields")
    @classmethod
    def _f(cls, v):
        return clean_fields(v)

    @field_validator("link")
    @classmethod
    def _l(cls, v):
        v = http_url(v)
        if not v:
            raise ValueError("a link to the full announcement is required")
        return v

    @field_validator("deadline")
    @classmethod
    def _d(cls, v):
        if not v:
            return ""
        try:
            d = date.fromisoformat(v)
        except ValueError:
            raise ValueError("deadline must be YYYY-MM-DD")
        if d < date.today():
            raise ValueError("deadline is in the past")
        return v


POSITIONS_PER_DAY, POSITIONS_ACTIVE_MAX = 5, 25


def position_api(p: Position) -> dict:
    """The shape of data/opportunities.json, so the Opportunities page treats a member's post like any other call."""
    where = ", ".join(x for x in (p.city, COUNTRIES.get(p.country, "")) if x)
    return {
        "id": f"m-{p.id}", "origin": "community", "type": "academic_job", "status": "published", "title": p.title,
        "organization": p.org + (f", {p.department}" if p.department else ""), "country": p.country, "city": p.city, "remote": p.remote,
        "summary": p.summary, "fields": json.loads(p.fields or "[]"), "all_fields": not json.loads(p.fields or "[]"), "methods_required": [],
        "career_stage": p.career_stage, "eligibility": {"programme": "open", "note": ""}, "deadline": p.deadline or None,
        "source_url": p.link, "source_name": f"Posted by {p.owner_name}", "posted_by": p.owner_name, "where": where,
        "curated_at": (p.created or "")[:10],
    }


def _active(p: Position) -> bool:
    return not p.deadline or p.deadline >= date.today().isoformat()


@main_app.get("/api/positions")
def list_positions():
    with Session(engine) as s:
        rows = s.exec(select(Position).order_by(Position.id.desc()).limit(500)).all()
    return [position_api(p) for p in rows if _active(p)]


@main_app.get("/api/me/positions")
def my_positions(user: dict = Depends(current_user)):
    with Session(engine) as s:
        rows = s.exec(select(Position).where(Position.owner_email == user["sub"]).order_by(Position.id.desc())).all()
    return [dict(position_api(p), expired=not _active(p)) for p in rows]


@main_app.post("/api/positions", status_code=201)
def add_position(body: PositionIn, user: dict = Depends(current_user)):
    with Session(engine) as s:
        mine = s.exec(select(Position).where(Position.owner_email == user["sub"])).all()
        since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
        if sum(1 for p in mine if p.created >= since) >= POSITIONS_PER_DAY:
            raise HTTPException(429, f"At most {POSITIONS_PER_DAY} positions a day.")
        if sum(1 for p in mine if _active(p)) >= POSITIONS_ACTIVE_MAX:
            raise HTTPException(429, "Remove an old position before posting another.")
        if any(p.title.strip().lower() == body.title.strip().lower() and _active(p) for p in mine):
            raise HTTPException(409, "You have already posted a position with this title.")
        p = Position(owner_email=user["sub"], owner_name=user["name"], created=_now(),
                     **{**body.model_dump(exclude={"fields"}), "fields": json.dumps(body.fields)})
        s.add(p); s.commit(); s.refresh(p)
        return position_api(p)


def _owned(s: Session, model, item_id: int, user: dict):
    it = s.get(model, item_id)
    if not it:
        raise HTTPException(404, "Not found")
    if it.owner_email != user["sub"] and user.get("role") != "admin":
        raise HTTPException(403, "This is not yours")
    return it


@main_app.put("/api/positions/{position_id}")
def edit_position(position_id: int, body: PositionIn, user: dict = Depends(current_user)):
    with Session(engine) as s:
        p = _owned(s, Position, position_id, user)
        for k, v in body.model_dump(exclude={"fields"}).items():
            setattr(p, k, v)
        p.fields = json.dumps(body.fields)
        s.add(p); s.commit(); s.refresh(p)
        return position_api(p)


@main_app.delete("/api/positions/{position_id}", status_code=204)
def delete_position(position_id: int, user: dict = Depends(current_user)):
    with Session(engine) as s:
        s.delete(_owned(s, Position, position_id, user)); s.commit()


# ---- members' papers ----
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")


class PaperIn(BaseModel):
    title: str = Field(min_length=5, max_length=300)
    authors: list[str] = Field(default_factory=list, max_length=40)
    venue: str = Field("", max_length=160)
    year: Optional[int] = Field(None, ge=1900, le=2100)
    doi: str = ""
    url: str = ""
    abstract: str = Field("", max_length=1500)
    fields: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("doi")
    @classmethod
    def _doi(cls, v):
        v = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", (v or "").strip(), flags=re.I)
        if v and not DOI_RE.match(v):
            raise ValueError("not a DOI")
        return v.lower()

    @field_validator("url")
    @classmethod
    def _url(cls, v):
        return http_url(v)

    @field_validator("fields")
    @classmethod
    def _f(cls, v):
        return clean_fields(v)

    @field_validator("authors")
    @classmethod
    def _a(cls, v):
        return [a.strip()[:80] for a in v if a.strip()]


PAPERS_PER_MEMBER = 300


def paper_api(p: Paper) -> dict:
    link = p.url or (f"https://doi.org/{p.doi}" if p.doi else "")
    return {"id": f"p-{p.id}", "kind": "paper", "title": p.title, "authors": json.loads(p.authors or "[]"), "venue": p.venue,
            "year": p.year, "doi": p.doi, "url": link, "summary": p.abstract, "fields": json.loads(p.fields or "[]"),
            "posted": (p.created or "")[:10], "first_seen": (p.created or "")[:10], "added_by": p.owner_name}


def _add_paper(s: Session, user: dict, body: PaperIn, have: list[Paper]) -> Optional[Paper]:
    if not (body.doi or body.url):
        raise ValueError("a DOI or a link is required, so readers can open the paper")
    key = body.doi or body.title.strip().lower()
    if any((p.doi or p.title.strip().lower()) == key for p in have):
        return None
    p = Paper(owner_email=user["sub"], owner_name=user["name"], created=_now(),
              **{**body.model_dump(exclude={"authors", "fields"}), "authors": json.dumps(body.authors), "fields": json.dumps(body.fields)})
    s.add(p)
    have.append(p)
    return p


@main_app.get("/api/papers")
def list_papers(q: str = "", field: str = "", limit: int = Query(200, le=500)):
    with Session(engine) as s:
        rows = s.exec(select(Paper).order_by(Paper.id.desc()).limit(2000)).all()
    items = [paper_api(p) for p in rows]
    if field:
        items = [i for i in items if field in i["fields"]]
    if q:
        ql = q.lower()
        items = [i for i in items if ql in (i["title"] + " " + i["summary"] + " " + " ".join(i["authors"])).lower()]
    items.sort(key=lambda i: ((i["year"] or 0), i["posted"]), reverse=True)
    return items[:limit]


@main_app.get("/api/me/papers")
def my_papers(user: dict = Depends(current_user)):
    with Session(engine) as s:
        return [paper_api(p) for p in s.exec(select(Paper).where(Paper.owner_email == user["sub"]).order_by(Paper.id.desc())).all()]


@main_app.post("/api/papers", status_code=201)
def add_paper(body: PaperIn, user: dict = Depends(current_user)):
    with Session(engine) as s:
        have = s.exec(select(Paper).where(Paper.owner_email == user["sub"])).all()
        if len(have) >= PAPERS_PER_MEMBER:
            raise HTTPException(429, "Paper limit reached.")
        try:
            p = _add_paper(s, user, body, have)
        except ValueError as e:
            raise HTTPException(422, str(e))
        if p is None:
            raise HTTPException(409, "You have already added this paper.")
        s.commit(); s.refresh(p)
        return paper_api(p)


@main_app.post("/api/papers/bulk")
def add_papers_bulk(body: list[PaperIn], user: dict = Depends(current_user)):
    """For the ORCID import: adds what is new, skips what is already there or has no way to be opened."""
    if len(body) > 100:
        raise HTTPException(422, "At most 100 papers at a time.")
    with Session(engine) as s:
        have = s.exec(select(Paper).where(Paper.owner_email == user["sub"])).all()
        added = skipped = 0
        for item in body:
            if len(have) >= PAPERS_PER_MEMBER:
                skipped += 1
                continue
            try:
                added, skipped = (added + 1, skipped) if _add_paper(s, user, item, have) else (added, skipped + 1)
            except ValueError:
                skipped += 1
        s.commit()
    return {"added": added, "skipped": skipped}


@main_app.delete("/api/papers/{paper_id}", status_code=204)
def delete_paper(paper_id: int, user: dict = Depends(current_user)):
    with Session(engine) as s:
        s.delete(_owned(s, Paper, paper_id, user)); s.commit()


# ---- CV text extraction (the analysis itself happens in the browser) ----
_cv_hits: dict[str, list[float]] = {}
CV_MAX = 5 * 1024 * 1024


def _docx_text(raw: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        xml = z.read("word/document.xml").decode("utf8", "ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


@main_app.post("/api/cv/extract")
async def cv_extract(request: Request, file: UploadFile = File(...)):
    """Turns an uploaded CV (PDF, DOCX or text) into plain text and forgets the file. Nothing is stored."""
    import time
    ip = client_ip(request)
    now = time.time()
    hits = [t for t in _cv_hits.get(ip, []) if now - t < 3600]
    if len(hits) >= 15:
        raise HTTPException(429, "Too many uploads from this address; try again in an hour.")
    _cv_hits[ip] = hits + [now]
    raw = await file.read(CV_MAX + 1)
    if len(raw) > CV_MAX:
        raise HTTPException(413, "The file is larger than 5 MB.")
    name = (file.filename or "").lower()
    try:
        if raw[:4] == b"%PDF" or name.endswith(".pdf"):
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            if reader.is_encrypted:
                raise HTTPException(422, "The PDF is password-protected.")
            text = "\n".join((pg.extract_text() or "") for pg in reader.pages[:30])
        elif raw[:2] == b"PK" or name.endswith(".docx"):
            text = _docx_text(raw)
        elif name.endswith((".txt", ".md", ".text")):
            text = raw.decode("utf8", "ignore")
        else:
            raise HTTPException(415, "Upload a PDF, DOCX or text file.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, "The file could not be read. Paste the text of your CV instead.")
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text) < 40:
        raise HTTPException(422, "No text found - a scanned CV needs to be pasted as text.")
    return {"text": text[:60000], "chars": len(text)}


# ---- admin: the members database ----
@main_app.get("/api/admin/members")
def admin_members(_: dict = Depends(admin_user)):
    with Session(engine) as s:
        users = s.exec(select(User)).all()
        profiles = {p.email: p for p in s.exec(select(Profile)).all()}
        pos = [p.owner_email for p in s.exec(select(Position)).all()]
        pap = [p.owner_email for p in s.exec(select(Paper)).all()]
    out = []
    for u in users:
        d = _profile_data(profiles.get(u.email))
        out.append({"name": u.name, "email": u.email, "role": u.role, "title": u.title, "institution": u.institution,
                    "country": COUNTRIES.get(d.get("country", ""), d.get("country", "")), "city": d.get("city", ""),
                    "orcid": d.get("orcid", ""), "fields": d.get("fields", []), "keywords": d.get("keywords", []),
                    "website": d.get("website", ""), "scholar": d.get("scholar", ""), "linkedin": d.get("linkedin", ""),
                    "has_photo": bool(d.get("photo")), "listed": profiles[u.email].listed if u.email in profiles else None,
                    "positions": pos.count(u.email), "papers": pap.count(u.email), "created": u.created,
                    "status": u.status, "invited": u.invited, "source": u.source})
    return sorted(out, key=lambda m: m["created"] or "", reverse=True)


@main_app.get("/api/admin/export.csv")
def admin_export(user: dict = Depends(admin_user)):
    rows = admin_members(user)
    buf = io.StringIO()
    cols = ["name", "email", "status", "title", "institution", "country", "city", "orcid", "fields", "keywords", "website", "scholar",
            "linkedin", "listed", "positions", "papers", "created", "invited"]
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([_csv_safe("; ".join(r[c]) if isinstance(r[c], list) else r[c]) for c in cols])
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="qist-members.csv"'})


def _csv_safe(v) -> str:
    """A cell that starts with = + - @ is executed as a formula by Excel; members type these cells themselves."""
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


# ---- invitations: accounts made from a member list, claimed by their owner through a personal link ----
def _sha(v: str) -> str:
    return hashlib.sha256(v.encode("utf8")).hexdigest()


def _site_url(v: str) -> str:
    v = (v or "").strip()
    if not re.match(r"^https?://[^\s]+$", v):
        raise HTTPException(422, "site_url must be the address of the site, starting with http(s)://")
    return re.sub(r"/[^/]*\.html?$", "", v).rstrip("/")


def _issue_claim(u: "User") -> str:
    token = secrets.token_urlsafe(32)
    u.claim_hash = _sha(token)
    u.claim_expires = (datetime.now(timezone.utc) + timedelta(days=CLAIM_DAYS)).isoformat(timespec="seconds")
    u.invited = _now()
    return token


def _links_csv(rows: list[tuple["User", str]], site: str) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["name", "email", "claim_link", "expires"])
    for u, token in rows:
        w.writerow([_csv_safe(u.name), _csv_safe(u.email), f"{site}/claim.html?t={token}", u.claim_expires[:10]])
    return buf.getvalue()


def _classify(field_text: str, body: str) -> list[str]:
    direct = [f for f in FIELDS if f != "Other Research Area" and f.lower() in (field_text or "").lower()]
    if direct:
        return direct[:6]
    return _taxonomy.classify_fields(field_text, body) if _taxonomy else []


def _country_code(text: str) -> str:
    found = _geo.find_countries(text) if _geo else []
    return found[0] if found else ""


def _parse_upload(s: Session, raw: bytes):
    suppressed = {r.email_hash for r in s.exec(select(Suppression)).all()}
    existing = {u.email for u in s.exec(select(User)).all()}
    # suppression is stored hashed, so the importer is given the hashes of the addresses it meets via a wrapper set
    class _Hashed(set):
        def __contains__(self, e):                       # noqa: D401
            return _sha(e) in suppressed
    return importer.parse_workbook(raw, _classify, _country_code, suppressed=_Hashed(), existing=existing)


@main_app.post("/api/admin/import")
async def admin_import(file: UploadFile = File(...), site_url: str = Form(...), commit: bool = Form(False), user: dict = Depends(admin_user)):
    """Preview (commit=false) or create (commit=true) unclaimed accounts from a spreadsheet. Commit returns the personal links
    as CSV, once: the tokens are stored hashed and cannot be shown again (use regenerate to issue new ones)."""
    site = _site_url(site_url)
    raw = await file.read(10 * 1024 * 1024 + 1)
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, "The file is larger than 10 MB.")
    try:
        with Session(engine) as s:
            records, report = _parse_upload(s, raw)
    except Exception:
        raise HTTPException(422, "The file could not be read as an .xlsx workbook.")
    report["sample"] = [{k: r[k] for k in ("name", "email", "institution", "country", "fields")} for r in records[:5]]
    report["no_email"], report["bad_email"] = report["no_email"][:300], report["bad_email"][:300]
    if not commit:
        return {"committed": False, **report}
    rows, now = [], _now()
    with Session(engine) as s:
        for r in records:
            if s.exec(select(User).where(User.email == r["email"])).first():
                continue
            u = User(email=r["email"], name=r["name"], password_hash="", role="member", title=r["title"], institution=r["institution"],
                     created=now, status="unclaimed", source=f"import {now[:10]}")
            s.add(u)
            s.flush()
            data = {"fields": r["fields"], "keywords": r["keywords"], "country": r["country"], "city": r["city"], "linkedin": r["linkedin"]}
            s.add(Profile(email=u.email, listed=False, data=json.dumps(data, ensure_ascii=False), updated=now))
            rows.append((u, _issue_claim(u)))
        s.commit()
        csv_text = _links_csv(rows, site)
    return {"committed": True, "created": len(rows), "csv": csv_text, **{k: v for k, v in report.items() if k != "records"}}


class RegenerateIn(BaseModel):
    site_url: str
    emails: Optional[list[EmailStr]] = None      # None = every unclaimed account that has not been removed


@main_app.post("/api/admin/invites/regenerate")
def admin_regenerate(body: RegenerateIn, _: dict = Depends(admin_user)):
    """New personal links for unclaimed accounts. The old links stop working."""
    site = _site_url(body.site_url)
    wanted = {e.lower() for e in body.emails} if body.emails is not None else None
    rows = []
    with Session(engine) as s:
        for u in s.exec(select(User).where(User.status == "unclaimed")).all():
            if wanted is not None and u.email not in wanted:
                continue
            rows.append((u, _issue_claim(u)))
            s.add(u)
        s.commit()
        csv_text = _links_csv(rows, site)
    return {"issued": len(rows), "csv": csv_text}


@main_app.delete("/api/admin/unclaimed")
def admin_delete_unclaimed(older_than_days: int = Query(..., ge=0), _: dict = Depends(admin_user)):
    """Delete unclaimed accounts created at least this many days ago (data minimisation for people who never came)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat(timespec="seconds")
    n = 0
    with Session(engine) as s:
        for u in s.exec(select(User).where(User.status == "unclaimed")).all():
            if (u.created or "") <= cutoff:
                if (pr := s.get(Profile, u.email)):
                    s.delete(pr)
                s.delete(u); n += 1
        s.commit()
    return {"deleted": n}


_claim_hits: dict[str, list[float]] = {}


def _claim_user(s: Session, token: str, request: Request) -> "User":
    import time
    ip, now = client_ip(request), time.time()
    hits = [t for t in _claim_hits.get(ip, []) if now - t < 3600]
    if len(hits) >= 60:
        raise HTTPException(429, "Too many attempts from this address; try again later.")
    _claim_hits[ip] = hits + [now]
    gone = HTTPException(404, "This invitation link is not valid any more.")       # one answer for wrong, used and expired
    if not token or len(token) > 100:
        raise gone
    u = s.exec(select(User).where(User.claim_hash == _sha(token))).first()
    if not u or u.status != "unclaimed" or not u.claim_hash:
        raise gone
    if u.claim_expires and u.claim_expires < _now():
        raise gone
    return u


@main_app.get("/api/claim/{token}")
def claim_get(token: str, request: Request):
    """What we prepared for this person, shown so they can check it. Needs the personal link; nothing is searchable."""
    with Session(engine) as s:
        u = _claim_user(s, token, request)
        d = _profile_data(s.get(Profile, u.email))
        return {"name": u.name, "email": u.email, "title": u.title, "institution": u.institution, "country": d.get("country", ""),
                "city": d.get("city", ""), "fields": d.get("fields", []), "keywords": d.get("keywords", []), "linkedin": d.get("linkedin", ""),
                "expires": (u.claim_expires or "")[:10]}


class ClaimIn(ProfileFields):
    name: Optional[str] = Field(None, min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=200)
    accept_terms: bool = False


@main_app.post("/api/claim/{token}")
def claim_accept(token: str, body: ClaimIn, request: Request):
    """The owner accepts the prepared profile (after editing it if they like), chooses a password and consents (or not) to being listed."""
    if not body.accept_terms:
        raise HTTPException(422, "Please confirm that you accept the terms to continue.")
    with Session(engine) as s:
        u = _claim_user(s, token, request)
        u.password_hash = pbkdf2_sha256.hash(body.password)
        u.status, u.claim_hash, u.claim_expires = "active", "", ""
        if body.listed is None:
            body.listed = False                       # listing is opt-in
        apply_profile(s, u, body, name=body.name)
        s.commit()
        s.refresh(u)
        return {"email": u.email, "name": u.name, "role": u.role, "token": make_token(u)}


@main_app.post("/api/claim/{token}/decline", status_code=204)
def claim_decline(token: str, request: Request):
    """"This is not me / remove my record": deletes everything and remembers (as a hash) not to import the address again."""
    with Session(engine) as s:
        u = _claim_user(s, token, request)
        s.merge(Suppression(email_hash=_sha(u.email), created=_now()))
        if (pr := s.get(Profile, u.email)):
            s.delete(pr)
        s.delete(u)
        s.commit()


# ---- matching / collaboration ----
@main_app.post("/api/collab", status_code=201)
def collab(body: CollabIn, user: dict = Depends(current_user)):
    with Session(engine) as s:
        s.add(CollabRequest(from_email=user["sub"], to_person_id=body.to_person_id,
                            to_name=body.to_name, topics=body.topics, goal=body.goal,
                            date=datetime.now(timezone.utc).strftime("%Y-%m-%d")))
        s.commit()
    return {"status": "recorded"}


@main_app.get("/api/collab")
def list_collab(user: dict = Depends(admin_user)):
    with Session(engine) as s:
        return [c.model_dump() for c in s.exec(select(CollabRequest)).all()]


@main_app.get("/api/subscribers")
def list_subscribers(_: dict = Depends(admin_user)):
    with Session(engine) as s:
        return [x.model_dump(exclude={"id"}) for x in s.exec(select(Subscriber)).all()]
