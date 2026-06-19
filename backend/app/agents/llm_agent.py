"""
LLM Agent - replaces OpenClaw with direct Claude API calls.
ML agents handle scoring/ranking. This agent handles natural language only.

Swap in Ollama by changing the summarize method to hit localhost:11434 instead.
"""
from __future__ import annotations

from anthropic import Anthropic

from app.config import settings
from app.models.schemas import QueueItem, UserProfile


class LLMAgent:

    def __init__(self) -> None:
        if settings.anthropic_api_key:
            self.client = Anthropic(api_key=settings.anthropic_api_key)
        else:
            self.client = None

    async def summarize_party_taste(
        self, users: list[UserProfile], queue: list[QueueItem]
    ) -> str:
        if not self.client:
            return self._fallback_summary(users, queue)

        user_summary = "\n".join(
            f"- {u.display_name}: genres={u.top_genres}, "
            f"energy={u.preferred_energy}, danceability={u.preferred_danceability}"
            for u in users
        )

        queue_summary = "\n".join(
            f"{i+1}. {q.track.name} by {q.track.artist} "
            f"(score={q.score}, genres={q.track.genres}, matched={q.matched_users})"
            for i, q in enumerate(queue[:8])
        )

        prompt = f"""You are the AI DJ for a social party playlist mixer app.

Guests at this party:
{user_summary}

Generated queue (ranked by ML scoring):
{queue_summary}

Write a 2-3 sentence party taste summary for the host explaining:
1. What music clusters exist among the guests
2. Why this queue order is fair to everyone
3. One fun observation about the group's combined taste

Keep it conversational, like a DJ talking to the host. No bullet points, no markdown."""

        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text
        except Exception as exc:
            return self._fallback_summary(users, queue)

    async def explain_track_choice(self, track_name: str, reasons: list[str], score: float) -> str:
        """Optional: ask the LLM to explain why a specific track was chosen."""
        if not self.client:
            return f"{track_name} scored {score} based on: {', '.join(reasons)}"

        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=100,
                messages=[{
                    "role": "user",
                    "content": (
                        f"In one sentence, explain why '{track_name}' (score: {score}) "
                        f"was picked for a party queue. Reasons: {reasons}. "
                        f"Be brief and fun, like a DJ."
                    ),
                }],
            )
            return message.content[0].text
        except Exception:
            return f"{track_name} scored {score} based on: {', '.join(reasons)}"

    def _fallback_summary(
        self, users: list[UserProfile], queue: list[QueueItem]
    ) -> str:
        genres: set[str] = set()
        for u in users:
            genres.update(u.top_genres)
        top_genres = ", ".join(sorted(genres)[:5])
        return (
            f"Party of {len(users)} guests spanning {top_genres}. "
            f"Queue balanced across {len(queue)} tracks using ML-based fairness ranking. "
            f"Set ANTHROPIC_API_KEY in .env for AI-powered summaries."
        )
