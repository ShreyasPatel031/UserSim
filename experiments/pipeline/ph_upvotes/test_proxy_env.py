"""Tests for proxy_env.sh (stubbed gcloud/gsutil) and the redaction in fetch_upvotes.py. python -m pytest experiments/pipeline/ph_upvotes/test_proxy_env.py"""
import importlib.util
import os
import pathlib
import stat
import subprocess

import pytest

HERE = pathlib.Path(__file__).resolve().parent
SECRET = "http://user123:p4ssw0rd-XYZ@gw.example.com:823"


def stub(bin_dir, name, body):
    p = bin_dir / name
    p.write_text("#!/bin/bash\n" + body + "\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)


def run_load(tmp_path, *, secret_ok, gcs_value, args=("sec", "proj", "gs://b/secrets/proxy_url.txt")):
    b = tmp_path / "bin"; b.mkdir(exist_ok=True)
    stub(b, "gcloud", f'[ "{int(secret_ok)}" = 1 ] && printf %s "{SECRET}" || {{ echo "ERROR: permission denied {SECRET}" >&2; exit 1; }}')
    stub(b, "gsutil", f'if [ -n "{gcs_value}" ]; then printf "%s\\r\\n" "{gcs_value}"; else echo "CommandException: no such object" >&2; exit 1; fi')
    out = tmp_path / "value.txt"
    script = f'. {HERE}/proxy_env.sh; load_proxy {" ".join(repr(a) for a in args)}; rc=$?; printf %s "${{PROXY_URL:-}}" > {out}; exit $rc'
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env={**os.environ, "PATH": f"{b}:{os.environ['PATH']}"})
    return r, out.read_text()


def test_secret_manager_is_used_first_and_the_value_is_never_printed(tmp_path):
    r, val = run_load(tmp_path, secret_ok=True, gcs_value="http://other:pw@h:1")
    assert r.returncode == 0 and val == SECRET
    assert "secret_manager" in r.stderr and SECRET not in r.stdout + r.stderr and "p4ssw0rd" not in r.stdout + r.stderr


def test_falls_back_to_the_private_gcs_object_and_strips_the_newline(tmp_path):
    r, val = run_load(tmp_path, secret_ok=False, gcs_value=SECRET)
    assert r.returncode == 0 and val == SECRET  # no trailing CR/LF in the exported value
    assert "gcs_object" in r.stderr and "p4ssw0rd" not in r.stdout + r.stderr


def test_gcs_only_when_no_secret_name_is_given(tmp_path):
    r, val = run_load(tmp_path, secret_ok=True, gcs_value=SECRET, args=("", "", "gs://b/secrets/proxy_url.txt"))
    assert val == SECRET and "gcs_object" in r.stderr


def test_fails_loudly_when_neither_source_works_and_exports_nothing(tmp_path):
    r, val = run_load(tmp_path, secret_ok=False, gcs_value="")
    assert r.returncode == 1 and val == "" and "no source gave a value" in r.stderr
    assert "p4ssw0rd" not in r.stdout + r.stderr  # the stubbed reader's error text must not leak either


def test_rejects_a_value_that_is_not_a_url(tmp_path):
    r, val = run_load(tmp_path, secret_ok=False, gcs_value="Access denied: not a url")
    assert r.returncode == 1 and val == "" and "not an http(s) URL" in r.stderr


def test_redaction_removes_the_proxy_url_user_and_password(monkeypatch):
    spec = importlib.util.spec_from_file_location("fu", HERE / "fetch_upvotes.py")
    fu = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fu)
    monkeypatch.setenv("PROXY_URL", SECRET)
    msg = f"net::ERR_PROXY at {SECRET} auth user123 failed with p4ssw0rd-XYZ for host gw.example.com"
    out = fu._redact(msg)
    assert "p4ssw0rd" not in out and "user123" not in out and SECRET not in out and "gw.example.com" in out
    monkeypatch.delenv("PROXY_URL")
    assert fu._redact("plain error") == "plain error"
