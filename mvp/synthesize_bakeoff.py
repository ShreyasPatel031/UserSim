#!/usr/bin/env python3
"""Synthesize comparative insights from multi-product bakeoff study.

Generates:
- Per-product strengths and weaknesses (with evidence)
- Cross-product comparisons (efficiency, success, user preference)
- "Who should pick X" recommendations
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

sa = ROOT / "secrets" / "sa.json"
if sa.is_file():
    os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(sa))


async def _call_gemini_async(prompt: str) -> str:
    """Call Gemini using the capability.gemini_config helper."""
    from capability.gemini_config import gemini_chat
    
    messages = [{"role": "user", "content": prompt}]
    return await gemini_chat(messages, json_mode=True)


def _call_gemini(prompt: str) -> str:
    """Synchronous wrapper for gemini_chat."""
    import asyncio
    return asyncio.run(_call_gemini_async(prompt))


def format_results_for_analysis(study_data: dict) -> str:
    """Format bakeoff results for LLM analysis."""
    parts = []
    
    products = study_data.get("products", {})
    agent_results = study_data.get("agent_results", [])
    
    # Group by product
    by_product = {}
    for r in agent_results:
        product = r.get("product", "unknown")
        if product not in by_product:
            by_product[product] = []
        by_product[product].append(r)
    
    for product_key, results in by_product.items():
        product_name = products.get(product_key, {}).get("name", product_key)
        parts.append(f"\n=== {product_name} ===")
        
        successes = sum(1 for r in results if r.get("success"))
        timeouts = sum(1 for r in results if r.get("harness_timeout"))
        failures = sum(1 for r in results if not r.get("success") and not r.get("harness_timeout"))
        
        parts.append(f"Success: {successes}/{len(results)}, Harness timeouts: {timeouts}, Product failures: {failures}")
        parts.append("")
        
        for r in results:
            agent_id = r.get("agent_id", "?")
            persona = r.get("persona_name", "?")
            task = r.get("task_title", "?")
            success = r.get("success", False)
            timeout = r.get("harness_timeout", False)
            steps = r.get("num_steps", 0)
            elapsed = r.get("elapsed_s", 0)
            
            status = "✓" if success else ("⏱TIMEOUT" if timeout else "✗FAILED")
            parts.append(f"Run: {agent_id}")
            parts.append(f"  Persona: {persona}, Task: {task}")
            parts.append(f"  Status: {status}, Steps: {steps}, Time: {elapsed:.0f}s")
            
            # Include trace summary for successful runs
            trace = r.get("trace", [])
            if trace and success:
                parts.append(f"  Trace ({len(trace)} steps):")
                for step in trace[:5]:  # First 5 steps
                    action = step.get("action", "")[:80]
                    parts.append(f"    Step {step.get('step', '?')}: {action}")
                if len(trace) > 5:
                    parts.append(f"    ... and {len(trace) - 5} more steps")
            
            parts.append("")
    
    return "\n".join(parts)


def synthesize_bakeoff_insights(study_data: dict) -> dict:
    """Generate comparative insights from bakeoff data."""
    
    products = study_data.get("products", {})
    product_names = {k: v.get("name", k) for k, v in products.items()}
    
    results_text = format_results_for_analysis(study_data)
    
    prompt = f"""Analyze this voice AI platform bakeoff comparing {', '.join(product_names.values())}.

Based on the actual run data below, generate insights for each product and comparative analysis.

RULES:
1. ONLY make claims you can prove from the data - cite specific run IDs and step numbers
2. Harness timeouts (⏱TIMEOUT) are infrastructure issues, NOT product failures - don't count them against products
3. Focus on meaningful differences: steps needed, time taken, success rates, what each product made easy or hard
4. Drop trivial observations (cookie banners, loading times)
5. Each insight needs evidence: run_id, step number, what happened

Output JSON with this structure:
{{
  "per_product": {{
    "retell": {{
      "strengths": [
        {{"claim": "Pricing page is clear and easy to find", "evidence": [{{"run_id": "...", "step": N, "detail": "..."}}]}}
      ],
      "weaknesses": [
        {{"claim": "Documentation structure is confusing", "evidence": [{{"run_id": "...", "step": N, "detail": "..."}}]}}
      ]
    }},
    "bland": {{ ... }},
    "vapi": {{ ... }}
  }},
  "comparisons": [
    {{
      "task": "Find pricing",
      "winner": "bland",
      "reasoning": "Bland showed pricing in 3 steps vs 5 for others",
      "steps_by_product": {{"retell": 5, "bland": 3, "vapi": 6}},
      "evidence": [{{"product": "bland", "run_id": "...", "detail": "..."}}]
    }}
  ],
  "recommendations": {{
    "retell": "Best for teams that need X because Y",
    "bland": "Best for teams that need X because Y",
    "vapi": "Best for teams that need X because Y"
  }}
}}

=== BAKEOFF DATA ===
{results_text}
=== END DATA ===

Generate 3-5 strengths and 3-5 weaknesses per product. Generate one comparison per task category.
Output ONLY valid JSON.
"""

    try:
        text = _call_gemini(prompt).strip()
        
        # Extract JSON
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        
        return json.loads(text)
        
    except Exception as e:
        print(f"Synthesis error: {e}", flush=True)
        return {"error": str(e)}


def add_bakeoff_insights(study_data: dict) -> dict:
    """Add synthesized insights to bakeoff study data."""
    
    insights = synthesize_bakeoff_insights(study_data)
    
    if "error" in insights:
        study_data["synthesis_error"] = insights["error"]
        return study_data
    
    # Add insights to study data
    study_data["insights"] = insights
    
    # Build summary for display
    summary = study_data.get("summary", {})
    
    # Extract top strengths/weaknesses per product
    per_product = insights.get("per_product", {})
    for product_key, product_insights in per_product.items():
        summary[f"{product_key}_strengths"] = [
            s.get("claim", "") for s in product_insights.get("strengths", [])[:5]
        ]
        summary[f"{product_key}_weaknesses"] = [
            w.get("claim", "") for w in product_insights.get("weaknesses", [])[:5]
        ]
    
    # Task comparisons
    comparisons = insights.get("comparisons", [])
    summary["task_winners"] = {
        c.get("task", "?"): c.get("winner", "?")
        for c in comparisons
    }
    
    # Recommendations
    summary["recommendations"] = insights.get("recommendations", {})
    
    summary["insights_synthesized"] = True
    study_data["summary"] = summary
    
    return study_data


def main():
    """Test synthesis on a bakeoff study file."""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python synthesize_bakeoff.py <bakeoff_result.json>")
        sys.exit(1)
    
    study_path = Path(sys.argv[1])
    if not study_path.exists():
        print(f"File not found: {study_path}")
        sys.exit(1)
    
    study_data = json.loads(study_path.read_text())
    
    results = study_data.get("agent_results", [])
    products = set(r.get("product") for r in results)
    print(f"Analyzing bakeoff with {len(results)} runs across {len(products)} products...")
    
    updated = add_bakeoff_insights(study_data)
    
    # Save updated study
    output_path = study_path.with_suffix(".synthesized.json")
    output_path.write_text(json.dumps(updated, indent=2, default=str))
    
    print(f"Saved to: {output_path}")
    
    # Print summary
    if "synthesis_error" in updated:
        print(f"\nSynthesis error: {updated['synthesis_error']}")
        return
    
    insights = updated.get("insights", {})
    per_product = insights.get("per_product", {})
    
    print("\n=== PRODUCT INSIGHTS ===")
    for product, pi in per_product.items():
        print(f"\n{product.upper()}:")
        print("  Strengths:")
        for s in pi.get("strengths", [])[:3]:
            print(f"    + {s.get('claim', '')[:70]}")
        print("  Weaknesses:")
        for w in pi.get("weaknesses", [])[:3]:
            print(f"    - {w.get('claim', '')[:70]}")
    
    print("\n=== TASK COMPARISONS ===")
    for comp in insights.get("comparisons", [])[:5]:
        print(f"  {comp.get('task', '?')}: {comp.get('winner', '?').upper()} wins")
        print(f"    {comp.get('reasoning', '')[:80]}")
    
    print("\n=== RECOMMENDATIONS ===")
    for product, rec in insights.get("recommendations", {}).items():
        print(f"  {product.upper()}: {rec[:80]}")


if __name__ == "__main__":
    main()
