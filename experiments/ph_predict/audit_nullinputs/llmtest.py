import os, sys, json
T = os.path.expanduser("~/w/phops_tm/h25fix"); sys.path.insert(0, T); sys.path.insert(1, os.path.expanduser("~/w/arm2_live")); os.chdir(os.path.expanduser("~/w/experiments/ph_predict")); sys.path.insert(2, ".")
import h25_live, features as F, run as RN
assert h25_live.__file__.startswith(T), h25_live.__file__
os.environ["H25_DATA"] = os.path.expanduser("~/w/phops_tm/h25data_test")
PA, info = h25_live.predict("2026-11-14")
root = os.environ["H25_DATA"]; print("predict ok", len(PA), info, "linked:", os.path.lexists(f"{root}/llm_pitch_gemini/2026-11-14.json"), os.path.lexists(f"{root}/llm_brand_gemini/2026-11-14.json"))
real = F.D; F.D = root
try:
    df = RN.load_llm(F.build(include_today=True))
finally:
    F.D = real
te = df[df.is_today & (df.day == "2026-11-14")]
print("llm_pitch nonnull", int(te.llm_pitch.notna().sum()), "of", len(te), "llm_brand nonnull", int(te.llm_brand.notna().sum()))
