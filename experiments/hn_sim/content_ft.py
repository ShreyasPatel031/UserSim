"""Content model at posting (orchestrator's bet, 2026-11-03): fine-tune a text classifier on what is known at posting
(title + domain + Show/Ask text; page text as a second variant) to predict "ever in a daily top 30".

Option (b) from the scoping: ModernBERT-base on one L4 (g2-standard-4, ~$0.71/h, 3-5 h), not Gemini tuning ($35-50).
Honest by construction: each model trains only on posts from days <= its cut, and scores only later posts.
  cut jun30 -> scores Jul 1 - Oct 14 2026, all out of sample (used as an input to the at-posting and 15-min models)
  cut aug30 -> Sep 1 - Oct 14 (stand-alone AUC / Caught, the at-posting test period)
  cut sep30 -> Oct 2 - 14 (stand-alone, freshest model for the 15-min test days)
  page_aug30 -> title + domain + page text, trained Jul 1 - Aug 30 2026 (page text exists only from Jul 2026)

    python content_ft.py prep       # local: build data.parquet, upload with this file
    python content_ft.py launch     # local: create the L4 VM (startup script trains, uploads scores, deletes the VM)
    python content_ft.py train      # on the VM
    python content_ft.py gate       # local: download scores, paired Caught vs 23.2% (at posting) and wb15 (15 min)
"""
import html
import json
import os
import re
import sys

import numpy as np
import pandas as pd

BUCKET = "usersim-bakeoff-347838016394"
PFX = "usersim_sim/hn_jobs/cache/content_ft/"
CUTS = {"jun30": "2026-06-30", "aug30": "2026-08-30", "sep30": "2026-09-30"}
FIRST, LAST = "2025-01-15", "2026-10-14"
MODEL = "answerdotai/ModernBERT-base"


def clean(t):
    t = re.sub(r"<[^>]+>", " ", html.unescape(t or ""))
    return re.sub(r"\s+", " ", t).strip()


def prep():
    import store as S
    CACHE = os.environ.get("USERSIM_CACHE", os.path.expanduser("~/.usersim_sim"))
    H = type("H", (), {"CACHE": CACHE})
    s = pd.read_parquet(os.path.join(H.CACHE, "bq_stories.parquet"), columns=["post_id", "title", "url", "text", "day"])
    s = s[(s.day >= FIRST) & (s.day <= LAST)].drop_duplicates("post_id").reset_index(drop=True)
    L = pd.concat([pd.read_json(os.path.join(CACHE, f), lines=True, dtype={"day": str}) for f in ("frontday.jsonl", "frontday_old.jsonl")])
    s["y"] = s.post_id.isin(set(L[L["rank"] <= 30].post_id)).astype(np.int8)
    dom = s.url.fillna("").str.replace(r"https?://(www\.)?", "", regex=True).str.split("/").str[0]
    body = s.text.fillna("").map(clean).str[:400]
    s["x"] = s.title.fillna("") + " [" + dom.where(dom != "", "self") + "] " + body
    page = {}
    for line in open(os.path.join(H.CACHE, "page_text.jsonl")):
        d = json.loads(line)
        if d.get("text"):
            page[d["post_id"]] = d["text"][:2000]
    s["page"] = s.post_id.map(page).fillna("")
    out = s[["post_id", "day", "y", "x", "page"]]
    f = os.path.join(H.CACHE, "content_ft_data.parquet")
    out.to_parquet(f, index=False)
    b = S._bucket()
    b.blob(PFX + "data.parquet").upload_from_filename(f)
    b.blob(PFX + "content_ft.py").upload_from_filename(__file__)
    print(f"{len(out)} posts, {int(out.y.sum())} winners, with page text {int((out.page != '').sum())}; uploaded", flush=True)


STARTUP = r"""#!/bin/bash
exec >> /var/log/cft.log 2>&1
B=gs://%(bucket)s/%(pfx)s
[ -f /opt/cft/started ] && exit 0
mkdir -p /opt/cft && cd /opt/cft && touch started
shutdown -h +420                                  # hard stop after 7 h whatever happens
(while true; do gcloud storage cp -q /opt/cft/train.log $B/train.log 2>/dev/null; gcloud storage cp -q /var/log/cft.log $B/startup.log; sleep 120; done) &
gcloud storage cp -q $B/data.parquet $B/content_ft.py .
for i in $(seq 60); do nvidia-smi && break; sleep 20; done
PY=python3
for p in /opt/conda/bin/python /opt/python/bin/python3 python3; do $p -c "import torch" 2>/dev/null && PY=$p && break; done
$PY -c "import torch" || $PY -m pip install -q torch
$PY -m pip install -q "transformers>=4.48" pandas pyarrow scikit-learn
$PY content_ft.py train > train.log 2>&1
gcloud storage cp -q train.log $B/train.log; gcloud storage cp -q scores_*.parquet $B/
gcloud storage cp -q /var/log/cft.log $B/startup.log
echo deleting; gcloud storage cp -q /var/log/cft.log $B/startup.log; gcloud compute instances delete $(hostname) --zone %(zone)s --quiet
"""


def launch(name="hn-cft-1", Z=None):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src"))
    from auth import vertex_credentials
    from google.cloud import compute_v1
    P, Z = "project-amer-scs-sandbox", Z or os.environ.get("CFT_ZONE", "us-central1-b")
    MT = os.environ.get("CFT_MACHINE", "g2-standard-4")     # L4; "n1-standard-4" = one T4 (L4 stocked out 2026-11-03)
    inst = compute_v1.Instance(
        name=name, machine_type=f"zones/{Z}/machineTypes/{MT}",
        guest_accelerators=[] if MT.startswith("g2") else [compute_v1.AcceleratorConfig(
            accelerator_count=1, accelerator_type=f"zones/{Z}/acceleratorTypes/nvidia-tesla-t4")],
        disks=[compute_v1.AttachedDisk(boot=True, auto_delete=True, initialize_params=compute_v1.AttachedDiskInitializeParams(
            source_image="projects/deeplearning-platform-release/global/images/family/pytorch-2-9-cu129-ubuntu-2204-nvidia-580",
            disk_size_gb=100))],
        network_interfaces=[compute_v1.NetworkInterface(network="global/networks/main-vpc",
                                                        subnetwork="regions/us-central1/subnetworks/primary-subnet",
                                                        access_configs=[compute_v1.AccessConfig(name="External NAT")])],
        service_accounts=[compute_v1.ServiceAccount(email="347838016394-compute@developer.gserviceaccount.com",
                                                    scopes=["https://www.googleapis.com/auth/cloud-platform"])],
        scheduling=compute_v1.Scheduling(on_host_maintenance="TERMINATE", automatic_restart=False),
        metadata=compute_v1.Metadata(items=[
            compute_v1.Items(key="install-nvidia-driver", value="True"),
            compute_v1.Items(key="startup-script", value=STARTUP % {"bucket": BUCKET, "pfx": PFX, "zone": Z})]),
        labels={"owner": "hn-sim", "purpose": "content-ft"})
    op = compute_v1.InstancesClient(credentials=vertex_credentials()).insert(project=P, zone=Z, instance_resource=inst)
    op.result(timeout=300)
    print("created", name, flush=True)


def train():
    import time

    import torch
    from sklearn.metrics import roc_auc_score
    from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup
    D = pd.read_parquet("data.parquet")
    tok = AutoTokenizer.from_pretrained(MODEL)
    dev = "cuda"
    import subprocess
    bf = torch.cuda.is_bf16_supported()                      # L4 yes; T4 no -> fp16 with loss scaling
    dt = torch.bfloat16 if bf else torch.float16
    scaler = torch.amp.GradScaler("cuda", enabled=not bf)
    print("GPU", torch.cuda.get_device_name(0), "bf16" if bf else "fp16", flush=True)

    def batches(texts, bs, maxlen):
        for i in range(0, len(texts), bs):
            yield i, tok(texts[i:i + bs], truncation=True, max_length=maxlen, padding=True, return_tensors="pt").to(dev)

    def run(name, tr, te, col, maxlen, epochs=2, bs=64):
        t0 = time.time()
        torch.manual_seed(0)
        m = AutoModelForSequenceClassification.from_pretrained(MODEL, num_labels=1).to(dev)
        opt = torch.optim.AdamW(m.parameters(), lr=3e-5, weight_decay=0.01)
        steps = epochs * ((len(tr) + bs - 1) // bs)
        sch = get_linear_schedule_with_warmup(opt, int(0.05 * steps), steps)
        lossf = torch.nn.BCEWithLogitsLoss()
        m.train()
        for ep in range(epochs):
            idx = np.random.default_rng(ep).permutation(len(tr))
            X, y = tr[col].to_numpy()[idx].tolist(), torch.tensor(tr.y.to_numpy()[idx], dtype=torch.float32)
            for k, (i, enc) in enumerate(batches(X, bs, maxlen)):
                with torch.autocast("cuda", dtype=dt):
                    out = m(**enc).logits.squeeze(-1)
                loss = lossf(out.float(), y[i:i + bs].to(dev))
                scaler.scale(loss).backward()
                scaler.unscale_(opt)
                torch.nn.utils.clip_grad_norm_(m.parameters(), 1.0)
                scaler.step(opt); scaler.update(); sch.step(); opt.zero_grad()
                if k % 500 == 0:
                    print(f"{name} ep{ep} step {k}/{steps // epochs} loss {loss.item():.4f} {time.time() - t0:.0f}s", flush=True)
        m.eval()
        s = np.zeros(len(te), np.float32)
        X = te[col].tolist()
        with torch.no_grad():
            for i, enc in batches(X, 256, maxlen):
                with torch.autocast("cuda", dtype=dt):
                    s[i:i + 256] = m(**enc).logits.squeeze(-1).float().cpu().numpy()
        auc = roc_auc_score(te.y, s) if te.y.nunique() == 2 else float("nan")
        print(f"== {name}: train {len(tr)} ({int(tr.y.sum())} winners), test {len(te)}, AUC {auc:.4f}, {time.time() - t0:.0f}s", flush=True)
        te[["post_id", "day", "y"]].assign(s=s).to_parquet(f"scores_{name}.parquet", index=False)
        subprocess.run(["gcloud", "storage", "cp", "-q", f"scores_{name}.parquet", f"gs://{BUCKET}/{PFX}scores_{name}.parquet"])
        del m, opt
        torch.cuda.empty_cache()

    for name in ("jun30", "aug30"):                          # priority order: these two feed both gates
        run(name, D[D.day <= CUTS[name]], D[D.day > CUTS[name]], "x", 128)
    P = D[(D.day >= "2026-07-01") & (D.page != "")].copy()
    P["xp"] = P.x + " || " + P.page
    run("page_aug30", P[P.day <= "2026-08-30"], P[P.day > "2026-08-30"], "xp", 512, bs=32)
    # same posts, title-only model trained on the same Jul-Aug rows (for a fair page-text comparison)
    run("pagectl_aug30", P[P.day <= "2026-08-30"], P[P.day > "2026-08-30"], "x", 128)
    run("sep30", D[D.day <= CUTS["sep30"]], D[D.day > CUTS["sep30"]], "x", 128)
    print("DONE", flush=True)


def kinds(Q):
    """Winner type per post: fast (front page within 1 h), late riser, re-up (first listed 2+ days after posting)."""
    import fine_io
    import odds_live as OL
    _, qs = fine_io.load()
    qb = {r.post_id: {"qn_f0": r.qn_f0, "qn_rank_10m": r.qn_rank_10m, "qn_up_10m": r.qn_up_10m, "qn_exp_10m": r.qn_exp_10m}
          for r in qs.itertuples()}
    vis60 = (OL.vote_feats(Q, qb, [60])[60].best_rank <= 30).to_numpy()       # a label only, never an input
    L = OL.lists()
    first = L[L["rank"] <= 30].groupby("post_id").day.min()
    lag = (pd.to_datetime(Q.post_id.map(first)) - pd.to_datetime(Q.day)).dt.days.to_numpy()
    y = Q.y.to_numpy()
    return np.where(y == 0, "none", np.where(lag >= 2, "reup", np.where(vis60, "fast", "late")))


def by_type(T, s, kind):
    k = int(T.y.sum())
    flag = pd.Series(s).rank(ascending=False, method="first").to_numpy() <= k
    return ", ".join(f"{t} {int((flag & (kind == t)).sum())}/{int((kind == t).sum())}" for t in ("fast", "late", "reup"))


def gate():
    import lightgbm as lgb
    from sklearn.metrics import roc_auc_score

    import caught as C
    import caught1h as C1
    import store as S
    import top100 as H
    import wb15 as W15
    import wb_caught as W
    b = S._bucket()
    sc = {}
    for n in list(CUTS) + ["page_aug30", "pagectl_aug30"]:
        f = os.path.join(H.CACHE, f"content_scores_{n}.parquet")
        x = b.get_blob(PFX + f"scores_{n}.parquet")
        if x is not None:
            x.download_to_filename(f)
            sc[n] = pd.read_parquet(f).drop_duplicates("post_id").set_index("post_id").s
    Q = C.Q
    te = C.te
    kind = kinds(Q)
    # --- checkpoint 3: at posting, Sep 1 - Oct 14 (the 23.2% test) ---
    T = Q[te][["post_id", "day", "y"]].reset_index(drop=True)
    kt = kind[te]
    rk = lambda v: pd.Series(np.asarray(v, float)).rank(pct=True).to_numpy()
    base = C.model(C.POST + C.KNN + C.EMB + C.CROWD)
    h = np.load(os.path.join(H.CACHE, "caught_hist2_test_scores.npy"))
    b23 = 0.5 * rk(base) + 0.5 * rk(h)
    c23 = C.caught(b23)
    print(f"AT POSTING (Sep 1 - Oct 14, {int(T.y.sum())} winners): current blend {C.ci(c23)} | by type {by_type(T, b23, kt)}", flush=True)
    if "aug30" in sc:
        ca = T.post_id.map(sc["aug30"]).fillna(-99).to_numpy()
        print(f"   content model alone (trained <= Aug 30): AUC {roc_auc_score(T.y, ca):.3f}, pairwise {C.pairwise(ca)}, "
              f"Caught {C.ci(C.caught(ca))} | by type {by_type(T, ca, kt)}", flush=True)
        s3 = (rk(base) + rk(h) + rk(ca)) / 3
        print(f"   3-way rank blend (pre-set equal weights): {C.ci(C.caught(s3))}, vs current {C.diff(C.caught(s3), c23)} "
              f"| by type {by_type(T, s3, kt)}", flush=True)
    if "jun30" in sc:
        cj = pd.DataFrame({"content": Q.post_id.map(sc["jun30"]).to_numpy()})
        m = C.model(C.POST + C.KNN + C.EMB + C.CROWD, extra=cj)
        s2 = 0.5 * rk(m) + 0.5 * rk(h)
        print(f"   content (trained <= Jun 30) as an input to the Jul-Aug model, same 50/50 blend: {C.ci(C.caught(s2))}, "
              f"vs current {C.diff(C.caught(s2), c23)}, pairwise vs current {C.pairwise(s2, b23)} | by type {by_type(T, s2, kt)}", flush=True)
    if "page_aug30" in sc and "pagectl_aug30" in sc:
        P = pd.DataFrame({"pg": sc["page_aug30"], "ct": sc["pagectl_aug30"]}).join(Q.set_index("post_id")[["y"]], how="inner")
        print(f"   page text (posts with a fetched page, {len(P)} Sep-Oct posts, {int(P.y.sum())} winners): AUC title+domain "
              f"{roc_auc_score(P.y, P.ct):.3f} -> + page text {roc_auc_score(P.y, P.pg):.3f}", flush=True)
    # --- checkpoint 2: 15 min, Oct 2-14 forward daily retrain (wb_gh base: votes + who, 28.4%) ---
    if "jun30" not in sc:
        return
    import fine_io
    import odds_live as OL
    import pj_eval
    Q = Q.merge(pd.read_parquet(os.path.join(H.CACHE, "hist_prior.parquet")), on="post_id", how="left")
    Q = Q.merge(pj_eval.judge_feats(), on="post_id", how="left")
    AT = C.POST + C.KNN + C.EMB + C.CROWD + ["hist_prior"] + [c for c in Q.columns if c.startswith("pj_")]
    _, qs = fine_io.load()
    qb = {r.post_id: {"qn_f0": r.qn_f0, "qn_rank_10m": r.qn_rank_10m, "qn_up_10m": r.qn_up_10m, "qn_exp_10m": r.qn_exp_10m}
          for r in qs.itertuples()}
    R = C.honest(OL.vote_feats(Q, qb, [15])[15], 15, set(qb))[["rank_now", "best_rank"]]
    C1.Q = Q
    CM, WHO = C1.comments(15)
    base = pd.concat([Q[AT], R, CM[["cm_n", "cm_people", "cm_first"]], W15.votes15(Q), WHO], axis=1)
    X1 = base.assign(content=Q.post_id.map(sc["jun30"]).to_numpy())
    y = Q.y.to_numpy()
    days = sorted(d for d in Q.day.unique() if "2026-10-02" <= d <= "2026-10-14")
    s0, s1 = np.full(len(Q), np.nan), np.full(len(Q), np.nan)
    for d in days:
        tr = (Q.day <= (pd.Timestamp(d) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")).to_numpy()
        tt = (Q.day == d).to_numpy()
        s0[tt] = lgb.LGBMClassifier(**W15.PRM).fit(base[tr], y[tr]).predict_proba(base[tt])[:, 1]
        s1[tt] = lgb.LGBMClassifier(**W15.PRM).fit(X1[tr], y[tr]).predict_proba(X1[tt])[:, 1]
    sel = Q.day.isin(days).to_numpy()
    T = Q[sel][["post_id", "day", "y"]].reset_index(drop=True)
    c0, c1 = W.caught_on(T, s0[sel]), W.caught_on(T, s1[sel])
    print(f"15 MIN (Oct 2-14, {int(T.y.sum())} winners): votes + who {W.ci2(c0)} | by type {by_type(T, s0[sel], kind[sel])}", flush=True)
    print(f"   + content model: {W.ci2(c1)}, difference {W.ci2(c1, c0)} | by type {by_type(T, s1[sel], kind[sel])}", flush=True)


if __name__ == "__main__":
    {"prep": prep, "launch": launch, "train": train, "gate": gate}[sys.argv[1]]()
