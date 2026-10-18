# Neutral-goal leakage audit (core 6)

Auditor: coding/evaluator agent (not a human). Done after the forecast prompt and
packets were committed, so reading the hidden reviews could not shape prompts.
Criterion: the runner/forecaster input (goal, fixture, success checks) must not carry
the reviewer's opinion, symptom or workaround. Scope derived from reported activities is
allowed by design (pack README §6).

| Case | Goal | Verdict | Note |
| --- | --- | --- | --- |
| case_92a5835cec (Asana) | Organize bug reports for a team | pass | Activity from pros; no opinion carried. |
| case_f692c7793d (Asana) | Track tasks and their due dates | pass | Activity from pros; reminder praise not carried. |
| case_140855addc (Trello) | Track leads through a sales pipeline | pass | Missing-automation complaint not carried. |
| case_604a32d5df (Trello) | Organize tasks with checklists and deadlines | pass, scope note | Fixture lists the same features the reviewer praised (dates, checklist, attachment, move). Not opinion, but it steers execution toward praised features. |
| case_4164789dd7 (ClickUp) | Manage sprint tasks and workflow statuses | pass, scope note | Fixture creates tasks inside a sprint, the area of the reviewer's reported friction. The symptom and backlog workaround are not stated. |
| case_11232793fc (ClickUp) | Coordinate internal technology project tasks | pass | Setup-difficulty complaint not carried. |

Edits: none. Goals frozen as supplied.
