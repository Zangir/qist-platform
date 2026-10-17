---
title: QIST API
emoji: 🌉
colorFrom: blue
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
short_description: Backend of the ScienceBridge AI platform by QIST
---

Backend (FastAPI + SQLite) of the ScienceBridge AI platform: accounts, profiles, positions, papers, invitations.
The website itself lives on GitHub Pages and talks to this Space. No member data is stored in this repository:
the database is kept on the Space's persistent storage (`/data`).

Source and documentation: https://github.com/Zangir/qist-platform (`backend/`, `deploy/huggingface/`).
