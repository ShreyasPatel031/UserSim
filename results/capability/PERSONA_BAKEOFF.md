# Voice AI persona bakeoff — Bland vs Vapi vs Retell

**Lens:** Bland customers / buyers evaluating voice-AI platforms.  
**Method:** UserSim browser agents (Gemini 2.5 Flash + Browser Use), signed-in product consoles.  
**Scale:** 6 personas × 5 unique goals × 3 platforms = **90 agent runs** + **30 comparative syntheses**.

## Personas

| ID | Name | Role | What they stress-test |
|----|------|------|------------------------|
| p1_ops | Maya Chen | Contact Center Ops Manager | Call logs, detail, filters, QA/triage, analytics |
| p2_fde | Jordan Blake | Forward-deployed Solutions Eng | Pathways/agents, create flow, config, tools, test loop |
| p3_outbound | Priya Nair | Outbound Campaign Lead | Numbers, batch/outbound, direction in logs, voices, metrics |
| p4_eng | Alex Rivera | Platform Engineer | API keys, org settings, tools, webhooks, dev-oriented config |
| p5_compliance | Sam Okonkwo | Compliance & Risk | Recordings, billing, team/RBAC, privacy, export |
| p6_founder | Elena Park | Founder / Head of Product | First agent, pricing, buy number, knowledge, in-app help |

No goal is reused across personas (30 distinct user jobs).

## Task completion

| Persona | Agent task success |
|---------|-------------------|
| P1 Maya (Ops) | 15/15 |
| P2 Jordan (FDE) | 15/15 |
| P3 Priya (Outbound) | 15/15 |
| P4 Alex (Eng) | 14/15 |
| P5 Sam (Compliance) | 15/15 |
| P6 Elena (Founder) | 15/15 |
| **Total** | **89/90 (98.9%)** |

## Comparative winners (which platform each persona would pick per goal)

Counts across 30 head-to-head goals:

| Platform | Wins | Share |
|----------|------|-------|
| **Bland** | **15** | **50%** |
| Vapi | 10 | 33% |
| Retell | 5 | 17% |

### By persona — who wins Maya/Priya/Sam/Elena (Bland-heavy buyers)

| Persona | Bland wins | Vapi | Retell | Bland story |
|---------|------------|------|--------|-------------|
| P1 Ops (Maya) | 3 | 0 | 2 | Call logs + analytics; Retell wins filters & QA page |
| P2 FDE (Jordan) | 2 | 3 | 0 | Pathways/create/templates; Vapi wins tools & test |
| P3 Outbound (Priya) | 3 | 2 | 0 | Numbers, batch, outbound-in-logs; Vapi voice + metrics |
| P4 Eng (Alex) | 0 | 4 | 1 | Vapi dominates dev ergonomics; Retell webhooks |
| P5 Compliance (Sam) | 3 | 0 | 2 | Recordings, compliance section, export; Retell billing/RBAC |
| P6 Founder (Elena) | 4 | 1 | 0 | Fast first-agent, pricing clarity, numbers, knowledge |

### Headline for Bland GTM

- **Ops + outbound + compliance + founder evaluators** lean **Bland** on product-console UX (15/30 goals).
- **Engineers** lean **Vapi** (API keys, org, tools, assistant config).
- **Retell** peaks on **QA/compliance admin** (dedicated Quality Assurance, usage billing, roles) and **filter density** on call history.

## Artifacts

```
src/capability/voice_ai_personas.py          # personas + 30 goals
scripts/voice_ai_auth/synthesize_persona_compare.py
results/capability/product_persona_p*_browser_use_*_all_v1.json
results/capability/persona_p*_comparative.json
results/capability/persona_comparative_rollup.json
```

## Re-run

```bash
# Single persona, single goal (3 platforms)
PYTHONPATH=src .venv/bin/python -m capability.run_bakeoff \
  --stage product_persona_p1_t1 --harness browser_use --max-actions 22 --tag run1

# Full study (90 runs)
--stage product_persona

# Comparative synthesis
PYTHONPATH=src .venv/bin/python scripts/voice_ai_auth/synthesize_persona_compare.py \
  --manifest results/capability/product_persona_p1_browser_use_p1_all_v1.json
```
