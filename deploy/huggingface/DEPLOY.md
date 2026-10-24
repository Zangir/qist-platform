# Deploying the API on Hugging Face

Live setup: Space `zangir/qist-api` (Docker), bucket `zangir/qist-data` (private) mounted at `/data`.

1. **Build the folder** and push it to a Docker Space:
   ```bash
   python deploy/huggingface/build_space.py /tmp/qist-space
   python - <<'PY'
   from huggingface_hub import HfApi
   HfApi().upload_folder(folder_path="/tmp/qist-space", repo_id="<you>/qist-api", repo_type="space")
   PY
   ```
2. **Storage.** Create a private bucket and mount it on the Space (Space > Settings > Volumes, or in Python):
   ```python
   from huggingface_hub import HfApi, Volume, create_bucket
   create_bucket("<you>/qist-data", private=True)
   HfApi().set_space_volumes("<you>/qist-api", [Volume(type="bucket", source="<you>/qist-data", mount_path="/data")])
   ```
   The live SQLite file stays on the container's local disk; `backend/app/persist.py` writes verified snapshots to `/data` (at the
   latest 30 s after any change and at shutdown), keeps the newest six, and restores the newest intact one at every start. A crash can
   lose at most the last ~30 s of writes. Without the mount the app refuses to start. A bucket costs per TB stored (cents for this
   data) and Hugging Face PRO includes a large private-storage allowance.
3. **Secrets** (Space > Settings > Variables and secrets): `QIST_ADMIN_PASSWORD` (secret), `QIST_JWT_SECRET` (secret, fixed so sessions
   survive restarts), `QIST_CORS_ORIGINS` (variable) = `https://zangir.github.io`. Never set `QIST_ALLOW_EPHEMERAL` on the live Space.
4. **Point the site at it:** `QIST.API_DEFAULT` in `assets/js/app.js` (done). `localStorage.qist_api_url = 'off'` forces static mode.
5. **Check:** `https://<you>-qist-api.hf.space/api/health`; sign in at `login.html` as `admin@qist.kz`.

Notes
- A Space on free hardware pauses after 48 h without a visit and takes a short while to wake. The daily GitHub Action pings it, and the
  site falls back to static mode (profile requests instead of accounts) whenever the API does not answer within 6 s.
- Back up: the snapshots in the bucket are the backup; also the admin Members tab exports CSV.
- The Space repository is public so the website can reach it; it holds code and the public seed data only. Member data lives in the
  private bucket.
- Live tests (`pipeline/tests/e2e_claims.py`, `e2e_members_backend.py`) create and delete accounts. They refuse to run on a server that
  already has members. `deploy/huggingface/wipe_test_data.py` empties a *test* state, and refuses if any account looks real.
