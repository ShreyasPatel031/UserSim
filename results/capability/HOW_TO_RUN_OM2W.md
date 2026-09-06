# How to run Online-Mind2Web properly (stop burning $ on blocks)

## Why our runs were contaminated

We ran Playwright / Browser Use from a **cloud datacenter IP**. Sites like apartments.com / uniqlo.com return Akamai **403 Access Denied**. Those are **environment failures**, not model failures — but they still cost Gemini tokens and pollute scores.

Published Fara / MolmoWeb / Stagehand OM2W numbers do **not** use raw GCP/Colab Chromium. They use **Browserbase** (residential proxies + stealth).

## What “proper” means (industry recipe)

| Layer | Do this | Don’t |
|-------|---------|--------|
| **Browser** | [Browserbase](https://browserbase.com) with **proxies + Advanced Stealth / Verified** | Local Chromium from Colab/GCP IP |
| **Tasks** | Maintained **Online-Mind2Web** 300 ([OSU repo](https://github.com/OSU-NLP-Group/Online-Mind2Web) / HF) | Old Mind2Web live dumps / random URLs |
| **Start URL** | Official task `website` only | Google → site (OM2W forbids this for fair compare) |
| **Blocks** | Label `BLOCKED` / env error; retry on Browserbase; **exclude from model score** or report separately | Count Akamai 403 as model FAIL |
| **Judge** | **WebJudge + o4-mini** (OM2W official) or open `osunlp/WebJudge-7B` | Ad-hoc Gemini judge alone if claiming OM2W |
| **Step budget** | Match claim: Fara often **100**; OpenWebRL/MolmoWeb tables often **30** | Mix budgets then compare % |
| **Smoke first** | `limit=5–10` reachable tasks before full 300 | Full100 on broken env |

Fara paper: Browserbase to cut session blocking; **two-pass** (Browserbase, then re-run only block-failures).  
MolmoWeb: `--env_type browserbase` + Advanced Stealth to reproduce Amazon/etc.

## Concrete stacks (pick one)

### A. Reproduce open-model numbers (best science)

1. **Browser:** Browserbase keys  
   `BROWSERBASE_API_KEY` + `BROWSERBASE_PROJECT_ID`  
   Enable residential proxies + Advanced Stealth.
2. **Harness:**  
   - MolmoWeb: `uv run python -m benchmarks.benchmarks run --benchmark online_mind2web --env_type browserbase …`  
   - Fara: `webeval` + `--browserbase` ([docs/eval_reproducibility.md](https://github.com/microsoft/fara/blob/main/docs/eval_reproducibility.md))
3. **Model:** Colab/GPU hosts weights (OpenWebRL-4B / Fara1.5-4B); **browser traffic leaves via Browserbase**, not the Colab IP.
4. **Judge:** WebJudge o4-mini (or WebJudge-7B to cut OpenAI spend).

### B. Keep Browser Use, fix the browser only (cheapest fix for us)

1. Point Browser Use at a **Browserbase CDP/session** (or Browser Use Cloud with residential/proxy), not local Chromium on the agent VM.
2. Load OM2W task JSON; force `goto(start_url)` before the agent loop.
3. On first paint: if “Access Denied” / CAPTCHA wall → **STOP**, tag `BLOCKED`, skip model steps (no more token burn).
4. Judge only non-blocked trajectories.

### C. Cheap preflight (before any paid model tokens)

```text
For each candidate task URL:
  Browserbase session (proxies=true) → goto(start_url) → screenshot
  OK if page title/body is not Access Denied / bot wall
Keep only OK tasks for Mini-N smoke
```

Cost: Browserbase session minutes only. Zero LLM until preflight passes.

## Cost firewall (mandatory)

1. **Preflight** all URLs on Browserbase (above).  
2. Smoke **≤10** tasks end-to-end.  
3. Only then scale concurrency.  
4. Cap: abort task on `BLOCKED` within 1–2 navigations.  
5. Never re-run full100 on local cloud Chromium for OM2W.

## What we already learned in-repo

- Mini-2 attempt 1 (Apartments + Uniqlo) = all **BLOCKED** from this IP → `mini2_harness_gemini-36-flash_attempt1_blocked.json`
- Eventbrite + IGN were reachable → valid harness compare
- `open_ecosystem/OPEN_ECOSYSTEM_ANALYSIS.md` already said: use maintained OM2W + don’t burn Pro on WAF noise

## Bottom line

**Benchmark = Online-Mind2Web.**  
**Proper run = Browserbase (residential) + OM2W tasks + WebJudge + separate BLOCKED.**  
Colab is for the **model**, not for the **exit IP**. Until Browserbase (or equivalent) is wired, further live OM2W spends are wasted.
