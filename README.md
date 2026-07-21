# QIST Platform

The community platform of **QIST — Qazaq International Science and Technology Association** ([qista.org](https://qista.org)): the global network of PhD students, postdocs, professors and industry scientists from Kazakhstan.

**Live site:** https://zangir.github.io/qist-platform/

## Features

- 🗺️ **Researcher map** — interactive world map (Leaflet + clustering) of community members, filterable by name, topic and country
- 🔎 **People directory** — search by research topic, career stage, country of work and years of experience
- 📢 **Channels** — on-platform boards: Jobs & Vacancies, Research Grants, Conferences & Events, Collaboration Requests, General Discussion
- 🤝 **Academic matching** — enter your interests and goal (co-author / mentor / mentee) and get ranked collaborator suggestions with match scores
- 📮 **QIST newsletter** — digest issues published on-site with email subscription
- 🔐 **Accounts** — participant registration/login plus an admin panel (manage researchers, moderate posts, view subscribers and collaboration requests)

## Architecture

Two modes, one data contract:

1. **Static mode (GitHub Pages, default)** — the frontend runs entirely from `data/*.json`; user-created records (accounts, posts, subscriptions, collaboration requests, admin edits) are kept in the browser's `localStorage`. Zero infrastructure, ideal for the first version.
2. **API mode (Python backend)** — the FastAPI app in [`backend/`](backend/) serves the same endpoints with a real SQLite database, hashed passwords and JWT auth. Point the frontend at it with `localStorage.setItem('qist_api_url', 'https://your-api')` and everything becomes shared and persistent. See [backend/README.md](backend/README.md).

## Demo accounts (static mode)

| Role   | Email             | Password           |
|--------|-------------------|--------------------|
| Admin  | `admin@qist.kz`   | `qist-admin-2026`  |
| Member | `member@qist.kz`  | `qist-member-2026` |

## Local development

Static site: any web server from the repo root, e.g. `python3 -m http.server 8080`.

Backend: see [backend/README.md](backend/README.md).

## Data

`data/people.json` seeds the directory/map with publicly known Kazakhstani researchers compiled from public sources (university pages, Google Scholar). To add, correct or remove an entry, open an issue or PR — or use the admin panel.
