from __future__ import annotations
from openai import OpenAI
from app.config import settings
from app.models.schemas import QueueItem, UserProfile


class LLMAgent:
    def __init__(self):
        if getattr(settings, 'groq_api_key', ''):
            self.client = OpenAI(api_key=settings.groq_api_key, base_url="https://api.groq.com/openai/v1")
            self.model = "llama-3.1-70b-versatile"
            self.provider = "groq"
        elif getattr(settings, 'openai_api_key', ''):
            self.client = OpenAI(api_key=settings.openai_api_key)
            self.model = "gpt-4o-mini"
            self.provider = "openai"
        else:
            self.client = None
            self.model = ""
            self.provider = "none"

    async def summarize_party_taste(self, users: list[UserProfile], queue: list[QueueItem]) -> str:
        if not self.client:
            return self._fallback(users, queue)

        user_lines = "\n".join(f"- {u.display_name}: genre={u.genre}, energy={u.preferred_energy}" for u in users)
        queue_lines = "\n".join(f"{i+1}. {q.track.name} by {q.track.artist} (score={q.score})" for i, q in enumerate(queue[:8]))

        try:
            resp = self.client.chat.completions.create(
                model=self.model, max_tokens=200,
                messages=[{"role": "user", "content": f"""You are an AI DJ for a party playlist mixer.

Guests:
{user_lines}

Queue (ML-ranked):
{queue_lines}

Write a 2-3 sentence party taste summary. What clusters exist, why the queue is fair, one fun observation. Conversational like a DJ."""}]
            )
            return resp.choices[0].message.content or self._fallback(users, queue)
        except Exception as e:
            print(f"LLM error ({self.provider}): {e}")
            return self._fallback(users, queue)

    def _fallback(self, users: list[UserProfile], queue: list[QueueItem]) -> str:
        genres = set()
        for u in users:
            genres.update(u.top_genres)
        return f"Party of {len(users)} guests across {', '.join(sorted(genres)[:5])}. Queue balanced with ML fairness ranking."
