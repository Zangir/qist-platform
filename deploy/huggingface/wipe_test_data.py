"""Empties the Space's database between live test runs (and once before launch): deletes every snapshot in the bucket and restarts the
Space, which then starts empty with only the admin account.
    python deploy/huggingface/wipe_test_data.py [space-id] [bucket-id]
SAFETY: refuses to run if any account other than the admin has an address outside example.org, so it cannot erase real members."""
import os, sys, time
import requests
from huggingface_hub import HfApi, batch_bucket_files

repo = sys.argv[1] if len(sys.argv) > 1 else "zangir/qist-api"
bucket = sys.argv[2] if len(sys.argv) > 2 else "zangir/qist-data"
url = "https://" + repo.replace("/", "-") + ".hf.space"
pw = os.environ.get("E2E_ADMIN_PASSWORD") or open(os.path.expanduser("~/.qist-hf-admin-password")).read().strip()
api = HfApi()


def members():
    t = requests.post(url + "/api/auth/login", json={"email": "admin@qist.kz", "password": pw}, timeout=15).json()["token"]
    return [m for m in requests.get(url + "/api/admin/members", headers={"Authorization": "Bearer " + t}, timeout=15).json() if m["role"] != "admin"]


real = [m["email"] for m in members() if not m["email"].endswith("@example.org") and not m["email"].endswith(".example")]
if real:
    raise SystemExit(f"Refusing to wipe: {len(real)} account(s) look real (e.g. {real[0]}). Nothing was changed.")
files = [f.path for f in api.list_bucket_tree(bucket)]
if files:
    batch_bucket_files(bucket, delete=files)
api.restart_space(repo)
time.sleep(10)
for i in range(40):
    try:
        n = len(members())
        print(i, "members:", n, "| snapshots in bucket:", len([f for f in api.list_bucket_tree(bucket)]))
        if n == 0:
            break
    except Exception as e:
        print(i, "not ready", type(e).__name__)
    time.sleep(8)
else:
    raise SystemExit("the Space did not come back empty")
