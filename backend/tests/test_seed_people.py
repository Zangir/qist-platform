"""The public directory in the backend holds every researcher from data/people.json exactly once."""
import json

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine, select

from backend.app import main


@pytest.fixture(autouse=True)
def fresh_database(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "engine", create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False}))
    main._claim_hits.clear()
    monkeypatch.setenv("QIST_ADMIN_PASSWORD", "admin-pass-for-tests")
    monkeypatch.delenv("QIST_DB_URL", raising=False)


SEED = json.loads((main.DATA_DIR / "people.json").read_text(encoding="utf8"))
EXPECTED = len([p for p in SEED if not p.get("possible_duplicate_of")])


def people(c):
    return c.get("/api/people").json()


def admin(c):
    return {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "admin@qist.kz", "password": "admin-pass-for-tests"}).json()["token"]}


def test_all_seed_researchers_are_served_once_without_flagged_duplicates():
    assert len(SEED) >= 497 and EXPECTED >= 490
    with TestClient(main.main_app) as c:
        ps = people(c)
        assert len(ps) == EXPECTED
        assert len({(p["name"], p["institution"]) for p in ps}) >= EXPECTED - 3          # (a few real namesakes are fine)
        flagged = {p["name"] for p in SEED if p.get("possible_duplicate_of")}
        names = [p["name"] for p in ps]
        assert all(names.count(n) == 1 for n in flagged if n in names)


def test_restarts_do_not_duplicate():
    with TestClient(main.main_app) as c:
        n = len(people(c))
    with TestClient(main.main_app) as c:                                                # second start-up runs the sync again
        assert len(people(c)) == n


def test_an_old_database_with_only_the_first_29_gets_the_rest_without_duplicates():
    curated = [p for p in SEED[:29]]
    with Session(main.engine) as s:                                                   # what the live Space held: 29 rows, no seed ids
        main.SQLModel.metadata.create_all(main.engine)
        for p in curated:
            s.add(main.Person(name=p["name"], title=p.get("title", ""), institution=p.get("institution", ""), country=p.get("country", "")))
        s.commit()
    with TestClient(main.main_app) as c:
        ps = people(c)
        assert len(ps) == EXPECTED
        assert all([q["name"] for q in ps].count(p["name"]) == 1 for p in curated)


def test_admin_removal_is_permanent():
    with TestClient(main.main_app) as c:
        h = admin(c)
        victim = people(c)[5]
        assert c.delete(f"/api/people/{victim['id']}", headers=h).status_code == 204
        n = len(people(c))
    with TestClient(main.main_app) as c:                                                # a restart must not bring it back
        assert len(people(c)) == n and victim["name"] not in [p["name"] for p in people(c)]


def test_a_member_with_the_same_name_takes_over_their_public_row():
    target = next(p for p in SEED if not p.get("possible_duplicate_of") and p.get("institution"))
    with TestClient(main.main_app) as c:
        before = len(people(c))
        r = c.post("/api/auth/register", json={"email": "owner@example.org", "name": target["name"], "password": "correct-horse-battery",
                                              "institution": "Updated Institute", "listed": True})
        assert r.status_code == 200
        ps = people(c)
        rows = [p for p in ps if p["name"] == target["name"]]
        assert len(ps) == before and len(rows) == 1 and rows[0]["institution"] == "Updated Institute"   # same row, updated, no duplicate
        hdr = {"Authorization": "Bearer " + r.json()["token"]}
        c.put("/api/me/profile", json={"listed": False}, headers=hdr)                     # opting out removes it, and for good
        assert target["name"] not in [p["name"] for p in people(c)]
    with TestClient(main.main_app) as c:
        assert target["name"] not in [p["name"] for p in people(c)]


def test_deleting_an_account_removes_the_adopted_row_for_good():
    target = next(p for p in SEED[40:] if not p.get("possible_duplicate_of"))
    with TestClient(main.main_app) as c:
        r = c.post("/api/auth/register", json={"email": "gone@example.org", "name": target["name"], "password": "correct-horse-battery", "listed": True})
        assert c.delete("/api/me", headers={"Authorization": "Bearer " + r.json()["token"]}).status_code == 204
        assert target["name"] not in [p["name"] for p in people(c)]
    with TestClient(main.main_app) as c:
        assert target["name"] not in [p["name"] for p in people(c)]
