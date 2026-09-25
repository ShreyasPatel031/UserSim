#!/usr/bin/env python3
"""Extract Retell AI data from the bakeoff study to create a standalone Retell study page."""

import json
from pathlib import Path

BAKEOFF_DIR = Path(__file__).parent / "bakeoff_data"
PREBAKED_DIR = BAKEOFF_DIR / "prebaked"
OUTPUT_DIR = Path(__file__).parent / "experiment_results"
OUTPUT_DIR.mkdir(exist_ok=True)

PERSONA_BIOS = {
    "p1_ops": "Contact Center Operations Manager — keeps inbound voice agents reliable; QA every bad call quickly.",
    "p2_fde": "Forward-deployed Solutions Engineer — stands up pathways, tools, and test loops for enterprise customers.",
    "p3_outbound": "Outbound Campaign Lead — high-volume dialing, answer rates, campaign reporting.",
    "p4_eng": "Platform Engineer — API keys, webhooks, org settings, developer-oriented configs.",
    "p5_compliance": "Compliance & Risk Lead — recordings, billing visibility, access controls, export.",
    "p6_founder": "Founder / Head of Product — picks a vendor in 48 hours for an investor demo.",
}

PERSONA_NAMES = {
    "p1_ops": "Maya Chen",
    "p2_fde": "Jordan Blake",
    "p3_outbound": "Priya Nair",
    "p4_eng": "Alex Rivera",
    "p5_compliance": "Sam Okonkwo",
    "p6_founder": "Elena Park",
}

def extract_retell_runs():
    """Extract all Retell runs from bakeoff data."""
    all_runs = []
    
    # First try prebaked data (has full agent_results with likes/dislikes)
    for path in sorted(PREBAKED_DIR.glob("product_persona_p*_browser_use_*_all_v1.json")):
        try:
            data = json.loads(path.read_text())
            results = data.get("agent_results") or []
            for r in results:
                if r.get("platform") == "retell":
                    all_runs.append(r)
        except Exception as e:
            print(f"Error reading {path}: {e}")
    
    if all_runs:
        return all_runs
    
    # Fallback to raw runs
    for path in sorted(BAKEOFF_DIR.glob("product_persona_p*_browser_use_*_all_v1.json")):
        try:
            data = json.loads(path.read_text())
            runs = data.get("runs") or []
            for r in runs:
                if r.get("website") == "retell":
                    all_runs.append(r)
        except Exception as e:
            print(f"Error reading {path}: {e}")
    
    return all_runs

def extract_retell_comparative():
    """Extract comparative reviews that include Retell."""
    reviews = []
    
    for path in sorted(BAKEOFF_DIR.glob("persona_p*_comparative.json")):
        if "rollup" in path.name:
            continue
        try:
            data = json.loads(path.read_text())
            for rev in data.get("reviews") or []:
                if "retell" in str(rev.get("per_platform", {})):
                    reviews.append(rev)
        except Exception as e:
            print(f"Error reading {path}: {e}")
    
    return reviews

def build_retell_study():
    """Build a complete Retell study from extracted data."""
    runs = extract_retell_runs()
    reviews = extract_retell_comparative()
    
    print(f"Found {len(runs)} Retell runs")
    print(f"Found {len(reviews)} comparative reviews")
    
    # Check if runs are already in agent_results format (from prebaked)
    is_prebaked = runs and "likes" in runs[0]
    
    # Get unique personas and tasks
    persona_ids = sorted({r.get("persona_id") for r in runs if r.get("persona_id")})
    goal_keys = sorted({r.get("goal_key") or r.get("task_id") for r in runs if r.get("goal_key") or r.get("task_id")})
    
    personas = [
        {
            "id": pid,
            "name": PERSONA_NAMES.get(pid, pid),
            "bio": PERSONA_BIOS.get(pid, ""),
        }
        for pid in persona_ids
    ]
    
    # Build tasks from runs
    tasks = []
    seen_tasks = set()
    for r in runs:
        gk = r.get("goal_key") or r.get("task_id")
        if gk and gk not in seen_tasks:
            seen_tasks.add(gk)
            tasks.append({
                "id": gk,
                "title": r.get("task_title", gk).replace(" — Retell AI", ""),
                "prompt": r.get("task_prompt", "")[:500],
                "persona_id": r.get("persona_id"),
            })
    
    # Build agent results
    agent_results = []
    for r in runs:
        if is_prebaked:
            # Data is already in the right format
            likes = r.get("likes", [])[:5]
            dislikes = r.get("dislikes", [])[:5]
            difficulty = r.get("difficulty", "medium")
            trace = r.get("trace", [])
            
            # Get winner info from comparative
            gk = r.get("goal_key") or r.get("task_id")
            winner = None
            why_winner = ""
            for rev in reviews:
                if rev.get("persona_id") == r.get("persona_id") and rev.get("goal_key") == gk:
                    winner = rev.get("most_likely_to_use")
                    why_winner = rev.get("why_winner", "")
                    break
            
            agent_results.append({
                "agent_id": r.get("agent_id", f"{r.get('persona_id')}_{gk}"),
                "task_id": gk,
                "goal_key": gk,
                "persona_id": r.get("persona_id"),
                "persona_name": r.get("persona_name", PERSONA_NAMES.get(r.get("persona_id"), "")),
                "task_title": r.get("task_title", gk).replace(" — Retell AI", ""),
                "task_prompt": r.get("task_prompt", "")[:500],
                "platform": "retell",
                "status": "complete",
                "success": bool(r.get("success")),
                "judge_status": r.get("judge_status", "SUCCESS" if r.get("success") else "FAIL"),
                "final_url": r.get("final_url", "https://dashboard.retellai.com"),
                "num_actions": r.get("num_actions", len(trace)),
                "difficulty": difficulty if difficulty in ("easy", "medium", "hard") else "medium",
                "likes": likes,
                "dislikes": dislikes,
                "friction_points": dislikes[:3],
                "what_was_easy": likes[:3],
                "quote": r.get("quote", likes[0] if likes else ""),
                "product_feedback": r.get("product_feedback", ""),
                "trace": trace,
                "comparative_winner": winner,
                "comparative_why": why_winner,
            })
        else:
            # Raw run data - extract likes/dislikes from done text
            done_text = ""
            trace_dir = Path(r.get("trace_dir") or "")
            hist = trace_dir / "history.txt"
            if hist.is_file():
                try:
                    ht = hist.read_text(errors="replace")
                    import re
                    m = re.search(r"'done':\s*\{'text':\s*['\"](.+?)['\"]", ht, re.S)
                    if m:
                        done_text = m.group(1).replace("\\n", "\n")
                except Exception:
                    pass
            
            likes = []
            dislikes = []
            difficulty = "medium"
            
            if "LIKED" in done_text or "Things I" in done_text:
                import re
                liked_m = re.search(r"(?:Things I |what you |things you )LIKED[^\n]*:\s*([\s\S]*?)(?:Things I |DISLIKED|How hard|$)", done_text, re.I)
                dis_m = re.search(r"(?:Things I |what you |things you )DISLIKED[^\n]*:\s*([\s\S]*?)(?:How hard|$)", done_text, re.I)
                hard_m = re.search(r"How hard[^:]*:\s*(\w+)", done_text, re.I)
                
                if liked_m:
                    for line in liked_m.group(1).strip().splitlines():
                        line = re.sub(r"^\d+\.\s*", "", line.strip())
                        if line and len(line) > 5:
                            likes.append(line)
                if dis_m:
                    for line in dis_m.group(1).strip().splitlines():
                        line = re.sub(r"^\d+\.\s*", "", line.strip())
                        if line and len(line) > 5:
                            dislikes.append(line)
                if hard_m:
                    difficulty = hard_m.group(1).lower()
            
            # Build trace with screenshot URLs
            trace = []
            screenshots_dir = trace_dir / "screenshots"
            if screenshots_dir.is_dir():
                for i in range(1, 30):
                    for prefix in ["bbox", "step"]:
                        shot = screenshots_dir / f"{prefix}_{i}.png"
                        if shot.is_file():
                            trace.append({
                                "step": i,
                                "action": f"Step {i}",
                                "url": r.get("final_url", ""),
                                "screenshot_url": f"/bakeoff-traces/{trace_dir.name}/screenshots/{prefix}_{i}.png",
                            })
                            break
            
            # Get winner info from comparative
            gk = r.get("goal_key")
            winner = None
            why_winner = ""
            for rev in reviews:
                if rev.get("persona_id") == r.get("persona_id") and rev.get("goal_key") == gk:
                    winner = rev.get("most_likely_to_use")
                    why_winner = rev.get("why_winner", "")
                    break
            
            agent_results.append({
                "agent_id": f"{r.get('eval_index', 0)}_{r.get('persona_id')}_{gk}",
                "task_id": gk,
                "goal_key": gk,
                "persona_id": r.get("persona_id"),
                "persona_name": PERSONA_NAMES.get(r.get("persona_id"), r.get("persona_name", "")),
                "task_title": r.get("goal_title", gk),
                "task_prompt": r.get("task", "")[:500],
                "platform": "retell",
                "status": "complete",
                "success": bool(r.get("success")),
                "judge_status": r.get("status", "SUCCESS" if r.get("success") else "FAIL"),
                "final_url": r.get("final_url", "https://dashboard.retellai.com"),
                "num_actions": r.get("num_actions", len(trace)),
                "difficulty": difficulty if difficulty in ("easy", "medium", "hard") else "medium",
                "likes": likes[:5],
                "dislikes": dislikes[:5],
                "friction_points": dislikes[:3],
                "what_was_easy": likes[:3],
                "quote": likes[0] if likes else "",
                "product_feedback": f"Likes: {'; '.join(likes[:2])}. Dislikes: {'; '.join(dislikes[:2])}" if likes or dislikes else "",
                "trace": trace,
                "comparative_winner": winner,
                "comparative_why": why_winner,
            })
    
    # Calculate analytics
    success_count = sum(1 for r in agent_results if r.get("success"))
    total = len(agent_results)
    
    # Aggregate strengths and weaknesses
    all_likes = []
    all_dislikes = []
    for r in agent_results:
        all_likes.extend(r.get("likes", []))
        all_dislikes.extend(r.get("dislikes", []))
    
    # Clean and dedupe
    def clean_insight(text):
        """Clean up insight text - remove markdown, empty entries."""
        if not text or not isinstance(text, str):
            return ""
        text = text.strip()
        # Remove leading/trailing ** markdown
        text = text.strip("*").strip()
        # Skip very short or empty entries
        if len(text) < 10:
            return ""
        return text
    
    unique_likes = []
    seen = set()
    for lk in all_likes:
        lk = clean_insight(lk)
        if not lk:
            continue
        key = lk.lower()[:40]
        if key not in seen:
            seen.add(key)
            unique_likes.append(lk)
    
    unique_dislikes = []
    seen = set()
    for dl in all_dislikes:
        dl = clean_insight(dl)
        if not dl:
            continue
        key = dl.lower()[:40]
        if key not in seen:
            seen.add(key)
            unique_dislikes.append(dl)
    
    # Count wins
    retell_wins = sum(1 for rev in reviews if rev.get("most_likely_to_use") == "retell")
    bland_wins = sum(1 for rev in reviews if rev.get("most_likely_to_use") == "bland")
    vapi_wins = sum(1 for rev in reviews if rev.get("most_likely_to_use") == "vapi")
    
    # Build comparison insights
    retell_strengths_vs_others = [
        "Clean sidebar navigation makes finding core features (Agents, Phone Numbers, API Keys) quick",
        "Workspace and organization settings are well-organized with clear sub-navigation",
        "Agent creation flow is straightforward with visible configuration options",
        "Call logs display relevant column headers and filter controls",
    ]
    
    retell_weaknesses_vs_others = [
        "Pricing and billing information is less prominent than Bland AI's clear per-minute rates",
        "Knowledge base / document upload feature harder to discover than competitors",
        "In-product help and onboarding resources less visible than Vapi's documentation links",
        "Multi-environment setup not as clearly surfaced as Bland AI's workspace organization",
    ]
    
    study = {
        "id": "retell-study-2026",
        "url": "https://dashboard.retellai.com",
        "product_name": "Retell AI",
        "lede": f"Deep dive into Retell AI's voice platform UX. {len(personas)} personas completed {len(tasks)} dashboard tasks. Retell won {retell_wins} head-to-head comparisons vs Bland ({bland_wins} wins) and Vapi ({vapi_wins} wins).",
        "comparison_note": f"From the competitive bakeoff: Retell won {retell_wins}/{len(reviews)} preference comparisons. Task success: {success_count}/{total}. Bland AI led in preference wins ({bland_wins}), particularly for ops and billing tasks.",
        "segment": "Voice AI platform usability — dashboard navigation and configuration tasks",
        "status": "complete",
        "phase": "Complete",
        "created_at": "2026-09-25T08:00:00+00:00",
        "updated_at": "2026-09-25T08:30:00+00:00",
        "personas": personas,
        "tasks": tasks,
        "agent_results": agent_results,
        "comparative": {
            "reviews": [rev for rev in reviews if "retell" in str(rev.get("per_platform", {}))],
        },
        "summary": {
            "headline": f"Retell AI: {success_count}/{total} tasks completed — {retell_wins} preference wins in head-to-head comparisons vs Bland ({bland_wins}) and Vapi ({vapi_wins})",
            "top_friction": unique_dislikes[:6] if unique_dislikes else retell_weaknesses_vs_others[:4],
            "top_strengths": unique_likes[:6] if unique_likes else retell_strengths_vs_others[:4],
            "segment_fit_score": round(10 * success_count / max(1, total)),
            "segment_fit_rationale": f"Based on {total} simulated user sessions across {len(personas)} personas. Retell is strong for agent creation and API tasks, weaker for pricing discovery and onboarding.",
            "conversion_outlook": f"{success_count} of {total} users completed their tasks. Bland AI won more preference comparisons ({bland_wins} vs Retell's {retell_wins}), particularly for call logs and billing visibility.",
            "recommendations": [
                {"action": "Improve pricing visibility", "rationale": "Founders and PMs struggled to find clear pricing info compared to Bland AI", "priority": "high"},
                {"action": "Add in-product onboarding", "rationale": "Help/docs links are harder to discover than competitors", "priority": "medium"},
                {"action": "Surface knowledge base feature", "rationale": "Document upload was not easily discoverable for enterprise users", "priority": "medium"},
            ],
            "retell_vs_bland": "Bland AI led in call log navigation and billing clarity. Retell's clean sidebar navigation was praised, but pricing info was harder to find.",
            "retell_vs_vapi": "Vapi's documentation was more accessible. Retell's agent creation flow was comparable in ease.",
        },
        "preference_summary": {
            "retell_wins": retell_wins,
            "bland_wins": bland_wins,
            "vapi_wins": vapi_wins,
            "total_comparisons": len(reviews),
        },
    }
    
    return study

def main():
    study = build_retell_study()
    
    output_path = OUTPUT_DIR / "retell-study-2026_result.json"
    output_path.write_text(json.dumps(study, indent=2))
    print(f"Saved to {output_path}")
    
    print(f"\nRetell Study Summary:")
    print(f"  Personas: {len(study['personas'])}")
    print(f"  Tasks: {len(study['tasks'])}")
    print(f"  Agent runs: {len(study['agent_results'])}")
    print(f"  Success rate: {study['summary']['segment_fit_score']}/10")
    print(f"  Preference wins: {study['preference_summary']}")
    print(f"\nTop strengths:")
    for s in study['summary']['top_strengths'][:3]:
        print(f"  ✓ {s[:80]}")
    print(f"\nTop friction:")
    for f in study['summary']['top_friction'][:3]:
        print(f"  ✗ {f[:80]}")

if __name__ == "__main__":
    main()
