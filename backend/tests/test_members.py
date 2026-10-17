"""Profiles, positions, papers, CV text, admin export, account deletion."""
import io
import json
import os
import sqlite3
import tempfile
import zipfile
from datetime import date, timedelta

os.environ["QIST_DB_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "m.db")
os.environ["QIST_JWT_SECRET"] = "test-secret-test-secret-test-secret-12"
os.environ["QIST_ADMIN_PASSWORD"] = "admin-pass-for-tests"

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402

PW = "correct-horse-battery"
ORCID = "0000-0002-1825-0097"        # ORCID's public demo record (valid check digit)


def client():
    return TestClient(main.main_app)


def register(c, email, **extra):
    r = c.post("/api/auth/register", json={"email": email, "name": "Ada Researcher", "password": PW, **extra})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def admin(c):
    r = c.post("/api/auth/login", json={"email": "admin@qist.kz", "password": "admin-pass-for-tests"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


POS = {"title": "PhD position in perovskite solar cells", "org": "Materials Lab, Nazarbayev University", "country": "KZ", "city": "Astana",
       "career_stage": "phd_student", "fields": ["Materials Science", "Energy, Renewable Energy"],
       "summary": "Fully funded four-year PhD on stable perovskite solar cells. Experience with thin films is a plus.",
       "link": "https://example.org/positions/1", "deadline": (date.today() + timedelta(days=30)).isoformat()}
PAPER = {"title": "Stable perovskite films by sustained release", "authors": ["A. Researcher", "B. Colleague"], "venue": "Advanced Materials",
         "year": 2026, "doi": "10.1002/adma.202600001", "abstract": "We show...", "fields": ["Materials Science"]}


# ---------------------------------------------------------------- profile
def test_register_with_full_profile_lists_the_member():
    with client() as c:
        register(c, "p1@example.org", title="PhD student", institution="Nazarbayev University", country="kz", city="Astana", orcid=ORCID,
                 fields=["Materials Science"], keywords=["perovskite", "solar cells"], website="https://example.org/ada", bio="I study films.")
        people = c.get("/api/people", params={"q": "perovskite"}).json()
        me = [p for p in people if p["name"] == "Ada Researcher"]
        assert me and me[0]["country"] == "Kazakhstan" and me[0]["orcid"] == ORCID and "perovskite" in me[0]["topics"]
        assert me[0]["link"] == "https://example.org/ada"


def test_profile_validation():
    with client() as c:
        for bad in ({"orcid": "0000-0002-1825-0098"}, {"orcid": "1234"}, {"country": "ZZ"}, {"fields": ["Astrology"]},
                    {"website": "javascript:alert(1)"}, {"photo": "data:text/html;base64,AAAA"}, {"fields": ["Neuroscience"] * 7}):
            r = c.post("/api/auth/register", json={"email": "bad@example.org", "name": "Bad Input", "password": PW, **bad})
            assert r.status_code == 422, (bad, r.status_code)
        assert c.post("/api/auth/register", json={"email": "bad@example.org", "name": "Ok Name", "password": "short"}).status_code == 422


def test_orcid_accepts_url_form_and_x_check_digit():
    assert main.orcid_ok("0000-0002-1825-0097") and main.orcid_ok("0000-0001-5109-3700") and not main.orcid_ok("0000-0002-1825-0098")
    with client() as c:
        h = register(c, "p2@example.org")
        r = c.put("/api/me/profile", json={"orcid": "https://orcid.org/0000-0002-1825-0097"}, headers=h)
        assert r.status_code == 200 and r.json()["orcid"] == ORCID


def test_edit_profile_and_unlist():
    with client() as c:
        h = register(c, "p3@example.org", institution="Old Uni", country="KZ")
        r = c.put("/api/me/profile", json={"institution": "New Uni", "keywords": ["graphene"], "photo": "data:image/jpeg;base64,/9j/AAAA"}, headers=h)
        assert r.status_code == 200 and r.json()["institution"] == "New Uni" and r.json()["photo"].startswith("data:image/jpeg")
        assert any(p["institution"] == "New Uni" and p["photo"] for p in c.get("/api/people").json())
        c.put("/api/me/profile", json={"listed": False}, headers=h)
        assert not any(p["institution"] == "New Uni" for p in c.get("/api/people").json())       # gone from the directory at once
        assert c.get("/api/me/profile", headers=h).json()["institution"] == "New Uni"           # but the account keeps its data
        c.put("/api/me/profile", json={"listed": True}, headers=h)
        assert any(p["institution"] == "New Uni" for p in c.get("/api/people").json())
        assert c.put("/api/me/profile", json={"name": "X"}, headers=h).status_code == 422


def test_profile_requires_auth():
    with client() as c:
        assert c.get("/api/me/profile").status_code == 401 and c.put("/api/me/profile", json={}).status_code == 401
        assert c.delete("/api/me").status_code == 401


# ---------------------------------------------------------------- positions
def test_position_lifecycle_and_privacy():
    with client() as c:
        h = register(c, "lab@example.org")
        r = c.post("/api/positions", json=POS, headers=h)
        assert r.status_code == 201, r.text
        pos = r.json()
        assert pos["origin"] == "community" and pos["type"] == "academic_job" and pos["career_stage"] == "phd_student"
        assert pos["source_url"] == POS["link"] and pos["posted_by"] == "Ada Researcher" and "Astana" in pos["where"]
        public = c.get("/api/positions").json()
        assert any(p["id"] == pos["id"] for p in public)
        assert "lab@example.org" not in json.dumps(public)                       # the owner's address is never published
        mine = c.get("/api/me/positions", headers=h).json()
        assert [p["id"] for p in mine] == [pos["id"]]
        pid = int(pos["id"].split("-")[1])
        r = c.put(f"/api/positions/{pid}", json=dict(POS, title="PhD position in tandem solar cells"), headers=h)
        assert r.status_code == 200 and r.json()["title"].startswith("PhD position in tandem")
        assert c.delete(f"/api/positions/{pid}", headers=h).status_code == 204
        assert not any(p["id"] == pos["id"] for p in c.get("/api/positions").json())


def test_position_validation_and_limits():
    with client() as c:
        h = register(c, "lab2@example.org")
        bad = [dict(POS, link=""), dict(POS, link="ftp://x"), dict(POS, link="javascript:alert(1)"), dict(POS, title="abc"), dict(POS, summary="too short"),
               dict(POS, career_stage="emperor"), dict(POS, fields=["Astrology"]), dict(POS, country="ZZ"), dict(POS, deadline="2020-01-01"), dict(POS, deadline="soon")]
        for b in bad:
            assert c.post("/api/positions", json=b, headers=h).status_code == 422, b
        assert c.post("/api/positions", json=POS).status_code == 401
        assert c.post("/api/positions", json=POS, headers=h).status_code == 201
        assert c.post("/api/positions", json=POS, headers=h).status_code == 409           # same title twice
        for i in range(4):
            assert c.post("/api/positions", json=dict(POS, title=f"Postdoc position number {i}"), headers=h).status_code == 201
        assert c.post("/api/positions", json=dict(POS, title="One more than the daily limit"), headers=h).status_code == 429


def test_only_owner_or_admin_can_change_a_position():
    with client() as c:
        a, b = register(c, "own@example.org"), register(c, "other@example.org")
        pid = int(c.post("/api/positions", json=dict(POS, title="Owner's own position"), headers=a).json()["id"].split("-")[1])
        assert c.delete(f"/api/positions/{pid}", headers=b).status_code == 403
        assert c.put(f"/api/positions/{pid}", json=POS, headers=b).status_code == 403
        assert c.delete(f"/api/positions/{pid}", headers=admin(c)).status_code == 204       # moderation
        assert c.delete(f"/api/positions/{pid}", headers=a).status_code == 404


def test_expired_position_hidden_publicly_but_kept_for_owner():
    with client() as c:
        h = register(c, "exp@example.org")
        pid = int(c.post("/api/positions", json=dict(POS, title="Soon to expire position"), headers=h).json()["id"].split("-")[1])
        from sqlmodel import Session
        with Session(main.engine) as s:
            p = s.get(main.Position, pid); p.deadline = (date.today() - timedelta(days=1)).isoformat(); s.add(p); s.commit()
        assert not any(p["id"] == f"m-{pid}" for p in c.get("/api/positions").json())
        mine = [p for p in c.get("/api/me/positions", headers=h).json() if p["id"] == f"m-{pid}"]
        assert mine and mine[0]["expired"] is True


# ---------------------------------------------------------------- papers
def test_paper_add_dedupe_search_delete():
    with client() as c:
        h = register(c, "pap@example.org")
        r = c.post("/api/papers", json=PAPER, headers=h)
        assert r.status_code == 201 and r.json()["url"] == "https://doi.org/10.1002/adma.202600001" and r.json()["added_by"] == "Ada Researcher"
        assert c.post("/api/papers", json=PAPER, headers=h).status_code == 409
        assert c.post("/api/papers", json=dict(PAPER, doi="https://doi.org/10.1002/ADMA.202600001"), headers=h).status_code == 409   # same DOI, other spelling
        assert c.post("/api/papers", json=dict(PAPER, title="No way to open it", doi=""), headers=h).status_code == 422
        assert c.post("/api/papers", json=dict(PAPER, title="Bad doi paper", doi="10.12/x"), headers=h).status_code == 422
        assert c.post("/api/papers", json=dict(PAPER, title="Bad link paper", doi="", url="javascript:1"), headers=h).status_code == 422
        assert c.post("/api/papers", json=PAPER).status_code == 401
        assert [p["title"] for p in c.get("/api/papers", params={"q": "perovskite"}).json()] == [PAPER["title"]]
        assert c.get("/api/papers", params={"field": "Neuroscience"}).json() == []
        assert c.get("/api/papers", params={"field": "Materials Science"}).json()
        pid = int(r.json()["id"].split("-")[1])
        assert c.delete(f"/api/papers/{pid}", headers=register(c, "intruder@example.org")).status_code == 403
        assert c.delete(f"/api/papers/{pid}", headers=h).status_code == 204


def test_bulk_import_skips_duplicates_and_unopenable():
    with client() as c:
        h = register(c, "bulk@example.org")
        batch = [dict(PAPER, title=f"Paper number {i} on films", doi=f"10.1000/x{i}") for i in range(3)]
        batch.append(dict(batch[0]))                                  # duplicate
        batch.append(dict(PAPER, title="Has no doi or link", doi=""))   # cannot be opened
        r = c.post("/api/papers/bulk", json=batch, headers=h)
        assert r.status_code == 200 and r.json() == {"added": 3, "skipped": 2}
        assert c.post("/api/papers/bulk", json=batch, headers=h).json() == {"added": 0, "skipped": 5}
        assert len(c.get("/api/me/papers", headers=h).json()) == 3


# ---------------------------------------------------------------- CV
def _minimal_pdf(text):
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out)); out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (len(objs) + 1, x)


def test_cv_extract_pdf_docx_txt_and_refusals():
    cv = "Ada Researcher. PhD in materials science. ORCID 0000-0002-1825-0097. Perovskite solar cells and thin films at Nazarbayev University."
    with client() as c:
        r = c.post("/api/cv/extract", files={"file": ("cv.pdf", _minimal_pdf(cv), "application/pdf")})
        assert r.status_code == 200 and "perovskite solar cells" in r.json()["text"].lower(), r.text
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("word/document.xml", f"<w:document><w:body><w:p><w:r><w:t>{cv}</w:t></w:r></w:p></w:body></w:document>")
        r = c.post("/api/cv/extract", files={"file": ("cv.docx", buf.getvalue(), "application/octet-stream")})
        assert r.status_code == 200 and "0000-0002-1825-0097" in r.json()["text"]
        r = c.post("/api/cv/extract", files={"file": ("cv.txt", cv.encode(), "text/plain")})
        assert r.status_code == 200 and r.json()["chars"] == len(cv)
        assert c.post("/api/cv/extract", files={"file": ("x.exe", b"MZ\x90\x00 binary", "application/octet-stream")}).status_code == 415
        assert c.post("/api/cv/extract", files={"file": ("empty.txt", b"hi", "text/plain")}).status_code == 422
        assert c.post("/api/cv/extract", files={"file": ("broken.pdf", b"%PDF-1.4 garbage", "application/pdf")}).status_code == 422
        assert c.post("/api/cv/extract", files={"file": ("big.txt", b"a" * (5 * 1024 * 1024 + 10), "text/plain")}).status_code == 413


# ---------------------------------------------------------------- admin and deletion
def test_admin_members_and_csv_are_admin_only_and_formula_safe():
    with client() as c:
        h = register(c, "csv@example.org", title="=HYPERLINK(\"http://evil\")", institution="Uni", country="KZ", fields=["Neuroscience"])
        c.post("/api/papers", json=PAPER, headers=h)
        assert c.get("/api/admin/members").status_code == 401
        assert c.get("/api/admin/members", headers=h).status_code == 403
        assert c.get("/api/admin/export.csv", headers=h).status_code == 403
        a = admin(c)
        rows = c.get("/api/admin/members", headers=a).json()
        mine = [r for r in rows if r["email"] == "csv@example.org"][0]
        assert mine["papers"] == 1 and mine["country"] == "Kazakhstan" and mine["fields"] == ["Neuroscience"] and "password_hash" not in json.dumps(rows)
        r = c.get("/api/admin/export.csv", headers=a)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
        body = r.text
        assert body.splitlines()[0].startswith("name,email,status,title") and "csv@example.org" in body
        assert "'=HYPERLINK" in body and ",=HYPERLINK" not in body               # a typed formula is defused


def test_delete_account_removes_everything():
    with client() as c:
        h = register(c, "gone@example.org", institution="Vanishing Uni", country="KZ")
        c.post("/api/positions", json=dict(POS, title="Position that will vanish"), headers=h)
        c.post("/api/papers", json=dict(PAPER, title="Paper that will vanish", doi="10.1000/gone"), headers=h)
        c.put("/api/me/feed-profile", json={"profile": {"stage": "any", "country": "KZ"}}, headers=h)
        assert c.delete("/api/me", headers=h).status_code == 204
        assert not any(p["institution"] == "Vanishing Uni" for p in c.get("/api/people").json())
        assert not any("vanish" in p["title"] for p in c.get("/api/positions").json())
        assert not any("vanish" in p["title"] for p in c.get("/api/papers").json())
        assert c.post("/api/auth/login", json={"email": "gone@example.org", "password": PW}).status_code == 401
        assert c.get("/api/admin/members", headers=admin(c)).json() and not any(m["email"] == "gone@example.org" for m in c.get("/api/admin/members", headers=admin(c)).json())


def test_old_database_gets_the_new_columns():
    path = os.path.join(tempfile.mkdtemp(), "old.db")
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE person (id INTEGER PRIMARY KEY, name TEXT, title TEXT, institution TEXT, city TEXT, country TEXT, lat REAL, lng REAL, topics TEXT, link TEXT, bio TEXT, experience INTEGER, featured INTEGER)')
    con.execute('CREATE TABLE user (id INTEGER PRIMARY KEY, email TEXT, name TEXT, password_hash TEXT, role TEXT, title TEXT, institution TEXT, topics TEXT)')
    con.commit(); con.close()
    from sqlmodel import create_engine
    old = main.engine
    try:
        main.engine = create_engine("sqlite:///" + path)
        main.ensure_columns()
        cols = {r[1] for r in sqlite3.connect(path).execute('PRAGMA table_info(person)')}
        assert {"photo", "orcid"} <= cols and "created" in {r[1] for r in sqlite3.connect(path).execute('PRAGMA table_info(user)')}
        main.ensure_columns()                                                    # idempotent
    finally:
        main.engine = old


def test_admin_password_is_never_the_published_default(monkeypatch, capsys):
    monkeypatch.delenv("QIST_ADMIN_PASSWORD", raising=False)
    from sqlmodel import Session, create_engine, SQLModel
    old = main.engine
    try:
        main.engine = create_engine("sqlite:///" + os.path.join(tempfile.mkdtemp(), "fresh.db"))
        SQLModel.metadata.create_all(main.engine)
        main.seed()
        out = capsys.readouterr().out
        assert "generated admin password" in out and "qist-admin-2026" not in out
        with Session(main.engine) as s:
            u = s.exec(main.select(main.User).where(main.User.email == "admin@qist.kz")).first()
            assert not main.pbkdf2_sha256.verify("qist-admin-2026", u.password_hash)
    finally:
        main.engine = old
