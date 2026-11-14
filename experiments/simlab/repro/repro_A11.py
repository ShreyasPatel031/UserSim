"""Repro A11 (d9b9a96f): rollback must work inside 00:05-01:00 PT in deploy_b12.sh and deploy_b12a.sh; deploy must still refuse there.
Each script is copied with W=/home/agent/w pointed at a temp dir, and date / crontab / gsutil / id stubbed (date +%H%M -> 0030).
    python repro_A11.py <ph-ops checkout root>     exit 0 = fixed, 1 = defect present"""
import sys, os, subprocess, tempfile, json
ROOT = sys.argv[1]; PP = f"{ROOT}/experiments/pipeline_patches"; res = {}
for name, rel in (("b12", "20261114_timed_writes/deploy_b12.sh"), ("b12a", "20261114_two_predictions/deploy_b12a.sh")):
    tmp = tempfile.mkdtemp(); stub = f"{tmp}/bin"; os.makedirs(stub)
    for b, body in (("date", 'case "$*" in *%H%M*) echo 0030;; *) /bin/date "$@";; esac'), ("crontab", 'if [ "$1" = -l ]; then echo "@reboot run_daily.sh"; fi; exit 0'),
                    ("gsutil", "exit 0"), ("id", "echo agent")):
        open(f"{stub}/{b}", "w").write("#!/bin/bash\n" + body + "\n"); os.chmod(f"{stub}/{b}", 0o755)
    s = open(f"{PP}/{rel}").read().replace("/home/agent/w", f"{tmp}/w").replace("export PATH=/opt/exp/bin:$PATH", f"export PATH={stub}:$PATH")
    os.makedirs(f"{tmp}/w"); open(f"{tmp}/d.sh", "w").write(s); env = dict(os.environ, PATH=f"{stub}:{os.environ['PATH']}")
    rb = subprocess.run(["bash", f"{tmp}/d.sh", "rollback"], capture_output=True, text=True, env=env)
    dp = subprocess.run(["bash", f"{tmp}/d.sh", "abc123", "deadbeef"] if name == "b12" else ["bash", f"{tmp}/d.sh", tmp], capture_output=True, text=True, env=env)
    res[name] = {"rollback rc": rb.returncode, "rollback out": (rb.stdout + rb.stderr).strip()[-120:], "deploy rc": dp.returncode, "deploy out": (dp.stdout + dp.stderr).strip()[-80:]}
ok = all(r["rollback rc"] == 0 and r["deploy rc"] != 0 and "not deploying" in r["deploy out"] for r in res.values())
print(json.dumps({**res, "A11 fixed": ok})); sys.exit(0 if ok else 1)
