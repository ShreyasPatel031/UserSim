"""Run a shell job on hn-sim-1: package the code (experiments/hn_sim + src), upload it, queue the job, optionally wait.
The job runs in a checkout where experiments/hn_sim and src sit as in the repo; the cache (~/.usersim_sim) on the VM
lives in the job's own folder ($USERSIM_CACHE), filled from / saved to gs://.../hn_jobs/cache/ with `pull` / `push`.

    python vm/submit.py <name> '<shell commands>' [--wait]
    python vm/submit.py --log <name>        # live or finished log
"""
import io
import os
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments" / "hn_sim"))
import store as S  # noqa: E402

Q = "usersim_sim/hn_jobs"
PRE = """set -e
export PYTHONPATH=$PWD/src PYTHONUNBUFFERED=1
export USERSIM_CACHE=$PWD/cache          # each job has its own cache: jobs on one VM never overwrite each other's files
mkdir -p $USERSIM_CACHE
C=gs://usersim-bakeoff-347838016394/usersim_sim/hn_jobs/cache
pull() { for f in "$@"; do gsutil -q cp $C/$f $USERSIM_CACHE/$f; done; }
push() { for f in "$@"; do gsutil -q cp $USERSIM_CACHE/$f $C/$f; done; }
cd experiments/hn_sim
"""


def code_tgz() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for d in ("experiments/hn_sim", "src"):
            for f in (ROOT / d).rglob("*.py"):
                if "/out/" not in str(f):
                    t.add(f, arcname=str(f.relative_to(ROOT)))
    return buf.getvalue()


def submit(name: str, cmd: str) -> None:
    b = S._bucket()
    b.blob(f"{Q}/code.tgz").upload_from_string(code_tgz())
    b.blob(f"{Q}/queue/{name}.sh").upload_from_string(PRE + cmd + "\n")
    print("queued", name)


def log(name: str) -> str:
    b = S._bucket()
    for where in ("done", "live"):
        bl = b.blob(f"{Q}/{where}/{name}.sh.log")
        if bl.exists():
            return f"[{where}]\n" + bl.download_as_text()
    return "(no log yet)"


def push_cache(*files: str) -> None:
    b = S._bucket()
    for f in files:
        b.blob(f"{Q}/cache/{f}").upload_from_filename(os.path.join(S.LOCAL, f))


def pull_cache(*files: str) -> None:
    b = S._bucket()
    for f in files:
        b.blob(f"{Q}/cache/{f}").download_to_filename(os.path.join(S.LOCAL, f))


if __name__ == "__main__":
    if sys.argv[1] == "--log":
        print(log(sys.argv[2])[-4000:])
    else:
        submit(sys.argv[1], sys.argv[2])
        if "--wait" in sys.argv:
            while "exit " not in (lg := log(sys.argv[1])):
                time.sleep(30)
            print(lg[-4000:])
