#!/usr/bin/env python3
"""Synthesize insights from study traces using LLM.

This module generates strengths and weaknesses claims from actual trace data,
with each claim citing specific run IDs and step numbers.
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
    # Use default model from gemini_config - it knows which models are available
    return await gemini_chat(messages, json_mode=True)


def _call_gemini(prompt: str) -> str:
    """Synchronous wrapper for gemini_chat."""
    import asyncio
    return asyncio.run(_call_gemini_async(prompt))


def format_trace_for_analysis(agent_result: dict) -> str:
    """Format an agent result's trace for LLM analysis."""
    parts = []
    
    agent_id = agent_result.get("agent_id", "unknown")
    persona = agent_result.get("persona_name", "User")
    task = agent_result.get("task_title", agent_result.get("task_prompt", ""))[:100]
    success = agent_result.get("success") or agent_result.get("completed")
    
    parts.append(f"=== Run: {agent_id} ===")
    parts.append(f"Persona: {persona}")
    parts.append(f"Task: {task}")
    parts.append(f"Completed successfully: {success}")
    parts.append("")
    
    trace = agent_result.get("trace") or []
    for step in trace:
        step_num = step.get("step", "?")
        action = step.get("action", "")[:150]
        thought = step.get("thought", "")[:200]
        url = step.get("url", "")
        
        parts.append(f"Step {step_num}: {action}")
        if thought:
            parts.append(f"  Thought: {thought}")
        if url:
            parts.append(f"  URL: {url}")
        parts.append("")
    
    # Add any feedback
    likes = agent_result.get("likes") or agent_result.get("what_was_easy") or []
    dislikes = agent_result.get("dislikes") or agent_result.get("friction_points") or []
    
    if likes:
        parts.append("User liked:")
        for like in likes[:3]:
            parts.append(f"  + {like}")
    
    if dislikes:
        parts.append("User disliked:")
        for dislike in dislikes[:3]:
            parts.append(f"  - {dislike}")
    
    return "\n".join(parts)


def synthesize_insights(study_data: dict) -> dict:
    """Generate insights from study data using LLM synthesis.
    
    Returns dict with:
    - strengths: list of {"claim": str, "evidence": [{"run_id": str, "step": int, "detail": str}]}
    - weaknesses: list of {"claim": str, "evidence": [{"run_id": str, "step": int, "detail": str}]}
    """
    agent_results = study_data.get("agent_results") or []
    if not agent_results:
        return {"strengths": [], "weaknesses": [], "error": "No agent results to analyze"}
    
    # Format all traces
    traces_text = []
    for result in agent_results:
        traces_text.append(format_trace_for_analysis(result))
    
    all_traces = "\n\n".join(traces_text)
    
    prompt = f"""Analyze these simulated user sessions on Retell AI's website. 
Based on the actual traces below, identify:

1. STRENGTHS: What did users find easy or well-designed? 
2. WEAKNESSES: What caused friction, confusion, or difficulty?

CRITICAL: Each claim MUST cite specific evidence from the traces.
- Cite by run ID and step number (e.g., "t1_pricing__p1_engineer, Step 3")
- Quote actual actions or thoughts from the traces
- Only make claims you can prove from the data below

Format your response as JSON:
{{
  "strengths": [
    {{
      "claim": "Clear pricing navigation - users found pricing page quickly",
      "evidence": [
        {{"run_id": "t1_pricing__p1_engineer", "step": 3, "detail": "User clicked Pricing link and found pricing page"}},
        {{"run_id": "t1_pricing__p2_pm", "step": 2, "detail": "Direct navigation to pricing from homepage"}}
      ]
    }}
  ],
  "weaknesses": [
    {{
      "claim": "Feature comparison is hard to understand",
      "evidence": [
        {{"run_id": "t3_features__p1_engineer", "step": 5, "detail": "User scrolled multiple times looking for feature details"}}
      ]
    }}
  ]
}}

=== TRACE DATA ===
{all_traces}
=== END TRACE DATA ===

Generate 3-5 strengths and 3-5 weaknesses, each with cited evidence.
Output ONLY valid JSON, no other text.
"""

    try:
        text = _call_gemini(prompt).strip()
        
        # Extract JSON from response
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        
        result = json.loads(text)
        return result
        
    except Exception as e:
        print(f"Synthesis error: {e}", flush=True)
        return {
            "strengths": [],
            "weaknesses": [],
            "error": str(e),
        }


def add_insights_to_study(study_data: dict) -> dict:
    """Add synthesized insights to study data."""
    insights = synthesize_insights(study_data)
    
    # Convert to the format expected by the report page
    strengths = []
    weaknesses = []
    
    for s in insights.get("strengths") or []:
        claim = s.get("claim", "")
        evidence = s.get("evidence") or []
        citations = [f"{e['run_id']} step {e['step']}" for e in evidence if e.get("run_id")]
        if claim:
            strengths.append({
                "text": claim,
                "citations": citations,
                "evidence": evidence,
            })
    
    for w in insights.get("weaknesses") or []:
        claim = w.get("claim", "")
        evidence = w.get("evidence") or []
        citations = [f"{e['run_id']} step {e['step']}" for e in evidence if e.get("run_id")]
        if claim:
            weaknesses.append({
                "text": claim,
                "citations": citations,
                "evidence": evidence,
            })
    
    # Update study summary
    if "summary" not in study_data:
        study_data["summary"] = {}
    
    study_data["summary"]["top_strengths"] = [s["text"] for s in strengths]
    study_data["summary"]["top_friction"] = [w["text"] for w in weaknesses]
    study_data["summary"]["strengths_with_evidence"] = strengths
    study_data["summary"]["weaknesses_with_evidence"] = weaknesses
    study_data["summary"]["insights_synthesized"] = True
    
    if insights.get("error"):
        study_data["summary"]["synthesis_error"] = insights["error"]
    
    return study_data


def main():
    """Test synthesis on a study file."""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python synthesize_insights.py <study_result.json>")
        sys.exit(1)
    
    study_path = Path(sys.argv[1])
    if not study_path.exists():
        print(f"File not found: {study_path}")
        sys.exit(1)
    
    study_data = json.loads(study_path.read_text())
    
    print(f"Analyzing {len(study_data.get('agent_results', []))} agent results...")
    
    updated = add_insights_to_study(study_data)
    
    # Save updated study
    output_path = study_path.with_suffix(".synthesized.json")
    output_path.write_text(json.dumps(updated, indent=2, default=str))
    
    print(f"Saved to: {output_path}")
    
    # Print summary
    summary = updated.get("summary", {})
    print("\n=== Synthesized Insights ===")
    print("\nStrengths:")
    for s in summary.get("strengths_with_evidence", []):
        print(f"  + {s['text']}")
        for c in s.get("citations", [])[:2]:
            print(f"    - {c}")
    
    print("\nWeaknesses:")
    for w in summary.get("weaknesses_with_evidence", []):
        print(f"  - {w['text']}")
        for c in w.get("citations", [])[:2]:
            print(f"    - {c}")


if __name__ == "__main__":
    main()
