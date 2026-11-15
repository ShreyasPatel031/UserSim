import os, sys, json, importlib
MODE = sys.argv[1]; T = os.path.expanduser("~/w/phops_tm/h25fix")
paths = ([os.path.expanduser("~/w/today_rows.new")] if MODE == "fixed" else []) + ([T] if MODE == "fixed" else []) + [os.path.expanduser("~/w/arm2_live")]
for i, p in enumerate(paths): sys.path.insert(i, p)
os.chdir(os.path.expanduser("~/w/experiments/ph_predict")); sys.path.insert(len(paths), ".")
import features as F
F.D = os.path.expanduser("~/w/experiments/ph_predict/data")
import h25_live
os.environ["H25_DATA"] = os.path.expanduser("~/w/phops_tm/h25data_" + MODE)
PA, info = h25_live.predict("2026-11-14")
print(json.dumps({"mode": MODE, "h25": h25_live.__file__, "features": F.__file__, "pred": dict(zip(PA.id, PA.pred_arm2.round(4)))}))
