"""Feed-profile endpoints: auth required, round trip, validation, isolation between accounts."""
import os
import tempfile

os.environ["QIST_DB_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["QIST_JWT_SECRET"] = "test-secret"

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402


def client():
    return TestClient(main.main_app)


def register(c, email):
    r = c.post("/api/auth/register", json={"email": email, "name": "Test User", "password": "correct-horse-battery"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


PROFILE = {"stage": "postdoc_plus", "country": "kz", "fields": ["Neuroscience", " Robotics "], "keywords": ["hippocampus", " "],
           "jobCountries": ["de", "ch"], "remote": False, "allStages": True}


def test_requires_auth():
    with client() as c:
        assert c.get("/api/me/feed-profile").status_code == 401
        assert c.put("/api/me/feed-profile", json={"profile": PROFILE}).status_code == 401


def test_round_trip_and_normalisation():
    with client() as c:
        h = register(c, "a@example.org")
        assert c.get("/api/me/feed-profile", headers=h).json() == {"profile": None, "updated": None}
        assert c.put("/api/me/feed-profile", json={"profile": PROFILE}, headers=h).status_code == 200
        got = c.get("/api/me/feed-profile", headers=h).json()["profile"]
        assert got["country"] == "KZ" and got["fields"] == ["Neuroscience", "Robotics"] and got["keywords"] == ["hippocampus"]
        assert got["jobCountries"] == ["DE", "CH"] and got["remote"] is False and got["allStages"] is True
        # a second save replaces, not appends
        c.put("/api/me/feed-profile", json={"profile": dict(PROFILE, keywords=["perovskite"])}, headers=h)
        assert c.get("/api/me/feed-profile", headers=h).json()["profile"]["keywords"] == ["perovskite"]


def test_validation():
    with client() as c:
        h = register(c, "b@example.org")
        assert c.put("/api/me/feed-profile", json={"profile": dict(PROFILE, stage="emperor")}, headers=h).status_code == 422
        assert c.put("/api/me/feed-profile", json={"profile": dict(PROFILE, fields=["x"] * 7)}, headers=h).status_code == 422
        assert c.put("/api/me/feed-profile", json={"profile": dict(PROFILE, keywords=["k"] * 13)}, headers=h).status_code == 422
        assert c.put("/api/me/feed-profile", json={"profile": dict(PROFILE, country="KAZ")}, headers=h).status_code == 422
        assert c.put("/api/me/feed-profile", json={"nope": 1}, headers=h).status_code == 422


def test_accounts_are_isolated():
    with client() as c:
        ha, hb = register(c, "c@example.org"), register(c, "d@example.org")
        c.put("/api/me/feed-profile", json={"profile": PROFILE}, headers=ha)
        assert c.get("/api/me/feed-profile", headers=hb).json()["profile"] is None
