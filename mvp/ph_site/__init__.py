"""Public Product Hunt pages on atelier-sim.com: /ph (live leaderboard forecast) and /try (try a product URL).

Read-only over the PH forecast files in GCS; never changes how they are produced. Every response is built from
whitelisted product fields; person data comes only from the redacted index (site/person_index_v1.*), which holds no
identifiers."""
