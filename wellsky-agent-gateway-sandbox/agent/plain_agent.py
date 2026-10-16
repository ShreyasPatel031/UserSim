"""A non-ADK agent: a plain Python class calling Gemini through the google-genai SDK.

Stands in for WellSky agents written without Google's ADK. Agent Runtime hosts any class with a
`query` method, so these can still sit behind Agent Gateway with Agent Identity.
"""
import os


class PlainAgent:
    def set_up(self):
        from google import genai
        self.client = genai.Client(vertexai=True, project=os.environ.get("WSKY_PROJECT", "project-amer-scs-sandbox"),
                                   location="us-central1")

    def query(self, input: str) -> dict:
        """Answer a question with Gemini, no framework."""
        try:
            r = self.client.models.generate_content(model="gemini-2.5-flash", contents=input)
            return {"framework": "plain python + google-genai", "answer": (r.text or "")[:500]}
        except Exception as e:
            return {"framework": "plain python + google-genai", "error": f"{type(e).__name__}: {e}"[:500]}
