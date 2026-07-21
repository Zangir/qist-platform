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
(the same files the static site uses). A default admin account is created:
`admin@qist.kz` / `qist-admin-2026` (override with `QIST_ADMIN_PASSWORD`).

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
| `QIST_ADMIN_PASSWORD` | `qist-admin-2026`        | Seeded admin password         |
| `QIST_CORS_ORIGINS`   | `*`                      | Comma-separated CORS origins  |

## API overview

- `GET  /api/health` — liveness
- `POST /api/auth/register`, `POST /api/auth/login` — JWT auth
- `GET/POST/PUT/DELETE /api/people` — researcher directory (writes: admin)
- `GET/POST/DELETE /api/posts?channel=jobs` — channel posts (post: member, delete: admin)
- `GET  /api/newsletter`, `POST /api/subscribe`
- `POST /api/collab` (member), `GET /api/collab`, `GET /api/subscribers` (admin)

Deploy anywhere that runs Python (Railway, Fly.io, Render, a university VM):
`uvicorn app.main:main_app --host 0.0.0.0 --port 8000`.
