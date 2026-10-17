# Deploying the API on Hugging Face

1. **Build the folder** and push it to a Docker Space:
   ```bash
   python deploy/huggingface/build_space.py /tmp/qist-space
   cd /tmp/qist-space && git init -b main && git remote add space https://huggingface.co/spaces/<you>/qist-api
   git add . && git commit -m "deploy" && git push -f space main
   ```
   (or `hf upload <you>/qist-api /tmp/qist-space . --repo-type space`)
2. **Persistent storage** (Space → Settings → Persistent storage → Small, a paid add-on). The database is `/data/qist.db`.
   Without it the app stops at start-up with a clear message instead of losing accounts at the next restart.
3. **Secrets** (Space → Settings → Variables and secrets):
   - `QIST_ADMIN_PASSWORD` (secret): the password of `admin@qist.kz`.
   - `QIST_JWT_SECRET` (secret): a long random string; sessions survive restarts only if it is fixed.
   - `QIST_CORS_ORIGINS` (variable): `https://zangir.github.io`
4. **Point the site at it**: put `https://<you>-qist-api.hf.space` into `API_DEFAULT` in `assets/js/app.js` (or try it first in a
   browser console: `localStorage.setItem('qist_api_url', 'https://<you>-qist-api.hf.space')`).
5. **Check**: `https://<you>-qist-api.hf.space/api/health` answers `{"status":"ok"}`; sign in at the site's `login.html` as `admin@qist.kz`.

Notes
- A Space on free hardware sleeps after a period without visits and takes a short while to wake; choose upgraded hardware to keep it awake.
- Back up the database: download `/data/qist.db` from the Space (or use the admin Members CSV export).
- The Space repository is public so the website can reach it; it contains code and the public seed data only.
