# QIST Platform — Python backend

FastAPI + SQLite backend serving the same API contract the static frontend expects.
The GitHub Pages site runs in static mode by default; point it at a deployed
instance of this backend to go fully dynamic (real accounts, shared posts, etc.).

## Run locally

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:main_app --reload --port 8000
```

The database (`qist.db`) is created on first start and seeded from `../data/*.json`
(the same files the static site uses). An admin account `admin@qist.kz` is created with the
password from `QIST_ADMIN_PASSWORD`. If that variable is not set, a random password is generated
and printed once in the log (the old default password was public, so there is no default any more).
Older databases get the new columns automatically at start-up.

## Connect the frontend

On any page of the deployed site, open the browser console and run:

```js
localStorage.setItem('qist_api_url', 'https://your-api-host.example.com');
```

…or set `QIST.apiBase` in `assets/js/app.js`. The frontend checks
`GET /api/health` and switches from static JSON + localStorage to the live API.

## Environment variables

| Variable              | Default                  | Purpose                       |
|-----------------------|--------------------------|-------------------------------|
| `QIST_DB_URL`         | `sqlite:///qist.db`      | SQLAlchemy database URL       |
| `QIST_JWT_SECRET`     | random per process       | JWT signing key (set in prod) |
| `QIST_ADMIN_PASSWORD` | random, printed once     | Seeded admin password         |
| `QIST_CORS_ORIGINS`   | `*`                      | Comma-separated CORS origins  |

## API overview

- `GET  /api/health` — liveness
- `POST /api/auth/register`, `POST /api/auth/login` — JWT auth
- `GET/POST/PUT/DELETE /api/people` — researcher directory (writes: admin)
- `GET/POST/DELETE /api/posts?channel=jobs` — channel posts (post: member, delete: admin)
- `GET  /api/newsletter`, `POST /api/subscribe`
- `POST /api/collab` (member), `GET /api/collab`, `GET /api/subscribers` (admin)
- `GET/PUT /api/me/profile`, `DELETE /api/me` — the member's own profile (ORCID, photo, fields, keywords, links); deleting removes everything they added
- `GET/POST/PUT/DELETE /api/positions` — positions members post from their labs (public list; edit/delete: owner or admin; 5 a day, 25 active)
- `GET/POST/DELETE /api/papers`, `POST /api/papers/bulk`, `GET /api/me/papers` — members' papers (DOI or link required)
- `POST /api/cv/extract` — turns a PDF/DOCX/text CV into plain text and forgets the file (the reading happens in the browser)
- `GET /api/admin/members`, `GET /api/admin/export.csv` — the members database (admin only; CSV cells are formula-safe)
- `GET/PUT /api/me/feed-profile` — the reader's matching profile

Tests: `python -m pytest backend/tests` (from the repository root).

### Deploy

`render.yaml` and `Dockerfile` deploy the API on Render in a few clicks; see the comments in them.
Set `QIST_ADMIN_PASSWORD`, keep the database on a persistent disk, and set `QIST_CORS_ORIGINS` to the site's address.

Deploy anywhere that runs Python (Railway, Fly.io, Render, a university VM):
`uvicorn app.main:main_app --host 0.0.0.0 --port 8000`.
