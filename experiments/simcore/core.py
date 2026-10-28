"""The domain-agnostic part: no Product Hunt concepts here.

A Context is one decision moment (a day's launch feed, a review site page, a product screen):
  items    the options people can act on
  weight   per person, the chance they show up (from their past activity, dated before the moment)
  choice   people x items, P(person acts on item | sees it), from the domain's person model (no outcome inputs)
  ties     channel -> people x items (0/1): a tie that makes the person see the item regardless of ranking
           (e.g. backed the maker before, follows the maker); dated channels are listed in CHANNELS_DATED

simulate(): the moment is split into slots; in each slot a weight/slots share of everyone shows up and sees item j
with visibility v0 + (1 - v0) * exp(-(rank_j - 1) / tau), rank_j = its rank by simulated actions so far (herding);
a tied person sees it with at least beta. Returns simulated actions per item.
exposure(): per item and channel, how many people (activity-weighted) are exposed, and their expected actions."""
import numpy as np

CHANNELS_DATED = ("backed",)


class Context:
    def __init__(self, key, items, weight, choice, ties):
        self.key, self.items = key, list(items)
        self.weight = np.asarray(weight, np.float32)
        self.choice = np.asarray(choice, np.float32)
        self.ties = {k: np.asarray(v, np.float32) for k, v in ties.items()}


def _tie(ctx, channels):
    mats = [ctx.ties[c] for c in channels if c in ctx.ties]
    return np.maximum.reduce(mats) if mats else np.zeros_like(ctx.choice)


def simulate(ctx, slots=4, tau=25.0, v0=0.5, beta=1.0, channels=CHANNELS_DATED):
    tie = _tie(ctx, channels)
    votes = np.zeros(len(ctx.items))
    jitter = np.random.default_rng(0).random(len(ctx.items)) * 1e-9   # starting order unknown: random tie-break
    for _ in range(slots):
        rank = np.argsort(np.argsort(-(votes + jitter))) + 1
        vis = v0 + (1 - v0) * np.exp(-(rank - 1) / tau)
        votes += (ctx.weight / slots) @ (np.maximum(vis[None, :], beta * tie) * ctx.choice)
    return dict(zip(ctx.items, votes))


def exposure(ctx, channels=CHANNELS_DATED):
    """Per item: activity-weighted reach and expected actions per tie channel, plus the whole population's."""
    w, P = ctx.weight, ctx.choice
    out = {x: {"ev_all": 0.0} for x in ctx.items}
    ev = w @ P; fans = np.sort(w[:, None] * P, 0)[-100:].sum(0)
    for j, x in enumerate(ctx.items):
        out[x].update(ev_all=float(ev[j]), fans=float(fans[j]))
    for c in channels:
        T = ctx.ties.get(c)
        if T is None:
            continue
        reach, evc = w @ T, w @ (T * P)
        for j, x in enumerate(ctx.items):
            out[x][f"reach_{c}"] = float(reach[j]); out[x][f"ev_{c}"] = float(evc[j])
    return out
