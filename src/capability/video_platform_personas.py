"""Bland-style 90-run comparative study for consumer video platforms."""

from __future__ import annotations

from dataclasses import dataclass

PLATFORMS = ("youtube", "vimeo", "dailymotion")
PLATFORM_HOME = {
    "youtube": "https://www.youtube.com/",
    "vimeo": "https://vimeo.com/",
    "dailymotion": "https://www.dailymotion.com/",
}
PLATFORM_NAME = {
    "youtube": "YouTube",
    "vimeo": "Vimeo",
    "dailymotion": "Dailymotion",
}


@dataclass(frozen=True)
class Persona:
    id: str
    name: str
    role: str
    context: str
    priorities: tuple[str, ...]


PERSONAS = (
    Persona("p1_viewer", "Avery Brooks", "Casual viewer", "Watches short sessions after work", ("relevance", "low friction", "recommendations")),
    Persona("p2_student", "Noah Kim", "University student", "Uses video to research and learn", ("search precision", "credibility", "navigation")),
    Persona("p3_creator", "Maya Patel", "Independent video creator", "Researches formats and competing creators", ("creator identity", "video context", "discovery")),
    Persona("p4_marketer", "Jordan Lee", "Social media marketing manager", "Finds examples and trends for campaigns", ("trend discovery", "metadata", "speed")),
    Persona("p5_parent", "Taylor Morgan", "Parent and household viewer", "Looks for suitable educational and family content", ("clarity", "predictability", "safe discovery")),
    Persona("p6_educator", "Elena Garcia", "Independent educator", "Curates useful videos for learners", ("topic depth", "channel quality", "shareable findings")),
)

GOALS = (
    ("search", "Find relevant content", "Search for a useful beginner-friendly video about personal productivity and inspect the first organic results.", "Report three relevant video titles and their creators/channels."),
    ("filters", "Evaluate search refinement", "Search for home workout videos and use any available sort or filter controls to narrow toward recent beginner content.", "Report which refinement controls were available and the best matching result."),
    ("creator", "Inspect creator information", "Find a science explainer video, open its creator/channel identity surface, and assess whether the creator appears credible.", "Report the video, creator/channel, and visible credibility signals."),
    ("discovery", "Evaluate discovery", "Starting from the home or discovery surface, find a promising cooking or recipe video without using an external search engine.", "Report the selected video and how the platform helped or hindered discovery."),
    ("playback", "Evaluate consumption UX", "Open one organic educational video and inspect the viewing page without playing more than a few seconds.", "Report title, creator/channel, and the useful viewing controls or context visible around the player."),
)


def _eval_index(persona_n: int, goal_n: int, platform: str) -> int:
    return 20_000 + persona_n * 100 + goal_n * 10 + PLATFORMS.index(platform) + 1


def all_video_tasks() -> list[dict]:
    tasks: list[dict] = []
    for persona_n, persona in enumerate(PERSONAS, start=1):
        for goal_n, (key, title, goal, success) in enumerate(GOALS, start=1):
            for platform in PLATFORMS:
                name = PLATFORM_NAME[platform]
                auth = "You are already signed in; first confirm the account avatar is present. " if platform == "youtube" else ""
                prompt = (
                    f"PERSONA: {persona.name}, {persona.role}. Context: {persona.context}. "
                    f"Priorities: {', '.join(persona.priorities)}. PLATFORM: {name}. {auth}"
                    f"GOAL: {goal} SUCCESS: {success} "
                    "Operate read-only: do not like, comment, follow, subscribe, upload, purchase, or change settings. "
                    f"Finish with what you accomplished, 2-4 UX likes, 2-4 UX dislikes, and ease (easy/medium/hard)."
                )
                tasks.append({
                    "task_id": f"video_{persona.id}_{key}_{platform}",
                    "eval_index": _eval_index(persona_n, goal_n, platform),
                    "website": platform,
                    "domain": "video_platform_persona",
                    "persona_id": persona.id,
                    "persona_name": persona.name,
                    "goal_key": key,
                    "goal_title": title,
                    "comparative_group": f"{persona.id}_{key}",
                    "task": prompt,
                    "start_url": PLATFORM_HOME[platform],
                    "human_n_steps": 18,
                    "human_actions": [],
                })
    return tasks


def youtube_pilot_tasks() -> list[dict]:
    """Eight deterministic YouTube tasks spanning every persona and goal type."""
    yt = [task for task in all_video_tasks() if task["website"] == "youtube"]
    return [yt[i] for i in (0, 1, 2, 3, 4, 5, 11, 17)]

