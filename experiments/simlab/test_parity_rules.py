"""parity_rules: the 16 measured nights raise no alert; each new kind of difference does.   python test_parity_rules.py"""
import copy, glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import parity_rules as R
N = [json.load(open(f)) for f in sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "arm2_rebuild/parity/2026-*.json")))]
fails = [r["day"] for r in N if R.classify(copy.deepcopy(r))]
assert len(N) == 16 and not fails, f"measured nights alerting: {fails}"
base = copy.deepcopy(N[0]); col = lambda s: {"share_equal": s, "expected": False}
def alerts(mut): r = copy.deepcopy(base); mut(r); return bool(R.classify(r))
assert alerts(lambda r: r["columns"].__setitem__("ph_new_column", col(0.9)))                 # a column never seen differing
assert alerts(lambda r: r["columns"].__setitem__("ph_desc_len", col(0.70)))                  # known column, worse than ever seen
assert alerts(lambda r: r.__setitem__("set change, all live columns together", [0, 0, 4]))   # bigger ranking effect than ever seen
assert not alerts(lambda r: r["columns"].__setitem__("ph_dayrank_ph_n_media", col(0.0)))     # line-up difference: known
assert not alerts(lambda r: r["columns"].__setitem__("ph_n_makers", col(0.85)))              # within the known range
print("parity_rules: 16 measured nights no alert; 3 new-kind cases alert; 2 known cases pass")
