"""Website freshness file (orchestrator 15:04Z Nov 12): results/web/heartbeat.json, one entry per timed step,
{step: {day, data_cut, written_at, status, late_min}} merged and uploaded on every write. Best effort: never raises."""
import json, os, subprocess
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(HERE, "results", "web", "heartbeat.json")
B = "gs://usersim-bakeoff-347838016394/usersim_sim"


def beat(step, day=None, data_cut=None, status="ok"):
    try:
        now = pd.Timestamp.now(tz="UTC"); os.makedirs(os.path.dirname(P), exist_ok=True)
        H = json.load(open(P)) if os.path.exists(P) else {}
        late = None
        if data_cut is not None:
            late = round((now - pd.Timestamp(data_cut)).total_seconds() / 60, 1)
        H.setdefault("steps", {})[step] = {"day": day, "data_cut": str(data_cut) if data_cut is not None else None,
                                          "written_at": now.isoformat(), "status": status, "late_min": late}
        H["updated_at"] = now.isoformat()
        json.dump(H, open(P, "w"), indent=1)
        subprocess.run(["gsutil", "-q", "cp", P, f"{B}/results/web/heartbeat.json"], timeout=60)
    except Exception as e:  # noqa: BLE001
        print("heartbeat skipped:", repr(e)[:120], flush=True)
