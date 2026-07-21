"""QIST Platform API — FastAPI backend.

Serves the same data contract the static frontend uses, so the site can be
switched from GitHub-Pages static mode to live mode by setting
`localStorage.qist_api_url` (or QIST.apiBase) to this server's URL.

Run:  uvicorn app.main:main_app --reload   (from backend/)
"""
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import jwt
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.hash import pbkdf2_sha256
from pydantic import BaseModel, EmailStr, Field
from sqlmodel import Field as SQLField
from sqlmodel import Session, SQLModel, create_engine, select

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
DATA_DIR = Path(__file__).resolve().parents[2] / "data"   # reuse the site's JSON seeds
DB_URL = os.getenv("QIST_DB_URL", "sqlite:///qist.db")
JWT_SECRET = os.getenv("QIST_JWT_SECRET", secrets.token_hex(32))
JWT_TTL_HOURS = 24 * 7

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
class RegisterIn(BaseModel):
    name: str = Field(min_length=2)
    email: EmailStr
    password: str = Field(min_length=8)
    title: str = ""
    institution: str = ""
    topics: list[str] = []


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
            s.add(User(email="admin@qist.kz", name="QIST Admin", role="admin",
                       password_hash=pbkdf2_sha256.hash(os.getenv("QIST_ADMIN_PASSWORD", "qist-admin-2026"))))
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
    SQLModel.metadata.create_all(engine)
    seed()


@main_app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "qist-api"}


# ---- auth ----
@main_app.post("/api/auth/register")
def register(body: RegisterIn):
    with Session(engine) as s:
        if s.exec(select(User).where(User.email == body.email.lower())).first():
            raise HTTPException(400, "An account with this email already exists.")
        u = User(email=body.email.lower(), name=body.name,
                 password_hash=pbkdf2_sha256.hash(body.password),
                 title=body.title, institution=body.institution,
                 topics="|".join(body.topics))
        s.add(u)
        # new members appear in the directory automatically
        s.add(Person(name=body.name, title=body.title or "Researcher",
                     institution=body.institution, country="Kazakhstan",
                     topics="|".join(body.topics), bio="New QIST member."))
        s.commit()
        s.refresh(u)
        return {"email": u.email, "name": u.name, "role": u.role, "token": make_token(u)}


@main_app.post("/api/auth/login")
def login(body: LoginIn):
    with Session(engine) as s:
        u = s.exec(select(User).where(User.email == body.email.lower())).first()
        if not u or not pbkdf2_sha256.verify(body.password, u.password_hash):
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
