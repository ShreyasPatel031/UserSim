import json
o = json.load(open("results/ctrl_v1.json"))["each_input_vs_over_performance"]
n = json.load(open("results/ctrl.json"))["each_input_vs_over_performance"]
keys = ["ps_name", "ps_tagline", "ps_description", "ps_first_comment", "ps_website", "ps_logo", "ps_gallery", "ps_video", "ps_n_images",
        "ps_visual_polish", "ps_top5_chance", "vs_problem_shown", "vs_hook", "vs_wow", "vs_shows_real_ui", "pf_free_plan", "pf_price_point_not_stated"]
fmt = lambda r: f"{r['corr']:+.3f} {r['ci95']}" if r else "  —"
for k in keys:
    print(f"{k:26s} before {fmt(o.get(k)):24s} now {fmt(n.get(k))}")
