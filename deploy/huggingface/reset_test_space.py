"""Restarts the Space and waits until its (throwaway) database is empty again. For live tests only, while the Space runs with
QIST_ALLOW_EPHEMERAL=1. Never run this against a Space with persistent storage: a restart keeps real accounts, so it would
simply loop until you stop it."""
import os, sys, time
import requests
from huggingface_hub import HfApi

repo = sys.argv[1] if len(sys.argv) > 1 else "zangir/qist-api"
url = "https://" + repo.replace("/", "-") + ".hf.space"
pw = open(os.path.expanduser("~/.qist-hf-admin-password")).read().strip()
HfApi().restart_space(repo)
for i in range(40):
    time.sleep(8)
    try:
        t = requests.post(url + "/api/auth/login", json={"email": "admin@qist.kz", "password": pw}, timeout=8).json()["token"]
        n = len([m for m in requests.get(url + "/api/admin/members", headers={"Authorization": "Bearer " + t}, timeout=8).json() if m["role"] != "admin"])
        print(i, "members:", n)
        if n == 0:
            break
    except Exception as e:
        print(i, "not ready", type(e).__name__)
else:
    raise SystemExit("the Space did not come back with an empty database")
