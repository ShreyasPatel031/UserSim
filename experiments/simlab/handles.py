"""Maker / hunter handle cleaning (Nov 11): the launches table lists the redaction placeholder "[REDACTED]" as a maker
on ~96% of launches, which made every person "tied" to almost every launch through a shared fake maker. Placeholders
(bracketed tokens) and empty handles are dropped before any team / tie feature is built."""


def clean_handles(xs):
    return {str(x) for x in xs if x and str(x).strip() and not str(x).strip().startswith("[")}
