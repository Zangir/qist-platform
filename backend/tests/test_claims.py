"""Accounts made from a member list and claimed through personal links."""
import csv
import io
import os
import tempfile
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

os.environ["QIST_DB_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "c.db")
os.environ["QIST_JWT_SECRET"] = "test-secret-test-secret-test-secret-12"
os.environ["QIST_ADMIN_PASSWORD"] = "admin-pass-for-tests"

from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import Workbook  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from backend.app import main  # noqa: E402

import pytest  # noqa: E402
from sqlmodel import create_engine  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_database(tmp_path, monkeypatch):
    """Every test gets an empty database (the app module is shared by all test files)."""
    monkeypatch.setattr(main, "engine", create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False}))
    main._claim_hits.clear(); main._cv_hits.clear()
    monkeypatch.delenv("QIST_DB_URL", raising=False)


SITE = "https://example.org/qist"
PW = "correct-horse-battery"


def client():
    return TestClient(main.main_app)


def admin(c):
    seed_member(c)                      # the sheets contain one person who already has an account
    r = c.post("/api/auth/login", json={"email": "admin@qist.kz", "password": "admin-pass-for-tests"})
    return {"Authorization": "Bearer " + r.json()["token"]}


def workbook(sheets):
    wb = Workbook(); wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        for r in rows:
            ws.append(r)
    buf = io.BytesIO(); wb.save(buf)
    return buf.getvalue()


# three sheets with the three different layouts of the real workbook; every person is invented
SHEETS = {
    "list": [["Name Surname", "Primary Field", "Keywords", "Statement", "Country Work", "Institution", "Position", "LinkedIn", "Email"],
             ["Aigerim Bekova", "Materials Science", "perovskite solar cells; thin films", "private note", "Kazakhstan", "Nazarbayev University", "PhD student", "https://www.linkedin.com/in/aigerim", "Aigerim.Bekova@NU.edu.kz"],
             ["Dias Omarov", "Neuroscience", "hippocampus, memory", "", "Germany", "Charité Berlin", "Postdoc", "", "dias@charite.example"],
             ["No Mail Person", "Economics", "", "", "Turkey", "Koc University", "Professor", "", ""],
             ["Bad Mail Person", "Economics", "", "", "Turkey", "Koc University", "Professor", "", "not-an-email"],
             ["", "Economics", "", "", "", "", "", "", "ghost@example.org"],
             ["Already Member", "Economics", "", "", "Kazakhstan", "NU", "Professor", "", "member@example.org"]],
    "event attendees1": [["Name", "Surname", "Country", "City", "Academic Role", "Field", "Research Topic", "Institution", "Hobbies & Interests", "Email"],
                         ["Dias", "Omarov", "Germany", "Berlin", "Postdoctoral researcher", "Neurosciences", "place cells and goal coding in mice", "Charité Berlin", "chess", "dias@charite.example"],
                         ["Mira", "Sadykova", "Kyrgyzstan", "Bishkek", "Lecturer", "Public health", "maternal health", "AUCA", "tea", "mira@auca.example"]],
    "event attendees": [["Name", "Surname", "Country", "City", "Position", "Institution", "Field", "Reasech topic", "Email", "Note"],
                        ["Mira", "Sadykova", "Kyrgyzstan", "Bishkek", "Senior lecturer", "AUCA", "Public Health, Epidemiology", "maternal health, nutrition", "MIRA@auca.example", "VIP"]],
    "empty tab": [],
}


def preview(c, h, raw=None):
    return c.post("/api/admin/import", headers=h, files={"file": ("m.xlsx", raw or workbook(SHEETS), "application/vnd.ms-excel")}, data={"site_url": SITE + "/index.html", "commit": "false"})


def commit(c, h, raw=None):
    return c.post("/api/admin/import", headers=h, files={"file": ("m.xlsx", raw or workbook(SHEETS), "application/vnd.ms-excel")}, data={"site_url": SITE, "commit": "true"})


def links(csv_text):
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    return {r["email"]: parse_qs(urlparse(r["claim_link"]).query)["t"][0] for r in rows}, rows


def seed_member(c):
    c.post("/api/auth/register", json={"email": "member@example.org", "name": "Already Member", "password": PW})


def test_preview_reports_without_writing():
    with client() as c:
        seed_member(c); h = admin(c)
        r = preview(c, h)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["committed"] is False and j["records"] == 3                                    # Aigerim, Dias, Mira
        assert j["rows"] == 9 and j["merged"] == 2                                             # Dias and Mira appear again on later sheets
        assert j["no_email"] == ["No Mail Person"] and j["bad_email"] == ["Bad Mail Person"] and j["no_name"] == 1 and j["already_accounts"] == 1
        with Session(main.engine) as s:
            assert s.exec(select(main.User).where(main.User.status == "unclaimed")).all() == []   # a preview creates nothing


def test_import_fields_are_read_and_notes_are_ignored():
    with client() as c:
        h = admin(c)
        assert commit(c, h).status_code == 200
        rows = {m["email"]: m for m in c.get("/api/admin/members", headers=h).json()}
        a = rows["aigerim.bekova@nu.edu.kz"]
        assert a["status"] == "unclaimed" and a["institution"] == "Nazarbayev University" and a["title"] == "PhD student"
        assert a["country"] == "Kazakhstan" and a["fields"] == ["Materials Science"] and "perovskite solar cells" in a["keywords"]
        assert a["linkedin"].startswith("https://www.linkedin.com/in/") and a["listed"] is False
        d = rows["dias@charite.example"]
        assert d["country"] == "Germany" and d["fields"] == ["Neuroscience"] and {"hippocampus", "memory"} <= set(d["keywords"])
        assert any("place cells" in k for k in d["keywords"])                                    # keywords merged across the two sheets
        m = rows["mira@auca.example"]
        assert m["country"] == "Kyrgyzstan" and "Public Health, Epidemiology" in m["fields"]
        dump = str(rows)
        assert "private note" not in dump and "chess" not in dump and "VIP" not in dump         # notes and hobbies are never imported


def test_unclaimed_accounts_are_invisible_and_cannot_sign_in():
    with client() as c:
        h = admin(c); commit(c, h)
        assert not [p for p in c.get("/api/people").json() if "Bekova" in p["name"]]
        assert c.post("/api/auth/login", json={"email": "aigerim.bekova@nu.edu.kz", "password": ""}).status_code in (401, 422)
        assert c.post("/api/auth/login", json={"email": "aigerim.bekova@nu.edu.kz", "password": PW}).status_code == 401
        assert c.post("/api/auth/register", json={"email": "aigerim.bekova@nu.edu.kz", "name": "Someone Else", "password": PW}).status_code == 400   # cannot be taken by signing up


def test_commit_returns_links_csv_once_and_tokens_are_not_stored():
    with client() as c:
        h = admin(c)
        j = commit(c, h).json()
        assert j["created"] == 3
        toks, rows = links(j["csv"])
        assert set(toks) == {"aigerim.bekova@nu.edu.kz", "dias@charite.example", "mira@auca.example"}
        assert all(len(t) >= 40 for t in toks.values()) and len(set(toks.values())) == 3
        assert all(r["claim_link"].startswith(SITE + "/claim.html?t=") for r in rows)
        with Session(main.engine) as s:
            raw = " ".join((u.claim_hash or "") for u in s.exec(select(main.User)).all())
            assert not any(t in raw for t in toks.values())                                       # only hashes in the database
        assert commit(c, h).json()["created"] == 0                                                # a second import adds nobody
        assert c.post("/api/admin/import", files={"file": ("m.xlsx", workbook(SHEETS))}, data={"site_url": SITE, "commit": "true"}).status_code == 401


def test_import_is_admin_only_and_validates_input():
    with client() as c:
        member = c.post("/api/auth/register", json={"email": "m2@example.org", "name": "Mem Ber", "password": PW}).json()["token"]
        assert c.post("/api/admin/import", headers={"Authorization": "Bearer " + member}, files={"file": ("m.xlsx", workbook(SHEETS))}, data={"site_url": SITE}).status_code == 403
        h = admin(c)
        assert c.post("/api/admin/import", headers=h, files={"file": ("m.xlsx", b"not a workbook")}, data={"site_url": SITE}).status_code == 422
        assert c.post("/api/admin/import", headers=h, files={"file": ("m.xlsx", workbook(SHEETS))}, data={"site_url": "javascript:alert(1)"}).status_code == 422


def test_claim_flow_edit_consent_and_sign_in():
    with client() as c:
        h = admin(c)
        toks, _ = links(commit(c, h).json()["csv"])
        t = toks["aigerim.bekova@nu.edu.kz"]
        pre = c.get(f"/api/claim/{t}")
        assert pre.status_code == 200 and pre.json()["name"] == "Aigerim Bekova" and pre.json()["email"] == "aigerim.bekova@nu.edu.kz" and pre.json()["fields"] == ["Materials Science"]
        assert "password" not in pre.text and "claim_hash" not in pre.text
        assert c.post(f"/api/claim/{t}", json={"password": PW}).status_code == 422               # terms must be accepted
        assert c.post(f"/api/claim/{t}", json={"password": "short", "accept_terms": True}).status_code == 422
        r = c.post(f"/api/claim/{t}", json={"password": PW, "accept_terms": True, "city": "Astana", "orcid": "0000-0002-1825-0097", "keywords": ["perovskite"]})
        assert r.status_code == 200 and r.json()["email"] == "aigerim.bekova@nu.edu.kz" and r.json()["token"]
        hdr = {"Authorization": "Bearer " + r.json()["token"]}
        me = c.get("/api/me/profile", headers=hdr).json()
        assert me["city"] == "Astana" and me["orcid"] == "0000-0002-1825-0097" and me["keywords"] == ["perovskite"] and me["institution"] == "Nazarbayev University" and me["listed"] is False
        assert not [p for p in c.get("/api/people").json() if "Bekova" in p["name"]]            # listing is opt-in: still hidden
        assert c.post("/api/auth/login", json={"email": "aigerim.bekova@nu.edu.kz", "password": PW}).status_code == 200
        assert c.get(f"/api/claim/{t}").status_code == 404 and c.post(f"/api/claim/{t}", json={"password": PW, "accept_terms": True}).status_code == 404   # single use
        c.put("/api/me/profile", json={"listed": True}, headers=hdr)
        assert [p for p in c.get("/api/people").json() if p["name"] == "Aigerim Bekova" and p["country"] == "Kazakhstan"]    # consent -> listed


def test_claim_with_consent_to_list_in_one_step():
    with client() as c:
        h = admin(c)
        t = links(commit(c, h).json()["csv"])[0]["dias@charite.example"]
        c.post(f"/api/claim/{t}", json={"password": PW, "accept_terms": True, "listed": True})
        assert [p for p in c.get("/api/people").json() if p["name"] == "Dias Omarov"]
        assert [m for m in c.get("/api/admin/members", headers=h).json() if m["email"] == "dias@charite.example"][0]["status"] == "active"


def test_wrong_used_and_expired_links_look_identical():
    with client() as c:
        h = admin(c)
        toks, _ = links(commit(c, h).json()["csv"])
        t = toks["mira@auca.example"]
        bad = [c.get("/api/claim/" + "x" * 43), c.get("/api/claim/short"), c.get("/api/claim/" + "A" * 300)]
        assert {r.status_code for r in bad} == {404} and len({r.text for r in bad}) == 1
        with Session(main.engine) as s:
            u = s.exec(select(main.User).where(main.User.email == "mira@auca.example")).first()
            u.claim_expires = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds"); s.add(u); s.commit()
        exp = c.get(f"/api/claim/{t}")
        assert exp.status_code == 404 and exp.text == bad[0].text                                # expired says the same as wrong


def test_regenerate_invalidates_old_links():
    with client() as c:
        h = admin(c)
        old, _ = links(commit(c, h).json()["csv"])
        r = c.post("/api/admin/invites/regenerate", headers=h, json={"site_url": SITE, "emails": ["mira@auca.example"]})
        assert r.status_code == 200 and r.json()["issued"] == 1
        new, _ = links(r.json()["csv"])
        assert c.get(f"/api/claim/{old['mira@auca.example']}").status_code == 404
        assert c.get(f"/api/claim/{new['mira@auca.example']}").status_code == 200
        assert c.get(f"/api/claim/{old['dias@charite.example']}").status_code == 200              # others untouched
        assert c.post("/api/admin/invites/regenerate", headers=h, json={"site_url": SITE}).json()["issued"] == 3
        assert c.post("/api/admin/invites/regenerate", json={"site_url": SITE}).status_code == 401


def test_decline_deletes_and_is_remembered():
    with client() as c:
        h = admin(c)
        t = links(commit(c, h).json()["csv"])[0]["mira@auca.example"]
        assert c.post(f"/api/claim/{t}/decline").status_code == 204
        assert c.get(f"/api/claim/{t}").status_code == 404
        assert not [m for m in c.get("/api/admin/members", headers=h).json() if m["email"] == "mira@auca.example"]
        again = commit(c, h).json()
        assert again["created"] == 0 and again["suppressed"] >= 1                                 # a later import skips them
        with Session(main.engine) as s:
            assert "mira@auca.example" not in " ".join(r.email_hash for r in s.exec(select(main.Suppression)).all())   # stored hashed


def test_delete_old_unclaimed_keeps_the_active():
    with client() as c:
        h = admin(c)
        toks, _ = links(commit(c, h).json()["csv"])
        c.post(f"/api/claim/{toks['dias@charite.example']}", json={"password": PW, "accept_terms": True})
        assert c.delete("/api/admin/unclaimed?older_than_days=0").status_code == 401
        assert c.delete("/api/admin/unclaimed?older_than_days=30", headers=h).json() == {"deleted": 0}      # too new to delete
        assert c.delete("/api/admin/unclaimed?older_than_days=0", headers=h).json() == {"deleted": 2}
        names = {m["email"] for m in c.get("/api/admin/members", headers=h).json()}
        assert "dias@charite.example" in names and "mira@auca.example" not in names


def test_csv_export_marks_status_and_defuses_formulas():
    with client() as c:
        h = admin(c)
        raw = workbook({"s": [["Name Surname", "Email", "Institution"], ["@cmd Person", "evil@example.org", "+SUM(A1)"]]})
        j = commit(c, h, raw).json()
        assert "'@cmd Person" in j["csv"] and ",@cmd" not in j["csv"]
        exp = c.get("/api/admin/export.csv", headers=h).text
        assert "unclaimed" in exp and "'+SUM" in exp and ",+SUM" not in exp


def test_startup_refuses_a_database_that_would_be_lost(monkeypatch, tmp_path):
    monkeypatch.setenv("QIST_DB_URL", "sqlite:////definitely/not/a/folder/qist.db")
    monkeypatch.delenv("QIST_ALLOW_EPHEMERAL", raising=False)
    try:
        main.check_deployment(); raised = False
    except SystemExit as e:
        raised = "Persistent" in str(e)
    assert raised
    monkeypatch.setenv("QIST_ALLOW_EPHEMERAL", "1"); main.check_deployment()                     # explicit override works
    monkeypatch.delenv("QIST_ALLOW_EPHEMERAL"); monkeypatch.setenv("QIST_DB_URL", f"sqlite:///{tmp_path}/ok.db"); main.check_deployment()


def test_proxy_address_is_used_only_when_trusted(monkeypatch):
    class R:
        headers = {"x-forwarded-for": "9.9.9.9, 10.0.0.1"}
        client = type("C", (), {"host": "10.0.0.1"})()
    monkeypatch.setattr(main, "TRUST_PROXY", False); assert main.client_ip(R) == "10.0.0.1"
    monkeypatch.setattr(main, "TRUST_PROXY", True); assert main.client_ip(R) == "9.9.9.9"
