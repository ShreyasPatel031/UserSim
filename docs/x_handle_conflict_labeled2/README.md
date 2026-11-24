# x_handle_conflict_labeled2 — DRAFT (not verified by fetch-ladder)
30 more conflicts. Taken from sample_conflicts.py --dir v3d --seed 142 (in shuffled order), skipping the 50 person_ids from the seed-141 set. Same labeling scheme as x_handle_conflict_labeled; X data comes from x_lookup.json and needed no extra calls.
Columns: label_link_field_both_neither_unsure plus per-handle label/confidence/note, x_exists, x_name. builder_rule_fires = link dead and field live; this ignores the name-similarity gate.
Tallies:
- Answer: link 15, field 7, neither 5, both 2, unsure 1.
- Link handle: match 18, mismatch 3, unsure 9.
- Field handle: match 10, mismatch 7, unsure 13.
Rule check (out of sample): dead link + live field fired on 6 rows. The field was right in 4. In the other 2 it was the wrong person (K. Soon, tco_99), and the builder's name-similarity ≥0.5 gate should block those. When the rule didn't fire: the link was right 15 times and the field 3 times (both handles alive: FlexClip employer account, 1752vc fund account, kbaqeri a different person).
One labeler pass, draft.
