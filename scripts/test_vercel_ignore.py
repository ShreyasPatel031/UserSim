"""Tests the ignoreCommand in vercel.json against a throwaway git repo. python -m pytest scripts/test_vercel_ignore.py
Vercel semantics: exit 0 = skip the build, exit 1 = build. Any error must mean build."""
import json
import os
import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CMD = json.loads((ROOT / "vercel.json").read_text())["ignoreCommand"]
SCRIPT = ROOT / "scripts" / "vercel_ignore.sh"


def test_ignore_command_fits_vercels_256_character_limit_and_points_at_the_script():
    # Vercel rejects the whole deployment otherwise ("ignoreCommand should NOT be longer than 256 characters"; a 272-character version did)
    assert len(CMD) <= 256 and CMD == "bash scripts/vercel_ignore.sh" and SCRIPT.is_file()


def sh(cwd, *args, env=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, env={**os.environ, **(env or {})})


@pytest.fixture()
def repo(tmp_path):
    sh(tmp_path, "git", "init", "-q")
    sh(tmp_path, "git", "config", "user.email", "t@t"); sh(tmp_path, "git", "config", "user.name", "t")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "vercel_ignore.sh").write_text(SCRIPT.read_text())  # the real script, as it sits in the repo on Vercel
    for f in ("api/index.py", "mvp/server.py", "docs/a.md", "experiments/x.py", "scripts/s.py"):
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_text("1")
    sh(tmp_path, "git", "add", "-A"); sh(tmp_path, "git", "commit", "-qm", "base")
    return tmp_path


def prev(repo):
    return sh(repo, "git", "rev-parse", "HEAD").stdout.strip()


def commit(repo, path):
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    old = (repo / path).read_text() if (repo / path).exists() else ""
    (repo / path).write_text(old + "\n# changed\n")  # append: the file under test may be the ignore script itself, which must stay runnable
    sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-qm", "c")


def run(repo, env):
    return sh(repo, "bash", "-c", CMD, env=env).returncode


@pytest.mark.parametrize("path", ["docs/a.md", "experiments/x.py", "scripts/s.py", "README.md"])
def test_non_app_changes_skip_the_preview_build(repo, path):
    p = prev(repo); commit(repo, path)
    assert run(repo, {"VERCEL_ENV": "preview", "VERCEL_GIT_PREVIOUS_SHA": p}) == 0


@pytest.mark.parametrize("path", ["api/index.py", "mvp/server.py", "src/m.py", "public/i.html", "vercel.json", "requirements.txt", "requirements-vercel.txt", "scripts/vercel_ignore.sh"])
def test_app_changes_build(repo, path):
    p = prev(repo); commit(repo, path)
    assert run(repo, {"VERCEL_ENV": "preview", "VERCEL_GIT_PREVIOUS_SHA": p}) == 1


def test_earlier_app_change_in_a_multi_commit_push_still_builds(repo):
    p = prev(repo); commit(repo, "mvp/server.py"); commit(repo, "docs/a.md")  # last commit is docs-only, the push is not
    assert run(repo, {"VERCEL_ENV": "preview", "VERCEL_GIT_PREVIOUS_SHA": p}) == 1


def test_production_always_builds_even_for_docs_only(repo):
    p = prev(repo); commit(repo, "docs/a.md")
    assert run(repo, {"VERCEL_ENV": "production", "VERCEL_GIT_PREVIOUS_SHA": p}) == 1


def test_first_deploy_of_a_branch_builds(repo):
    commit(repo, "docs/a.md")
    assert run(repo, {"VERCEL_ENV": "preview", "VERCEL_GIT_PREVIOUS_SHA": ""}) == 1


def test_unknown_previous_sha_means_build_not_skip(repo):
    commit(repo, "docs/a.md")
    assert run(repo, {"VERCEL_ENV": "preview", "VERCEL_GIT_PREVIOUS_SHA": "0" * 40}) == 1


# ---- the Nov 3 failure: .vercelignore deleted .git before the ignore step, so `git diff` died with "Not a git repository" and every push built

def test_not_a_git_repository_builds_and_says_why(tmp_path):
    (tmp_path / "scripts").mkdir(); (tmp_path / "scripts" / "vercel_ignore.sh").write_text(SCRIPT.read_text())
    r = sh(tmp_path, "bash", "-c", CMD, env={"VERCEL_ENV": "preview", "VERCEL_GIT_PREVIOUS_SHA": "a" * 40})
    assert r.returncode == 1 and ".git" in r.stderr and "no git repository" in r.stderr


def test_previous_commit_missing_from_a_shallow_clone_builds_and_says_why(repo):
    commit(repo, "docs/a.md")
    r = sh(repo, "bash", "-c", CMD, env={"VERCEL_ENV": "preview", "VERCEL_GIT_PREVIOUS_SHA": "0" * 40})
    assert r.returncode == 1 and "not in this" in r.stderr


def test_the_build_log_explains_a_skip(repo):
    p = prev(repo); commit(repo, "docs/a.md")
    r = sh(repo, "bash", "-c", CMD, env={"VERCEL_ENV": "preview", "VERCEL_GIT_PREVIOUS_SHA": p})
    assert r.returncode == 0 and "skipping" in r.stderr


def test_vercelignore_keeps_git_for_the_ignore_step_and_the_function_excludes_it():
    # Both halves are needed together: .git is ~265 MB, over the ~250 MB function limit, so it must never be bundled; and it must not be
    # deleted before the ignore command runs, or the command cannot see what changed.
    lines = [l.strip() for l in (ROOT / ".vercelignore").read_text().splitlines()]
    assert ".git" not in lines and ".git/" not in lines and ".git/**" not in lines
    exclude = json.loads((ROOT / "vercel.json").read_text())["functions"]["api/index.py"]["excludeFiles"]
    assert ".git" in exclude
