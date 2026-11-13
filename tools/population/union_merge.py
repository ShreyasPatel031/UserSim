"""Lossless person merge (population agent, 12:3xZ Nov 13).

A newer pull of a person used to REPLACE the stored record, silently dropping every item and field the older pull had
and the newer one lacked (Nov 13 12:01Z batch: 1,138 of 1,539 replaced people lost items, e.g. 35k following edges).
Rule from now on: nothing a pull ever saw is dropped.

union(new, old) returns the newer pull with everything from the older record carried over:
  - the newest pull's own fields, items, counts and paging are left exactly as fetched, so completeness is still judged
    on the newest full read (mixing old items in tripped the repeated-page check for 48 of 1,539 people);
  - list tabs: items seen only by an older pull go to the tab's "items_earlier" list, marked "_carried_from":
    <that pull's finished_utc>;
  - every older record, minus the items moved above, is archived whole under "earlier_records";
  - "pull_history": every finished_utc this record has merged, oldest first.
The older record itself is also kept, untouched, under vm/_history/<stamp>/ by the caller.
"""
import copy
import json

TABS = ["about", "forums", "activity", "upvotes", "hunted", "collections", "stacks", "reviews", "followers", "following"]
IDK = {"upvotes": "post_id", "hunted": "post_id", "following": "ph_user_id", "followers": "ph_user_id",
       "collections": "collection_id", "stacks": "url", "reviews": "review_id", "activity": "id", "forums": "url"}


def _fin(d):
    return str((d.get("run") or {}).get("finished_utc") or d.get("fetched_at") or "")


def _item_key(t, x):
    if not isinstance(x, dict):
        return json.dumps(x, sort_keys=True, default=str)
    k = IDK.get(t)
    v = x.get(k) if k else None
    if v in (None, ""):
        v = x.get("url") or x.get("id")
    return f"{k}:{v}" if v not in (None, "") else json.dumps(x, sort_keys=True, default=str)


def _fill(dst, src):
    """keys missing from dst are copied from src; dicts recursively; dst values win."""
    for k, v in src.items():
        if k not in dst:
            dst[k] = copy.deepcopy(v)
        elif isinstance(dst[k], dict) and isinstance(v, dict):
            _fill(dst[k], v)


def union(new, old, keep_base=False):
    """newest pull untouched; everything only the older record had is kept beside it (see module docstring).
    keep_base=True: `new` stays the base even if `old` carries a later time (recovery from copies that never passed the
    audit must not let such a copy become the main record)."""
    if not isinstance(old, dict):
        return new
    if not isinstance(new, dict):
        return old
    if not keep_base and _fin(old) > _fin(new):
        new, old = old, new
    out = copy.deepcopy(new)
    of = _fin(old)
    for t in TABS:
        ot, nt = old.get(t), out.get(t)
        if not isinstance(ot, dict):
            continue
        if not isinstance(nt, dict):  # tab absent from the newest pull: keep the older tab whole, under the archive below
            continue
        seen = {_item_key(t, x) for x in (nt.get("items") or [])}
        earlier = list(nt.get("items_earlier") or [])
        seen |= {_item_key(t, x) for x in earlier}
        for x in list(ot.get("items") or []) + list(ot.get("items_earlier") or []):
            k = _item_key(t, x)
            if k in seen:
                continue
            seen.add(k)
            y = copy.deepcopy(x)
            if isinstance(y, dict) and "_carried_from" not in y:
                y["_carried_from"] = of
            earlier.append(y)
        if earlier or "items_earlier" in ot or "items_earlier" in nt:  # an empty list an older record had is kept too
            nt["items_earlier"] = earlier
    # every older record (minus its item lists, which are now in items_earlier) is archived whole
    arch = list(new.get("earlier_records") or []) + list(old.get("earlier_records") or [])
    o2 = {k: (v if k not in TABS or not isinstance(v, dict) else {kk: vv for kk, vv in v.items() if kk not in ("items", "items_earlier")})
          for k, v in old.items() if k not in ("earlier_records", "pull_history")}
    for t in TABS:  # a tab the newest pull lacks keeps its items in the archive
        if isinstance(old.get(t), dict) and not isinstance(out.get(t), dict):
            o2[t] = copy.deepcopy(old[t])
    if _fin(o2) != _fin(new) or o2.get("run") != new.get("run"):  # re-merging a record into itself archives nothing
        arch.append(o2)
    uniq, keys = [], set()
    for r in arch:  # idempotent: a record merged twice (retried run) is archived once
        k = json.dumps(r, sort_keys=True, default=str)
        if k not in keys:
            keys.add(k)
            uniq.append(r)
    out["earlier_records"] = uniq
    hist = list(old.get("pull_history") or ([of] if of else [])) + list(new.get("pull_history") or [])
    nf = _fin(new)
    if nf:
        hist.append(nf)
    out["pull_history"] = sorted(set(h for h in hist if h))
    return out


def lost(old, merged):
    """(items, field paths) present in old but absent from merged; both must be 0 after union()."""
    li = 0
    for t in TABS:
        ot, mt = old.get(t), merged.get(t)
        if not isinstance(ot, dict):
            continue
        ok = {_item_key(t, x) for x in (ot.get("items") or [])}
        mk = set()
        if isinstance(mt, dict):
            mk |= {_item_key(t, x) for x in (mt.get("items") or []) + (mt.get("items_earlier") or [])}
        for r in merged.get("earlier_records") or []:
            if isinstance(r.get(t), dict):
                mk |= {_item_key(t, x) for x in (r[t].get("items") or [])}
        li += len(ok - mk)

    def paths(o, p=""):
        s = set()
        if isinstance(o, dict):
            for k, v in o.items():
                q = p + "." + k
                s.add(q)
                if isinstance(v, dict):
                    s |= paths(v, q)
        return s
    have = paths(merged)
    for r in merged.get("earlier_records") or []:
        have |= paths(r)
    return li, len(paths(old) - have)


def union_with_store(local_dir, vm_url, names, tmp_dir):
    """Before upload: union each audited local copy local_dir/<n>.json with the record currently in the store
    (vm_url/<n>.json), in place. Bulk download; people not yet in the store are left as they are. Returns counts."""
    import os
    import subprocess
    os.makedirs(tmp_dir, exist_ok=True)
    for f in os.listdir(tmp_dir):
        os.remove(os.path.join(tmp_dir, f))
    for i in range(0, len(names), 2000):
        subprocess.run(["gcloud", "storage", "cp", "-I", f"{tmp_dir}/"], input="".join(f"{vm_url}/{n}.json\n" for n in names[i:i + 2000]),
                       capture_output=True, text=True)
    c = {"in_store": 0, "unioned_items_earlier": 0, "lost": 0}
    for n in names:
        rp, lp = os.path.join(tmp_dir, n + ".json"), os.path.join(local_dir, n + ".json")
        if not os.path.exists(rp) or not os.path.exists(lp):
            continue
        try:
            old, new = json.load(open(rp)), json.load(open(lp))
        except Exception:
            continue
        m = union(new, old)
        li, lpth = lost(old, m)
        c["lost"] += li + lpth
        c["in_store"] += 1
        c["unioned_items_earlier"] += sum(len((m.get(t) or {}).get("items_earlier") or []) for t in TABS if isinstance(m.get(t), dict))
        if li + lpth:  # never upload a record that would drop anything
            raise RuntimeError(f"union lost data for one person ({li} items, {lpth} fields); not uploading")
        json.dump(m, open(lp, "w"))
    return c
