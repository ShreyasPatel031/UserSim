import json, sys, pandas as pd
SP = sys.argv[1]; X = pd.read_parquet(f"{SP}/rb/X_full.parquet", columns=["id", "day", "name", "tagline", "description", "topics", "llm_pitch", "dailyRank", "votes", "ph_day_n_launches", "hist_hunter_n"])
H = {"try": [("ProductHunt Chaos Simulator", None), ("Firstpass", None), ("Articos", None)],
     "board": [("NODUS PH Radar for Product Hunt", None), ("PHBench", None), ("Product Huntr", None), ("Product Hunt Topics by xTopics", None), ("Product Hunt for Raycast", None), ("VisualPH", None)],
     "panel": [("Sapien", None), ("TheySaid 4.0", None), ("Snap", "2025-10-16"), ("Uxia", None), ("Userology AI", None), ("Velozity", "2025-05-03")],
     "pack": [("Submit.DIY", None), ("LaunchForge", None), ("Spira for Product Hunt Makers", None), ("FirstUser.app", None), ("IndieCrush - The Pre-Launch Playground", None), ("shippedit.me", None), ("Uneed Community", None)]}
W = {"try": [("HuntOMeter", "Predict your Product Hunt upvotes from your tagline", "Type a tagline and get an estimated upvote count. HuntOMeter compares it against more than 19,500 past Product Hunt products.", ["Artificial Intelligence", "Marketing", "Product Hunt"]),
             ("Roast My Landing Page AI", "Simulated target users roast your landing page", "Paste a landing page and simulated target users react to it. Roast mode gives fast first impressions; Professional mode gives structured diagnostics. Uses 50+ personas built from interviews, surveys and secondary research.", ["Marketing", "Artificial Intelligence", "User Experience"]),
             ("MockUsers", "AI personas browse your site and tell you why they would bounce", "A free tool that generates AI personas from your page content. They browse the site and report what is confusing, what they think you are selling, and why they would leave.", ["Marketing", "Artificial Intelligence", "User Experience"]),
             ("Wynter Message Test grader", "Grade your B2B homepage with 15 simulated buyers", "A free AI grader from Wynter. About 15 behaviourally diverse simulated personas read your page and are scored on whether they can tell what problem you solve and who it is for. Directional, not a replacement for a real panel.", ["Marketing", "SaaS", "Artificial Intelligence"])],
     "board": [("hunted.space", "Real-time Product Hunt launch stats", "Track upvotes, comments and rank of every Product Hunt launch hour by hour through launch day, compare launches, and use an AI predictor that models how evidence changes the odds of a launch.", ["Analytics", "Product Hunt", "Marketing"])],
     "panel": [("Synthetic Users (syntheticusers.com)", "User research without the users", "An AI research platform that runs interviews and surveys with synthetic personas built on large language models, for early product and concept testing.", ["User Experience", "Artificial Intelligence", "SaaS"]),
               ("Wynter", "On-demand messaging and market research", "Test B2B messaging with a panel of real, verified people from your target audience and get results in under 48 hours. Message tests, preference tests and surveys.", ["Marketing", "SaaS", "Analytics"])],
     "pack": [("Uprows Hub", "Product Hunt upvotes and engagement packages", "Packages priced by the number of Product Hunt upvotes and the engagement required for a launch, from a free trial to custom packages for larger launches.", ["Marketing", "Growth Hacking", "Product Hunt"])]}
out = []
for job in H:
    for nm, day in H[job]:
        r = X[(X.name == nm) & ((X.day == day) if day else True)].sort_values("day").iloc[-1]
        out.append({"job": job, "name": nm, "tagline": r.tagline, "description": r.description, "topics": list(r.topics)[:3], "source": "Product Hunt launch in our held data",
                    "finish": {"day": r.day, "rank": int(r.dailyRank), "launches_that_day": int(r.ph_day_n_launches), "votes": int(r.votes), "hunter_prior_hunts": int(r.hist_hunter_n), "stored_pitch": None if pd.isna(r.llm_pitch) else float(r.llm_pitch)}})
    for nm, tg, ds, tp in W[job]: out.append({"job": job, "name": nm, "tagline": tg, "description": ds, "topics": tp, "source": "web search summary; wording is ours", "finish": None})
json.dump(out, open(f"{SP}/comp/competitors.json", "w"), indent=1); print(len(out), pd.Series([o["job"] for o in out]).value_counts().to_dict())
