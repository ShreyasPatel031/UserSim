"""Crowd step v0: expected votes per launch = sum over sampled people of P(sees it) x P(upvotes | sees it).
  P(upvotes | sees)  the person's reaction score (persona engine), mapped to [0, 1]
  P(sees)            base visibility for everyone on the homepage, raised for people who follow the poster or a maker
                     (follow lists are read today: undated)
  herding            optional: launches already ahead pull extra votes, V <- V * (1 + beta * standing within the day)
Returns one score per launch for the harness."""
import json
import numpy as np, pandas as pd
from . import store


def expected_votes(person_scores, base_see=0.3, follow_see=0.9, beta=0.0):
    people, items, _ = store.load()
    fol = {r.person: set(json.loads(r.follows)) if isinstance(r.follows, str) else set() for r in people.itertuples()}
    team = {r.id: set(json.loads(r.makers)) | {r.poster} for r in items.itertuples()}
    day = dict(zip(items.id, items.day))
    P = person_scores.copy()
    P["follows_team"] = [bool(fol.get(u, set()) & team.get(i, set())) for u, i in zip(P.person, P.id)]
    P["see"] = np.where(P.follows_team, follow_see, base_see)
    P["up"] = (P.score - 1) / 4
    V = (P.see * P.up).groupby(P.id).sum().rename("crowd").reset_index()
    if beta:
        V["day"] = V.id.map(day)
        V["crowd"] = V.crowd * (1 + beta * V.groupby("day").crowd.rank(pct=True))
    return V[["id", "crowd"]], float(P.follows_team.mean())
