"""Assembles the folder that is pushed to the Hugging Face Space.
    python deploy/huggingface/build_space.py /path/to/space-folder
Only what the API needs is copied. Never copied: data/private (people waiting to claim their profile), data/feeds, tests,
the spreadsheets, anything untracked."""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ["taxonomy.json", "eligibility.json", "people.json", "posts.json", "newsletter.json"]
PIPELINE = ["__init__.py", "taxonomy.py", "geo.py"]


def build(out: Path) -> None:
    if out.exists():
        for child in out.iterdir():
            if child.name != ".git":
                shutil.rmtree(child) if child.is_dir() else child.unlink()
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "deploy/huggingface/README.md", out / "README.md")
    shutil.copy(ROOT / "deploy/huggingface/Dockerfile", out / "Dockerfile")
    (out / "backend").mkdir()
    shutil.copy(ROOT / "backend/requirements.txt", out / "backend/requirements.txt")
    shutil.copytree(ROOT / "backend/app", out / "backend/app", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (out / "data").mkdir()
    for n in DATA:
        shutil.copy(ROOT / "data" / n, out / "data" / n)
    (out / "pipeline").mkdir()
    for n in PIPELINE:
        shutil.copy(ROOT / "pipeline" / n, out / "pipeline" / n)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    build(Path(sys.argv[1]))
    print("built", sys.argv[1])
