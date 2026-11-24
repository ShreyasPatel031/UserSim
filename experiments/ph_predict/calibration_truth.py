"""Calibration truth for the plugin agent's simulated user tests (orchestrator 08:50Z Nov 21).
usage: python calibration_truth.py <D> [--dry OUTDIR]  ->  gs://.../results/calibration/<D>/truth.json (or OUTDIR/truth.json with --dry)
Per launch_id of day D (PT):
  - final daily rank and votes: official API ranking order (board_ts page=api_v2_ranking) in the label snapshot = the first 15-minute
    snapshot with snapshot_id >= <D>T2345PT (orchestrator 19:00Z Nov 13); truth_daily.json rank added when present.
  - comments: every comment row in live/comments_ts.jsonl (official API v2) created at or before the day's close (23:59:59 PT),
    as text with timestamp, is_maker (commenter user id in the API team list for that launch), is_reply (parent_id set).
    No usernames, user ids or comment ids in the output.
  - themes: E5's complaint-recall truth labelling (experiments/simlab/complaint_recall/run.py truth(), Gemini 2.5 flash on Vertex,
    same prompt): complaints and questions, counted by distinct non-team commenters. No Claude calls.
Notes carried in the file: replies are absent if the capture held none; comments are as captured (PH totals can be higher)."""
import html, json, os, re, subprocess, sys, tempfile, time, urllib.request
import pandas as pd
B = "gs://usersim-bakeoff-347838016394/usersim_sim"
GEMINI = ("https://aiplatform.googleapis.com/v1/projects/project-amer-scs-sandbox/locations/global/publishers/google/"
          "models/gemini-2.5-flash:generateContent")
cat = lambda p: subprocess.run(["gsutil", "cat", p], capture_output=True, text=True).stdout
rows = lambda p: [json.loads(l) for l in cat(p).splitlines() if l.strip()]
scrub = lambda s: re.sub(r"@\w+", "", str(s))
TRUTH_PROMPT = ("Below are real comments left by Product Hunt users on one product launch (team replies removed). Each line: [commenter code] comment.\n"
    "List the distinct COMPLAINTS (complaints, doubts, worries, things missing or broken) and the distinct QUESTIONS (things commenters asked the makers) that they raised. Be specific to this product; ignore praise and congratulations; merge near-duplicates; at most 12 of each. A point can be both only if two different commenters framed it differently.\n"
    "Return JSON: {\"complaints\": [{\"theme\": \"<under 18 words>\", \"commenters\": [\"c1\"]}], \"questions\": [{\"theme\": \"...\", \"commenters\": [\"c2\"]}]}\n\n")


def text(body):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(body or "")))).strip()


def gemini(prompt):
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 3000, "responseMimeType": "application/json", "thinkingConfig": {"thinkingBudget": 0}}}
    for i in range(4):
        try:
            tok = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
            req = urllib.request.Request(GEMINI, json.dumps(body).encode(), {"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                j = json.load(r)
            return json.loads(re.search(r"\{.*\}", "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"]), re.S).group(0))
        except Exception as e:  # noqa: BLE001  (class name only: never print error bodies)
            print("gemini retry", i, type(e).__name__, flush=True); time.sleep(5 * (i + 1))
    return None


def themes(g):
    g = g[~g.is_maker & (g.text.str.len() > 15)]
    if not len(g): return {"complaints": [], "questions": [], "n_commenters": 0, "n_comments": 0, "status": "no non-team comments"}
    code = {u: f"c{k + 1}" for k, u in enumerate(g.uid.unique())}
    t = gemini(TRUTH_PROMPT + "\n".join(f"[{code[u]}] {x[:500]}" for u, x in zip(g.uid, g.text)))
    if t is None: return {"status": "labelling failed", "n_commenters": len(code), "n_comments": len(g)}
    f = lambda L: [{"theme": scrub(x["theme"]), "n_commenters": len(set(x.get("commenters", [])) & set(code.values()))}
                   for x in L if len(set(x.get("commenters", [])) & set(code.values()))]
    return {"complaints": f(t.get("complaints", [])), "questions": f(t.get("questions", [])), "n_commenters": len(code), "n_comments": len(g), "status": "ok"}


def main(d, dry=None):
    L = f"{B}/raw/ph_at_launch/{d}/live"
    close = pd.Timestamp(d + " 23:59:59", tz="America/Los_Angeles").tz_convert("UTC")
    cov = rows(f"{L}/coverage_ts.jsonl"); label = sorted({r["snapshot_id"] for r in cov if r["snapshot_id"] >= d.replace("-", "") + "T2345PT"})
    if not label: sys.exit(f"no label snapshot at or after {d} 23:45 PT yet")
    sid = label[0]
    board = [r for r in rows(f"{L}/board_ts.jsonl") if r["snapshot_id"] == sid and r.get("page") == "api_v2_ranking"]
    if not board: sys.exit(f"no official ranking rows in label snapshot {sid}")
    td = json.loads(cat(f"{B}/results/web/truth_daily.json") or "{}").get("days", {}).get(d, {}).get("ranks", {})
    team = {}
    for r in rows(f"{B}/raw/ph_at_launch/{d}/api_teams.jsonl"):
        team.setdefault(str(r.get("post_id")), set()).add(str(r.get("maker_id")))
    C = pd.DataFrame(rows(f"{L}/comments_ts.jsonl"))
    if len(C):
        C = C.drop_duplicates("comment_id"); C["ts"] = pd.to_datetime(C.created_at, utc=True, errors="coerce"); n_after = int((C.ts > close).sum())
        C = C[C.ts <= close].copy(); C["launch_id"] = C.launch_id.astype(str); C["uid"] = C.user_id.astype(str); C["text"] = C.body.map(text)
        C["is_maker"] = [u in team.get(l, set()) for u, l in zip(C.uid, C.launch_id)]; C["is_reply"] = C.parent_id.notna()
    else:
        n_after = 0
    out = {}
    for r in sorted(board, key=lambda r: int(r["daily_rank"]) if str(r.get("daily_rank")) not in ("", "None") else 10**6):
        i = str(r["launch_id"]); g = C[C.launch_id == i].sort_values("ts") if len(C) else pd.DataFrame()
        out[i] = {"slug": r.get("slug"), "final_daily_rank": (int(r["daily_rank"]) if str(r.get("daily_rank")) not in ("", "None") else None),
                  "final_votes": (int(r["votes_shown"]) if str(r.get("votes_shown")) not in ("", "None") else None),
                  "truth_daily_rank": td.get(i),
                  "comments": [{"text": scrub(x.text), "created_at": x.ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "is_maker": bool(x.is_maker), "is_reply": bool(x.is_reply)}
                               for x in g.itertuples()] if len(g) else [],
                  "themes": themes(g) if len(g) else {"complaints": [], "questions": [], "n_commenters": 0, "n_comments": 0, "status": "no comments"}}
    n_rep = int(C.is_reply.sum()) if len(C) else 0
    res = {"day": d, "written_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"), "label_snapshot": sid, "launches": len(out),
           "source": {"rank_votes": "official API v2 ranking order in the label snapshot (board_ts page=api_v2_ranking)",
                      "comments": "live/comments_ts.jsonl (official API v2), created_at <= day close 23:59:59 PT; no usernames or ids",
                      "is_maker": "commenter user id in api_teams.jsonl makers for that launch (hunter not flagged)",
                      "themes": "E5 complaint_recall truth labelling (complaints / questions by distinct non-team commenters), Gemini 2.5 flash, temperature 0"},
           "notes": ([f"no replies in the capture for this day ({len(C)} comments, all top-level)"] if len(C) and not n_rep else [])
                    + [f"{n_after} comments created after the day's close are left out",
                       "comments are as captured by the live official-API loop; a launch's comments_count on PH can be higher than the rows here"],
           "by_launch": out}
    s = json.dumps(res, indent=1, ensure_ascii=False)
    if dry:
        os.makedirs(dry, exist_ok=True); open(f"{dry}/truth.json", "w").write(s); print("DRY", f"{dry}/truth.json")
    else:
        fd, p = tempfile.mkstemp(suffix=".json"); os.write(fd, s.encode()); os.close(fd)
        subprocess.run(["gsutil", "-q", "cp", p, f"{B}/results/calibration/{d}/truth.json"], check=True); os.remove(p)
    print(json.dumps({"day": d, "label_snapshot": sid, "launches": len(out), "comments": int(len(C)), "replies": n_rep,
                      "themes_ok": sum(v["themes"].get("status") == "ok" for v in out.values()),
                      "themes_failed": sum(v["themes"].get("status") == "labelling failed" for v in out.values())}))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[3] if len(sys.argv) > 3 and sys.argv[2] == "--dry" else None)
