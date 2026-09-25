# UserSim Experiment Guide

## Quick Start

### View the Retell AI Study
```bash
# Start the dev server
cd /workspace
PYTHONPATH=src:. python3 -m uvicorn mvp.server:app --host 0.0.0.0 --port 3000

# Open in browser:
# http://localhost:3000/retell
```

### Retell Study Summary
- **30 agent runs** across 6 personas and 30 dashboard tasks
- **29/30 tasks completed** (97% success rate)
- **5 preference wins** vs Bland (15 wins) and Vapi (10 wins)
- **Zero voice credits used** — all browser/dashboard tasks

## Defining Your Own Experiments

### Experiment Spec Format (JSON)

Create a file like `mvp/experiments/my-experiment.json`:

```json
{
  "id": "my-experiment-2026",
  "product_name": "Product Name",
  "product_url": "https://example.com",
  "lede": "Brief description of the study",
  "comparison_note": "Optional comparison context",
  
  "personas": [
    {
      "id": "p1_dev",
      "name": "Alex Developer",
      "bio": "Platform engineer evaluating the product for API integration",
      "occupation": "Platform Engineer"
    },
    {
      "id": "p2_pm",
      "name": "Sarah PM",
      "bio": "Product manager comparing vendors for a new feature",
      "occupation": "Product Manager"
    }
  ],
  
  "tasks": [
    {
      "id": "t1_signup",
      "title": "Sign up and explore",
      "prompt": "As a first-time user, sign up for the product and explore the main features. Note what you find easy or confusing.",
      "success_criteria": "Account created and main dashboard visible"
    },
    {
      "id": "t2_pricing",
      "title": "Find pricing",
      "prompt": "Find pricing information. Understand the cost model and what's included.",
      "success_criteria": "Pricing page or billing info visible"
    }
  ],
  
  "assignments": [
    {"persona_id": "p1_dev", "task_id": "t1_signup"},
    {"persona_id": "p1_dev", "task_id": "t2_pricing"},
    {"persona_id": "p2_pm", "task_id": "t1_signup"},
    {"persona_id": "p2_pm", "task_id": "t2_pricing"}
  ],
  
  "config": {
    "max_steps": 25,
    "timeout_s": 180,
    "browserbase_owner": "report"
  }
}
```

### Running Experiments

```bash
# Dry run (no real browsers, for testing the pipeline):
PYTHONPATH=src:. python3 mvp/run_experiment.py mvp/experiments/my-experiment.json --dry-run

# Live run with Browserbase:
PYTHONPATH=src:. python3 mvp/run_experiment.py mvp/experiments/my-experiment.json

# Control concurrency (default is 2 concurrent sessions):
PYTHONPATH=src:. python3 mvp/run_experiment.py mvp/experiments/my-experiment.json --max-concurrent 1
```

### Viewing Results

Results are saved to `mvp/experiment_results/<id>_result.json`.

To view in the UI:
1. Start the dev server
2. Go to `http://localhost:3000/study/<id>` or `http://localhost:3000/api/experiment/<id>`

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /retell` | Retell AI study page |
| `GET /study/<slug>` | Generic study page |
| `GET /api/experiment/<id>` | Get experiment results JSON |
| `GET /api/experiments` | List all experiments |

## Best Practices

### For Voice AI Products (Retell, Bland, Vapi)
- **Avoid voice credits**: Focus on dashboard/browser tasks
- **Good tasks**: Create agent (form only), find pricing, find docs, configure settings
- **Avoid**: Making actual calls, testing live voice features

### For Browserbase Sessions
- Use `owner=report` tag to identify your sessions
- Max 2 concurrent sessions to share with other agents
- Sessions timeout after ~3 minutes of inactivity

### Writing Good Task Prompts
1. Be specific about the goal
2. Include success criteria
3. Tell the agent when to stop (e.g., "Stop once the form is visible")
4. Ask for feedback: likes, dislikes, difficulty

### Persona Design
- Give each persona a distinct role and goals
- Include occupation for context
- Bio should explain what they care about
- 3-4 personas is usually enough

## Credits Log

| Run | Product | Agents | Credits |
|-----|---------|--------|---------|
| retell-study-2026 | Retell AI | 30 | 0 voice credits (browser only) |

## Troubleshooting

### "ModuleNotFoundError: No module named 'browserbase'"
```bash
pip3 install browserbase playwright browser-use google-genai pillow
~/.local/bin/playwright install chromium
```

### Browser sessions timing out
- Browserbase sessions have limited duration
- Reduce `timeout_s` in config
- Use `--max-concurrent 1` for stability

### Results not showing in UI
- Check `mvp/experiment_results/` for the JSON file
- Verify the experiment ID matches
- Restart the dev server after adding new results
